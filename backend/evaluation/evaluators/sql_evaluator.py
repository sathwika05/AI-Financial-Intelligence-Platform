"""
SQL (Structured Query Language) evaluator.

Purpose
-------
Evaluate both:
1. Execution correctness by comparing actual query results with golden results.
2. Semantic equivalence by comparing generated SQL with golden SQL.

Golden dataset inputs
---------------------
expected_sql
expected_result

Pipeline outputs
----------------
generated_sql
actual_result

Metrics produced
----------------
sql_accuracy
    Computed with DataCompyScore after converting both results into
    CSV (Comma-Separated Values).

sql_equivalence
    Computed with SQLSemanticEquivalence using an independent
    LLM (Large Language Model) judge and the database schema. Binary: 1.0
    or 0.0, with no partial credit for a near miss.

sql_column_coverage
    Fraction of the reference's columns present in the result. Diagnostic
    only — it exists because DataCompyScore compares shared columns and
    cannot see a dropped one.

Scoring
-------
The two scored metrics are weighted, not averaged as equals — see
ACCURACY_WEIGHT. Pass/fail turns on execution accuracy whenever golden rows
exist, and falls back to equivalence only when there is nothing to execute
against.

Full forms
----------
SQL = Structured Query Language
CSV = Comma-Separated Values
CTE = Common Table Expression
F1 = Harmonic mean of precision and recall
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from backend.evaluation.schemas import EvaluatorResult
from backend.observability.logging import log_span


# Execution correctness is the ground truth, and semantic equivalence is a
# secondary signal, so they are not averaged as equals.
#
# One question has many correct SQL queries. Equivalence asks whether the
# generated query matches one particular reference *phrasing*, and it is
# binary — a query differing only by an unselected filter column scores the
# same 0.0 as a query that answers a different question entirely. Execution
# accuracy asks whether the right rows came back, which is what the pipeline
# is actually judged on, and it is what text-to-SQL benchmarks headline for
# exactly this reason.
#
# Equivalence still earns a quarter of the score: a query returning the right
# rows by accident, or one that would diverge on different data, is worth
# knowing about.
ACCURACY_WEIGHT = 0.75
EQUIVALENCE_WEIGHT = 0.25

PASS_THRESHOLD = 0.70


class SQLEvaluator:
    """Evaluate SQL result correctness, semantic equivalence, and safety."""

    def __init__(
        self,
        *,
        judge_llm: Any,
        datacompy_mode: str = "rows",
        datacompy_metric: str = "f1",
    ) -> None:
        """
        judge_llm:
            A RAGAS-compatible judge LLM created with ragas.llms.base.llm_factory.

        datacompy_mode:
            "rows" or "columns".

        datacompy_metric:
            Usually "f1", "precision", or "recall".
        """
        self.judge_llm = judge_llm
        self.datacompy_mode = datacompy_mode
        self.datacompy_metric = datacompy_metric

    @log_span("generated_sql")
    async def evaluate(
        self,
        *,
        generated_sql: str | None,
        actual_result: Any,
        expected_sql: str | None,
        expected_result: Any,
        database_schema: str,
    ) -> EvaluatorResult:
        generated = (generated_sql or "").strip()
        reference_sql = (expected_sql or "").strip()

        errors: list[str] = []

        # Guardrail: generated SQL (Structured Query Language) must be read-only.
        read_only = self._is_read_only_query(
            generated
        )

        if not generated:
            errors.append(
                "The pipeline did not generate SQL."
            )
        elif not read_only:
            errors.append(
                "Generated SQL is not a read-only SELECT/CTE query."
            )

        sql_accuracy: float | None = None
        sql_equivalence: float | None = None

        # ------------------------------------------------------------------
        # 1. Execution-based evaluation: compare actual result with golden result.
        # ------------------------------------------------------------------
        if expected_result is not None:
            try:
                from ragas.metrics.collections import DataCompyScore

                response_csv = self._result_to_csv(
                    actual_result
                )
                reference_csv = self._result_to_csv(
                    expected_result
                )

                metric = DataCompyScore(
                    mode=self.datacompy_mode,
                    metric=self.datacompy_metric,
                )

                score_result = await metric.ascore(
                    response=response_csv,
                    reference=reference_csv,
                )

                sql_accuracy = self._clamp(
                    float(score_result.value)
                )

            except Exception as exc:
                errors.append(
                    f"DataCompyScore failed: {exc}"
                )

        # ------------------------------------------------------------------
        # 2. Non-execution evaluation: compare generated SQL with golden SQL.
        # ------------------------------------------------------------------
        if generated and reference_sql:
            try:
                from ragas.metrics.collections import (
                    SQLSemanticEquivalence,
                )

                metric = SQLSemanticEquivalence(
                    llm=self.judge_llm
                )

                score_result = await metric.ascore(
                    response=generated,
                    reference=reference_sql,
                    reference_contexts=[
                        database_schema
                    ],
                )

                sql_equivalence = self._clamp(
                    float(score_result.value)
                )

            except Exception as exc:
                errors.append(
                    f"SQLSemanticEquivalence failed: {exc}"
                )

        # Diagnostic only. Records which reference columns the result is
        # missing, because DataCompyScore compares the columns the two sides
        # share and is therefore blind to a dropped one — it scored a perfect
        # 1.0 on a result missing two columns while printing "df1 does not
        # match df2". Reported rather than scored: a missing column that
        # actually breaks something shows up in the evaluator that depends on
        # it, and failing here as well would double-count it.
        column_coverage = self._column_coverage(
            actual_result,
            expected_result,
        )

        # Weighted, using only the metrics that were computable. Weights are
        # renormalised over what is present, so a question with no golden rows
        # is still scored out of 1.0 on equivalence alone rather than being
        # capped at 0.25.
        weighted = [
            (score, weight)
            for score, weight in (
                (sql_accuracy, ACCURACY_WEIGHT),
                (sql_equivalence, EQUIVALENCE_WEIGHT),
            )
            if score is not None
        ]

        total_weight = sum(
            weight for _, weight in weighted
        )

        overall_score = (
            sum(
                score * weight
                for score, weight in weighted
            )
            / total_weight
            if total_weight
            else 0.0
        )

        # Pass/fail turns on the strongest signal available, not on the blend.
        # Execution accuracy is that signal whenever golden rows exist: a query
        # returning exactly the expected rows has answered the question, and a
        # disagreement with the reference phrasing should not overturn that.
        # Equivalence only decides when there is nothing to execute against.
        primary_signal = (
            sql_accuracy
            if sql_accuracy is not None
            else sql_equivalence
        )

        # Safety is mandatory even when quality metrics are high.
        passed = (
            read_only
            and primary_signal is not None
            and primary_signal >= PASS_THRESHOLD
            and not errors
        )

        metrics: dict[str, float] = {}

        if sql_accuracy is not None:
            metrics["sql_accuracy"] = round(
                sql_accuracy,
                4,
            )

        if sql_equivalence is not None:
            metrics["sql_equivalence"] = round(
                sql_equivalence,
                4,
            )

        if column_coverage is not None:
            metrics["sql_column_coverage"] = round(
                column_coverage,
                4,
            )

        return EvaluatorResult(
            evaluator="sql",
            applicable=True,
            passed=passed,
            score=round(
                overall_score,
                4,
            ),
            metrics=metrics,
            details={
                "generated_sql": generated or None,
                "expected_sql": reference_sql or None,
                "read_only": read_only,
                "datacompy_mode": self.datacompy_mode,
                "datacompy_metric": self.datacompy_metric,
                # Which signal decided pass/fail, so a result that passes on
                # accuracy while equivalence reads 0.0 is self-explaining.
                "primary_signal": (
                    "sql_accuracy"
                    if sql_accuracy is not None
                    else "sql_equivalence"
                ),
                "weights": {
                    "sql_accuracy": ACCURACY_WEIGHT,
                    "sql_equivalence": EQUIVALENCE_WEIGHT,
                },
            },
            errors=errors,
        )

    @classmethod
    def _column_coverage(
        cls,
        actual_result: Any,
        expected_result: Any,
    ) -> float | None:
        """
        Fraction of the reference's columns that the result also has.

        Returns None when either side has no identifiable columns, so a
        question without golden rows reports nothing rather than a
        misleading zero.
        """
        expected_columns = cls._column_names(
            expected_result
        )

        if not expected_columns:
            return None

        actual_columns = cls._column_names(
            actual_result
        )

        if not actual_columns:
            return 0.0

        present = sum(
            1
            for column in expected_columns
            if column in actual_columns
        )

        return present / len(expected_columns)

    @classmethod
    def _column_names(
        cls,
        result: Any,
    ) -> set[str]:
        """Column names of a result, in any of the shapes seen upstream."""
        if result is None:
            return set()

        # An executor payload carries its own column list.
        if isinstance(result, Mapping):
            columns = result.get("columns")

            if isinstance(columns, (list, tuple)):
                return {
                    str(column).strip().lower()
                    for column in columns
                }

        # pandas DataFrame.
        if hasattr(result, "columns") and not isinstance(
            result,
            Mapping,
        ):
            try:
                return {
                    str(column).strip().lower()
                    for column in result.columns
                }
            except TypeError:
                return set()

        # Otherwise take the union of the keys the rows carry.
        names: set[str] = set()

        for row in cls._extract_rows(result):
            if isinstance(row, Mapping):
                names.update(
                    str(key).strip().lower()
                    for key in row.keys()
                )

        return names

    @staticmethod
    def _is_read_only_query(
        query: str,
    ) -> bool:
        """Allow SELECT and WITH CTE (Common Table Expression) queries; reject data-changing statements."""
        if not query:
            return False

        normalized = query.strip().lower()

        starts_as_read = (
            normalized.startswith("select")
            or normalized.startswith("with")
        )

        forbidden = re.compile(
            r"\b("
            r"insert|update|delete|drop|alter|truncate|"
            r"create|grant|revoke|copy|merge"
            r")\b",
            re.IGNORECASE,
        )

        return (
            starts_as_read
            and forbidden.search(query) is None
        )

    @classmethod
    def _result_to_csv(
        cls,
        result: Any,
    ) -> str:
        """
        Convert common SQL (Structured Query Language) result shapes into CSV (Comma-Separated Values) required by DataCompyScore.

        Supported forms:
        - list[dict]
        - dict containing rows/data/results
        - pandas DataFrame
        - list[tuple] with generated column names
        - scalar values
        """
        # pandas DataFrame support without importing pandas directly.
        if hasattr(result, "to_csv"):
            return result.to_csv(
                index=False
            )

        rows = cls._extract_rows(
            result
        )

        if not rows:
            return ""

        # Dictionary rows preserve real column names.
        if all(
            isinstance(row, Mapping)
            for row in rows
        ):
            fieldnames: list[str] = []

            for row in rows:
                for key in row.keys():
                    key_text = str(key)

                    if key_text not in fieldnames:
                        fieldnames.append(key_text)

            buffer = io.StringIO()
            writer = csv.DictWriter(
                buffer,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()

            for row in rows:
                writer.writerow(
                    {
                        key: cls._serialize_cell(
                            row.get(key)
                        )
                        for key in fieldnames
                    }
                )

            return buffer.getvalue()

        # Tuple/list rows receive stable generated column names.
        if all(
            isinstance(row, Sequence)
            and not isinstance(
                row,
                (str, bytes, bytearray),
            )
            for row in rows
        ):
            width = max(
                len(row)
                for row in rows
            )
            fieldnames = [
                f"column_{index + 1}"
                for index in range(width)
            ]

            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(fieldnames)

            for row in rows:
                writer.writerow(
                    [
                        cls._serialize_cell(value)
                        for value in row
                    ]
                )

            return buffer.getvalue()

        # Scalar fallback.
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["value"])

        for row in rows:
            writer.writerow(
                [
                    cls._serialize_cell(row)
                ]
            )

        return buffer.getvalue()

    @staticmethod
    def _extract_rows(
        result: Any,
    ) -> list[Any]:
        if result is None:
            return []

        if isinstance(result, Mapping):
            for key in (
                "rows",
                "data",
                "results",
                "result",
            ):
                value = result.get(key)

                if isinstance(value, list):
                    return value

            # A single dictionary row.
            return [result]

        if isinstance(result, list):
            return result

        if isinstance(result, tuple):
            return list(result)

        return [result]

    @staticmethod
    def _serialize_cell(
        value: Any,
    ) -> Any:
        if isinstance(
            value,
            (dict, list, tuple),
        ):
            return json.dumps(
                value,
                sort_keys=True,
                default=str,
            )

        return value

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
