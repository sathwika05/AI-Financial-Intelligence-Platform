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
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
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


# What each ordering mode tells the equivalence judge, appended to the
# metric's own instruction.
#
# This is evaluation policy, not schema, so it is delivered through the
# prompt's `instruction` rather than through `reference_contexts`. Ragas
# joins reference_contexts into a `database_schema` field, and policy
# arriving there reads to the model as documentation about the tables.
# SQLSemanticEquivalence assigns `self.equivalence_prompt` in __init__, so
# swapping in a subclass overrides the instruction without touching
# site-packages.
#
# Every mode restates what stays strict. The failure to avoid is a contract
# that reads as general permission — the goal is to stop counting one
# incidental ORDER BY, not to soften the judge.
_STRICT_REGARDLESS = """
Regardless of ordering, the queries are NOT equivalent if they differ in
filters, joins, required selected columns, calculations, aggregation,
grouping, or the number of rows returned.

REDUNDANT PREDICATES ARE NOT A DIFFERENCE IN FILTERS.
A filter difference has to change which rows qualify. Two predicates that
provably select the same rows are one filter written two ways:

  `x IS NOT NULL AND x > 0`  selects exactly what  `x > 0`  selects,
  because a comparison against NULL is never true.

Adding or omitting a guard that another predicate already implies is a
stylistic difference. Do not judge queries non-equivalent for it alone.

This applies ONLY where the predicates are provably interchangeable, which
you must check rather than assume. `x > 0` and `x >= 0` differ. So do
`x > 0` and `x IS NOT NULL` on a column that can hold negatives: the first
excludes them and the second keeps them. When you cannot show the two
select the same rows for every possible value of the column, they differ.
"""

_ORDER_CONTRACTS: dict[str, str] = {
    "none": (
        """

ROW ORDERING FOR THIS COMPARISON:
Row ordering is NOT part of the requested SQL semantics. The question did
not make this query responsible for producing an order.

Therefore do NOT judge the queries non-equivalent solely because:
- their ORDER BY clauses differ
- one query has an ORDER BY and the other has none
- they sort in different directions
- the reference query contains incidental ordering

Judge them under order-insensitive semantics: do both retrieve the same
required rows and values?
"""
        + _STRICT_REGARDLESS
    ),
    "ranking": (
        """

ROW ORDERING FOR THIS COMPARISON:
Row ordering IS part of the requested SQL semantics. The question asked
this query to return rows in a specific order, so the ordering is part of
the answer rather than a presentation detail.

Treat the queries as NOT equivalent if they differ in the column they sort
on, or in sort direction. ORDER BY market_cap ASC and ORDER BY market_cap
DESC are not equivalent.
"""
        + _STRICT_REGARDLESS
    ),
    "top_k": (
        """

ROW ORDERING FOR THIS COMPARISON:
Ordering DETERMINES WHICH ROWS ARE RETURNED. The question asked for the
top or bottom K rows by some measure, so the ORDER BY is what selects the
K rows, not merely how they are arranged.

Treat the queries as NOT equivalent if they differ in the ranking column,
the ranking direction, or K. In particular, a query with LIMIT K and no
ORDER BY is NOT equivalent to one with ORDER BY <measure> <direction>
LIMIT K: the first returns an arbitrary K rows, and only the second
returns the K the question asked for.
"""
        + _STRICT_REGARDLESS
    ),
}


