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
    LLM (Large Language Model) judge and the database schema.

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

        # Use only metrics that were actually computable.
        available_scores = [
            score
            for score in (
                sql_accuracy,
                sql_equivalence,
            )
            if score is not None
        ]

        overall_score = (
            sum(available_scores)
            / len(available_scores)
            if available_scores
            else 0.0
        )

        # Safety is mandatory even when quality metrics are high.
        passed = (
            read_only
            and bool(available_scores)
            and overall_score >= 0.70
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
            },
            errors=errors,
        )

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
