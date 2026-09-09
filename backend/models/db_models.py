import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from backend.services.postgres_service import Base


# ---------------------------------------------------------------------------
# Financial data tables
# ---------------------------------------------------------------------------


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    ticker = Column(String, unique=True)
    sector = Column(String)
    market_cap = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class Theme(Base):
    """
    A category a company can belong to — "AI", "Semiconductors", "Cloud".

    `sector` is the only categorical column the database had, and it holds
    eight broad values that cannot express any of these. Asked for
    "AI-related stocks", the SQL generator had nothing to filter on and
    invented one, ending up with

        WHERE EXISTS (SELECT 1 FROM documents d
                      WHERE d.company_id = c.id AND d.content ILIKE '%AI%')

    which selected 35 of 50 companies, because '%AI%' matches the letters
    "ai" inside words like "maintains". A theme is the structured fact that
    makes the question answerable instead of guessable.
    """

    __tablename__ = "themes"

    id = Column(Integer, primary_key=True, index=True)

    # Display form, e.g. "Cloud Computing".
    name = Column(String, nullable=False)

    # Canonical lookup key, e.g. "cloud". Queries match on this so that
    # wording differences in the question never reach the database.
    slug = Column(String, nullable=False, unique=True)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


class CompanyTheme(Base):
    """
    Membership of a company in a theme.

    Many-to-many on purpose: NVDA is both AI and Semiconductors, and AI
    contains many companies. A `theme` column on `companies` would allow
    only one, and adding a boolean column per theme would need a migration
    for every new category.

    Curated rather than derived. A news article mentioning a topic does not
    place the company it is filed under in that category, which is the
    mistake this table exists to stop being repeated at query time.
    """

    __tablename__ = "company_themes"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    theme_id = Column(
        Integer,
        ForeignKey("themes.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        # One row per pair; re-running the theme seed must not accumulate
        # duplicates.
        UniqueConstraint(
            "company_id",
            "theme_id",
            name="uq_company_themes_company_theme",
        ),
        # Resolving a theme to its companies is the read this table exists
        # for, and it filters on theme_id.
        Index(
            "ix_company_themes_theme_id",
            "theme_id",
        ),
    )


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
    )

    pe_ratio = Column(Float)
    eps = Column(Float)
    revenue_growth = Column(Float)

    updated_at = Column(
        DateTime,
        server_default=func.now(),
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
    )

    title = Column(String)
    content = Column(Text)
    doc_type = Column(String)
    source = Column(String)

    # Canonical article URL — tracking parameters stripped — used as the
    # primary duplicate identity. Nullable because a provider may omit it,
    # and Postgres allows repeated NULLs in a unique index, so articles
    # without a URL fall back to content_hash alone.
    source_url = Column(String)

    # SHA-256 of the whitespace-normalised content. The second duplicate
    # identity, for the same article republished under different URLs.
    content_hash = Column(String(64))

    # How strongly the provider associated this article with the owning
    # company. Alpha Vantage supplies it per ticker; Finnhub is already
    # company-scoped and leaves it null.
    relevance_score = Column(Float)

    # Where this document is in its ingestion. The row is written before
    # a single chunk exists, so without this a document whose embedding
    # failed is indistinguishable from one that worked -- both are a row
    # with no chunks. Not read by retrieval.
    #
    #   processing  stored, not yet indexed
    #   ready       indexed and retrievable
    status = Column(
        String(16),
        nullable=False,
        server_default="ready",
        index=True,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        # Enforced in the database rather than only in the seed, so a
        # duplicate cannot be introduced by any other writer.
        UniqueConstraint(
            "source_url",
            name="uq_documents_source_url",
        ),
        UniqueConstraint(
            "content_hash",
            name="uq_documents_content_hash",
        ),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
    )

    # Position of this chunk inside its source document.
    chunk_index = Column(Integer)

    # A chunk identity that survives reindexing, derived from the
    # document, the position and the content. The primary key does not:
    # it is reassigned every time a document is reindexed, which leaves
    # "did this document's chunks actually change?" unanswerable.
    # Nullable because every chunk written before this column predates it.
    chunk_uid = Column(String(64), index=True)

    # The heading this chunk fell under, where the document had any.
    # Docling recovers a filing's sections; without this a passage about
    # margins has nothing to say it came from Item 7.
    section = Column(String)

    # Text used for retrieval and answer generation.
    content = Column(Text)

    # OpenAI text-embedding-3-small currently produces 1,536 dimensions.
    embedding = Column(
        Vector(1536),
        nullable=True,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


class RetrievalLog(Base):
    """
    One row per answered query, for counting rather than for reading.

    system_logs holds text lines a person reads. This holds a row a
    person aggregates: percentile latency, queries per day, which route
    is slowest. No amount of grep over log text produces a p95.
    """

    __tablename__ = "retrieval_logs"

    id = Column(Integer, primary_key=True, index=True)

    # PII-masked and truncated. This is a public unauthenticated endpoint
    # in portfolio mode, so what people type is not assumed to be safe to
    # keep -- the same treatment security events already give it.
    query = Column(Text)

    # The classified intent, which is what decided the route:
    # VALUATION / GROWTH / SENTIMENT / MIXED / OUT_OF_SCOPE.
    retrieval_path = Column(String)

    latency_ms = Column(Float)

    # How it ended. Without this, "p95 latency" averages together answered
    # queries and out-of-scope refusals that returned in a second, which
    # describes neither population.
    decision = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Benchmark and aggregate evaluation tables
# ---------------------------------------------------------------------------


class User(Base):
    """
    A person who can sign in.

    Two roles only -- see backend/auth/roles.py. The password is stored as
    a bcrypt hash; nothing anywhere keeps the plaintext.
    """

    __tablename__ = "users"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Case-insensitive in practice: the login path lowercases before
    # looking up, so "A@b.com" and "a@b.com" are the same account.
    email = Column(
        String,
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash = Column(
        String,
        nullable=False,
    )

    # "admin" or "analyst". Stored as text rather than a database enum so
    # adding a role later does not need a migration on this column.
    role = Column(
        String,
        nullable=False,
        default="analyst",
    )

    # Disabling beats deleting: it keeps the audit trail intact and stops
    # the login immediately.
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class BenchmarkRun(Base):
    """
    One row per benchmark run.

    The UI sends only provider_id. The backend resolves that provider's
    enabled small, medium, and large models and stores their names in model.
    """

    __tablename__ = "benchmark_runs"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Public benchmark identifier used by API routes and evaluation_metrics.
    run_id = Column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )

    # Selected provider from the benchmark UI.
    provider_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "llm_providers.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # Snapshot for easy dashboard display even if provider data later changes.
    provider_name = Column(
        String(50),
        nullable=True,
    )

    # Resolved tier snapshot, for example:
    # small=gpt-5.4-nano, medium=gpt-5.4-mini, large=gpt-5.6-sol
    model = Column(
        String,
        nullable=True,
    )

    dataset = Column(String)
    retrieval_mode = Column(String)
    question_set = Column(String)
    company_filter = Column(
        String,
        default="all",
    )

    # queued / running / completed / failed
    status = Column(
        String,
        default="queued",
    )

    total_requests = Column(
        Integer,
        default=0,
    )
    total_cost = Column(
        Float,
        default=0.0,
    )

    # Raised by the cancel endpoint, read by the runner between questions.
    # Server-side default so rows written before this column existed read
    # as "not cancelled" rather than NULL.
    cancel_requested = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # Run-level dashboard KPIs.
    pass_rate = Column(
        Float,
        nullable=True,
    )
    route_accuracy = Column(
        Float,
        nullable=True,
    )

    # Which retrieval pipeline produced this run.
    #
    # Both off is the baseline that every run before these existed used,
    # hence the false server_default: an old row is not unknown, it is
    # known to have been the baseline.
    rrf_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    cross_encoder_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    benchmark_version = Column(
        String(20),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )
    dataset_version = Column(
        String(20),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )
    completed_at = Column(
        DateTime,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )


class EvaluationMetric(Base):
    """
    One aggregate metrics row per benchmark run.

    Metric names intentionally match the evaluation code and dashboard.
    The canonical RAGAS field is response_relevancy.
    """

    __tablename__ = "evaluation_metrics"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    run_id = Column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # RankingEvaluator
    # ------------------------------------------------------------------

    precision_at_k = Column(Float)
    recall_at_k = Column(Float)
    mrr = Column(Float)
    ndcg_at_k = Column(Float)
    k = Column(
        Integer,
        default=5,
    )

    # ------------------------------------------------------------------
    # RagasEvaluator
    # ------------------------------------------------------------------

    faithfulness = Column(Float)

    # Canonical project/database name.
    # Do not use answer_relevance or response_relevance.
    response_relevancy = Column(Float)

    context_precision = Column(Float)
    context_recall = Column(Float)
    context_entity_recall = Column(Float)
    noise_sensitivity = Column(Float)

    # Derived explicitly by an evaluator or as 1 - faithfulness fallback.
    hallucination_rate = Column(Float)

    # ------------------------------------------------------------------
    # IntentEvaluator
    # ------------------------------------------------------------------

    intent_accuracy = Column(Float)

    # Question counts per actual execution route, for example
    # {"SQL Only": 7, "Vector Only": 8, "Hybrid": 5}.
    # Stored as JSON because the route set is defined by the pipeline, not
    # by this schema, and a column per route would need a migration each
    # time a route is added.
    route_distribution = Column(
        JSON,
        nullable=True,
    )

    # Per-route metric averages keyed by the same route names, for example
    # {"SQL Only": {"count": 7, "pass_rate": 0.86, "sql_accuracy": 0.94, ...}}.
    # Every canonical metric is stored so the dashboard can choose which to
    # show per route without another migration.
    route_performance = Column(
        JSON,
        nullable=True,
    )

    # Per-tool invocation counts, for example
    # {"sql": {"calls": 7, "expected": 7, "hits": 7, "recall": 1.0, ...}}.
    tool_summary = Column(
        JSON,
        nullable=True,
    )

    # Mean wall-clock time per graph node, for example
    # {"retrieval": {"avg_latency_ms": 865.2, "executions": 20}}.
    node_latency = Column(
        JSON,
        nullable=True,
    )

    # Total LLM tokens consumed across the run, measured per call.
    total_tokens = Column(Integer)

    # ------------------------------------------------------------------
    # SQLEvaluator
    # ------------------------------------------------------------------

    sql_accuracy = Column(Float)
    sql_equivalence = Column(Float)

    # ------------------------------------------------------------------
    # ToolEvaluator
    # ------------------------------------------------------------------

    tool_accuracy = Column(Float)
    tool_precision = Column(Float)
    tool_recall = Column(Float)
    tool_f1 = Column(Float)

    # ------------------------------------------------------------------
    # MarketEvaluator
    # ------------------------------------------------------------------

    market_accuracy = Column(Float)

    # ------------------------------------------------------------------
    # Runtime performance and cost
    # ------------------------------------------------------------------

    avg_latency_ms = Column(Float)
    p50_latency = Column(Float)
    p95_latency = Column(Float)
    p99_latency = Column(Float)

    cost_per_request = Column(Float)
    total_cost = Column(Float)

    # ------------------------------------------------------------------
    # Benchmark configuration snapshot
    # ------------------------------------------------------------------

    dataset = Column(String)
    model = Column(String)
    retrieval_mode = Column(String)
    question_set = Column(String)
    total_requests = Column(Integer)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Optional observability and human-review tables
# ---------------------------------------------------------------------------


class QuestionResult(Base):
    """
    One question's outcome within a benchmark run.

    evaluation_metrics holds a single averaged row per run, so until this
    existed nothing recorded how an individual question scored. The only
    trace was a log line, which meant a question could not be compared
    across runs, a regression could not be attributed to the question that
    caused it, and the dashboard could show a run's average but never its
    shape.

    evaluator_results is stored whole rather than flattened into columns.
    Evaluators come and go — ragas and market do not apply to every
    question, and sql gained order and top-k diagnostics recently — so a
    column per metric would need a migration each time and would leave
    every earlier row null for the new ones. The averaged, queryable copy
    already exists on evaluation_metrics; this keeps the detail.
    """

    __tablename__ = "question_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        index=True,
    )

    question_id = Column(String, nullable=False, index=True)
    question = Column(Text)

    expected_intent = Column(String)
    actual_intent = Column(String)

    overall_score = Column(Float)
    passed = Column(Boolean)

    # Per-evaluator scores, metrics and details, exactly as scored.
    evaluator_results = Column(
        JSON,
        nullable=True,
    )

    # Flattened "<evaluator>.<metric>" values, matching what
    # finalize_question_result already computes for the run aggregate.
    aggregate_metrics = Column(
        JSON,
        nullable=True,
    )

    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        # A question appears once per run, so a re-persist updates rather
        # than accumulating duplicates.
        UniqueConstraint(
            "run_id",
            "question_id",
            name="uq_question_results_run_question",
        ),
    )


