"""
Tool-call evaluator.

Purpose
-------
Compare actual structured tool calls with golden expected tool calls.

Golden dataset input
--------------------
expected_tool_calls

Pipeline output
---------------
actual_tool_calls

Metrics produced
----------------
tool_accuracy
tool_precision
tool_recall
tool_f1

Full forms
----------
RAGAS = Retrieval-Augmented Generation Assessment
F1 = Harmonic mean of precision and recall
TP = True Positive
FP = False Positive
FN = False Negative
"""
from __future__ import annotations

import json
from typing import Any

from backend.evaluation.schemas import EvaluatorResult
from backend.observability.logging import log_span


class ToolEvaluator:
    """Evaluate structured tool names, arguments, and call sequence."""

    def __init__(
        self,
        *,
        strict_order: bool = False,
    ) -> None:
        # Use False for tools that may execute in parallel.
        self.strict_order = strict_order

    @log_span("expected_tool_calls")
    async def evaluate(
        self,
        *,
        user_query: str,
        actual_tool_calls: list[dict[str, Any]],
        expected_tool_calls: list[dict[str, Any]],
    ) -> EvaluatorResult:
        if not expected_tool_calls:
            return EvaluatorResult(
                evaluator="tool",
                applicable=False,
                passed=None,
                score=None,
                metrics={},
                details={
                    "actual_tool_calls": actual_tool_calls,
                },
                errors=[],
            )

        try:
            from ragas.messages import (
                AIMessage,
                HumanMessage,
                ToolCall,
            )
            from ragas.metrics.collections import (
                ToolCallAccuracy,
                ToolCallF1,
            )

            actual_calls = [
                self._to_ragas_tool_call(
                    ToolCall,
                    item,
                )
                for item in actual_tool_calls
            ]

            reference_calls = [
                self._to_ragas_tool_call(
                    ToolCall,
                    item,
                )
                for item in expected_tool_calls
            ]

            # Build the minimal conversation required by RAGAS (Retrieval-Augmented Generation Assessment).
            user_input = [
                HumanMessage(
                    content=user_query
                ),
                AIMessage(
                    content=(
                        "Executing the required financial tools."
                    ),
                    tool_calls=actual_calls,
                ),
            ]

            accuracy_metric = ToolCallAccuracy(
                strict_order=self.strict_order
            )
            f1_metric = ToolCallF1()

            accuracy_result = await accuracy_metric.ascore(
                user_input=user_input,
                reference_tool_calls=reference_calls,
            )

            f1_result = await f1_metric.ascore(
                user_input=user_input,
                reference_tool_calls=reference_calls,
            )

            tool_accuracy = self._clamp(
                float(accuracy_result.value)
            )
            tool_f1 = self._clamp(
                float(f1_result.value)
            )

            # Derive precision and recall from exact structured matches.
            precision, recall = (
                self._structured_precision_recall(
                    actual_tool_calls=actual_tool_calls,
                    expected_tool_calls=expected_tool_calls,
                )
            )

            return EvaluatorResult(
                evaluator="tool",
                applicable=True,
                passed=(
                    tool_accuracy >= 0.70
                    and tool_f1 >= 0.70
                ),
                score=round(
                    (
                        tool_accuracy
                        + tool_f1
                    )
                    / 2,
                    4,
                ),
                metrics={
                    "tool_accuracy": round(
                        tool_accuracy,
                        4,
                    ),
                    "tool_precision": round(
                        precision,
                        4,
                    ),
                    "tool_recall": round(
                        recall,
                        4,
                    ),
                    # F1: harmonic mean of tool precision and tool recall.
                    "tool_f1": round(
                        tool_f1,
                        4,
                    ),
                },
                details={
                    "strict_order": self.strict_order,
                    "expected_tool_calls": expected_tool_calls,
                    "actual_tool_calls": actual_tool_calls,
                },
                errors=[],
            )

        except Exception as exc:
            return EvaluatorResult(
                evaluator="tool",
                applicable=True,
                passed=False,
                score=0.0,
                metrics={},
                details={
                    "strict_order": self.strict_order,
                    "expected_tool_calls": expected_tool_calls,
                    "actual_tool_calls": actual_tool_calls,
                },
                errors=[
                    f"Tool evaluation failed: {exc}"
                ],
            )

    @staticmethod
    def _to_ragas_tool_call(
        tool_call_class: Any,
        value: dict[str, Any],
    ) -> Any:
        return tool_call_class(
            name=str(
                value.get("name", "")
            ),
            args=dict(
                value.get("args")
                or {}
            ),
        )

    @classmethod
    def _structured_precision_recall(
        cls,
        *,
        actual_tool_calls: list[dict[str, Any]],
        expected_tool_calls: list[dict[str, Any]],
    ) -> tuple[float, float]:
        actual = [
            cls._canonical_call(item)
            for item in actual_tool_calls
        ]
        expected = [
            cls._canonical_call(item)
            for item in expected_tool_calls
        ]

        # Use TP (True Positive), FP (False Positive), and FN (False Negative) matching so duplicate calls are handled correctly.
        remaining_expected = expected.copy()
        true_positives = 0

        for call in actual:
            if call in remaining_expected:
                true_positives += 1
                remaining_expected.remove(
                    call
                )

        false_positives = (
            len(actual)
            - true_positives
        )
        false_negatives = (
            len(expected)
            - true_positives
        )

        precision = cls._safe_divide(
            true_positives,
            true_positives
            + false_positives,
        )
        recall = cls._safe_divide(
            true_positives,
            true_positives
            + false_negatives,
        )

        return precision, recall

    @staticmethod
    def _canonical_call(
        value: dict[str, Any],
    ) -> tuple[str, str]:
        name = str(
            value.get("name", "")
        ).strip().lower()

        args = json.dumps(
            value.get("args") or {},
            sort_keys=True,
            default=str,
        )

        return name, args

    @staticmethod
    def _safe_divide(
        numerator: float,
        denominator: float,
    ) -> float:
        if denominator == 0:
            return 0.0

        return numerator / denominator

    @staticmethod
    def _clamp(
        value: float,
    ) -> float:
        return max(
            0.0,
            min(
                1.0,
                value,
            ),
        )
