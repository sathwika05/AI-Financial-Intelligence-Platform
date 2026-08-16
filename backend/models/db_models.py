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

    content = Column(Text)
    doc_type = Column(String)
    source = Column(String)

    created_at = Column(
        DateTime,
        server_default=func.now(),
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
    __tablename__ = "retrieval_logs"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text)
    retrieval_path = Column(String)
    latency_ms = Column(Float)

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Benchmark and aggregate evaluation tables
# ---------------------------------------------------------------------------


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

    # Run-level dashboard KPIs.
    pass_rate = Column(
        Float,
        nullable=True,
    )
    route_accuracy = Column(
        Float,
        nullable=True,
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


class PipelineTrace(Base):
    """One row per graph node per run."""

    __tablename__ = "pipeline_traces"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        index=True,
    )

    node_name = Column(
        String,
        nullable=False,
    )
    started_at = Column(DateTime)
    ended_at = Column(DateTime)
    latency_ms = Column(Float)

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

    retry_count = Column(
        Integer,
        default=0,
    )

    # success / failed / retried
    status = Column(
        String,
        default="success",
    )

    error_msg = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
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

    filename = Column(String)
    snippet = Column(Text)
    relevance_score = Column(Float)

    # sec_filing / earnings_call / news / fundamentals
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


class Alert(Base):
    """Threshold breach generated from evaluation or observability metrics."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
        nullable=True,
    )

    # hallucination / latency / retry_rate / cache_hit
    alert_type = Column(String)

    threshold = Column(Float)
    actual_value = Column(Float)

    # warning / critical
    severity = Column(String)

    triggered_at = Column(
        DateTime,
        server_default=func.now(),
    )
    resolved_at = Column(
        DateTime,
        nullable=True,
    )


class HumanReview(Base):
    """Human feedback that may later be synchronized with LangSmith."""

    __tablename__ = "human_reviews"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("benchmark_runs.run_id"),
    )

    question = Column(Text)
    answer = Column(Text)

    # Expected range: 1 through 5.
    rating = Column(Integer)

    reviewer_notes = Column(
        Text,
        nullable=True,
    )

    reviewed_at = Column(
        DateTime,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Configurable LLM provider and model tables
# ---------------------------------------------------------------------------


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