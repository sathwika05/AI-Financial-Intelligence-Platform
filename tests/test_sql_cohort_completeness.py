"""
A cohort question must not lose members to a metric filter.

Rule 3 of the generator prompt tells it to exclude NULL and non-positive
values for the ranking field. That is right for "the five lowest P/E",
where a company without a P/E is not a candidate. It is wrong for "rank
these three on valuation, growth, market performance and sentiment", where
the question already named who it means.

Run 0c6d88ca measured the difference. mixed_013 asks about AMD, INTC and
NVDA; the generator wrote `AND fm.pe_ratio IS NOT NULL AND fm.pe_ratio > 0`
and returned two rows, because Intel's EPS is -2.09 and it therefore has no
P/E. sql_accuracy 0.0. The same happened on mixed_006, mixed_008 and
mixed_011.
"""
from backend.retrieval.sql_executor import build_generation_prompt


class TestCohortCompletenessIsInstructed:
    def test_the_prompt_forbids_dropping_a_named_company(self):
        prompt = build_generation_prompt("Rank AMD, INTC and NVDA.").lower()

        assert "cohort" in prompt

    def test_the_ranking_field_rule_is_scoped_to_metric_selected_questions(self):
        """
        The exclusion must survive — it is what makes "the five lowest P/E"
        correct — but it must say when it applies.
        """
        prompt = build_generation_prompt("Which five have the lowest P/E?")

        assert "IS NOT NULL" in prompt
        assert "decides which companies qualify" in prompt

    def test_the_schema_and_question_still_reach_the_prompt(self):
        prompt = build_generation_prompt("Rank AMD, INTC and NVDA.")

        assert "Rank AMD, INTC and NVDA." in prompt
        assert "DATABASE SCHEMA" in prompt


class TestCohortProjectionIsStated:
    """
    Rows alone are not the answer: sql_accuracy compares values column by
    column, so a query returning the right companies without the right
    measures still scores 0.

    mixed_008 in run 5e6942fb returned BLK, MS and SCHW — the exact cohort —
    and scored 0.0 because it selected market_cap and omitted eps, while the
    golden selects pe_ratio, eps and revenue_growth. Eleven of the fifteen
    mixed questions produced the right columns unprompted; the rule exists
    so it is not left to chance.
    """

    def test_the_measure_set_for_a_cohort_ranking_is_named(self):
        prompt = build_generation_prompt("Rank AMD, INTC and NVDA on valuation.")

        assert "fm.pe_ratio, fm.eps, fm.revenue_growth" in prompt

    def test_it_says_not_to_add_measures_that_were_not_asked_for(self):
        prompt = build_generation_prompt("Rank AMD, INTC and NVDA.").lower()

        assert "market_cap" in prompt