class ClaimEvaluation(Base):
    """
    One factual claim from one benchmark answer, and how it was judged.

    Separate from question_results, and deliberately not part of the
    benchmark's pass/fail. A question can pass every evaluator while
    asserting a figure no retrieved document carries; that is the failure
    this table exists to count.

    The evidence is stored per row rather than referenced. PipelineExecution
    is not persisted anywhere -- question_results keeps scores and evaluator
    details only -- so without a copy here the validation page could show a
    claim but never what it was judged against, and a label given without
    the evidence beside it is not worth recording.

    human_label is written only by a person, through the validation page.
    Re-running the evaluator overwrites evaluator_label and leaves the human
    column alone: the whole point is to compare the two, which is impossible
    if one can silently overwrite the other.
    """

    __tablename__ = "claim_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        index=True,
    )

    question_id = Column(String, nullable=False, index=True)

    # The expected intent, copied so the validation page can group by route
    # without joining back to question_results.
    route = Column(String)

    claim_index = Column(Integer, nullable=False)

    # What was judged: intensifiers stripped.
    claim = Column(Text, nullable=False)

    # What the answer actually said, so a human reads the sentence rather
    # than the reduction of it.
    original = Column(Text)

    # Numeric claims are held to the strict arithmetic rule, so which ones
    # they were has to survive into the row.
    is_numeric = Column(Boolean, default=False, index=True)
    numeric_values = Column(JSON, default=list)

    evidence = Column(JSON, default=list)

    evaluator_label = Column(String(24), nullable=False, index=True)
    evaluator_reasoning = Column(Text)
    evaluator_model = Column(String)

    # Never written by the evaluator.
    human_label = Column(String(24), nullable=True, index=True)
    human_labeled_by = Column(String, nullable=True)
    human_labeled_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    __table_args__ = (
        # A claim appears once per run, so re-persisting a run updates its
        # rows rather than accumulating duplicates.
        UniqueConstraint(
            "run_id",
            "question_id",
            "claim_index",
            name="uq_claim_evaluations_run_question_index",
        ),
    )


