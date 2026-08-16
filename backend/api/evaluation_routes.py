"""
Evaluation API routes.

Endpoints:
    POST /api/evaluation/run          — trigger a benchmark run
    GET  /api/evaluation/runs         — list  benchmark runs
    GET  /api/evaluation/runs/{run_id} — get single run with metrics
    GET  /api/evaluation/metrics/comparison — retrieval mode comparison
    GET  /api/evaluation/metrics/timeseries — metrics over time for chart
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.evaluation.benchmark_runner import (
    BenchmarkRunner,
)
from backend.evaluation.schemas import (
    BenchmarkConfig,
)
from backend.graph.financial_graph import (
    financial_graph,
)
from backend.llm.llm_config_service import (
    LLMConfigService,
)
from backend.models.db_models import (
    BenchmarkRun,
    EvaluationMetric,
)
from backend.services.postgres_service import (
    AsyncSessionLocal,
    get_db,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/evaluation",
    tags=["evaluation"],
)


class RunRequest(BaseModel):
    """
    Benchmark request sent by the UI.

    There is intentionally no `model` field here.
    The UI sends only provider_id, and the backend resolves that
    provider's enabled small, medium, and large models.
    """

    provider_id: UUID

    dataset: str = "SEC Filings"
    retrieval_mode: str = "hybrid+reranker"

    question_set: Literal[
        "valuation",
        "growth",
        "sentiment",
        "mixed",
        # Every question across the four sets; defined in question_sets.py
        # but previously unreachable through this endpoint.
        "all",
    ] = "valuation"

    company_filter: str = "all"

    top_k: int = Field(
        default=5,
        ge=1,
        le=100,
    )

    benchmark_version: str = "v1"
    dataset_version: str = "v1"


class RunResponse(BaseModel):
    """Immediate response returned after the run is queued."""

    run_id: UUID
    status: str

    provider_name: str
    models: dict[str, str]

    message: str


class MetricsResponse(BaseModel):
    """Run and aggregate metric payload used by the dashboard."""

    run_id: UUID

    provider_id: UUID | None
    provider_name: str | None

    dataset: str
    model: str
    retrieval_mode: str
    question_set: str

    status: str
    total_requests: int
    total_cost: float

    pass_rate: float | None
    route_accuracy: float | None

    precision_at_k: float | None
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None

    faithfulness: float | None
    response_relevancy: float | None
    context_precision: float | None
    context_recall: float | None
    context_entity_recall: float | None
    noise_sensitivity: float | None

    hallucination_rate: float | None
    intent_accuracy: float | None

    # Question counts per actual execution route. None for runs recorded
    # before this was persisted.
    route_distribution: dict[str, int] | None

    # Metric averages per route, keyed by the same route names.
    route_performance: dict[str, dict[str, float | int | None]] | None

    # Invocation counts per tool name.
    tool_summary: dict[str, dict[str, float | int | None]] | None

    sql_accuracy: float | None
    sql_equivalence: float | None

    tool_accuracy: float | None
    tool_precision: float | None
    tool_recall: float | None
    tool_f1: float | None

    market_accuracy: float | None

    avg_latency_ms: float | None
    p50_latency: float | None
    p95_latency: float | None
    p99_latency: float | None

    cost_per_request: float | None
    k: int | None

    created_at: str
    completed_at: str | None
    error_message: str | None


@router.post(
    "/run",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_benchmark_run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> RunResponse:
    """
    Validate the provider, create benchmark_runs, and queue execution.
    """
    run_id = uuid4()

    try:
        llm_config_service = LLMConfigService(
            session
        )

        # Resolve provider -> enabled small/medium/large models.
        llm_runtime = (
            await llm_config_service
            .load_provider_runtime(
                provider_id=request.provider_id
            )
        )

        models = llm_runtime.describe()

        # Store a readable immutable snapshot of the resolved runtime.
        model_snapshot = _build_model_snapshot(
            models
        )

        benchmark_run = BenchmarkRun(
            run_id=run_id,

            provider_id=request.provider_id,
            provider_name=llm_runtime.provider_name,

            model=model_snapshot,

            dataset=request.dataset,
            retrieval_mode=request.retrieval_mode,
            question_set=request.question_set,
            company_filter=request.company_filter,

            status="queued",

            total_requests=0,
            total_cost=0.0,

            pass_rate=None,
            route_accuracy=None,

            benchmark_version=request.benchmark_version,
            dataset_version=request.dataset_version,

            completed_at=None,
            error_message=None,
        )

        session.add(
            benchmark_run
        )

        await session.commit()
        await session.refresh(
            benchmark_run
        )

        # The HTTP request returns immediately; the benchmark continues
        # using a separate database session.
        background_tasks.add_task(
            _execute_benchmark,

            run_id=run_id,
            provider_id=request.provider_id,

            dataset=request.dataset,
            retrieval_mode=request.retrieval_mode,
            question_set=request.question_set,
            company_filter=request.company_filter,

            top_k=request.top_k,

            benchmark_version=request.benchmark_version,
            dataset_version=request.dataset_version,

            model_snapshot=model_snapshot,
        )

        logger.info(
            "[EVALUATION] Benchmark queued "
            "run_id=%s provider=%s models=%s",
            run_id,
            llm_runtime.provider_name,
            models,
        )

        return RunResponse(
            run_id=run_id,
            status="queued",
            provider_name=llm_runtime.provider_name,
            models=models,
            message="Benchmark run queued.",
        )

    except RuntimeError as exc:
        await session.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    except Exception as exc:
        await session.rollback()

        logger.exception(
            "[EVALUATION] Failed to create run"
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Unable to create benchmark run."
            ),
        ) from exc


async def _execute_benchmark(
    *,
    run_id: UUID,
    provider_id: UUID,

    dataset: str,
    retrieval_mode: str,
    question_set: str,
    company_filter: str,

    top_k: int,

    benchmark_version: str,
    dataset_version: str,

    model_snapshot: str,
) -> None:
    """
    Background execution using its own AsyncSession.
    """
    async with AsyncSessionLocal() as session:
        try:
            benchmark_run = await _get_run_record(
                session=session,
                run_id=run_id,
            )

            if benchmark_run is None:
                logger.error(
                    "[EVALUATION] Run not found "
                    "run_id=%s",
                    run_id,
                )
                return

            benchmark_run.status = "running"
            await session.commit()

            llm_config_service = LLMConfigService(
                session
            )

            # Re-resolve the runtime in this background task because
            # the original request-scoped session is no longer used.
            llm_runtime = (
                await llm_config_service
                .load_provider_runtime(
                    provider_id=provider_id
                )
            )

            # Passed into every LangGraph node. Nodes read llm_runtime
            # from config["configurable"] through get_llm_client(...).
            runnable_config: RunnableConfig = {
                "configurable": {
                    "llm_runtime": llm_runtime,
                    "request_type": "benchmark",
                    "benchmark_run_id": str(
                        run_id
                    ),
                },

                # These values are propagated to LangSmith traces.
                "tags": [
                    "benchmark",
                    question_set,
                    retrieval_mode,
                    llm_runtime.provider_name,
                ],

                "metadata": {
                    "request_type": "benchmark",
                    "benchmark_run_id": str(
                        run_id
                    ),
                    "provider_id": str(
                        provider_id
                    ),
                    "provider": llm_runtime.provider_name,
                    "models": llm_runtime.describe(),
                    "dataset": dataset,
                    "question_set": question_set,
                    "retrieval_mode": retrieval_mode,
                },
            }

            # Internal config includes the backend-resolved model snapshot.
            benchmark_config = BenchmarkConfig(
                dataset=dataset,
                question_set=question_set,

                model=model_snapshot,
                retrieval_strategy=retrieval_mode,

                company_filter=company_filter,
                top_k=top_k,

                benchmark_version=benchmark_version,
                dataset_version=dataset_version,
            )

            runner = BenchmarkRunner(
                graph=financial_graph
            )

            benchmark_result = await runner.run(
                config=benchmark_config,
                runnable_config=runnable_config,
                run_id=run_id,
            )

            aggregate = (
                benchmark_result.aggregate_metrics
                or {}
            )

            # Persist run-level fields.
            benchmark_run.status = (
                benchmark_result.status.value
            )
            benchmark_run.total_requests = (
                benchmark_result.total_questions
            )
            benchmark_run.total_cost = (
                aggregate.get("total_cost")
                or 0.0
            )
            benchmark_run.pass_rate = (
                aggregate.get(
                    "overall_pass_rate"
                )
            )
            benchmark_run.route_accuracy = (
                aggregate.get(
                    "route_accuracy"
                )
            )
            benchmark_run.completed_at = (
                _utcnow_naive()
            )
            benchmark_run.error_message = (
                benchmark_result.error
            )

            # Persist evaluator/latency/cost aggregates.
            await _upsert_evaluation_metrics(
                session=session,

                run_id=run_id,

                dataset=dataset,
                model=model_snapshot,
                retrieval_mode=retrieval_mode,
                question_set=question_set,

                top_k=top_k,
                aggregate=aggregate,
            )

            await session.commit()

            logger.info(
                "[EVALUATION] Benchmark finished "
                "run_id=%s status=%s",
                run_id,
                benchmark_result.status.value,
            )

        except Exception as exc:
            await session.rollback()

            logger.exception(
                "[EVALUATION] Benchmark failed "
                "run_id=%s",
                run_id,
            )

            failed_run = await _get_run_record(
                session=session,
                run_id=run_id,
            )

            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(
                    exc
                )
                failed_run.completed_at = (
                    _utcnow_naive()
                )

                await session.commit()


async def _upsert_evaluation_metrics(
    *,
    session: AsyncSession,

    run_id: UUID,

    dataset: str,
    model: str,
    retrieval_mode: str,
    question_set: str,

    top_k: int,

    aggregate: dict[str, object],
) -> None:
    """
    Insert or update the single aggregate evaluation_metrics row
    associated with this run_id.
    """
    result = await session.execute(
        select(EvaluationMetric).where(
            EvaluationMetric.run_id
            == run_id
        )
    )

    evaluation_metric = (
        result.scalar_one_or_none()
    )

    values = {
        # RankingEvaluator
        "precision_at_k": aggregate.get(
            "precision_at_k"
        ),
        "recall_at_k": aggregate.get(
            "recall_at_k"
        ),
        "mrr": aggregate.get("mrr"),
        "ndcg_at_k": aggregate.get(
            "ndcg_at_k"
        ),

        # RagasEvaluator
        "faithfulness": aggregate.get(
            "faithfulness"
        ),
        "response_relevancy": aggregate.get(
            "response_relevancy"
        ),
        "context_precision": aggregate.get(
            "context_precision"
        ),
        "context_recall": aggregate.get(
            "context_recall"
        ),
        "context_entity_recall": aggregate.get(
            "context_entity_recall"
        ),
        "noise_sensitivity": aggregate.get(
            "noise_sensitivity"
        ),

        # Intent and hallucination
        "hallucination_rate": aggregate.get(
            "hallucination_rate"
        ),
        "intent_accuracy": aggregate.get(
            "intent_accuracy"
        ),

        # Route mix
        "route_distribution": aggregate.get(
            "route_distribution"
        ),
        "route_performance": aggregate.get(
            "route_performance"
        ),
        "tool_summary": aggregate.get(
            "tool_summary"
        ),

        # SQLEvaluator
        "sql_accuracy": aggregate.get(
            "sql_accuracy"
        ),
        "sql_equivalence": aggregate.get(
            "sql_equivalence"
        ),

        # ToolEvaluator
        "tool_accuracy": aggregate.get(
            "tool_accuracy"
        ),
        "tool_precision": aggregate.get(
            "tool_precision"
        ),
        "tool_recall": aggregate.get(
            "tool_recall"
        ),
        "tool_f1": aggregate.get(
            "tool_f1"
        ),

        # MarketEvaluator
        "market_accuracy": aggregate.get(
            "market_accuracy"
        ),

        # Runtime latency
        "avg_latency_ms": aggregate.get(
            "avg_latency_ms"
        ),
        "p50_latency": aggregate.get(
            "p50_latency"
        ),
        "p95_latency": aggregate.get(
            "p95_latency"
        ),
        "p99_latency": aggregate.get(
            "p99_latency"
        ),

        # Cost
        "cost_per_request": aggregate.get(
            "cost_per_request"
        ),
        "total_cost": aggregate.get(
            "total_cost"
        ),

        # Benchmark configuration snapshot
        "k": top_k,
        "dataset": dataset,
        "model": model,
        "retrieval_mode": retrieval_mode,
        "question_set": question_set,

        "total_requests": aggregate.get(
            "total_requests"
        ),
    }

    if evaluation_metric is None:
        session.add(
            EvaluationMetric(
                run_id=run_id,
                **values,
            )
        )
        return

    for field_name, value in values.items():
        setattr(
            evaluation_metric,
            field_name,
            value,
        )


async def _get_run_record(
    *,
    session: AsyncSession,
    run_id: UUID,
) -> BenchmarkRun | None:
    """Load one benchmark run by its public UUID."""
    result = await session.execute(
        select(BenchmarkRun).where(
            BenchmarkRun.run_id == run_id
        )
    )

    return result.scalar_one_or_none()


@router.get(
    "/runs",
    response_model=list[MetricsResponse],
)
async def list_runs(
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    session: AsyncSession = Depends(get_db),
) -> list[MetricsResponse]:
    """List recent benchmark runs with their aggregate metrics."""
    result = await session.execute(
        select(
            BenchmarkRun,
            EvaluationMetric,
        )
        .outerjoin(
            EvaluationMetric,
            BenchmarkRun.run_id
            == EvaluationMetric.run_id,
        )
        .order_by(
            desc(BenchmarkRun.created_at)
        )
        .limit(limit)
        .offset(offset)
    )

    return [
        _build_metrics_response(
            run=run,
            metric=metric,
        )
        for run, metric in result.all()
    ]


@router.get(
    "/runs/{run_id}",
    response_model=MetricsResponse,
)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> MetricsResponse:
    """Get one benchmark run and its aggregate metrics."""
    result = await session.execute(
        select(
            BenchmarkRun,
            EvaluationMetric,
        )
        .outerjoin(
            EvaluationMetric,
            BenchmarkRun.run_id
            == EvaluationMetric.run_id,
        )
        .where(
            BenchmarkRun.run_id == run_id
        )
    )

    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=(
                "Benchmark run not found"
            ),
        )

    benchmark_run, metric = row

    return _build_metrics_response(
        run=benchmark_run,
        metric=metric,
    )


def _build_model_snapshot(
    models: dict[str, str],
) -> str:
    """
    Convert LLMRuntime.describe() into a readable database snapshot.
    """
    return (
        f"small={models.get('small', 'unknown')}, "
        f"medium={models.get('medium', 'unknown')}, "
        f"large={models.get('large', 'unknown')}"
    )


def _utcnow_naive() -> datetime:
    """
    Return UTC without tzinfo for PostgreSQL TIMESTAMP WITHOUT TIME ZONE.

    Change this only if your ORM column uses timezone=True.
    """
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _build_metrics_response(
    *,
    run: BenchmarkRun,
    metric: EvaluationMetric | None,
) -> MetricsResponse:
    """Convert the joined ORM rows into the dashboard response model."""

    def metric_value(
        field_name: str,
    ):
        if metric is None:
            return None

        return getattr(
            metric,
            field_name,
            None,
        )

    return MetricsResponse(
        run_id=run.run_id,

        provider_id=run.provider_id,
        provider_name=run.provider_name,

        dataset=run.dataset or "",
        model=run.model or "",
        retrieval_mode=(
            run.retrieval_mode or ""
        ),
        question_set=(
            run.question_set or ""
        ),

        status=run.status,
        total_requests=(
            run.total_requests or 0
        ),
        total_cost=(
            run.total_cost or 0.0
        ),

        pass_rate=run.pass_rate,
        route_accuracy=run.route_accuracy,

        precision_at_k=metric_value(
            "precision_at_k"
        ),
        recall_at_k=metric_value(
            "recall_at_k"
        ),
        mrr=metric_value("mrr"),
        ndcg_at_k=metric_value(
            "ndcg_at_k"
        ),

        faithfulness=metric_value(
            "faithfulness"
        ),
        response_relevancy=metric_value(
            "response_relevancy"
        ),
        context_precision=metric_value(
            "context_precision"
        ),
        context_recall=metric_value(
            "context_recall"
        ),
        context_entity_recall=metric_value(
            "context_entity_recall"
        ),
        noise_sensitivity=metric_value(
            "noise_sensitivity"
        ),

        hallucination_rate=metric_value(
            "hallucination_rate"
        ),
        intent_accuracy=metric_value(
            "intent_accuracy"
        ),

        route_distribution=metric_value(
            "route_distribution"
        ),

        route_performance=metric_value(
            "route_performance"
        ),

        tool_summary=metric_value(
            "tool_summary"
        ),

        sql_accuracy=metric_value(
            "sql_accuracy"
        ),
        sql_equivalence=metric_value(
            "sql_equivalence"
        ),

        tool_accuracy=metric_value(
            "tool_accuracy"
        ),
        tool_precision=metric_value(
            "tool_precision"
        ),
        tool_recall=metric_value(
            "tool_recall"
        ),
        tool_f1=metric_value(
            "tool_f1"
        ),

        market_accuracy=metric_value(
            "market_accuracy"
        ),

        avg_latency_ms=metric_value(
            "avg_latency_ms"
        ),
        p50_latency=metric_value(
            "p50_latency"
        ),
        p95_latency=metric_value(
            "p95_latency"
        ),
        p99_latency=metric_value(
            "p99_latency"
        ),

        cost_per_request=metric_value(
            "cost_per_request"
        ),
        k=metric_value("k"),

        created_at=(
            run.created_at.isoformat()
        ),
        completed_at=(
            run.completed_at.isoformat()
            if run.completed_at
            else None
        ),
        error_message=run.error_message,
    )

