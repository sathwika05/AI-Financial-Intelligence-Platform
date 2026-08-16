from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


from backend.evaluation.schemas import (
    BenchmarkRunResult,
    EvaluatorResult,
    QuestionEvaluationResult,
)


# A question passes only when its average evaluator score is at least 0.70
# and no applicable evaluator explicitly fails or returns errors.
PASS_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# Execution routes
# ---------------------------------------------------------------------------

ROUTE_SQL = "SQL Only"
ROUTE_VECTOR = "Vector Only"
ROUTE_HYBRID = "Hybrid"

# Only appears when a question recorded neither retrieval artifacts nor a
# usable intent, so a miscount is visible rather than folded into a real slice.
ROUTE_UNCLASSIFIED = "Unclassified"

CANONICAL_ROUTES = (
    ROUTE_SQL,
    ROUTE_VECTOR,
    ROUTE_HYBRID,
)

# The routes the planner takes per intent. See planner_node's prompt:
# VALUATION/GROWTH use sql_query alone, SENTIMENT uses vector_query alone,
# and MIXED combines sql + vector + market.
_ROUTE_BY_INTENT = {
    "VALUATION": ROUTE_SQL,
    "GROWTH": ROUTE_SQL,
    "SENTIMENT": ROUTE_VECTOR,
    "MIXED": ROUTE_HYBRID,
}


def classify_execution_route(
    result: QuestionEvaluationResult,
) -> str:
    """
    Determine which route a question actually took.

    Derived from the artifacts the pipeline produced rather than from the
    intent it was classified as, so a question that was routed one way but
    executed another is counted as what it did. The intent is used only as a
    fallback when no artifacts were recorded at all.
    """
    execution = result.execution

    # Truthiness, not `is not None`. combine_results only sets a channel's
    # key when that channel actually ran, and retrieval_node then fills the
    # gaps with `.get(key, {})` — so an unused channel arrives as an empty
    # dict, which is not None. Testing against None marked every question as
    # having used SQL and the market API, so everything classified as Hybrid.
    used_sql = bool(
        execution.generated_sql
    ) or bool(
        execution.sql_result
    )

    used_vector = bool(
        execution.retrieved_contexts
        or execution.reranked_contexts
    )

    used_market = bool(
        execution.market_result
    )

    active_channels = sum(
        [
            used_sql,
            used_vector,
            used_market,
        ]
    )

    if active_channels >= 2:
        return ROUTE_HYBRID

    if used_sql:
        return ROUTE_SQL

    if used_vector:
        return ROUTE_VECTOR

    # A live market lookup on its own is still the combined path, since no
    # intent reaches the market API without also planning SQL and vector.
    if used_market:
        return ROUTE_HYBRID

    return _ROUTE_BY_INTENT.get(
        (result.actual_intent or "").upper(),
        ROUTE_UNCLASSIFIED,
    )


def build_route_distribution(
    results: list[QuestionEvaluationResult],
) -> dict[str, int]:
    """
    Count questions per execution route.

    The three canonical routes are always present, at zero if unused, so the
    dashboard renders a stable set of slices across runs.
    """
    distribution: dict[str, int] = {
        route: 0
        for route in CANONICAL_ROUTES
    }

    for result in results:
        route = classify_execution_route(
            result
        )

        distribution[route] = (
            distribution.get(route, 0) + 1
        )

    return distribution


# Canonical metric name -> the evaluator metric names it can arrive under.
# Shared by the run-level aggregate and the per-route breakdown so the two
# can never disagree about what "faithfulness" is called.
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "intent_accuracy": ("intent_accuracy",),

    "precision_at_k": ("precision_at_k", "precision@k"),
    "recall_at_k": ("recall_at_k", "recall@k"),
    "mrr": ("mrr", "mean_reciprocal_rank"),
    "ndcg_at_k": ("ndcg_at_k", "ndcg@k"),

    "faithfulness": ("faithfulness",),
    "response_relevancy": (
        "response_relevancy",
        # Compatibility aliases from older code/RAGAS versions:
        "answer_relevancy",
        "answer_relevance",
        "response_relevance",
    ),
    "context_precision": ("context_precision",),
    "context_recall": ("context_recall",),
    "context_entity_recall": ("context_entity_recall",),
    "noise_sensitivity": ("noise_sensitivity",),

    "sql_accuracy": ("sql_accuracy", "result_accuracy", "answer_accuracy"),
    "sql_equivalence": (
        "sql_equivalence",
        "sql_semantic_equivalence",
        "query_equivalence",
    ),

    "tool_accuracy": ("tool_accuracy", "tool_call_accuracy"),
    "tool_precision": ("tool_precision",),
    "tool_recall": ("tool_recall",),
    "tool_f1": ("tool_f1", "tool_call_f1"),

    "market_accuracy": ("market_accuracy", "market_data_accuracy"),

    "hallucination_rate": ("hallucination_rate",),
}


