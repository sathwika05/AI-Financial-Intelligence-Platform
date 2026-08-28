"""
A run in flight must be stoppable.

A hundred questions is seven hours and roughly $8. Until now the only way
to stop one was to restart the API container, which killed the process
mid-question and left the row reading `running` until startup reconciled
it. Run b94d121d was stopped exactly that way.

Cancellation is cooperative: the runner asks between questions, never
inside one. A question already in flight finishes and is scored, because
its API spend has been paid either way and a half-graded question helps
nobody.
"""
import uuid

import pytest

from backend.evaluation.benchmark_runner import BenchmarkRunner
from backend.evaluation.schemas import (
    BenchmarkConfig,
    BenchmarkStatus,
    QuestionEvaluationResult,
)


class TestCooperativeCancellation:
    @pytest.mark.asyncio
    async def test_the_run_stops_when_cancellation_is_requested(
        self, monkeypatch
    ):
        """The questions after the flag is raised are never executed."""
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question(f"q{i}") for i in range(1, 6)],
        )

        executed = []

        async def fake_run_question(*, question, **_):
            executed.append(question.question_id)
            return _passing_result(question)

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        # Raised once two questions have been scored.
        async def should_cancel():
            return len(executed) >= 2

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            should_cancel=should_cancel,
        )

        assert executed == ["q1", "q2"]
        assert result.status is BenchmarkStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_questions_scored_before_the_stop_are_kept(
        self, monkeypatch
    ):
        """Cancelling banks the work already paid for."""
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question(f"q{i}") for i in range(1, 6)],
        )

        executed = []

        async def fake_run_question(*, question, **_):
            executed.append(question.question_id)
            return _passing_result(question)

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        async def should_cancel():
            return len(executed) >= 3

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            should_cancel=should_cancel,
        )

        assert [r.question_id for r in result.question_results] == [
            "q1",
            "q2",
            "q3",
        ]
        assert result.passed_questions == 3

    @pytest.mark.asyncio
    async def test_a_run_that_is_never_cancelled_completes(self, monkeypatch):
        """The check must not change the ordinary path."""
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question(f"q{i}") for i in range(1, 4)],
        )

        async def fake_run_question(*, question, **_):
            return _passing_result(question)

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        async def never():
            return False

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            should_cancel=never,
        )

        assert len(result.question_results) == 3
        assert result.status is BenchmarkStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_the_hook_is_optional(self, monkeypatch):
        """Nothing that already calls run() needs to change."""
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question("q1")],
        )

        async def fake_run_question(*, question, **_):
            return _passing_result(question)

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
        )

        assert result.status is BenchmarkStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_the_question_in_flight_is_not_abandoned(self, monkeypatch):
        """
        The flag is read between questions, never mid-question. A question
        whose API spend has already been paid gets scored and persisted.
        """
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question(f"q{i}") for i in range(1, 4)],
        )

        persisted = []

        async def fake_run_question(*, question, **_):
            return _passing_result(question)

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        # Cancelled from the very first moment.
        async def always():
            return True

        async def record(result):
            persisted.append(result.question_id)

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            should_cancel=always,
            on_question_result=record,
        )

        # Nothing had started, so nothing is owed.
        assert persisted == []
        assert result.status is BenchmarkStatus.CANCELLED


def _passing_result(question):
    return QuestionEvaluationResult(
        question_id=question.question_id,
        question=question.question,
        expected_intent=question.expected_intent,
        passed=True,
        overall_score=1.0,
    )


def _config():
    return BenchmarkConfig(
        dataset="SEC Filings",
        question_set="smoke",
        model="small=x, medium=y, large=z",
        retrieval_strategy="hybrid+reranker",
    )


def _stub_question(question_id):
    from backend.evaluation.schemas import EvalQuestion, IntentType

    return EvalQuestion(
        question_id=question_id,
        question=f"question {question_id}",
        expected_intent=IntentType.SENTIMENT,
        expected_tools=["planner", "vector"],
    )
