"""
A run that dies must keep the questions it already scored.

Results were persisted once, after every question had finished. On
2026-08-22 the Docker daemon stopped during run 64671f10 with 76 of 100
questions scored — valuation and growth complete, sentiment two thirds
through — and none of it reached the database, because the single write
comes after the loop. Seven hours of API spend, nothing to show.

_upsert_question_results already upserts on (run_id, question_id), so it
was always safe to call per question. The runner just never offered a point
to call it from.
"""
import uuid

import pytest

from backend.evaluation.benchmark_runner import BenchmarkRunner
from backend.evaluation.schemas import (
    BenchmarkConfig,
    QuestionEvaluationResult,
)


class TestIncrementalReporting:
    @pytest.mark.asyncio
    async def test_each_result_is_reported_as_it_finishes(self, monkeypatch):
        reported = []

        runner = BenchmarkRunner(graph=object())

        questions = [
            _stub_question("q1"),
            _stub_question("q2"),
            _stub_question("q3"),
        ]
        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: questions,
        )

        async def fake_run_question(*, question, **_):
            return QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=question.expected_intent,
                passed=True,
                overall_score=1.0,
            )

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        async def record(result):
            reported.append((result.question_id, len(reported)))

        await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            on_question_result=record,
        )

        assert [qid for qid, _ in reported] == ["q1", "q2", "q3"]

    @pytest.mark.asyncio
    async def test_the_callback_is_optional(self, monkeypatch):
        """Nothing that already calls run() needs to change."""
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question("q1")],
        )

        async def fake_run_question(*, question, **_):
            return QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=question.expected_intent,
                passed=True,
                overall_score=1.0,
            )

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
        )

        assert len(result.question_results) == 1

    @pytest.mark.asyncio
    async def test_a_failing_callback_does_not_lose_the_run(self, monkeypatch):
        """
        Persistence is a side effect of measuring, not the point of it. A
        database hiccup on question 3 must not discard questions 1 and 2,
        nor stop question 4 from being scored.
        """
        runner = BenchmarkRunner(graph=object())

        monkeypatch.setattr(
            "backend.evaluation.benchmark_runner.get_question_set",
            lambda name: [_stub_question(f"q{i}") for i in range(1, 5)],
        )

        async def fake_run_question(*, question, **_):
            return QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=question.expected_intent,
                passed=True,
                overall_score=1.0,
            )

        monkeypatch.setattr(runner, "_run_question", fake_run_question)

        async def explode(result):
            if result.question_id == "q3":
                raise RuntimeError("database went away")

        result = await runner.run(
            config=_config(),
            runnable_config={},
            run_id=uuid.uuid4(),
            on_question_result=explode,
        )

        assert [r.question_id for r in result.question_results] == [
            "q1",
            "q2",
            "q3",
            "q4",
        ]


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
