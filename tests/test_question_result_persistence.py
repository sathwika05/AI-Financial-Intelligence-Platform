"""
Per-question result persistence.

evaluation_metrics holds one averaged row per run, so until question_results
existed nothing recorded how an individual question scored. The only trace
was a log line printed during the run — which meant a question could not be
compared across runs, and recovering even one run's detail meant parsing
interleaved container logs.

Runs inside a transaction that is rolled back, so the benchmark history is
never modified.
"""
import uuid

import pytest
from sqlalchemy import func, select

from backend.api.evaluation_routes import _upsert_question_results
from backend.evaluation.schemas import (
    EvaluatorResult,
    IntentType,
    PipelineExecution,
    QuestionEvaluationResult,
)
from backend.models.db_models import BenchmarkRun, QuestionResult
from backend.services.postgres_service import AsyncSessionLocal


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
async def run(db):
    """A throwaway benchmark run to hang question rows off."""
    row = BenchmarkRun(
        run_id=uuid.uuid4(),
        question_set="valuation",
        status="completed",
    )
    db.add(row)
    await db.flush()
    return row


def make_result(question_id="valuation_002", score=0.9375, passed=True):
    return QuestionEvaluationResult(
        question_id=question_id,
        question="Which five profitable technology companies...",
        expected_intent=IntentType.VALUATION,
        actual_intent="VALUATION",
        execution=PipelineExecution(actual_intent="VALUATION"),
        evaluator_results={
            "sql": EvaluatorResult(
                evaluator="sql",
                applicable=True,
                passed=passed,
                score=score,
                metrics={
                    "sql_accuracy": 1.0,
                    "sql_order_correctness": 1.0,
                },
                details={"sql_order_requirement": "top_k"},
                errors=[],
            )
        },
        overall_score=score,
        passed=passed,
        aggregate_metrics={"sql.sql_accuracy": 1.0},
    )


class TestPersistence:
    async def test_a_question_is_written(self, db, run):
        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[make_result()],
        )
        await db.flush()

        row = (
            await db.execute(
                select(QuestionResult).where(
                    QuestionResult.run_id == run.run_id
                )
            )
        ).scalar_one()

        assert row.question_id == "valuation_002"
        assert row.overall_score == 0.9375
        assert row.passed is True

    async def test_evaluator_detail_survives_the_round_trip(self, db, run):
        """
        The whole point: the per-evaluator metrics and details are what the
        log line used to carry and nothing else kept.
        """
        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[make_result()],
        )
        await db.flush()

        row = (
            await db.execute(
                select(QuestionResult).where(
                    QuestionResult.run_id == run.run_id
                )
            )
        ).scalar_one()

        sql = row.evaluator_results["sql"]
        assert sql["metrics"]["sql_accuracy"] == 1.0
        assert sql["metrics"]["sql_order_correctness"] == 1.0
        assert sql["details"]["sql_order_requirement"] == "top_k"
        assert row.aggregate_metrics["sql.sql_accuracy"] == 1.0

    async def test_re_persisting_updates_rather_than_duplicating(
        self, db, run
    ):
        """
        Idempotent on (run_id, question_id). Without this a re-persist
        would leave two rows for one question and silently double it in
        any aggregate built from the table.
        """
        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[make_result(score=0.5, passed=False)],
        )
        await db.flush()

        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[make_result(score=0.9375, passed=True)],
        )
        await db.flush()

        count = (
            await db.execute(
                select(func.count())
                .select_from(QuestionResult)
                .where(QuestionResult.run_id == run.run_id)
            )
        ).scalar_one()
        assert count == 1

        row = (
            await db.execute(
                select(QuestionResult).where(
                    QuestionResult.run_id == run.run_id
                )
            )
        ).scalar_one()
        assert row.overall_score == 0.9375
        assert row.passed is True

    async def test_several_questions_in_one_run(self, db, run):
        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[
                make_result("valuation_002"),
                make_result("growth_001"),
                make_result("mixed_001", score=0.88, passed=False),
            ],
        )
        await db.flush()

        rows = (
            await db.execute(
                select(QuestionResult)
                .where(QuestionResult.run_id == run.run_id)
                .order_by(QuestionResult.question_id)
            )
        ).scalars().all()

        assert [r.question_id for r in rows] == [
            "growth_001",
            "mixed_001",
            "valuation_002",
        ]
        assert [r.passed for r in rows] == [True, False, True]

    async def test_empty_input_writes_nothing(self, db, run):
        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[],
        )
        await db.flush()

        count = (
            await db.execute(
                select(func.count())
                .select_from(QuestionResult)
                .where(QuestionResult.run_id == run.run_id)
            )
        ).scalar_one()
        assert count == 0

    async def test_history_query_uses_a_real_run_column(self, db, run):
        """
        Guards a column-name mistake that only appeared at runtime: the
        endpoint ordered by BenchmarkRun.started_at, which does not exist
        — the column is created_at — and returned a 500.
        """
        from backend.models.db_models import BenchmarkRun as BR

        columns = {c.name for c in BR.__table__.columns}
        assert "created_at" in columns
        assert "started_at" not in columns

    async def test_a_failed_question_records_its_error(self, db, run):
        """A question that raised has no scores; the error is the result."""
        failed = make_result("broken_001", score=0.0, passed=False)
        failed.error = "pipeline exploded"

        await _upsert_question_results(
            session=db,
            run_id=run.run_id,
            question_results=[failed],
        )
        await db.flush()

        row = (
            await db.execute(
                select(QuestionResult).where(
                    QuestionResult.question_id == "broken_001"
                )
            )
        ).scalar_one()
        assert row.error == "pipeline exploded"
