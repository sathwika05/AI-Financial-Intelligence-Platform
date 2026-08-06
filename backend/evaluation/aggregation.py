from __future__ import annotations

import math
from typing import Any

from backend.evaluation.schemas import (
    BenchmarkRunResult,
    EvaluatorResult,
    QuestionEvaluationResult,
)


# A question passes only when its average evaluator score is at least 0.70
# and no applicable evaluator explicitly fails or returns errors.
PASS_THRESHOLD = 0.70


def finalize_question_result(
    result: QuestionEvaluationResult,
) -> QuestionEvaluationResult:
    """
    Calculate one question's overall score and pass/fail result.
    """
    applicable_results = [
        evaluator
        for evaluator in result.evaluator_results.values()
        if evaluator.applicable
    ]

    if not applicable_results:
        result.overall_score = 0.0
        result.passed = False
        result.aggregate_metrics = {}
        return result

    scores = [
        _get_evaluator_score(evaluator)
        for evaluator in applicable_results
    ]

    result.overall_score = _average(scores) or 0.0

    result.passed = (
        result.overall_score >= PASS_THRESHOLD
        and all(
            evaluator.passed is not False
            for evaluator in applicable_results
        )
        and all(
            not evaluator.errors
            for evaluator in applicable_results
        )
    )

    # Preserve every evaluator metric with a namespaced key.
    result.aggregate_metrics = {
        f"{evaluator.evaluator}.{metric_name}": metric_value
        for evaluator in applicable_results
        for metric_name, metric_value in evaluator.metrics.items()
    }

    return result


def aggregate_benchmark_run(
    run: BenchmarkRunResult,
) -> dict[str, Any]:
    """
    Aggregate question-level evaluator outputs into one run-level
    metric dictionary that can be persisted to evaluation_metrics.
    """
    question_results = run.question_results

    if not question_results:
        return _empty_aggregate()

    total_questions = len(question_results)
    passed_questions = sum(
        1
        for result in question_results
        if result.passed
    )

    # Exclude hard pipeline failures from evaluator averaging.
    completed_results = [
        result
        for result in question_results
        if result.error is None
    ]

    route_matches: list[float] = []
    latencies: list[float] = []
    costs: list[float] = []

    collected_metrics: dict[str, list[float]] = {}

    for result in completed_results:
        expected_intent = (
            result.expected_intent or ""
        ).upper()

        actual_intent = (
            result.actual_intent or ""
        ).upper()

        route_matches.append(
            1.0
            if expected_intent == actual_intent
            else 0.0
        )

        latencies.append(
            float(result.execution.latency_ms)
        )

        if result.execution.cost_usd is not None:
            costs.append(
                float(result.execution.cost_usd)
            )

        for evaluator in result.evaluator_results.values():
            if not evaluator.applicable:
                continue

            for metric_name, metric_value in evaluator.metrics.items():
                numeric_value = _to_float(
                    metric_value
                )

                if numeric_value is None:
                    continue

                collected_metrics.setdefault(
                    metric_name,
                    [],
                ).append(
                    numeric_value
                )

    total_cost = (
        round(sum(costs), 6)
        if costs
        else None
    )

    faithfulness = _metric_average(
        collected_metrics,
        "faithfulness",
    )

    explicit_hallucination_rate = _metric_average(
        collected_metrics,
        "hallucination_rate",
    )

    # Fallback only when no dedicated hallucination metric exists.
    hallucination_rate = (
        explicit_hallucination_rate
        if explicit_hallucination_rate is not None
        else (
            round(
                max(
                    0.0,
                    min(
                        1.0,
                        1.0 - faithfulness,
                    ),
                ),
                4,
            )
            if faithfulness is not None
            else None
        )
    )

    return {
        "total_questions": total_questions,
        "passed_questions": passed_questions,
        "failed_questions": (
            total_questions - passed_questions
        ),

        "overall_pass_rate": round(
            passed_questions / total_questions,
            4,
        ),

        "route_accuracy": (
            _average(route_matches) or 0.0
        ),

        # Intent
        "intent_accuracy": _metric_average(
            collected_metrics,
            "intent_accuracy",
        ),

        # Ranking
        "precision_at_k": _metric_average(
            collected_metrics,
            "precision_at_k",
            "precision@k",
        ),
        "recall_at_k": _metric_average(
            collected_metrics,
            "recall_at_k",
            "recall@k",
        ),
        "mrr": _metric_average(
            collected_metrics,
            "mrr",
            "mean_reciprocal_rank",
        ),
        "ndcg_at_k": _metric_average(
            collected_metrics,
            "ndcg_at_k",
            "ndcg@k",
        ),

        # Canonical RAGAS names used by the database and dashboard.
        "faithfulness": faithfulness,
        "response_relevancy": _metric_average(
            collected_metrics,
            "response_relevancy",
            # Compatibility aliases from older code/RAGAS versions:
            "answer_relevancy",
            "answer_relevance",
            "response_relevance",
        ),
        "context_precision": _metric_average(
            collected_metrics,
            "context_precision",
        ),
        "context_recall": _metric_average(
            collected_metrics,
            "context_recall",
        ),
        "context_entity_recall": _metric_average(
            collected_metrics,
            "context_entity_recall",
        ),
        "noise_sensitivity": _metric_average(
            collected_metrics,
            "noise_sensitivity",
        ),

        "hallucination_rate": hallucination_rate,

        # SQL
        "sql_accuracy": _metric_average(
            collected_metrics,
            "sql_accuracy",
            "result_accuracy",
            "answer_accuracy",
        ),
        "sql_equivalence": _metric_average(
            collected_metrics,
            "sql_equivalence",
            "sql_semantic_equivalence",
            "query_equivalence",
        ),

        # Tools
        "tool_accuracy": _metric_average(
            collected_metrics,
            "tool_accuracy",
            "tool_call_accuracy",
        ),
        "tool_precision": _metric_average(
            collected_metrics,
            "tool_precision",
        ),
        "tool_recall": _metric_average(
            collected_metrics,
            "tool_recall",
        ),
        "tool_f1": _metric_average(
            collected_metrics,
            "tool_f1",
            "tool_call_f1",
        ),

        # Market
        "market_accuracy": _metric_average(
            collected_metrics,
            "market_accuracy",
            "market_data_accuracy",
        ),

        # Latency
        "avg_latency_ms": _average(
            latencies
        ),
        "p50_latency": _percentile(
            latencies,
            50,
        ),
        "p95_latency": _percentile(
            latencies,
            95,
        ),
        "p99_latency": _percentile(
            latencies,
            99,
        ),

        # Cost
        "total_cost": total_cost,
        "cost_per_request": (
            round(
                total_cost / total_questions,
                6,
            )
            if total_cost is not None
            and total_questions > 0
            else None
        ),

        "total_requests": total_questions,
    }


