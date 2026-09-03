"""
The persistence path that the benchmark actually calls.

WHY THIS EXISTS
    upsert_claims had its own passing tests, and claim_routes had its own
    passing tests, and the wiring between them was broken in production
    for a whole benchmark run: the import of upsert_claims into
    evaluation_routes never landed, so `_upsert_question_results` raised
    NameError on every question. The callback that calls it catches
    Exception and logs "the run continues", so 100 questions were scored
    and then silently discarded.

    Nothing failed because nothing exercised the seam. Both sides were
    tested; the line joining them was not.

    So this test calls _upsert_question_results directly -- the same
    function the runner's per-question callback calls -- and asserts that
    a question row and its claim rows both arrive.
"""
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.api.evaluation_routes import _upsert_question_results
from backend.evaluation.claims.audit import ClaimAudit, ClaimRecord
from backend.evaluation.claims.store import claims_for_run
from backend.evaluation.schemas import (
    EvaluatorResult,
    QuestionEvaluationResult,
)
from backend.services.postgres_service import AsyncSessionLocal, engine


@pytest.fixture
async def run_id():
    identifier = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO benchmark_runs (run_id, status, dataset, "
                "question_set, model, retrieval_mode) VALUES "
                "(:id, 'running', 'test', 'all', 'test', 'hybrid')"
            ),
            {"id": identifier},
        )

    yield identifier

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM claim_evaluations WHERE run_id = :id"),
            {"id": identifier},
        )
        await conn.execute(
            text("DELETE FROM question_results WHERE run_id = :id"),
            {"id": identifier},
        )
        await conn.execute(
            text("DELETE FROM benchmark_runs WHERE run_id = :id"),
            {"id": identifier},
        )


def _question(with_audit: bool) -> QuestionEvaluationResult:
    return QuestionEvaluationResult(
        question_id="valuation_pe_sector_01",
        question="Which three Technology companies have the lowest P/E ratios?",
        expected_intent="VALUATION",
        actual_intent="VALUATION",
        evaluator_results={
            "intent": EvaluatorResult(
                evaluator="intent", score=1.0, passed=True
            ),
        },
        overall_score=1.0,
        passed=True,
        claim_audit=(
            ClaimAudit(
                claims=[
                    ClaimRecord(
                        index=0,
                        claim="Adobe trades at a P/E of 15.56.",
                        original="Adobe trades at a P/E of 15.56.",
                        is_numeric=True,
                        numeric_values=("15.56",),
                        evidence=['[sql] {"ticker": "ADBE", "pe_ratio": 15.564}'],
                        label="SUPPORTED",
                        reasoning="The SQL row carries the figure.",
                        evaluator_model="gpt-4o-mini",
                    ),
                ],
                dropped=["ADBE may continue to outperform."],
            )
            if with_audit
            else None
        ),
    )


class TestTheSeamTheBenchmarkUses:
    async def test_the_question_row_is_written(self, run_id):
        async with AsyncSessionLocal() as session:
            await _upsert_question_results(
                session=session,
                run_id=run_id,
                question_results=[_question(with_audit=True)],
            )
            await session.commit()

        async with engine.begin() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM question_results "
                        "WHERE run_id = :id"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()

        assert count == 1

    async def test_the_claim_rows_are_written_too(self, run_id):
        """
        The assertion that was missing. Both sides had tests; this is the
        line between them.
        """
        async with AsyncSessionLocal() as session:
            await _upsert_question_results(
                session=session,
                run_id=run_id,
                question_results=[_question(with_audit=True)],
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            claims = await claims_for_run(session, run_id=run_id)

        assert len(claims) == 1
        assert claims[0]["claim"] == "Adobe trades at a P/E of 15.56."
        assert claims[0]["evaluator_label"] == "SUPPORTED"
        assert claims[0]["route"] == "VALUATION"

    async def test_a_question_without_an_audit_still_persists(self, run_id):
        """
        Every run before this feature existed, and any question whose
        audit failed. The question row must not depend on the audit.
        """
        async with AsyncSessionLocal() as session:
            await _upsert_question_results(
                session=session,
                run_id=run_id,
                question_results=[_question(with_audit=False)],
            )
            await session.commit()

        async with engine.begin() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM question_results "
                        "WHERE run_id = :id"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()

        async with AsyncSessionLocal() as session:
            claims = await claims_for_run(session, run_id=run_id)

        assert count == 1
        assert claims == []

    async def test_persisting_twice_does_not_duplicate_either_table(
        self, run_id
    ):
        """The runner persists per question and again at the end."""
        for _ in range(2):
            async with AsyncSessionLocal() as session:
                await _upsert_question_results(
                    session=session,
                    run_id=run_id,
                    question_results=[_question(with_audit=True)],
                )
                await session.commit()

        async with engine.begin() as conn:
            questions = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM question_results "
                        "WHERE run_id = :id"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()

        async with AsyncSessionLocal() as session:
            claims = await claims_for_run(session, run_id=run_id)

        assert questions == 1
        assert len(claims) == 1


class TestTheImportIsActuallyThere:
    def test_upsert_claims_resolves_in_the_route_module(self):
        """
        The direct check for the failure mode: a NameError at runtime
        inside a callback that catches Exception and keeps going. Cheap,
        and it fails loudly at import time rather than after six hours of
        benchmark.
        """
        from backend.api import evaluation_routes

        assert callable(evaluation_routes.upsert_claims)
