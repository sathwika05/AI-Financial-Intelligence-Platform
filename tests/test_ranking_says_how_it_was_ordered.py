"""
When rank order does not follow final_score, the answer has to say so.

A live preprod query for "undervalued companies with low P/E ratios"
returned:

    1. HON   0.697
    2. PYPL  0.657
    3. EOG   0.780   <- higher score than rank 1

That is correct behaviour. `_sql_order_is_authoritative` decides that a
deterministic question -- "the five lowest P/E" -- is already answered by
the ORDER BY the SQL layer wrote, and the composite score cannot
reproduce it: the composite scores P/E, revenue growth and EPS only, and
sorts hardcoded descending, so "smallest" cannot be expressed by it at
all. The scores stay attached for the explainability panel and stop
deciding position.

The problem is that nothing in the response says which rule applied, so
correct behaviour is indistinguishable from a broken sort. A reader sees
rank 1 scoring below rank 3 and concludes the ranking is broken -- in
about five seconds, with no charity.

So the ordering basis is now reported. Not a behaviour change: the same
companies come back in the same order, and the console can explain
itself.

Only visible since preprod moved to a provider whose SQL generation
works. On the previous one every query returned sources_used sql: false,
so the SQL-order branch never ran.
"""
from __future__ import annotations

import pytest

from backend.scoring.ranker import (
    ORDERED_BY_COMPOSITE,
    ORDERED_BY_SQL,
    _sql_order_is_authoritative,
)


class TestWhenSqlOrderWins:
    def test_sql_alone_is_authoritative(self):
        assert _sql_order_is_authoritative(
            sql_result={"generated_sql": "SELECT ticker FROM companies ORDER BY pe_ratio ASC LIMIT 5"},
            sql_tickers=["HON", "PYPL"],
            has_sql=True,
            has_vector=False,
            has_market=False,
        ) is True

    @pytest.mark.parametrize(
        "vector,market", [(True, False), (False, True), (True, True)]
    )
    def test_any_other_source_hands_it_back_to_the_composite(
        self, vector, market
    ):
        """
        Once the question is fuzzy enough to need several signals,
        blending them is the whole point.
        """
        assert _sql_order_is_authoritative(
            sql_result={"generated_sql": "SELECT ticker FROM companies ORDER BY pe_ratio ASC LIMIT 5"},
            sql_tickers=["HON"],
            has_sql=True,
            has_vector=vector,
            has_market=market,
        ) is False

    def test_empty_tickers_refuse_authority(self):
        assert _sql_order_is_authoritative(
            sql_result={"generated_sql": "SELECT ticker FROM companies ORDER BY pe_ratio ASC"},
            sql_tickers=[],
            has_sql=True,
            has_vector=False,
            has_market=False,
        ) is False


class TestTheBasisIsNamed:
    def test_the_two_values_are_distinct(self):
        assert ORDERED_BY_SQL != ORDERED_BY_COMPOSITE

    def test_they_are_stable_strings(self):
        """
        The console branches on these, so they are contract.
        """
        assert ORDERED_BY_SQL == "sql_order"
        assert ORDERED_BY_COMPOSITE == "composite"


class TestEveryRankedCompanyCarriesIt:
    @staticmethod
    def _ranked(basis: str) -> list[dict]:
        return [
            {"ticker": "HON", "final_score": 0.697, "ordered_by": basis},
            {"ticker": "EOG", "final_score": 0.780, "ordered_by": basis},
        ]

    def test_scoring_result_reports_sql_order(self):
        from backend.nodes.scoring_node import ordering_basis

        assert ordering_basis(self._ranked(ORDERED_BY_SQL)) == ORDERED_BY_SQL

    def test_scoring_result_reports_the_composite(self):
        from backend.nodes.scoring_node import ordering_basis

        assert ordering_basis(
            self._ranked(ORDERED_BY_COMPOSITE)
        ) == ORDERED_BY_COMPOSITE

    def test_an_unstamped_ranking_falls_back_to_the_composite(self):
        """
        The composite is the default everywhere else, so an absent value
        must not make the console claim SQL chose the order.
        """
        from backend.nodes.scoring_node import ordering_basis

        assert ordering_basis(
            [{"ticker": "HON", "final_score": 0.6}]
        ) == ORDERED_BY_COMPOSITE

    def test_no_companies_is_the_composite(self):
        from backend.nodes.scoring_node import ordering_basis

        assert ordering_basis([]) == ORDERED_BY_COMPOSITE


class TestTheConsoleCanExplainIt:
    def test_the_response_type_declares_the_field(self):
        source = open("frontend/src/api/types.ts").read()

        assert "ordering" in source

    def test_the_console_explains_a_sql_ordering(self):
        source = open(
            "frontend/src/components/RankingMethodology.tsx"
        ).read()

        assert "sql_order" in source, (
            "a score that disagrees with the rank needs a sentence, not a "
            "tooltip"
        )