class RetrievedEvidence(Base):
    """Top evidence chunks retained for a benchmark run."""

    __tablename__ = "retrieved_evidence"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        index=True,
    )

    # Matches question_results.question_id, so the two join.
    #
    # run_id alone was the wrong grain. The reason to keep retrieved
    # evidence at all is to make an ablation explainable -- "which chunk
    # did the RRF arm surface that the dense arm ranked fourteenth" -- and
    # that question is per question, not per run. Without this the two
    # arms are two undifferentiated piles of rows.
    question_id = Column(String, nullable=True, index=True)

    filename = Column(String)
    snippet = Column(Text)
    relevance_score = Column(Float)

    # sql / vector / market -- the branch the evidence came from, which is
    # the distinction the RAGAS context metrics need: grading retrieval
    # over market rows measures the market API, not the document corpus.
    source_type = Column(String)

    rank_position = Column(Integer)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


class ModelCost(Base):
    """Per-node model token and cost breakdown."""

    __tablename__ = "model_costs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        index=True,
    )

    model = Column(String)
    node_name = Column(String)

    tokens_in = Column(
        Integer,
        default=0,
    )
    tokens_out = Column(
        Integer,
        default=0,
    )
    cost_usd = Column(
        Float,
        default=0.0,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


class SystemLog(Base):
    """Structured application log associated with a run or graph node."""

    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        nullable=True,
        index=True,
    )

    level = Column(String)
    node = Column(String)
    message = Column(Text)

    # Python attribute is meta_data; PostgreSQL column remains metadata.
    meta_data = Column(
        "metadata",
        JSON,
        default=dict,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Canonical examples: openai / anthropic / google_genai / groq.
    name = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )

    display_name = Column(
        String(100),
        nullable=False,
    )

    encrypted_api_key = Column(
        Text,
        nullable=False,
    )

    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    # Used automatically for normal, non-benchmark financial requests.
    is_default = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # untested / valid / invalid
    connection_status = Column(
        String(20),
        nullable=False,
        default="untested",
        server_default=text("'untested'"),
    )

    last_tested_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # PostgreSQL partial unique index: at most one default provider.
        Index(
            "uq_one_default_llm_provider",
            "is_default",
            unique=True,
            postgresql_where=text(
                "is_default = true"
            ),
        ),
    )


