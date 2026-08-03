# Financial Intelligence Pipeline

A FastAPI + LangGraph service that answers natural-language financial questions by routing them across **SQL** (structured company/financial data), **vector/RAG retrieval** (earnings calls, SEC filings, news), and **live market data** (yfinance), then scores, ranks, and synthesizes the results into a cited, reviewed report. Includes a RAGAS-based evaluation harness for benchmarking pipeline quality.

## Contents

- [Architecture](#architecture)
- [Request flow](#request-flow)
- [API reference](#api-reference)
- [Data model](#data-model)
- [Setup](#setup)
- [Configuration](#configuration)
- [Seeding data](#seeding-data)
- [Project layout](#project-layout)
- [Known issues](#known-issues)

## Architecture

The system is a set of **LangGraph state graphs** orchestrating LLM calls, tool use, and retrieval:

```
                       ┌─────────────────────────────────────────┐
                       │           financial_graph                │
                       │ (backend/graph/financial_graph.py)        │
                       └─────────────────────────────────────────┘
  intent → planner → retrieval → scoring → analysis → reviewer ──┐
                         ▲                                       │
                         └──────── retry (should_retry) ─────────┘
                                                                  │
                                                                  ▼
                                                                 END
```

- **intent_node** — classifies the query into `VALUATION | GROWTH | SENTIMENT | MIXED` (`gpt-5.4-nano`, structured output).
- **planner_node** — decomposes the query into `sql_query`, `vector_query`, `market_query` (tickers) and a `strategy` (`PARALLEL` / `SQL_FIRST` / `VECTOR_FIRST`) (`gpt-5.4-mini`).
- **retrieval** — an async node wrapping `hybrid_retrieve_async` (see below); this is where intent-based branching actually happens, not at the graph-edge level.
- **scoring_node** — reranks retrieved companies (`backend/scoring/ranker.py`), attaches evidence and explainability.
- **analysis_node** — synthesizes a structured JSON report with per-company recommendations and cited evidence (`gpt-5.4`, the "strong" model).
- **reviewer_node** — fact-checks the draft report (confidence thresholds, missing evidence, flags, LLM hallucination check, citation validation) and either approves it (`final_report`) or loops back to `retrieval` (up to 3 retries, then force-passes).

Two additional sub-graphs implement single-source retrieval as **ReAct tool-calling agents**, and are also exposed directly via their own API routes:

- **`sql_graph.py`** — `sql_agent` node (LLM bound to SQL tools: schema lookup, query generation/validation/execution, error-fix) ↔ `tools`, looping until done or 3 failed fix attempts.
- **`vector_graph.py`** — `agent` node (LLM bound to a single `retrieve_similar` tool) ↔ `tools`.

### Hybrid retrieval

`backend/retrieval/hybrid_retrieval.py` fans work out based on intent:

| Intent | Sources used | Weights |
|---|---|---|
| `VALUATION` / `GROWTH` | SQL only | SQL 100% |
| `SENTIMENT` | Vector only | Vector 100% |
| `MIXED` | SQL + Vector + Market (parallel, `asyncio.gather`) | SQL 40% / Vector 30% / Market 30% (redistributes to 60/40 if market data unavailable) |

Per-source timeouts: SQL 45s, Vector 10s, Market 8s, overall `MIXED` fan-out 60s, with graceful degradation on partial failures. `combine_results()` produces an `overall_confidence` from the weighted sources.

Vector search itself is two-stage: a raw pgvector cosine-similarity query over `document_chunks` (`backend/retrieval/vector_search.py`) pulls `top_k*4` candidates, which are then reranked with `rank_bm25.BM25Plus` against LLM-extracted financial keywords.

### Scoring & ranking

`backend/scoring/ranker.py` computes, per company, four normalized (0–1) dimension scores — **valuation** (PE + price momentum), **growth** (revenue growth + EPS sign), **relevance** (avg. chunk cosine similarity), **sentiment** (positive/negative financial-term ratio in matched chunks) — combined with dynamic weights that shift based on which sources actually returned data, optionally blended 70/30 with an LLM holistic score (`llm_rerank_companies`). `evidence_builder.py` attaches per-company citations (`"NVDA-sql-1"`, `"NVDA-vector-2"`, `"NVDA-market-1"`) and `score_normalizer.py` builds the human-readable explainability breakdown and recommendation bucket (Strong buy → Avoid).

## Request flow

1. Client `POST`s a natural-language question to `/api/retrieve/financial`.
2. `intent_node` classifies it; `planner_node` splits it into sub-queries per source.
3. `hybrid_retrieve_async` fans out to SQL / vector / market retrieval per the intent-weight table above.
4. `scoring_node` ranks the top 5 companies with attached evidence.
5. `analysis_node` drafts a structured report citing that evidence.
6. `reviewer_node` fact-checks the draft; on failure, loops back to retrieval (max 3 retries) with a refined strategy, otherwise finalizes `final_report`.

## API reference

### Financial (combined pipeline)

`POST /api/retrieve/financial`
```json
// request
{ "query": "Compare valuation and sentiment for NVDA and AMD" }
// response
{ "query": "...", "final_report": { ... }, "result": { ... } }
```

### SQL-only

`POST /api/retrieve/sql`
```json
{ "query": "What is the average PE ratio of software companies?" }
// → { "answer": "..." }
```

### Vector-only (RAG)

`POST /api/retrieve/vector`
```json
{ "query": "What did management say about AI capex?", "top_k": 5 }
// → { "query": "...", "answer": "..." }
```

`POST /api/index/documents` — requires header `X-Admin-Key`. Body `{ "document_id": 123 }` to (re)index one document, or `{}` to index all unindexed documents. Runs as a `BackgroundTask` calling `embed_document`/`embed_all_documents`.

### Evaluation (RAGAS benchmarking)

Prefix `/api/evaluation`:

| Endpoint | Purpose |
|---|---|
| `POST /run` | Kick off a benchmark run (`question_set`, `dataset`, `model`, `retrieval_mode`, `company_filter`, `k`) against a curated question set. **Currently broken** — see [Known issues](#known-issues). |
| `GET /runs?limit&offset` | List recent benchmark runs with their metrics. |
| `GET /runs/{run_id}` | Fetch a single run's metrics. |
| `GET /metrics/comparison` | Average metrics grouped by `retrieval_mode`, for charting. |
| `GET /metrics/timeseries?minutes=30` | Metric points over a recent time window, for charting. |

### Health

`GET /health` — checks Postgres and Redis connectivity, returns `{status, db, redis}`.

## Data model

Postgres (pgvector-enabled) via SQLAlchemy (`backend/models/db_models.py`):

- **`companies`** — ticker, name, sector, market_cap.
- **`financial_metrics`** — per-company PE ratio, EPS, revenue growth.
- **`documents`** — raw source text (earnings calls, filings, news) with `doc_type`/`source`.
- **`document_chunks`** — chunked document text with a `Vector(1536)` embedding column (this is where embeddings actually live; document-level embeddings were migrated out).
- **`evaluation_metrics`** / **`benchmark_runs`** — RAGAS + custom metrics per benchmark run.
- **`retrieval_logs`**, **`pipeline_traces`**, **`retrieved_evidence`**, **`model_costs`**, **`system_logs`**, **`alerts`**, **`human_reviews`** — observability tables defined in the schema but **not yet written to** by any code path (planned dashboard support).

Migrations live in `alembic/versions/` (3 revisions: add embedding to documents → move to chunk-level `document_chunks` → add evaluation/observability tables).

## Setup

Requires Python 3.13 (`.python-version`) and [`uv`](https://github.com/astral-sh/uv).

```bash
# Start Postgres (pgvector) + Redis
docker compose up -d postgres redis

# Install deps
uv sync

# Run migrations
uv run alembic upgrade head

# Seed reference data (companies, financials, sample documents)
uv run python -m seeds.seed_data

# Run the API
uv run uvicorn backend.main:app --reload --port 8000
```

Or run the whole stack (API included) via `docker compose up --build` — see the caveat about the `/coded` volume mount below.

## Configuration

Settings are loaded from `.env` via `backend/config.py` (`pydantic-settings`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | — | Postgres connection string |
| `REDIS_URL` | yes | — | Redis connection string |
| `APP_ENV` | no | `development` | Environment name |
| `APP_HOST` / `APP_PORT` | no | — | Used by local run scripts |
| `OPENAI_API_KEY` | yes (for any LLM/embedding call) | `""` | Chat + embedding models |
| `ADMIN_API_KEY` | no | `admin-secret-key` | Guards `POST /api/index/documents` |
| `ALPHA_VANTAGE_API_KEY` | for seeding news sentiment | `""` | Used only by `seeds/seed_data.py` |
| `LANGCHAIN_API_KEY` / `LANGCHAIN_TRACING_V2` / `LANGCHAIN_PROJECT` | no | — | LangSmith tracing env vars are read but no tracing is actually wired up (see Known issues) |

**Models used**: `gpt-5.4-nano` (classification, ticker extraction), `gpt-5.4-mini` (planning, SQL/vector agents, reranking), `gpt-5.4` (final report synthesis, reviewer fact-check), `text-embedding-3-small` (document embeddings, 1536-dim).

**Docker Compose ports**: Postgres `5433→5432`, Redis `6379→6379`, API `8000→8000`.

## Seeding data

`seeds/companies.csv` lists 50 tech-heavy tickers (AAPL, MSFT, GOOGL, NVDA, …). `seeds/seed_data.py` clears and repopulates `companies`, `financial_metrics`, and `documents` by pulling live fundamentals from yfinance and up to 3 news-sentiment articles per company from Alpha Vantage. It sleeps 12s between companies to respect rate limits, so a full seed run takes roughly 10 minutes.

## Project layout

```
backend/
  api/            FastAPI routers (financial, sql, vector, evaluation)
  graph/          LangGraph state graphs (financial, sql, vector)
  nodes/          Individual graph nodes (intent, planner, retrieval-adjacent, scoring, analysis, reviewer)
  retrieval/      Hybrid retrieval, vector search, SQL execution, query filters
  scoring/        Ranking, evidence attachment, score normalization
  ingestion/      Document loading, chunking, embedding/indexing
  evaluation/     RAGAS evaluator, custom metrics, benchmark runner, question sets
  services/       LLM client tiers, market data (yfinance), Postgres, Redis
  models/         SQLAlchemy models
  observability/  Logging/metrics/tracing — currently empty stubs
alembic/          DB migrations
seeds/            Reference data + seeding script
frontend/         Empty placeholder (no implementation yet)
```

## Known issues

These were found while documenting the codebase and are worth fixing before relying on the affected paths:

- **`POST /api/evaluation/run` is broken** — `evaluation_routes.py` imports `from graph.financial_graph import FinancialGraph`, but the real module is `backend.graph.financial_graph` and it exports a compiled graph object (`financial_graph`), not a `FinancialGraph` class.
- **Evaluation routes mix sync/async DB sessions** — they depend on `AsyncSession`, but `postgres_service.get_db()` yields a synchronous SQLAlchemy `Session` from a sync engine.
- **`CustomMetrics.compute_run_metrics` will raise `AttributeError`** — an indentation bug in `backend/evaluation/custom_metrics.py` defines `recall_at_k`, `mean_average_precision`, `hallucination_rate`, and `compute_run_metrics` as module-level functions instead of `CustomMetrics` methods, but `benchmark_runner.py` calls them as `CustomMetrics.compute_run_metrics(...)`.
- **`BenchmarkRunner` expects a pipeline shape that doesn't match `financial_graph`** — it calls `.invoke({"question":..., "run_id":..., "retrieval_mode":...})` and expects `answer`/`retrieved_tickers`/`context_chunks`/`cost_usd`, none of which match the actual `FinancialState` shape.
- **`docker-compose.yml` volume mount path mismatch** — mounts `.:/coded` but the Dockerfile's `WORKDIR` is `/code`, so the bind mount doesn't overlay the app source as likely intended.
- **`embedding_service.py` and all of `backend/observability/*.py` are empty stub files** — not implemented. Embedding logic currently lives inline in `ingestion/indexing_service.py` and `retrieval/vector_search.py`; logging is ad hoc via `logging.getLogger` rather than a shared observability layer.
- **Several DB tables have no writers** — `retrieval_logs`, `pipeline_traces`, `retrieved_evidence`, `model_costs`, `system_logs`, `alerts`, `human_reviews` are defined in the schema but nothing currently inserts into them (planned dashboard support, not yet wired up).
- **`question_sets.py` has duplicate dead redefinitions** of `GROWTH_QUESTIONS`, `SENTIMENT_QUESTIONS`, and `MIXED_QUESTIONS` (harmless — the later definition just overwrites the identical earlier one).
- **`frontend/components` is empty** — no frontend implementation exists yet, despite the evaluation endpoints being shaped for dashboard charts.
