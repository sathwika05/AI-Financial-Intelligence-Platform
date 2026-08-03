from __future__ import annotations

from collections import defaultdict

from backend.evaluation.schemas import (
    BenchmarkRunResult,
    EvaluatorResult,
    QuestionEvaluationResult,
)


def aggregate_evaluator_results(
    evaluator_results: dict[str, EvaluatorResult],
) -> dict[str, float]:
    metrics: dict[str, float] = {}

    for evaluator_name, result in evaluator_results.items():
        if not result.applicable:
            continue

        for metric_name, value in result.metrics.items():
            if isinstance(value, bool):
                metrics[
                    f"{evaluator_name}.{metric_name}"
                ] = float(value)

            elif isinstance(value, (int, float)):
                metrics[
                    f"{evaluator_name}.{metric_name}"
                ] = float(value)

    return metrics


def determine_question_pass(
    evaluator_results: dict[str, EvaluatorResult],
) -> bool:
    applicable_results = [
        result
        for result in evaluator_results.values()
        if result.applicable
    ]

    if not applicable_results:
        return False

    return all(
        result.passed is True
        for result in applicable_results
    )


def aggregate_benchmark_run(
    result: BenchmarkRunResult,
) -> dict[str, float]:
    metric_values: dict[str, list[float]] = defaultdict(list)

    for question_result in result.question_results:
        for metric_name, value in (
            question_result.aggregate_metrics.items()
        ):
            metric_values[metric_name].append(value)

    aggregate_metrics = {
        metric_name: round(
            sum(values) / len(values),
            4,
        )
        for metric_name, values in metric_values.items()
        if values
    }

    if result.total_questions:
        aggregate_metrics["overall_pass_rate"] = round(
            result.passed_questions / result.total_questions,
            4,
        )
    else:
        aggregate_metrics["overall_pass_rate"] = 0.0

    return aggregate_metrics


def finalize_question_result(
    result: QuestionEvaluationResult,
) -> QuestionEvaluationResult:
    result.aggregate_metrics = aggregate_evaluator_results(
        result.evaluator_results
    )

    result.passed = determine_question_pass(
        result.evaluator_results
    )

    return result