class LLMModel(Base):
    __tablename__ = "llm_models"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    provider_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "llm_providers.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # small / medium / large
    tier = Column(
        String(20),
        nullable=False,
    )

    # Exact model identifier accepted by the provider.
    model_name = Column(
        String(150),
        nullable=False,
    )

    display_name = Column(
        String(150),
        nullable=True,
    )

    input_cost_per_million = Column(
        Numeric(14, 8),
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    output_cost_per_million = Column(
        Numeric(14, 8),
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # One configured model per provider tier.
        UniqueConstraint(
            "provider_id",
            "tier",
            name="uq_provider_model_tier",
        ),
    )


class IngestionEvent(Base):
    """
    One attempt to bring a file into the corpus, however it ended.

    Everything else visible about ingestion is an outcome: a documents
    row, a status, a chunk count. A file that produced no row produced no
    trace either — a duplicate, an unreadable PDF, a filing whose text
    could not be read — and those are exactly the cases someone needs to
    see.

    Not read by retrieval. It exists so "did that work?" has an answer
    that does not involve reading a server log.
    """

    __tablename__ = "ingestion_events"

    id = Column(Integer, primary_key=True, index=True)

    # Which door the file came through: upload, sec_edgar, or s3 for the
    # bucket path. The route, not the publisher.
    source = Column(String(32), nullable=False, index=True)

    # What was attempted: a filename, an accession number, an object key.
    reference = Column(String, nullable=False)

    # One of ingestion.events_log.OUTCOMES.
    outcome = Column(String(16), nullable=False, index=True)

    # Why, for anything that is not "indexed". The only thing that makes
    # a failed row actionable.
    detail = Column(Text)

    # Set only when a document was actually stored.
    #
    # No foreign key, deliberately. An event records that a file was
    # attempted, which is a fact about the past; a document being deleted
    # does not unmake it. The key also made the log collateral damage of
    # snapshot restore, which truncates documents with CASCADE -- the log
    # vanished exactly when the corpus was reset, which is when someone
    # would want to read it.
    document_id = Column(Integer)
    chunks = Column(Integer)

    created_at = Column(DateTime, server_default=func.now(), index=True)


class Escalation(Base):
    """
    A query whose answer the system refused to show, waiting on a human.

    The reviewer withholds a ranking below ESCALATION_THRESHOLD, so the
    analyst gets a sentence instead of a table. This is where the ranking
    goes: without it an administrator can see that something was withheld
    but never what, which makes every row an investigation from scratch.

    Distinct from `human_reviews`, which hangs off benchmark_runs and
    rates a benchmark answer one to five. This is about a live analyst
    query, which has no run_id, and about a decision rather than a score.

    No foreign key to anything. An escalation records what the system did
    at a moment in time; a later reseed of the corpus does not unmake it.
    """

    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True, index=True)

    # The analyst's question, as asked.
    query = Column(Text, nullable=False)

    # VALUATION / GROWTH / SENTIMENT / MIXED, for triage.
    intent = Column(String(20))

    # What tripped the threshold. Kept as a number so the queue can be
    # read worst-first.
    confidence = Column(Float, nullable=False)

    # The sentence the analyst saw in place of the ranking.
    notice = Column(Text)

    # The draft the analyst did not see. The reason this table exists.
    withheld_report = Column(JSON)

    # The reviewer's own account of what was wrong with it.
    review_flags = Column(JSON)

    # pending | resolved | dismissed. See service.RESOLUTIONS.
    status = Column(
        String(16),
        nullable=False,
        server_default="pending",
        index=True,
    )

    reviewed_by = Column(String)
    resolution_note = Column(Text)
    reviewed_at = Column(DateTime)

    created_at = Column(
        DateTime,
        server_default=func.now(),
        index=True,
    )
