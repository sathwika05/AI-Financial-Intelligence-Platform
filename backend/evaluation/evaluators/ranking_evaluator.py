from typing import Any

from backend.evaluation.metrics.retrieval_metrics import (
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from backend.evaluation.schemas import EvaluatorResult


class RankingEvaluator:
    name = "ranking"

    def evaluate(
        self,
        *,
        ranked_companies: list[dict[str, Any]],
        expected_companies: list[str],
        k: int = 5,
    ) -> EvaluatorResult:
        if not expected_companies:
            return EvaluatorResult(
                evaluator=self.name,
                applicable=False,
                passed=None,
                metrics={},
            )

        retrieved_tickers = [
            str(company.get("ticker", "")).upper()
            for company in ranked_companies
            if company.get("ticker")
        ]

        expected_tickers = [
            ticker.upper()
            for ticker in expected_companies
        ]

        precision = precision_at_k(
            retrieved_tickers,
            expected_tickers,
            k,
        )

        recall = recall_at_k(
            retrieved_tickers,
            expected_tickers,
            k,
        )

        mrr = reciprocal_rank(
            retrieved_tickers,
            expected_tickers,
        )

        hit_rate = hit_rate_at_k(
            retrieved_tickers,
            expected_tickers,
            k,
        )

        ndcg = ndcg_at_k(
            retrieved_tickers,
            expected_tickers,
            k,
        )

        return EvaluatorResult(
            evaluator=self.name,
            applicable=True,
            passed=recall >= 0.8,
            metrics={
                f"precision_at_{k}": round(precision, 4),
                f"recall_at_{k}": round(recall, 4),
                "mrr": round(mrr, 4),
                f"hit_rate_at_{k}": round(hit_rate, 4),
                f"ndcg_at_{k}": round(ndcg, 4),
            },
        )










