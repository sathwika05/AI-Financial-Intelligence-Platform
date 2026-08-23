"""
The report's key_metrics come from the ranked companies, not the model.

pe_ratio, eps, revenue_growth and market_cap are already on each ranked
company, straight from SQL. Asking the analysis LLM to restate them in its
JSON costs output tokens on every company — the analysis node is the
slowest stage at 15-36s, and that time is dominated by tokens generated,
not by prompt size — and it puts a transcription step between a database
value and the screen.

That step corrupts. frontend/src/api/types.ts documents the result:
market_cap "has been observed as a number (5453358039040.0)" and sometimes
as a string, while revenue_growth "arrives pre-formatted" as "85.2%". Those
inconsistencies exist because a model is retyping numbers it was handed.

So the prompt no longer asks for them, and they are attached after the call
from the values the ranker already holds.
"""
from backend.nodes.analysis_node import (
    SYSTEM_PROMPT,
    attach_ranked_metrics,
)


class TestThePromptDoesNotAskForMetrics:
    def test_key_metrics_is_not_requested(self):
        assert "key_metrics" not in SYSTEM_PROMPT

    def test_the_prompt_still_asks_for_the_evidence(self):
        """Trimming output must not cost the grounded part."""
        assert "citation_id" in SYSTEM_PROMPT
        assert "summary" in SYSTEM_PROMPT


class TestMetricsComeFromTheRanking:
    def test_each_company_gets_the_ranked_values(self):
        report = {
            "companies": [
                {"ticker": "NVDA", "summary": "..."},
                {"ticker": "INTC", "summary": "..."},
            ]
        }
        ranked = [
            {
                "ticker": "NVDA",
                "metrics": {
                    "pe_ratio": 33.2,
                    "eps": 6.53,
                    "revenue_growth": 0.852,
                    "market_cap": 3.3e12,
                },
            },
            {
                "ticker": "INTC",
                "metrics": {
                    "pe_ratio": None,
                    "eps": -2.09,
                    "revenue_growth": 0.254,
                    "market_cap": 1.0e11,
                },
            },
        ]

        attach_ranked_metrics(report, ranked)

        assert report["companies"][0]["key_metrics"]["pe_ratio"] == 33.2
        assert report["companies"][1]["key_metrics"]["eps"] == -2.09

    def test_a_null_metric_is_preserved_not_dropped(self):
        """
        Intel has no P/E because its EPS is negative. That absence is a
        fact about the company and must reach the screen as null, not as a
        missing key or an invented number.
        """
        report = {"companies": [{"ticker": "INTC"}]}
        ranked = [{"ticker": "INTC", "metrics": {"pe_ratio": None}}]

        attach_ranked_metrics(report, ranked)

        assert report["companies"][0]["key_metrics"]["pe_ratio"] is None

    def test_a_company_the_ranker_does_not_know_is_left_alone(self):
        report = {"companies": [{"ticker": "WHO"}]}

        attach_ranked_metrics(report, [])

        assert report["companies"][0].get("key_metrics") is None

    def test_a_report_without_companies_does_not_explode(self):
        report = {}

        attach_ranked_metrics(report, [])

        assert report == {}