def _collect_metrics(
    results: list[QuestionEvaluationResult],
) -> dict[str, list[float]]:
    """Gather every applicable evaluator metric across the given questions."""
    collected: dict[str, list[float]] = {}

    for result in results:
        for evaluator in result.evaluator_results.values():
            if not evaluator.applicable:
                continue

            for metric_name, metric_value in evaluator.metrics.items():
                numeric_value = _to_float(
                    metric_value
                )

                if numeric_value is None:
                    continue

                collected.setdefault(
                    metric_name,
                    [],
                ).append(
                    numeric_value
                )

    return collected


def _canonical_averages(
    collected: dict[str, list[float]],
) -> dict[str, float | None]:
    """Average each canonical metric, resolving aliases."""
    return {
        canonical_name: _metric_average(
            collected,
            *aliases,
        )
        for canonical_name, aliases in _METRIC_ALIASES.items()
    }


def _derive_hallucination_rate(
    canonical: dict[str, float | None],
) -> float | None:
    """
    Prefer an explicit hallucination metric, else fall back to
    1 - faithfulness.
    """
    explicit = canonical.get(
        "hallucination_rate"
    )

    if explicit is not None:
        return explicit

    faithfulness = canonical.get(
        "faithfulness"
    )

    if faithfulness is None:
        return None

    return round(
        max(
            0.0,
            min(
                1.0,
                1.0 - faithfulness,
            ),
        ),
        4,
    )


def build_route_performance(
    results: list[QuestionEvaluationResult],
) -> dict[str, dict[str, Any]]:
    """
    Per-route metric averages.

    Questions are bucketed by the route they actually took, then each bucket
    is averaged exactly as the whole run is. Every canonical metric is stored,
    not a hand-picked subset, so the dashboard decides which to show per route
    without needing another backend change.

    Only routes that ran appear. A route with no questions has nothing to
    average, and an empty card is worse than an absent one.
    """
    buckets: dict[str, list[QuestionEvaluationResult]] = {}

    for result in results:
        buckets.setdefault(
            classify_execution_route(result),
            [],
        ).append(result)

    performance: dict[str, dict[str, Any]] = {}

    for route, bucket in buckets.items():
        canonical = _canonical_averages(
            _collect_metrics(bucket)
        )

        canonical["hallucination_rate"] = (
            _derive_hallucination_rate(canonical)
        )

        latencies = [
            float(result.execution.latency_ms)
            for result in bucket
        ]

        passed = sum(
            1
            for result in bucket
            if result.passed
        )

        performance[route] = {
            # Kept alongside the metrics so a card can show what its
            # averages are based on.
            "count": len(bucket),
            "pass_rate": round(
                passed / len(bucket),
                4,
            ),
            "avg_latency_ms": _average(
                latencies
            ),

            # Percentiles are computed per route rather than averaged from
            # the run-level ones, because a percentile of a percentile is
            # not a percentile.
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
            **{
                name: value
                for name, value in canonical.items()
                if value is not None
            },
        }

    return performance


def _tool_names(values: Any) -> set[str]:
    """
    Reduce a tool list to a set of tool names.

    Tool lists reach this module in two different shapes. The pipeline's
    `execution.executed_tools` is a list of plain names, but the evaluator's
    details carry RAGAS-style calls built by `_to_tool_calls`, which are
    dicts of {"name": ..., "args": {...}}. Dicts are unhashable, so they have
    to be reduced to names before they can go into a set at all.
    """
    names: set[str] = set()

    for value in values or []:
        if isinstance(value, str):
            name = value
        elif isinstance(value, dict):
            name = str(
                value.get("name", "")
            )
        else:
            # RAGAS ToolCall objects, and anything else with a name.
            name = str(
                getattr(value, "name", "")
                or ""
            )

        name = name.strip()

        if name:
            names.add(name)

    return names