def _equivalence_prompt_for(order_requirement: str):
    """
    An SQLEquivalencePrompt carrying this question's ordering contract.

    Imported lazily so the module keeps loading when ragas is absent, which
    is how the rest of this evaluator already treats it.
    """
    from ragas.metrics.collections.sql_semantic_equivalence.util import (
        SQLEquivalencePrompt,
    )

    contract = _ORDER_CONTRACTS.get(
        order_requirement,
        _ORDER_CONTRACTS["none"],
    )

    class _ContractPrompt(SQLEquivalencePrompt):
        instruction = (
            SQLEquivalencePrompt.instruction + contract
        )

    return _ContractPrompt()


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
            "rows" or "columns". "rows" compares positionally — the same
            rows in a different order score 0.0 — so it is the right mode
            only when the question asked SQL to produce an order. The
            default stays "rows"; evaluate() takes a per-question override.

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
        sql_order_requirement: str = "none",
    ) -> EvaluatorResult:
        """
        sql_order_requirement:
            "none", "ranking" or "top_k" — what the question makes this
            query responsible for orderwise. Drives both sql_accuracy and
            sql_equivalence, so the result-level and query-level metrics
            judge the same contract. See EvalQuestion.sql_order_requirement.
        """
        generated = (generated_sql or "").strip()
        order_matters = sql_order_requirement in {
            "ranking",
            "top_k",
        }
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
        equivalence_reason: str | None = None

        # ------------------------------------------------------------------
        # 1. Execution-based evaluation: compare actual result with golden result.
        # ------------------------------------------------------------------
        if expected_result is not None:
            try:
                from ragas.metrics.collections import DataCompyScore

                # When the question did not ask SQL to sort, both sides are
                # put in the same canonical row order first. DataCompyScore
                # compares "rows" positionally, so without this the right
                # rows in a different order score 0.0 — which is correct for
                # a ranking question and wrong for every other kind.
                #
                # Sorting rather than switching to mode="columns" keeps the
                # comparison row-shaped: every row must still match a row on
                # the other side, only their positions stop mattering.
                response_csv = self._result_to_csv(
                    actual_result,
                    sort_rows=not order_matters,
                )
                reference_csv = self._result_to_csv(
                    expected_result,
                    sort_rows=not order_matters,
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

                # Same contract the result comparison above is using, so
                # the query-level and result-level metrics cannot disagree
                # about whether ordering was this query's job. Without it,
                # declaring order irrelevant for sql_accuracy still left
                # sql_equivalence failing on the same ORDER BY, and a
                # correct query capped at 0.75.
                metric.equivalence_prompt = _equivalence_prompt_for(
                    sql_order_requirement
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

                # The judge explains both queries. Kept so a 0.0 can be read
                # rather than guessed at — the difference it objected to may
                # be a real one.
                equivalence_reason = getattr(
                    score_result,
                    "reason",
                    None,
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

        # Diagnostics: they explain a failure, they do not cause one. Both
        # stay out of the weighted score below, because sql_accuracy already
        # enforces this contract at the result level and adding them would
        # count one ordering mistake three times.
        #
        # Derived from the rows themselves rather than from the SQL text.
        # A query can carry ORDER BY ... LIMIT K and still select the wrong
        # K, so reading the clause would prove nothing about what came back.
        order_correctness = self._order_correctness(
            actual_result,
            expected_result,
            order_matters=order_matters,
        )
        topk_membership = self._topk_membership(
            actual_result,
            expected_result,
            applicable=sql_order_requirement == "top_k",
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

        # Omitted entirely when not applicable, rather than reported as 0.0
        # or 1.0. Aggregation averages the metric names it finds, so a
        # placeholder would either deflate or inflate the run: absence is
        # the only honest encoding of "this question did not ask".
        if order_correctness is not None:
            metrics["sql_order_correctness"] = round(
                order_correctness,
                4,
            )

        if topk_membership is not None:
            metrics["sql_topk_membership"] = round(
                topk_membership,
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
                # The contract both primary metrics were judged against.
                "sql_order_requirement": sql_order_requirement,
                # The judge's own account of both queries, so a 0.0 can be
                # read rather than assumed to be about ordering.
                "equivalence_reason": equivalence_reason,
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
    def _row_key(
        cls,
        row: Any,
        columns: set[str] | None = None,
    ) -> str:
        """
        A row reduced to a comparable string.

        `columns` restricts the key to those column names, which is what
        keeps these diagnostics agreeing with sql_accuracy: DataCompy
        compares the columns the two sides share, so a query selecting an
        extra column, or omitting one the reference had, still matches on
        the rest. Keying on the whole row instead made every row differ
        whenever the column lists differed at all — growth_001 scored
        sql_accuracy 1.0 with membership 0.0, which cannot both be true.
        A genuinely missing column is reported by sql_column_coverage.

        Deliberately thin otherwise. It reuses `_serialize_cell` and json's
        own number formatting rather than adding coercions — this change is
        about ordering semantics, and quietly deciding that "10" equals 10,
        or that 10.0000001 equals 10.0, would redefine value correctness
        along the way. DataCompy still owns what counts as an equal value
        for sql_accuracy; these diagnostics need only a stable identity.
        """
        if isinstance(row, Mapping):
            return json.dumps(
                {
                    str(key): cls._comparable_cell(value)
                    for key, value in row.items()
                    if columns is None
                    or str(key).strip().lower() in columns
                },
                sort_keys=True,
                default=str,
            )

        return json.dumps(
            cls._comparable_cell(row),
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _comparable_cell(
        cls,
        value: Any,
    ) -> Any:
        """
        One cell reduced to the identity these diagnostics compare on.

        Numbers are widened to float because DataCompy already treats 10 and
        10.0 as the same value, and sql_accuracy is scored on that basis.
        Without it the diagnostics disagreed with the metric they exist to
        explain: valuation_002 stores market_cap as an int in its golden
        while Postgres returns double precision, so every row read as
        different and membership scored 0.0 against an accuracy of 1.0.

        This aligns with existing behaviour rather than adding leniency —
        the evaluator's notion of an equal value is unchanged. Nothing else
        is coerced: "10" stays a string, and no rounding is applied, so a
        genuinely different value still differs.

        Two known limits, neither reachable with this data: integers beyond
        2**53 lose precision as floats, and bool is excluded explicitly
        because it subclasses int and True would otherwise equal 1.0.
        """
        if isinstance(value, bool):
            return value

        if isinstance(value, int):
            return float(value)

        if isinstance(value, Decimal):
            return float(value)

        return cls._serialize_cell(value)

    @classmethod
    def _shared_columns(
        cls,
        actual_result: Any,
        expected_result: Any,
    ) -> set[str] | None:
        """
        Column names both sides have, or None when either side has none.

        None means "compare whole rows", which is the right fallback for
        tuple or scalar results that carry no column names.
        """
        actual_columns = cls._column_names(actual_result)
        expected_columns = cls._column_names(expected_result)

        if not actual_columns or not expected_columns:
            return None

        shared = actual_columns & expected_columns

        return shared or None

    @classmethod
    def _row_multiset(
        cls,
        result: Any,
        columns: set[str] | None = None,
    ) -> Counter:
        """
        Rows as a multiset, so duplicate counts survive the comparison.

        A set would make [Tech, Tech] equal [Tech], which is a different
        answer to "how many companies per sector".
        """
        return Counter(
            cls._row_key(row, columns)
            for row in cls._extract_rows(result)
        )

    @classmethod
    def _order_correctness(
        cls,
        actual_result: Any,
        expected_result: Any,
        *,
        order_matters: bool,
    ) -> float | None:
        """
        Whether the rows came back in the order the question asked for.

        None when the question asked for no order — reporting 1.0 there
        would claim the query satisfied a requirement that was never made.

        Scored as the fraction of positions holding the expected row, so a
        near-miss reads differently from a reversal. Diagnostic only.
        """
        if not order_matters:
            return None

        expected_rows = cls._extract_rows(expected_result)

        if not expected_rows:
            return None

        actual_rows = cls._extract_rows(actual_result)

        columns = cls._shared_columns(
            actual_result,
            expected_result,
        )

        matches = sum(
            1
            for index, expected_row in enumerate(expected_rows)
            if index < len(actual_rows)
            and cls._row_key(actual_rows[index], columns)
            == cls._row_key(expected_row, columns)
        )

        return matches / len(expected_rows)

    @classmethod
    def _topk_membership(
        cls,
        actual_result: Any,
        expected_result: Any,
        *,
        applicable: bool,
    ) -> float | None:
        """
        Whether the right K rows were selected, ignoring their order.

        Answers the question ordering decides for a top-K query: not "are
        these arranged correctly" but "are these the right rows at all". A
        bare LIMIT 5 returns five rows and usually the wrong five, and this
        is what separates that from a correct query whose sort differs.

        Computed from the returned rows rather than from ORDER BY ... LIMIT
        in the SQL text, which proves only that the query asked for a top-K,
        never that it got one. Diagnostic only.
        """
        if not applicable:
            return None

        columns = cls._shared_columns(
            actual_result,
            expected_result,
        )

        expected_counts = cls._row_multiset(
            expected_result,
            columns,
        )

        if not expected_counts:
            return None

        actual_counts = cls._row_multiset(
            actual_result,
            columns,
        )

        overlap = sum(
            min(count, actual_counts.get(key, 0))
            for key, count in expected_counts.items()
        )

        return overlap / sum(expected_counts.values())

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
        *,
        sort_rows: bool = False,
    ) -> str:
        """
        Convert common SQL (Structured Query Language) result shapes into CSV (Comma-Separated Values) required by DataCompyScore.

        Supported forms:
        - list[dict]
        - dict containing rows/data/results
        - pandas DataFrame
        - list[tuple] with generated column names
        - scalar values

        sort_rows puts the rows in a canonical order so two results holding
        the same rows in different orders produce identical CSV. Applied to
        both sides or neither, so it never changes what counts as a match —
        only whether position counts.
        """
        # pandas DataFrame support without importing pandas directly.
        if hasattr(result, "to_csv"):
            # Left in source order: the pipeline hands this evaluator
            # list[dict], so a DataFrame only arrives from a caller that
            # built one deliberately, and reordering it is not this
            # method's decision to make.
            return result.to_csv(
                index=False
            )

        rows = cls._extract_rows(
            result
        )

        if not rows:
            return ""

        if sort_rows:
            # Keyed on the serialised row so the order is total and stable
            # across mixed types — sorting the rows directly raises on a
            # dict, and comparing floats to strings raises on a tuple.
            rows = sorted(
                rows,
                key=lambda row: json.dumps(
                    row,
                    sort_keys=True,
                    default=str,
                ),
            )

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
