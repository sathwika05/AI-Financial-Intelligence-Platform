# Financial Intelligence Pipeline

A FastAPI + LangGraph service that answers natural-language financial questions by routing them across **SQL** (structured company and financial data), **vector/RAG retrieval** (news, filings, earnings coverage), and **live market data**, then scores, ranks and synthesizes the results into a cited report that a reviewer node fact-checks before it is returned.

Around that pipeline sit the parts that make its quality measurable: a 100-question benchmark with versioned ground truth, RAGAS and custom evaluators, a claim-level audit, an escalation path for low-confidence answers, and a dashboard for reading the results.

## Contents

- [Architecture](#architecture)
- [Deployment modes](#deployment-modes)
- [Request flow](#request-flow)
- [API reference](#api-reference)
- [Data model](#data-model)
- [Evaluation](#evaluation)
- [Security](#security)
- [Setup](#setup)
- [Configuration](#configuration)
- [Seeding and the frozen snapshot](#seeding-and-the-frozen-snapshot)
- [Deployment](#deployment)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Known issues](#known-issues)

## Architecture

The system is a set of **LangGraph state graphs** orchestrating LLM calls, tool use and retrieval:

```
                   ┌──────────────────────────────────────────┐
                   │              financial_graph             │
                   │      (backend/graph/financial_graph.py)  │
                   └──────────────────────────────────────────┘

  intent → planner → retrieval → scoring → analysis → reviewer ──┐
                        ▲                                        │
                        └────────── retry (should_retry) ────────┘
                                                                 │
                                                                 ▼
                                                                END
```

- **intent_node** — classifies the query into `VALUATION | GROWTH | SENTIMENT | MIXED` (small tier, structured output).
- **planner_node** — decomposes the query into `sql_query`, `vector_query`, `market_query` (tickers) and a `strategy` (`PARALLEL` / `SQL_FIRST` / `VECTOR_FIRST`).
- **retrieval** — an async node wrapping `hybrid_retrieve_async`. Intent-based branching happens here, not at the graph-edge level.
- **scoring_node** — reranks retrieved companies (`backend/scoring/ranker.py`), attaches evidence and explainability.
- **analysis_node** — synthesizes a structured report with per-company recommendations and cited evidence (large tier).
- **reviewer_node** — fact-checks the draft against its evidence (confidence thresholds, missing evidence, citation validation, hallucination check) and either approves it as `final_report` or loops back to retrieval, up to 3 retries before force-passing.

`market_node`, `sql_node`, `vector_node` and `reranker_node` provide the single-source work the retrieval stage composes. Two sub-graphs implement single-source retrieval as **ReAct tool-calling agents** and are exposed on their own routes in `full` mode:

- **`sql_graph.py`** — an LLM bound to SQL tools (schema lookup, query generation, validation, execution, error-fix) looping against `tools` until done or 3 failed fix attempts.
- **`vector_graph.py`** — an LLM bound to a single `retrieve_similar` tool.

### Hybrid retrieval

`backend/retrieval/hybrid_retrieval.py` fans work out based on intent:

| Intent | Sources | Weights |
|---|---|---|
| `VALUATION` / `GROWTH` | SQL only | SQL 100% |
| `SENTIMENT` | Vector only | Vector 100% |
| `MIXED` | SQL + Vector + Market, in parallel | SQL 40 / Vector 30 / Market 30, redistributing to 60/40 when market data is unavailable |
| `OUT_OF_SCOPE` | none — the graph exits at the classifier | — |

`VALUATION` and `GROWTH` are answered from columns, so the reviewer accepts the metrics table as evidence for them. Requiring a document chunk to support a database fact is the same error the retrieval-precision metric made, and it turned every numeric question into a refusal. Narrative intents still require a retrieved document, and no evidence at all remains a failure for every intent.

Per-source timeouts are SQL 45s, Vector 10s, Market 8s, with a 60s ceiling on the `MIXED` fan-out and graceful degradation on partial failure. `combine_results()` derives an `overall_confidence` from whichever sources actually returned.

### The retrieval stack

Vector search is two-stage by default. A raw pgvector cosine query over `document_chunks` pulls `top_k × 4` candidates, which `rank_bm25.BM25Plus` then reranks against LLM-extracted financial keywords. Two further stages exist behind per-run flags and are **off by default**:

| Stage | Module | Default | Cost |
|---|---|---|---|
| pgvector ANN | `vector_search.py` | always | a query |
| BM25 **rerank** | `vector_search.py` — `bm25_rerank()` | always | pure Python |
| BM25 **corpus-wide** + reciprocal rank fusion | `lexical_search.py` + `fusion.py` | off | an in-memory index; fusion is `1/(60 + rank)` |
| Cross-encoder rerank | `cross_encoder.py` | off | loads torch, ~270 MB, plus per-query inference |

There are two distinct BM25 stages and they are easy to confuse. `bm25_rerank` reorders what pgvector already returned, so it can only change the order of that list. `search_chunks_lexical` ranks the *whole* corpus independently, which is what reciprocal rank fusion needs — fusing two lists that cannot disagree adds nothing.

Those flags are set per benchmark run, which is what they were built for: they make retrieval variants measurable against the same questions. A live query sets none of them and runs the baseline.

Query embeddings are cached in Redis for 30 days, keyed on a SHA-256 of `(model, exact text)`. The key is deliberately exact rather than semantic — the benchmark contains near-identical questions like *"the 5 companies with the strongest revenue growth"* and *"the 10"*, which differ by one digit and have different correct answers.

### Scoring and ranking

`backend/scoring/ranker.py` computes four normalized (0–1) dimension scores per company — **valuation** (P/E and price momentum), **growth** (revenue growth and EPS sign), **relevance** (mean chunk similarity) and **sentiment** (positive/negative term ratio in matched chunks) — combined with weights that shift according to which sources actually returned data, optionally blended 70/30 with an LLM holistic score.

`evidence_builder.py` attaches per-company citations (`NVDA-sql-1`, `NVDA-vector-2`, `NVDA-market-1`), and `score_normalizer.py` produces the explainability breakdown and recommendation bucket. Dimensions with no data are reported as `unmeasured` rather than scored as zero.

### Model configuration

Models are **not hardcoded**. Providers and their models live in the `llm_providers` and `llm_models` tables, and the pipeline asks for a tier — `small`, `medium` or `large` — rather than a model name. Provider API keys are stored Fernet-encrypted under `LLM_KEY_ENCRYPTION_SECRET`; nothing reads a provider key from the environment.

This is what lets the same code run on OpenAI locally and on Groq for a public deployment, where an unauthenticated endpoint makes a free tier the difference between a rate limit and a bill. The one exception is embeddings: `text-embedding-3-small` (1536-dim) via `OPENAI_API_KEY`, because Groq has no embeddings API.

## Deployment modes

`DEPLOYMENT_MODE` decides which routers are mounted, and the absence is the control — unlinking a route from the UI leaves it reachable, so a public deployment must not mount it at all.

| | `portfolio` | `full` |
|---|---|---|
| Auth | none — no login route is mounted | JWT, roles enforced per router |
| Mounted | the financial query endpoint, `/health` | everything |
| Absent | admin, indexing, ingestion, evaluation, claims, escalations, SQL and vector routes | — |
| Control on cost | per-IP rate limit | login |

`/health` reports `auth_required`, and the frontend reads it to decide whether to render a sign-in screen — rather than probing an auth route that may not exist.

### Environments

Mode and environment are related but not the same thing, and comments in this
repository name the environment whenever a number depends on it. There are three:

| | **local** | **preprod** | **production** |
|---|---|---|---|
| Purpose | development and the test suite | the public demo anyone can open | the deployment the infrastructure targets |
| Mode | `full` | `portfolio` | `full` |
| Host | docker compose | Render, one web service | AWS ECS Fargate |
| Size | your machine | **0.5 CPU / 512 MB**, one instance | task-sized, `desired_count = 1`, no autoscaling |
| Database | local Postgres + pgvector | Neon | RDS |
| Redis | compose service | Render, set in the dashboard | a sidecar container in the same task |
| Provider | whatever is default in your database | Groq free tier — **200,000 tokens/day** | metered |
| Auth | login | none, by design | login |

**Most tight numbers in this repository are preprod numbers.** 512 MB, 0.5 CPU,
the 200,000-token daily ceiling and the two-query concurrency bound all describe
the Render deployment, because that is the constrained one and the one the
public can reach. Production sizing is Terraform's business and is set in
`infrastructure/production/`.

Two consequences worth stating, because they are easy to read the wrong way:

- **The concurrency bound and the rate limiter are process-local.** On preprod
  that is the true ceiling, because there is one instance. On production with
  more than one task they bound each task rather than the service, and the
  count belongs in Redis.
- **The EDGAR rate limiter has the same shape.** Its lock is per-process while
  the NAT gateway's address is shared, so it is correct at
  `desired_count = 1` and one Terraform line away from being silently wrong.

## Request flow

1. Client `POST`s a natural-language question to `/api/retrieve/financial`.
2. `intent_node` classifies it as `VALUATION`, `GROWTH`, `SENTIMENT`, `MIXED` or `OUT_OF_SCOPE`. The last exits here — a greeting is answered in about a second rather than researched for forty. `planner_node` splits the rest into per-source sub-queries.
3. `hybrid_retrieve_async` fans out to SQL, vector and market retrieval per the intent-weight table.
4. `scoring_node` ranks companies and attaches evidence.
5. `analysis_node` drafts a structured report citing that evidence.
6. `reviewer_node` fact-checks the draft. A retry goes back to **analysis**, not retrieval: by that point the query, the cohort and the corpus are fixed, so re-retrieving returns the same documents and raises the same flags. What can differ is the draft, because the rejected claims are handed to the analysis prompt.

A retry is also skipped when this attempt's feedback is identical to the last one's — the same flags produced the same draft once already.

The reviewer has four terminals: `approved`, `forced_pass` at the retry limit, and two that withhold the ranking rather than present it as reviewed — `withheld_review_unavailable` when the fact-checking model could not be reached, and `withheld_provider_unavailable` when the provider refused the analysis call. Those two exist because a transport failure is not a finding about the answer, and telling a reader "the reviewer raised 0 unresolved issues" while withholding their result is worse than telling them nothing.

## API reference

### Available in every mode

`POST /api/retrieve/financial`

```jsonc
// request
{ "query": "Compare valuation and sentiment for NVDA and AMD" }
// response
{ "query": "...", "final_report": { ... }, "result": { ... } }
```

Query length is bounded to 3–500 characters. In `full` mode this route requires the analyst role; in `portfolio` mode it is public and the rate limiter is the only ceiling.

`GET /health` — Postgres and Redis connectivity plus the deployment's auth posture: `{status, db, redis, auth_required}`. Redis reporting `error` is not fatal; every caller fails open.

### `full` mode only

| Prefix | Purpose |
|---|---|
| `POST /api/retrieve/sql` | SQL agent alone |
| `POST /api/retrieve/vector` | Vector/RAG agent alone |
| `POST /api/index/documents` | (Re)index one document or all unindexed ones, as a background task |
| `/api/ingestion` | Upload, EDGAR collection, ingestion job status and event log |
| `/api/evaluation` | Benchmark runs, metrics, per-question results, claim audit |
| `/api/auth` | Sign-in, token issue, current user |
| `/admin/llm` | Provider and model configuration |
| `/admin/escalations` | Low-confidence answers queued for human review |
| `/admin/security` | Security event feed |
| `/api/admin` | External console links |

## Data model

Postgres with pgvector, via SQLAlchemy (`backend/models/db_models.py`). 23 tables:

**Corpus and reference**
`companies`, `financial_metrics`, `documents`, `document_chunks` (a `Vector(1536)` column — chunk-level, after embeddings were migrated off `documents`), `themes`, `company_themes`.

**Configuration**
`llm_providers` (encrypted keys, a partial unique index enforcing at most one default), `llm_models` (one model per provider per tier), `users`.

**Evaluation**
`benchmark_runs`, `evaluation_metrics`, `question_results`, `claim_evaluations`, `escalations`, `human_reviews`.

**Operations**
`ingestion_events` (one row per attempt, including the attempts that produced no document — duplicates, unreadable PDFs), `system_logs`, `retrieval_logs`, `retrieved_evidence`, `model_costs`, `alembic_version`.

### A note on migrations

Two things write this schema: SQLAlchemy's `create_all` in the app lifespan, and Alembic's 23 revisions. The Alembic chain begins at *"add embedding column to documents"* — it **alters** base tables rather than creating them, because those tables already existed when the chain started.

So `alembic upgrade head` is only correct against a database Alembic has already seen. On an empty database it fails on a table that does not exist yet. `backend/startup_migration.py` decides which case applies by looking for the version table, and stamps rather than replays when the schema came from the models. Use it instead of calling Alembic directly.

## Evaluation

100 golden questions, split 30 valuation / 30 growth / 25 sentiment / 15 mixed, plus a 4-question `smoke` set and an env-driven `focus` set for iterating on specific questions.

Ground truth is maintained in two halves for a reason:

- **Derived** — the 60 valuation and growth questions are generated from specifications in `question_bank.py` by querying the seeded database. Never hand-edited; regenerate after every reseed.
- **Authored** — the sentiment and mixed questions carry reference answers and reference contexts written by a human. A model-written reference would only confirm the model's own output.

```bash
uv run python -m backend.evaluation.datasets.generate_ground_truth   # rebuild derived rows
uv run python -m backend.evaluation.datasets.verify_ground_truth     # check everything, non-zero on drift
```

**Reseeding invalidates all of it.** The seed pulls live fundamentals, so market caps and P/E ratios move and the membership of a "top five" can change outright — one reseed dropped NVDA out of the five smallest technology market caps and brought CRM in. The pipeline then answers correctly and the benchmark marks it wrong, which looks exactly like a regression. This is what the [frozen snapshot](#seeding-and-the-frozen-snapshot) exists to prevent.

Beyond RAGAS, a **claim audit** extracts individual factual claims from an answer and checks each against the retrieved evidence, so an answer that is right overall but unsupported in one sentence is visible as such.

### What the database records, and what LangSmith does

Three systems observe a run and the split between them is deliberate.

**LangSmith owns the trace hierarchy.** LangGraph opens one run per registered
node and the retrieval branches carry `@traceable` — 57 instrumented spans. For
inspecting a single query after the fact, nothing here competes with it, and
`observability/tracing.py` deliberately avoids adding a second span per node.

**The database keeps what has to be joined or aggregated.** *"p95 latency for
withheld answers on healthcare questions last week"* needs traces joined to
decisions and to the corpus; that is one SQL query and an export-and-spreadsheet
exercise anywhere else. It also survives a third party's quota and retention,
and an enterprise deployment that cannot send data outside its own network.

| Table | Written | Earns its place by |
|---|---|---|
| `retrieval_logs` | per live query | percentile latency and the withheld share, grouped by decision |
| `model_costs` | per benchmark run | which node spends the money — one call was 91% of it |
| `retrieved_evidence` | per benchmark question | diffing which chunks two retrieval arms surfaced |

Three tables were dropped rather than filled, each because something else
already answered the question:

- **`alerts`** — threshold-breach alerting that was never built, with no
  destination for an alert and no plan to add one.
- **`pipeline_traces`** — `node_name`, `latency_ms`, `tokens_in`, `tokens_out`
  and `cost_usd`, four of which `model_costs` now holds, with latency already
  in `node_timings` and the trace detail already in LangSmith.
- **`human_reviews`** — a human rating a *benchmark* answer. The review loop
  that matters runs on `escalations`, which already carries `status`,
  `reviewed_by`, `resolution_note` and `reviewed_at`, is served by
  `GET /api/escalations` and `POST /api/escalations/{id}/resolve`, and is read
  by the admin screen. A second loop for grading evaluation output is one we
  decided against — authored ground truth is written before a run, not rated
  after it.

## Security

`backend/security/` runs on the query path, measured at roughly 0.4 ms in total against a pipeline that takes 10–45 seconds:

- **input_guard** — prompt-injection and abuse patterns
- **pii** — detection over inbound text
- **output_validator** — checks on what the pipeline is about to return
- **rate_limit** — per-caller ceiling, Redis-backed, **fails open** by design so a cache outage does not become an outage
- **concurrency** — a ceiling on how many queries run *at once*, across all callers, refusing the surplus with a `Retry-After` rather than queueing them. Not a substitute for the line above: several callers are several addresses, each inside its own per-caller limit, and all their pipelines start together on one small instance
- **llm_guard** — an optional LLM-based check, off by default because it costs an API round trip per query

Every layer records what it did to `system_logs`, which the admin security feed reads.

## Setup

Requires Python 3.13 (`.python-version`) and [`uv`](https://github.com/astral-sh/uv).

```bash
# Postgres (pgvector) + Redis
docker compose up -d postgres redis

# Dependencies
uv sync

# Schema. NOT `alembic upgrade head` on a fresh database — see the note above.
uv run python -m backend.startup_migration
uv run uvicorn backend.main:app --reload --port 8000
```

The first server start creates any missing tables via `create_all`. Load data with either the [live seed or the frozen snapshot](#seeding-and-the-frozen-snapshot).

The frontend is a separate Vite app:

```bash
cd frontend && npm install && npm run dev     # :5173
```

It calls the API through a Vite dev proxy rather than directly, because the backend registers no CORS middleware and the frontend uses relative `/api` paths throughout. Every deployment therefore serves both halves from one origin, or rewrites `/api` and `/health` to the API.

## Configuration

Loaded from `.env` by `backend/config.py` (`pydantic-settings`). Environment variables take precedence over the file.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | — | Postgres, async driver (`postgresql+asyncpg://`) |
| `SYNC_DATABASE_URL` | yes | — | Postgres, sync driver — Alembic and the SQL agent |
| `LLM_KEY_ENCRYPTION_SECRET` | yes | — | Fernet key for provider API keys in `llm_providers` |
| `REDIS_URL` | no | `redis://localhost:6379/0` | Cache and rate-limit store; unreachable is tolerated, blank is not |
| `OPENAI_API_KEY` | for embeddings | `""` | `text-embedding-3-small` only; chat models come from the database |
| `DEPLOYMENT_MODE` | no | `full` | `portfolio` or `full` — see [Deployment modes](#deployment-modes) |
| `APP_ENV` | no | `development` | Environment name |
| `JWT_SECRET` | for `full` | `""` | Signs access tokens; no default on purpose |
| `JWT_EXPIRE_HOURS` | no | `12` | Token lifetime |
| `ADMIN_API_KEY` | no | `""` | Guards the indexing route; empty means refuse |
| `SECURITY_RATE_LIMIT` | no | `20` | Requests per window, per caller |
| `SECURITY_RATE_WINDOW_SECONDS` | no | `60` | Window length |
| `SECURITY_LLM_GUARD_ENABLED` | no | `false` | The optional LLM guard |
| `READONLY_DATABASE_URL` | no | `""` | SELECT-only role for generated SQL; falls back to `DATABASE_URL` |
| `SEC_USER_AGENT` | for EDGAR | `""` | SEC requires a caller and contact; empty disables the collector |
| `ALPHA_VANTAGE_API_KEY` | for seeding | `""` | News sentiment during a live seed |
| `AWS_REGION`, `RAW_BUCKET`, `PROCESSED_BUCKET`, `INGESTION_QUEUE_URL` | no | — | The S3 → SQS → worker ingestion path; empty means the fetcher writes straight to Postgres |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGCHAIN_PROJECT` | no | — | Tracing |
| `CLOUDWATCH_LOGS_URL`, `LANGSMITH_PROJECT_URL` | no | `""` | Console links for the admin rail |

Two notes worth knowing before a deployment fails obscurely:

- **`backend.main` cannot be imported without `OPENAI_API_KEY`.** `OpenAIEmbeddings` is constructed at module scope and validates credentials on construction, so uvicorn exits at import from a clean shell. Export `.env` first.
- **A blank `REDIS_URL` is worse than a missing one.** Missing falls back to the default; blank is a string `redis.from_url` rejects at import.

**Docker Compose ports:** Postgres `5433→5432`, Redis `6379→6379`, API `8000→8000`.

## Seeding and the frozen snapshot

`seeds/companies.csv` lists 50 tech-heavy tickers. `seeds/seed_data.py` repopulates `companies`, `financial_metrics` and `documents` from live fundamentals and news, sleeping 12s between companies to respect rate limits — a full run takes roughly 10 minutes and **changes the ground under the benchmark**.

`seeds/snapshot.py` exists to break that dependency:

```bash
uv run python -m seeds.snapshot create    # freeze the current database
uv run python -m seeds.snapshot restore   # load the frozen data back
uv run python -m seeds.snapshot verify    # compare database against file
```

The snapshot captures companies, themes, metrics, documents and `document_chunks` **including each chunk's embedding**, so a restore needs no embedding API call and vector search returns the same chunks every run. Primary keys are preserved and sequences reset afterwards, so foreign keys survive the round trip.

With the snapshot restored, a score change can only have come from the code. What it does not capture is live market data, which is fetched at query time — a `MIXED` question still varies by however much prices moved.

## Deployment

**The preprod deployment** runs on managed services, none of which need an always-on machine:

| Piece | Service | Why |
|---|---|---|
| API | Render web service (Docker) | A query takes ~95s, which rules out any serverless host with a short timeout |
| UI | Render static site | Never sleeps, so the page paints instantly and only the query waits |
| Database | Neon Postgres | Free tier supports pgvector and does not sleep |
| Cache | Upstash Redis | Makes the rate limit real and the embedding cache shared |

`infrastructure/preprod/render.yaml` is the blueprint, and it carries the reasoning for each choice in comments. The static site rewrites `/api/*` and `/health` to the API, which keeps the browser same-origin — necessary because the backend mounts no CORS middleware.

**The AWS topology** is defined in `infrastructure/production/`: ALB → ECS Fargate (an API task and an ingestion worker sharing one image), RDS Postgres in private subnets, S3 → SQS → worker ingestion, and Secrets Manager, all in Terraform.

One gotcha it encodes: the ECS image serves the frontend from the same container, and it only has a frontend because `frontend/dist` exists in the developer's working tree at `docker build` time. `dist` is gitignored, so an image built from a clean clone is API-only and answers `/` with a 404. That is exactly why the Render deployment builds the UI as a separate static site instead.

## Project layout

```
backend/
  api/            FastAPI routers — financial, sql, vector, ingestion, evaluation,
                  claims, escalation, security, auth, admin
  graph/          LangGraph state graphs (financial, sql, vector) and the runner
  nodes/          Graph nodes — intent, planner, sql, vector, market, scoring,
                  reranker, analysis, reviewer
  retrieval/      Hybrid retrieval, pgvector search, BM25, RRF fusion,
                  cross-encoder, embedding cache, SQL execution, theme resolution
  scoring/        Ranking, evidence attachment, score normalization
  ingestion/      Upload, EDGAR collection, chunking, embedding, queue worker
  evaluation/     Question sets, ground-truth generation, RAGAS and custom
                  evaluators, benchmark runner, claim audit
  security/       Input guard, PII, output validation, rate limiting, event log
  auth/           Passwords, tokens, roles, dependencies
  escalation/     Low-confidence answers routed to human review
  llm/            Provider registry, tiers, key encryption, usage tracking
  observability/  Structured logging, node-boundary tracing, LangSmith setup
  services/       Postgres, Redis, market data
  models/         SQLAlchemy models
alembic/          23 migrations
seeds/            Reference data, live seed, frozen benchmark snapshot
tests/            101 test modules
frontend/         Vite + React + TypeScript
  src/components/ Query console, company cards, comparison table, details drawer
  src/evaluation/ Benchmark dashboard — runs, metrics, per-question, comparisons
  src/admin/      Providers, indexing, ingestion, human review
infrastructure/
  preprod/        Render blueprint and Vercel config
  production/     Terraform for the AWS topology
  shared/         ECR repository and ACM certificate
```

## Testing

```bash
uv run pytest -q
```

101 test modules. They are written as statements about behaviour rather than coverage of functions — `test_events_survive_a_restore.py`, `test_run_totals_survive_a_crash.py`, `test_every_question_resolves_its_cohort.py`, `test_sql_prompt_guardrails.py`.

Note that `.env` sets `DEPLOYMENT_MODE=portfolio` for local demo work, and the routers absent in that mode make their tests fail on a missing route. Run the full suite with `DEPLOYMENT_MODE=full`.

## Known issues

- **No CORS middleware.** `backend/main.py` registers none, so a browser app on a different origin cannot call the API. Every deployment shares an origin or rewrites `/api` and `/health`; local development uses the Vite proxy. Deliberate, but it constrains how the API can be consumed.
- **Escalation rows are written in `portfolio` mode and cannot be read back there.** `record_escalation` files a row in every mode; `escalation_router` is mounted only in `full`. That is deliberate — the rows record what the public demo declined to stand behind, and they are read out of band or by a full-mode deployment against the same database. Rows nobody serves are not the same as a table nobody writes.
- **`human_reviews` has a screen but no writer.** `HumanReviewScreen.tsx` is in the admin UI and `escalations` records that a report was withheld, but nothing records what a human then decided about one. Either the loop gets closed or the table goes.
- **The Alembic chain cannot build a database from scratch.** Its first revision alters tables that `create_all` is expected to have made. `backend/startup_migration.py` handles both cases; calling Alembic directly on an empty database does not.
- **`backend.main` imports ~235 MB.** It was 404 MB until `backend/_transformers_guard.py` stopped `langchain_core`'s import-time feature probe from pulling in torch, which arrives transitively through `docling`. Enabling the cross-encoder adds roughly 270 MB and would not fit a 512 MB instance. The text splitter is imported lazily for the same reason.
- **The public demo's provider has a daily token ceiling.** Groq's free tier allows 200,000 tokens per day for the whole organisation, and one question with retries can spend ten to twenty thousand — so the demo answers roughly twenty questions a day before refusing. It says so plainly when it happens. `scripts/switch_default_provider.py` moves the deployment to a metered provider when that matters, after proving the new one answers.
- **An LLM holistic score is blended into the ranking at a hardcoded 30%.** Nothing justifies 30 over 10 or 50. Either an ablation defends the weight or the component should go.
