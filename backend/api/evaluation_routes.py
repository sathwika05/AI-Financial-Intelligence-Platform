"""
Evaluation API routes.

Endpoints:
    POST /api/evaluation/run          — trigger a benchmark run
    GET  /api/evaluation/runs         — list all benchmark runs
    GET  /api/evaluation/runs/{run_id} — get single run with metrics
    GET  /api/evaluation/metrics/comparison — retrieval mode comparison
    GET  /api/evaluation/metrics/timeseries — metrics over time for chart
"""

from __future__ import annotations

import logging
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from backend.models.db_models import BenchmarkRun, EvaluationMetric
from backend.services.postgres_service import AsyncSessionLocal, get_db
from backend.evaluation.benchmark_runner import BenchmarkRunner, RunConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    question_set:   Literal["valuation", "growth", "sentiment", "mixed"] = "valuation"
    dataset:        str = "SEC Filings"
    model:          str = "gpt-4o"
    retrieval_mode: str = "hybrid+reranker"
    company_filter: str = "all"
    k:              int = 5


class RunResponse(BaseModel):
    run_id:         UUID
    status:         str
    message:        str


class MetricsResponse(BaseModel):
    run_id:             UUID
    dataset:            str
    model:              str
    retrieval_mode:     str
    question_set:       str
    precision_at_k:     Optional[float]
    recall_at_k:        Optional[float]
    faithfulness:       Optional[float]
    hallucination_rate: Optional[float]
    p95_latency:        Optional[float]
    p99_latency:        Optional[float]
    avg_latency_ms:     Optional[float]
    cost_per_request:   Optional[float]
    total_cost:         Optional[float]
    total_requests:     Optional[int]
    status:             str
    created_at:         str


class ComparisonRow(BaseModel):
    retrieval_mode:     str
    precision_at_k:     float
    recall_at_k:        float
    faithfulness:       float
    hallucination_rate: float
    avg_latency_ms:     float


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED,)
async def trigger_benchmark_run(
    req: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger a new benchmark evaluation run.
    Runs in background — returns run_id immediately.
    Poll GET /api/evaluation/runs/{run_id} for status.
    """
    config = RunConfig(
        question_set=req.question_set,
        dataset=req.dataset,
        model=req.model,
        retrieval_mode=req.retrieval_mode,
        company_filter=req.company_filter,
        k=req.k,
    )

   


    # Generate run_id upfront so we can return it immediately
    run_id = uuid4()

    # Create the database row immediately
    current_run = BenchmarkRun(
        run_id=run_id,
        status="queued",
        dataset=req.dataset,
        model=req.model,
        retrieval_mode=req.retrieval_mode,
        question_set=req.question_set,
        company_filter=req.company_filter,
    )

    try:
        db.add(current_run)
        await db.commit()
        await db.refresh(current_run)
    except Exception:
        await db.rollback()
        raise

     # Import your pipeline here — adjust to your actual pipeline class
    from backend.graph.financial_graph import financial_graph

    async def _run():
        # Create a separate session for the background task
        async with AsyncSessionLocal() as background_db:
            try:
                runner = BenchmarkRunner(
                    db=background_db,
                    pipeline=financial_graph,
                )
                await runner.run(config=config,
                                 run_id=run_id)
            except Exception:
                await background_db.rollback()
                logger.exception("Benchmark run %s failed", run_id)

    background_tasks.add_task(_run)

    return RunResponse(
        run_id=current_run.run_id,
        status=current_run.status,
        message=f"Benchmark run started. Poll /api/evaluation/runs/{run_id} for status.",
    )


@router.get("/runs", response_model=list[MetricsResponse])
async def list_runs(
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List recent benchmark runs with their metrics."""
    result = await db.execute(
        select(BenchmarkRun, EvaluationMetric)
        .outerjoin(EvaluationMetric, BenchmarkRun.run_id == EvaluationMetric.run_id)
        .order_by(desc(BenchmarkRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    return [
        _build_metrics_response(run, metric)
        for run, metric in rows
    ]


@router.get("/runs/{run_id}", response_model=MetricsResponse)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a single benchmark run with full metrics."""
    result = await db.execute(
        select(BenchmarkRun, EvaluationMetric)
        .outerjoin(EvaluationMetric, BenchmarkRun.run_id == EvaluationMetric.run_id)
        .where(BenchmarkRun.run_id == run_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    run, metric = row
    return _build_metrics_response(run, metric)


@router.get("/metrics/comparison", response_model=list[ComparisonRow])
async def get_retrieval_comparison(db: AsyncSession = Depends(get_db)):
    """
    Average metrics grouped by retrieval_mode across all completed runs.
    Feeds the horizontal bar chart on the dashboard.
    """
    from sqlalchemy import func
    result = await db.execute(
        select(
            EvaluationMetric.retrieval_mode,
            func.avg(EvaluationMetric.precision_at_k).label("precision_at_k"),
            func.avg(EvaluationMetric.recall_at_k).label("recall_at_k"),
            func.avg(EvaluationMetric.faithfulness).label("faithfulness"),
            func.avg(EvaluationMetric.hallucination_rate).label("hallucination_rate"),
            func.avg(EvaluationMetric.avg_latency_ms).label("avg_latency_ms"),
        )
        .group_by(EvaluationMetric.retrieval_mode)
        .order_by(desc("precision_at_k"))
    )
    rows = result.all()

    return [
        ComparisonRow(
            retrieval_mode=r.retrieval_mode or "unknown",
            precision_at_k=round(r.precision_at_k or 0, 4),
            recall_at_k=round(r.recall_at_k or 0, 4),
            faithfulness=round(r.faithfulness or 0, 4),
            hallucination_rate=round(r.hallucination_rate or 0, 4),
            avg_latency_ms=round(r.avg_latency_ms or 0, 2),
        )
        for r in rows
    ]


@router.get("/metrics/timeseries")
async def get_metrics_timeseries(
    minutes: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """
    Metrics over time for the line chart panel.
    Returns one data point per completed run in the last N minutes.
    """
    import datetime
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)

    result = await db.execute(
        select(EvaluationMetric)
        .where(EvaluationMetric.created_at >= cutoff)
        .order_by(EvaluationMetric.created_at)
    )
    metrics = result.scalars().all()

    return [
        {
            "timestamp":        m.created_at.isoformat(),
            "precision_at_k":   m.precision_at_k,
            "recall_at_k":      m.recall_at_k,
            "faithfulness":     m.faithfulness,
            "hallucination_rate": m.hallucination_rate,
            "retrieval_mode":   m.retrieval_mode,
        }
        for m in metrics
    ]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_metrics_response(run: BenchmarkRun, metric: Optional[EvaluationMetric]) -> MetricsResponse:
    return MetricsResponse(
        run_id=run.run_id,
        dataset=run.dataset or "",
        model=run.model or "",
        retrieval_mode=run.retrieval_mode or "",
        question_set=run.question_set or "",
        precision_at_k=metric.precision_at_k if metric else None,
        recall_at_k=metric.recall_at_k if metric else None,
        faithfulness=metric.faithfulness if metric else None,
        hallucination_rate=metric.hallucination_rate if metric else None,
        p95_latency=metric.p95_latency if metric else None,
        p99_latency=metric.p99_latency if metric else None,
        avg_latency_ms=metric.avg_latency_ms if metric else None,
        cost_per_request=metric.cost_per_request if metric else None,
        total_cost=metric.total_cost if metric else None,
        total_requests=metric.total_requests if metric else None,
        status=run.status,
        created_at=run.created_at.isoformat(),
    )