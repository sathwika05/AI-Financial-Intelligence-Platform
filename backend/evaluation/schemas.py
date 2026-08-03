

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from openai import BaseModel
from pydantic import Field


class IntentType(str, Enum):
    VALUATION = "VALUATION"
    GROWTH = "GROWTH"
    SENTIMENT = "SENTIMENT"
    MIXED = "MIXED"

class BenchmarkStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class BenchmarkConfig(BaseModel):
    model: str
    embedding_model: str
    index_type: str
    retrieval_strategy: str
    reranking_strategy: str
    context_processing: str
    dataset: str
    question_set: str

    top_k: int = Field(default = 5, ge=1)
    benchmark_version: str = "v1"
    dataset_version: str = "v1"

class EvalQuestion(BaseModel):
    question_id: str
    question: str

    expected_intent: IntentType
    expected_tools: list[str] = Field(default_factory=list)

    reference_answer: str | None = None
    reference_contexts: list[str] = Field(default_factory=list)  

    expected_sql: str | None = None
    expected_sql_result: Any | None = None

    expected_ranking: list[str] = Field(default_factory=list)  
    

class PipelineExecution(BaseModel):
    actual_intent: str | None = None

    generated_sql: str | None = None
    sql_result: Any | None = None

    retrieved_contexts: list[str] = Field(default_factory=list)
    reranked_contexts: list[str] = Field(default_factory=list)

    market_result: Any | None = None

    ranked_companies: list[dict[str, Any]]= Field(
        default_factory=list
    )

    executed_tools: list[str] = Field(default_factory=list)

    final_answer: Any | None = None

    latency_ms: float | None = None
    cost_usd: float | None = None

    raw_state: dict[str, Any] = Field(default_factory=dict)

class EvaluatorResult(BaseModel):
    evaluator: str
    applicable: bool = True
    passed: bool | None = None

    metrics: dict[str, float | int | bool | None]=Field(
        default_factory=dict
    )

    errors: list[str] = Field(default_factory=list)

class QuestionEvaluationResult(BaseModel):
    question_id: str
    question: str

    expected_intent: str
    actual_intent: str | None = None

    execution: PipelineExecution
    evaluator_results: dict[str, EvaluatorResult] = Field(
        default_factory=dict
    )

    aggregate_metrics: dict[str, float] = Field(
        default_factory=dict
    )

    passed: bool = False
    error: str | None = None

class BenchmarkRunResult(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    status: BenchmarkStatus = BenchmarkStatus.PENDING

    config: BenchmarkConfig

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None

    question_results: list[QuestionEvaluationResult] = Field(
        default_factory=list
    )

    aggregate_metrics: dict[str, float] = Field(
        default_factory=dict
    )

    total_questions: int = 0
    passed_questions: int = 0
    failed_questions: int =0

    error: str | None = None