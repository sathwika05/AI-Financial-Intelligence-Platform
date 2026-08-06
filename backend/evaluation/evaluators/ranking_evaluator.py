"""
Finance-specific ranking evaluator.

Purpose
-------
Compare the returned company ranking with the golden expected ranking.

Golden dataset input
--------------------
expected_companies / expected_ranking

Pipeline output
---------------
ranked_companies

Metrics produced
----------------
Precision@K = Precision at K
Recall@K = Recall at K
MRR = Mean Reciprocal Rank
NDCG@K = Normalized Discounted Cumulative Gain at K

Additional full forms
---------------------
DCG = Discounted Cumulative Gain
IDCG = Ideal Discounted Cumulative Gain
"""
from __future__ import annotations

import math
from typing import Any

from backend.evaluation.schemas import EvaluatorResult


class RankingEvaluator:
    """Compare returned company ordering with the golden ranking."""

    def evaluate(
        self,
        *,
        ranked_companies: list[dict[str, Any]],
        expected_companies: list[str],
        k: int,
    ) -> EvaluatorResult:
        if not expected_companies:
            return EvaluatorResult(
                evaluator="ranking",
                applicable=False,
                passed=None,
                score=None,
                metrics={},
                details={},
                errors=[],
            )

        expected = [
            self._normalize(value)
            for value in expected_companies
            if value
        ]

        actual = [
            self._extract_identifier(company)
            for company in ranked_companies
        ]
        actual = [
            value
            for value in actual
            if value
        ]

        effective_k = max(
            1,
            k,
        )
        top_k = actual[
            :effective_k
        ]

        expected_set = set(
            expected
        )

        relevant = [
            value
            for value in top_k
            if value in expected_set
        ]

        precision_at_k = (
            len(relevant)
            / effective_k
        )

        recall_at_k = (
            len(set(relevant))
            / len(expected_set)
        )

        mrr = self._reciprocal_rank(
            actual=top_k,
            expected=expected_set,
        )

        ndcg = self._ndcg_at_k(
            actual=top_k,
            expected_order=expected,
            k=effective_k,
        )

        return EvaluatorResult(
            evaluator="ranking",
            applicable=True,
            passed=(
                recall_at_k > 0
                and ndcg >= 0.50
            ),
            score=round(
                ndcg,
                4,
            ),
            metrics={
                # Precision@K (Precision at K): relevant companies in returned top-K.
                "precision_at_k": round(
                    precision_at_k,
                    4,
                ),
                # Recall@K (Recall at K): golden companies recovered in top-K.
                "recall_at_k": round(
                    recall_at_k,
                    4,
                ),
                # MRR (Mean Reciprocal Rank): rank of the first relevant company.
                "mrr": round(
                    mrr,
                    4,
                ),
                # NDCG@K (Normalized Discounted Cumulative Gain at K): ranking quality with position discounts.
                "ndcg_at_k": round(
                    ndcg,
                    4,
                ),
            },
            details={
                "k": effective_k,
                "expected_companies": expected,
                "actual_companies": actual,
                "top_k_companies": top_k,
                "matched_companies": relevant,
            },
            errors=[],
        )

    @staticmethod
    def _extract_identifier(
        company: dict[str, Any],
    ) -> str:
        value = (
            company.get("ticker")
            or company.get("symbol")
            or company.get("name")
            or ""
        )

        return RankingEvaluator._normalize(
            str(value)
        )

    @staticmethod
    def _normalize(
        value: str,
    ) -> str:
        return value.strip().upper()

    @staticmethod
    def _reciprocal_rank(
        *,
        actual: list[str],
        expected: set[str],
    ) -> float:
        for index, value in enumerate(
            actual,
            start=1,
        ):
            if value in expected:
                return 1.0 / index

        return 0.0

    @staticmethod
    def _ndcg_at_k(
        *,
        actual: list[str],
        expected_order: list[str],
        k: int,
    ) -> float:
        # Earlier golden positions receive higher graded relevance for NDCG@K (Normalized Discounted Cumulative Gain at K).
        relevance = {
            company: (
                len(expected_order)
                - index
            )
            for index, company in enumerate(
                expected_order
            )
        }

        dcg = 0.0

        for index, company in enumerate(
            actual[:k],
            start=1,
        ):
            gain = relevance.get(
                company,
                0,
            )

            if gain > 0:
                dcg += (
                    gain
                    / math.log2(
                        index + 1
                    )
                )

        ideal_gains = sorted(
            relevance.values(),
            reverse=True,
        )[:k]

        ideal_dcg = sum(
            gain
            / math.log2(
                index + 1
            )
            for index, gain in enumerate(
                ideal_gains,
                start=1,
            )
        )

        return (
            dcg / ideal_dcg
            if ideal_dcg
            else 0.0
        )
