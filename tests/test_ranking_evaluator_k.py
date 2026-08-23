"""
precision_at_k must be winnable.

A question that names three companies is answered perfectly by returning
those three in the right order. Dividing by the run's configured top_k of
5 instead of by the three that were asked for caps precision_at_k at 0.6
for that perfect answer, which is what the 2026-08-21 sentiment run
measured: sentiment_002 and sentiment_021 both returned the exact expected
cohort in the exact expected order — mrr 1.0, recall_at_k 1.0, ndcg 1.0 —
and both scored precision_at_k exactly 0.600. No question in that run
scored higher.
"""
from backend.evaluation.evaluators.ranking_evaluator import RankingEvaluator


def _ranked(*tickers):
    return [{"ticker": t} for t in tickers]


class TestPrecisionIsWinnable:
    def test_a_perfect_three_company_answer_scores_one(self):
        result = RankingEvaluator().evaluate(
            ranked_companies=_ranked("NVDA", "AMD", "INTC"),
            expected_companies=["NVDA", "AMD", "INTC"],
            k=5,
        )

        assert result.metrics["precision_at_k"] == 1.0

    def test_the_other_metrics_are_unchanged_by_the_fix(self):
        result = RankingEvaluator().evaluate(
            ranked_companies=_ranked("NVDA", "AMD", "INTC"),
            expected_companies=["NVDA", "AMD", "INTC"],
            k=5,
        )

        assert result.metrics["recall_at_k"] == 1.0
        assert result.metrics["mrr"] == 1.0
        assert result.metrics["ndcg_at_k"] == 1.0

    def test_padding_the_answer_with_extra_companies_still_costs_precision(self):
        """
        The fix must not make precision unloseable. Three expected, and the
        pipeline returns two of them plus three global names: two of the
        three graded slots are right.
        """
        result = RankingEvaluator().evaluate(
            ranked_companies=_ranked("GE", "NVDA", "AMD", "GS", "MS"),
            expected_companies=["NVDA", "AMD", "INTC"],
            k=5,
        )

        assert result.metrics["precision_at_k"] < 1.0
