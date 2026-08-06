"""
Intent evaluator.

Purpose
-------
Compare the expected financial route from the golden dataset with the
actual route returned by the financial graph.

Golden dataset input
--------------------
expected_intent

Pipeline output
---------------
actual_intent

Metric produced
---------------
intent_accuracy


"""
from __future__ import annotations

from backend.evaluation.schemas import EvaluatorResult


class IntentEvaluator:
    """Evaluate whether the pipeline selected the correct financial route."""

    def evaluate(
        self,
        *,
        expected_intent: str,
        actual_intent: str | None,
    ) -> EvaluatorResult:
        # Normalize both values so case and surrounding spaces do not matter.
        # Normalize the golden expected route.
        expected = (expected_intent or "").strip().upper()
        # Normalize the actual route returned by the pipeline.
        actual = (actual_intent or "").strip().upper()

        # Exact match gives full intent accuracy.
        matched = bool(actual) and expected == actual

        return EvaluatorResult(
            evaluator="intent",
            applicable=True,
            passed=matched,
            score=1.0 if matched else 0.0,
            metrics={
                "intent_accuracy": 1.0 if matched else 0.0,
            },
            details={
                "expected_intent": expected,
                "actual_intent": actual or None,
            },
            errors=(
                []
                if actual
                else ["The pipeline did not return an intent."]
            ),
        )