def _get_evaluator_score(
    evaluator: EvaluatorResult,
) -> float:
    """
    Prefer evaluator.score. Otherwise average normalized metric values.
    Count-like metrics greater than 1 are ignored.
    """
    if evaluator.score is not None:
        return _clamp(
            evaluator.score
        )

    normalized_values: list[float] = []

    for value in evaluator.metrics.values():
        numeric_value = _to_float(value)

        if (
            numeric_value is not None
            and 0.0 <= numeric_value <= 1.0
        ):
            normalized_values.append(
                numeric_value
            )

    if normalized_values:
        return _average(
            normalized_values
        ) or 0.0

    return (
        1.0
        if evaluator.passed is True
        else 0.0
    )


def _metric_average(
    metrics: dict[str, list[float]],
    *possible_names: str,
) -> float | None:
    """Return the first available average for the supplied aliases."""
    for metric_name in possible_names:
        values = metrics.get(
            metric_name
        )

        if values:
            return _average(values)

    return None


def _average(
    values: list[float],
) -> float | None:
    if not values:
        return None

    return round(
        sum(values) / len(values),
        4,
    )


def _percentile(
    values: list[float],
    percentile: int,
) -> float | None:
    """
    Calculate an interpolated percentile without adding NumPy.
    """
    if not values:
        return None

    ordered_values = sorted(values)

    if len(ordered_values) == 1:
        return round(
            ordered_values[0],
            3,
        )

    position = (
        percentile / 100
    ) * (
        len(ordered_values) - 1
    )

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return round(
            ordered_values[lower_index],
            3,
        )

    interpolated = (
        ordered_values[lower_index]
        + (
            ordered_values[upper_index]
            - ordered_values[lower_index]
        )
        * (
            position - lower_index
        )
    )

    return round(
        interpolated,
        3,
    )


def _to_float(
    value: float | int | bool | None,
) -> float | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return 1.0 if value else 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(
    value: float,
) -> float:
    return max(
        0.0,
        min(
            1.0,
            float(value),
        ),
    )


def _empty_aggregate() -> dict[str, Any]:
    """Complete empty result shape used when no questions execute."""
    return {
        "total_questions": 0,
        "passed_questions": 0,
        "failed_questions": 0,

        "overall_pass_rate": 0.0,
        "route_accuracy": 0.0,

        "intent_accuracy": None,

        "precision_at_k": None,
        "recall_at_k": None,
        "mrr": None,
        "ndcg_at_k": None,

        "faithfulness": None,
        "response_relevancy": None,
        "context_precision": None,
        "context_recall": None,
        "context_entity_recall": None,
        "noise_sensitivity": None,

        "hallucination_rate": None,

        "sql_accuracy": None,
        "sql_equivalence": None,

        "tool_accuracy": None,
        "tool_precision": None,
        "tool_recall": None,
        "tool_f1": None,

        "market_accuracy": None,

        "avg_latency_ms": None,
        "p50_latency": None,
        "p95_latency": None,
        "p99_latency": None,

        "total_cost": None,
        "cost_per_request": None,
        "total_requests": 0,
    }