def _safe_extra(
    name: str,
    builder: Any,
    results: list[QuestionEvaluationResult],
) -> dict[str, Any]:
    """
    Build one optional dashboard aggregate, never failing the run.

    These feed display panels only, and they are computed after every real
    metric is already in hand. Losing a whole benchmark — minutes of LLM
    calls across every question — because a summary panel raised would be
    the wrong trade, so the failure is logged and the panel goes missing
    instead.
    """
    try:
        return builder(results)
    except Exception:
        logger.exception(
            "Could not build %s for this run; continuing without it",
            name,
        )

        return {}


def build_tool_summary(
    results: list[QuestionEvaluationResult],
) -> dict[str, dict[str, Any]]:
    """
    Per-tool invocation counts across a run.

    `plan_to_tools` records which tools a question committed the pipeline to
    ("planner", "sql", "vector", "market") and the golden dataset declares
    which it should have used, so both sides of the comparison exist per
    question. That yields, per tool:

      calls      - questions where the tool was actually invoked
      expected   - questions where the dataset expected it
      hits       - questions where both agree
      recall     - of the questions expecting it, how many invoked it
      precision  - of the questions invoking it, how many should have

    Note what is absent: per-tool latency and per-tool success. The pipeline
    times a question end to end, not each tool, and records no per-tool
    outcome, so neither can be derived here.
    """
    summary: dict[str, dict[str, Any]] = {}

    def bucket(tool: str) -> dict[str, Any]:
        return summary.setdefault(
            tool,
            {
                "calls": 0,
                "expected": 0,
                "hits": 0,
            },
        )

    for result in results:
        actual = _tool_names(
            result.execution.executed_tools
        )

        # The dataset's expectation is echoed back by ToolEvaluator's
        # details, which is the only place it survives onto the result.
        tool_result = result.evaluator_results.get(
            "tool"
        )

        expected: set[str] = set()

        if tool_result is not None:
            expected = _tool_names(
                tool_result.details.get(
                    "expected_tool_calls",
                    [],
                )
            )

        for tool in actual:
            bucket(tool)["calls"] += 1

        for tool in expected:
            bucket(tool)["expected"] += 1

        for tool in actual & expected:
            bucket(tool)["hits"] += 1

    for counts in summary.values():
        counts["recall"] = (
            round(
                counts["hits"] / counts["expected"],
                4,
            )
            if counts["expected"]
            else None
        )

        counts["precision"] = (
            round(
                counts["hits"] / counts["calls"],
                4,
            )
            if counts["calls"]
            else None
        )

    return summary


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

    canonical = _canonical_averages(
        _collect_metrics(completed_results)
    )

    total_cost = (
        round(sum(costs), 6)
        if costs
        else None
    )

    # Fallback to 1 - faithfulness only when no dedicated metric exists.
    hallucination_rate = _derive_hallucination_rate(
        canonical
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

        # Counts per actual execution route, for the dashboard's route donut.
        "route_distribution": _safe_extra(
            "route_distribution",
            build_route_distribution,
            completed_results,
        ),

        # The same buckets, averaged, for the per-route performance cards.
        "route_performance": _safe_extra(
            "route_performance",
            build_route_performance,
            completed_results,
        ),

        # Per-tool invocation counts for the tool execution summary.
        "tool_summary": _safe_extra(
            "tool_summary",
            build_tool_summary,
            completed_results,
        ),

        # Intent
        "intent_accuracy": canonical["intent_accuracy"],

        # Ranking
        "precision_at_k": canonical["precision_at_k"],
        "recall_at_k": canonical["recall_at_k"],
        "mrr": canonical["mrr"],
        "ndcg_at_k": canonical["ndcg_at_k"],

        # Canonical RAGAS names used by the database and dashboard.
        "faithfulness": canonical["faithfulness"],
        "response_relevancy": canonical["response_relevancy"],
        "context_precision": canonical["context_precision"],
        "context_recall": canonical["context_recall"],
        "context_entity_recall": canonical["context_entity_recall"],
        "noise_sensitivity": canonical["noise_sensitivity"],

        "hallucination_rate": hallucination_rate,

        # SQL
        "sql_accuracy": canonical["sql_accuracy"],
        "sql_equivalence": canonical["sql_equivalence"],

        # Tools
        "tool_accuracy": canonical["tool_accuracy"],
        "tool_precision": canonical["tool_precision"],
        "tool_recall": canonical["tool_recall"],
        "tool_f1": canonical["tool_f1"],

        # Market
        "market_accuracy": canonical["market_accuracy"],

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

        "route_distribution": {
            route: 0
            for route in CANONICAL_ROUTES
        },
        "route_performance": {},
        "tool_summary": {},

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
