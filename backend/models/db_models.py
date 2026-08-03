

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func, UniqueConstraint, text
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from backend.services.postgres_service import Base


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key= True, index=True)
    name = Column(String, nullable=False)
    ticker = Column(String, unique=True)
    sector = Column(String)
    market_cap=Column(Float)
    created_at= Column(DateTime, server_default=func.now())

class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    id = Column(Integer, primary_key = True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    pe_ratio = Column(Float)
    eps = Column(Float)
    revenue_growth = Column(Float)
    updated_at = Column(DateTime, server_default=func.now())

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key = True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    content = Column(Text)
    doc_type = Column(String)
    source = Column(String)
    created_at = Column(DateTime, server_default=func.now())

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id         = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    chunk_index = Column(Integer)                        # which chunk number
    content     = Column(Text)                           # chunk text
    embedding   = Column(Vector(1536), nullable=True)    # chunk vector
    created_at  = Column(DateTime, server_default=func.now())

class RetrievalLog(Base):
    __tablename__="retrieval_logs"
    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text)
    retrieval_path = Column(String)
    latency_ms= Column(Float)
    created_at = Column(DateTime, server_default=func.now())

class EvaluationMetric(Base):
    """Extended — replaces your existing EvaluationMetric model."""
    __tablename__ = "evaluation_metrics"

    id = Column(Integer, primary_key= True, index=True)
    run_id = Column(PG_UUID(as_uuid=True))

    # Retrieval quality
    precision_at_k = Column(Float)
    recall_at_k = Column(Float)
    k = Column(Integer, default=5)

    # LLM quality (RAGAS)
    faithfulness        = Column(Float)
    answer_relevance    = Column(Float)
    context_precision   = Column(Float)
    context_recall      = Column(Float)
    hallucination_rate  = Column(Float)

    # Latency
    avg_latency_ms      = Column(Float)
    p95_latency         = Column(Float)
    p99_latency         = Column(Float)

    # Cost
    cost_per_request    = Column(Float)
    total_cost          = Column(Float)

    # Run context
    dataset             = Column(String)     # SEC Filings / Earnings Calls / etc
    model               = Column(String)     # gpt-4.1 / claude-3.5 / etc
    retrieval_mode      = Column(String)     # hybrid+reranker / sql_only / etc
    question_set        = Column(String)     # valuation / growth / sentiment / mixed
    total_requests      = Column(Integer)
 
    created_at          = Column(DateTime, server_default=func.now())


class BenchmarkRun(Base):
    """One row per benchmark run. Parent of all other observability tables."""
    __tablename__ = "benchmark_runs"
 
    id              = Column(Integer, primary_key=True, index=True)
    run_id          = Column(PG_UUID(as_uuid=True),unique=True,nullable=False,index=True,)
    dataset         = Column(String)
    model           = Column(String)
    retrieval_mode  = Column(String)
    question_set    = Column(String)
    company_filter  = Column(String, default="all")
    status          = Column(String, default="running")  # running / completed / failed
    error_message = Column(Text, nullable=True)

    total_requests  = Column(Integer, default=0)
    total_cost      = Column(Float, default=0.0)
    created_at      = Column(DateTime, server_default=func.now())
    completed_at    = Column(DateTime, nullable=True)

class PipelineTrace(Base):
    """One row per node per run. Feeds the pipeline execution trace panel."""
    __tablename__ = "pipeline_traces"
 
    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(PG_UUID(as_uuid=True),ForeignKey("benchmark_runs.run_id"),index=True,)
    node_name   = Column(String, nullable=False)
    started_at  = Column(DateTime)
    ended_at    = Column(DateTime)
    latency_ms  = Column(Float)
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    retry_count = Column(Integer, default=0)
    status      = Column(String, default="success")   # success / failed / retried
    error_msg   = Column(Text, nullable=True)
    created_at  = Column(DateTime, server_default=func.now())


class RetrievedEvidence(Base):
    """Top evidence chunks retrieved per run. Feeds evidence snippets panel."""
    __tablename__ = "retrieved_evidence"
 
    id              = Column(Integer, primary_key=True, index=True)
    run_id          = Column(PG_UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id"), index=True)
    filename        = Column(String)
    snippet         = Column(Text)
    relevance_score = Column(Float)
    source_type     = Column(String)   # sec_filing / earnings_call / news / fundamentals
    rank_position   = Column(Integer)
    created_at      = Column(DateTime, server_default=func.now())


class ModelCost(Base):
    """Per-node cost breakdown. Feeds cost by model bar chart."""
    __tablename__ = "model_costs"
 
    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(PG_UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id"), index=True)
    model       = Column(String)
    node_name   = Column(String)
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    created_at  = Column(DateTime, server_default=func.now())

class SystemLog(Base):
    """Structured log per node event. Feeds CloudWatch log tab."""
    __tablename__ = "system_logs"
 
    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(PG_UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id"), nullable=True, index=True)
    level       = Column(String)    # INFO / WARN / ERROR / DEBUG
    node        = Column(String)
    message     = Column(Text)
    meta_data = Column("metadata", JSON, default=dict)
    created_at  = Column(DateTime, server_default=func.now())


class Alert(Base):
    """Threshold breach alerts. Feeds alerts panel."""
    __tablename__ = "alerts"
 
    id              = Column(Integer, primary_key=True, index=True)
    run_id          = Column(PG_UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id"), nullable=True)
    alert_type      = Column(String)   # hallucination / latency / retry_rate / cache_hit
    threshold       = Column(Float)
    actual_value    = Column(Float)
    severity        = Column(String)   # warning / critical
    triggered_at    = Column(DateTime, server_default=func.now())
    resolved_at     = Column(DateTime, nullable=True)


class HumanReview(Base):
    """Human-in-the-loop ratings. Feeds LangSmith feedback sync."""
    __tablename__ = "human_reviews"
 
    id              = Column(Integer, primary_key=True, index=True)
    run_id          = Column(PG_UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id"))
    question        = Column(Text)
    answer          = Column(Text)
    rating          = Column(Integer)   # 1–5
    reviewer_notes  = Column(Text, nullable=True)
    reviewed_at     = Column(DateTime, server_default=func.now())

class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # openai / anthropic / google_genai / groq
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

    # Can this provider be used?
    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    # Used automatically for regular financial requests.
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
        Index(
            "uq_one_default_llm_provider",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true"),
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
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # small / medium / large
    tier = Column(
        String(20),
        nullable=False,
    )

    # Exact provider model ID.
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
        UniqueConstraint(
            "provider_id",
            "tier",
            name="uq_provider_model_tier",
        ),
    )


    


    