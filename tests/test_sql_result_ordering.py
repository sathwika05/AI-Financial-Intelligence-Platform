"""
SQL ordering semantics: none / ranking / top_k.

The SQL evaluator answers "did this query satisfy the SQL semantics the
question required", not "did it reproduce every incidental habit of the
golden SQL". sql_order_requirement carries that distinction, and both
primary metrics read it — sql_accuracy at the result level, sql_equivalence
at the query level — so the two cannot disagree about whether ordering was
this query's job.

The risk in loosening any metric is that it stops catching what it was for,
so roughly half of these pin failures rather than passes.
"""
import pytest

from backend.evaluation.datasets.question_sets import get_question_set
from backend.evaluation.evaluators.sql_evaluator import (
    _ORDER_CONTRACTS,
    SQLEvaluator,
)


ROWS = [
    {"ticker": "NVDA", "pe_ratio": 34.457886, "revenue_growth": 0.852},
    {"ticker": "AMD", "pe_ratio": 131.42857, "revenue_growth": 0.501},
    {"ticker": "META", "pe_ratio": 22.22539, "revenue_growth": 0.28},
    {"ticker": "GOOGL", "pe_ratio": 17.364967, "revenue_growth": 0.242},
    {"ticker": "MSFT", "pe_ratio": 27.622198, "revenue_growth": 0.177},
]

# The same five rows as the pipeline returned them: pe_ratio ascending
# rather than revenue_growth descending.
REORDERED = [ROWS[3], ROWS[2], ROWS[4], ROWS[0], ROWS[1]]


def accuracy_inputs(actual, expected, requirement):
    """The two CSVs DataCompyScore would be handed for this requirement."""
    order_matters = requirement in {"ranking", "top_k"}
    return (
        SQLEvaluator._result_to_csv(actual, sort_rows=not order_matters),
        SQLEvaluator._result_to_csv(expected, sort_rows=not order_matters),
    )


def matches(actual, expected, requirement):
    """Whether sql_accuracy would see the two results as identical."""
    a, b = accuracy_inputs(actual, expected, requirement)
    return a == b


# ---------------------------------------------------------------------------
# A-D: the three modes behave differently on order
# ---------------------------------------------------------------------------


class TestOrderingModes:
    def test_a_none_accepts_any_order(self):
        """Same rows and values, order irrelevant -> equivalent."""
        assert matches(REORDERED, ROWS, "none")

    def test_b_ranking_rejects_wrong_order(self):
        """Same rows, order was the answer -> not equivalent."""
        assert not matches(REORDERED, ROWS, "ranking")

    def test_c_topk_accepts_correct_k_in_correct_order(self):
        assert matches(ROWS, ROWS, "top_k")

    def test_d_topk_rejects_arbitrary_k_rows(self):
        """
        Correct filters, five rows, wrong five. A bare LIMIT 5 lands here:
        it returns the right shape and the wrong answer.
        """
        arbitrary = ROWS[:4] + [
            {"ticker": "EOG", "pe_ratio": 10.98, "revenue_growth": 0.587}
        ]
        assert not matches(arbitrary, ROWS, "top_k")

    def test_topk_does_not_degrade_to_an_unordered_set(self):
        """
        top_k grades membership AND order. Correct five, wrong sequence
        must still fail the result comparison.
        """
        assert not matches(REORDERED, ROWS, "top_k")


# ---------------------------------------------------------------------------
# E-H: loosening order must not loosen anything else
# ---------------------------------------------------------------------------


class TestStrictnessPreserved:
    @pytest.mark.parametrize("requirement", ["none", "ranking", "top_k"])
    def test_e_missing_row_fails(self, requirement):
        assert not matches(ROWS[:-1], ROWS, requirement)

    @pytest.mark.parametrize("requirement", ["none", "ranking", "top_k"])
    def test_f_extra_row_fails(self, requirement):
        extra = ROWS + [
            {"ticker": "EOG", "pe_ratio": 10.98, "revenue_growth": 0.587}
        ]
        assert not matches(extra, ROWS, requirement)

    @pytest.mark.parametrize("requirement", ["none", "ranking", "top_k"])
    def test_g_wrong_value_fails(self, requirement):
        wrong = [dict(r) for r in ROWS]
        wrong[0]["revenue_growth"] = 0.111
        assert not matches(wrong, ROWS, requirement)

    @pytest.mark.parametrize("requirement", ["none", "ranking", "top_k"])
    def test_h_duplicate_count_differs_fails(self, requirement):
        """
        Multiset, not set. [Tech, Tech] is a different answer from [Tech]
        to "how many companies per sector".
        """
        expected = [{"sector": "Tech"}, {"sector": "Tech"}, {"sector": "Fin"}]
        actual = [{"sector": "Tech"}, {"sector": "Fin"}]
        assert not matches(actual, expected, requirement)

    def test_duplicates_survive_canonicalisation(self):
        counts = SQLEvaluator._row_multiset(
            [{"sector": "Tech"}, {"sector": "Tech"}]
        )
        assert sum(counts.values()) == 2

    def test_wrong_rows_fail_even_with_matching_count(self):
        wrong = ROWS[:4] + [
            {"ticker": "EOG", "pe_ratio": 10.98, "revenue_growth": 0.587}
        ]
        assert not matches(wrong, ROWS, "none")


# ---------------------------------------------------------------------------
# I-L: whole-question semantics
# ---------------------------------------------------------------------------


class TestQuestionSemantics:
    def test_i_mixed_multisource_passes_on_arbitrary_order(self):
        """
        SQL supplies structured evidence for a ranking it cannot compute,
        so its row order is not part of the contract.
        """
        assert matches(REORDERED, ROWS, "none")

    def test_j_sql_owned_ranking_stays_strict(self):
        """
        A downstream ranking evaluator existing does not release SQL from
        an ordering the question asked SQL for.
        """
        assert not matches(REORDERED, ROWS, "ranking")

    def test_k_limit_without_ranking_is_not_an_ordering_requirement(self):
        """
        "Show five companies with positive earnings" limits without
        ranking: any five qualifying rows, in any order.
        """
        five = ROWS[:5]
        assert matches(list(reversed(five)), five, "none")

    def test_l_topk_needs_the_right_members_not_just_the_right_count(self):
        arbitrary = [
            {"ticker": "EOG", "pe_ratio": 10.98, "revenue_growth": 0.587},
            {"ticker": "XOM", "pe_ratio": 20.4, "revenue_growth": 0.441},
            {"ticker": "CVX", "pe_ratio": 19.0, "revenue_growth": 0.535},
            {"ticker": "JPM", "pe_ratio": 15.5, "revenue_growth": 0.304},
            {"ticker": "GS", "pe_ratio": 16.1, "revenue_growth": 0.425},
        ]
        assert len(arbitrary) == len(ROWS)
        assert not matches(arbitrary, ROWS, "top_k")


# ---------------------------------------------------------------------------
# M-Q: the equivalence judge's contract
# ---------------------------------------------------------------------------


class TestEquivalenceContract:
    def test_m_none_contract_permits_an_absent_order_by(self):
        contract = _ORDER_CONTRACTS["none"]
        assert "one query has an ORDER BY and the other has none" in contract
        assert "NOT part of the requested SQL semantics" in contract

    def test_n_none_contract_permits_a_different_order_by(self):
        contract = _ORDER_CONTRACTS["none"]
        assert "their ORDER BY clauses differ" in contract
        assert "order-insensitive semantics" in contract

    def test_o_ranking_contract_requires_direction(self):
        contract = _ORDER_CONTRACTS["ranking"]
        assert "sort direction" in contract
        # Normalised because the contract is hard-wrapped for the prompt.
        flat = " ".join(contract.split())
        assert (
            "ORDER BY market_cap ASC and ORDER BY market_cap DESC are not "
            "equivalent" in flat
        )

    def test_p_topk_contract_rejects_a_bare_limit(self):
        contract = _ORDER_CONTRACTS["top_k"]
        flat = " ".join(contract.split())
        assert "LIMIT K and no ORDER BY is NOT equivalent" in flat
        assert "arbitrary K rows" in flat

    @pytest.mark.parametrize("mode", ["none", "ranking", "top_k"])
    def test_q_every_contract_keeps_non_ordering_semantics_strict(self, mode):
        """
        The failure to avoid: a contract that reads as general permission.
        Ignoring an incidental ORDER BY must not excuse a wrong filter.
        """
        contract = _ORDER_CONTRACTS[mode]
        assert "NOT equivalent if they differ in" in contract
        for semantic in (
            "filters",
            "joins",
            "required selected columns",
            "aggregation",
        ):
            assert semantic in contract

    def test_contract_is_delivered_as_instruction_not_schema(self):
        """
        Policy belongs in the judge's instruction. Ragas joins
        reference_contexts into a `database_schema` field, where policy
        would read as documentation about the tables.
        """
        from backend.evaluation.evaluators.sql_evaluator import (
            _equivalence_prompt_for,
        )

        prompt = _equivalence_prompt_for("none")
        assert "ROW ORDERING FOR THIS COMPARISON" in prompt.instruction
        # The metric's own instruction is preserved, not replaced.
        assert "semantically equivalent" in prompt.instruction

    def test_each_mode_produces_a_distinct_instruction(self):
        from backend.evaluation.evaluators.sql_evaluator import (
            _equivalence_prompt_for,
        )

        instructions = {
            mode: _equivalence_prompt_for(mode).instruction
            for mode in ("none", "ranking", "top_k")
        }
        assert len(set(instructions.values())) == 3

    def test_unknown_mode_falls_back_to_the_strictest_safe_default(self):
        from backend.evaluation.evaluators.sql_evaluator import (
            _equivalence_prompt_for,
        )

        assert (
            _equivalence_prompt_for("nonsense").instruction
            == _equivalence_prompt_for("none").instruction
        )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_order_correctness_is_none_when_not_applicable(self):
        """
        Absent, not 1.0. Reporting 1.0 would claim the query satisfied a
        requirement the question never made, and inflate the run average.
        """
        assert (
            SQLEvaluator._order_correctness(
                ROWS, ROWS, order_matters=False
            )
            is None
        )

    def test_order_correctness_is_one_for_a_correct_order(self):
        assert (
            SQLEvaluator._order_correctness(ROWS, ROWS, order_matters=True)
            == 1.0
        )

    def test_order_correctness_falls_for_a_wrong_order(self):
        score = SQLEvaluator._order_correctness(
            REORDERED, ROWS, order_matters=True
        )
        assert score < 1.0

    def test_topk_membership_is_none_when_not_applicable(self):
        assert (
            SQLEvaluator._topk_membership(ROWS, ROWS, applicable=False)
            is None
        )

    def test_topk_membership_ignores_order(self):
        """Correct K, wrong sequence: membership 1, order tells the story."""
        assert (
            SQLEvaluator._topk_membership(
                REORDERED, ROWS, applicable=True
            )
            == 1.0
        )
        assert (
            SQLEvaluator._order_correctness(
                REORDERED, ROWS, order_matters=True
            )
            < 1.0
        )

    def test_topk_membership_falls_for_wrong_members(self):
        arbitrary = ROWS[:3] + [
            {"ticker": "EOG", "pe_ratio": 10.98, "revenue_growth": 0.587},
            {"ticker": "XOM", "pe_ratio": 20.4, "revenue_growth": 0.441},
        ]
        assert (
            SQLEvaluator._topk_membership(
                arbitrary, ROWS, applicable=True
            )
            == pytest.approx(0.6)
        )

    def test_diagnostics_ignore_columns_the_two_sides_do_not_share(self):
        """
        The bug this caught in a real run: growth_001 reported
        sql_accuracy 1.0 alongside membership 0.0, which cannot both be
        true. DataCompy compares shared columns, so a generated query
        selecting fewer or more columns still matched on the rest — while
        the diagnostics keyed on whole rows and saw nothing in common.
        """
        expected = [
            {"ticker": "NVDA", "revenue_growth": 0.852, "eps": 6.53},
            {"ticker": "AMD", "revenue_growth": 0.501, "eps": 3.85},
        ]
        # Same rows, but the query never selected eps.
        actual_missing = [
            {"ticker": "NVDA", "revenue_growth": 0.852},
            {"ticker": "AMD", "revenue_growth": 0.501},
        ]
        # Same rows, plus a column the reference did not ask for.
        actual_extra = [
            {"ticker": "NVDA", "revenue_growth": 0.852, "eps": 6.53, "mc": 1},
            {"ticker": "AMD", "revenue_growth": 0.501, "eps": 3.85, "mc": 2},
        ]

        for actual in (actual_missing, actual_extra):
            assert (
                SQLEvaluator._topk_membership(
                    actual, expected, applicable=True
                )
                == 1.0
            )
            assert (
                SQLEvaluator._order_correctness(
                    actual, expected, order_matters=True
                )
                == 1.0
            )

    def test_int_and_float_of_the_same_number_are_one_row(self):
        """
        Caught in a real run: valuation_002 stores market_cap as an int in
        its golden while Postgres returns double precision, so 100980899840
        and 100980899840.0 keyed differently and membership scored 0.0
        against an accuracy of 1.0. DataCompy already treats these as equal,
        so the diagnostics have to agree with the metric they explain.
        """
        expected = [{"ticker": "ADBE", "market_cap": 100980899840}]
        actual = [{"ticker": "ADBE", "market_cap": 100980899840.0}]

        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 1.0
        )
        assert (
            SQLEvaluator._order_correctness(
                actual, expected, order_matters=True
            )
            == 1.0
        )

    def test_decimal_matches_the_same_float(self):
        from decimal import Decimal

        expected = [{"t": "X", "v": Decimal("10.5")}]
        actual = [{"t": "X", "v": 10.5}]
        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 1.0
        )

    def test_numeric_widening_does_not_equate_strings_to_numbers(self):
        """Aligning int with float must not start coercing "10" to 10."""
        expected = [{"t": "X", "v": 10}]
        actual = [{"t": "X", "v": "10"}]
        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 0.0
        )

    def test_booleans_do_not_collapse_into_numbers(self):
        """bool subclasses int, so True must not become 1.0."""
        expected = [{"t": "X", "flag": True}]
        actual = [{"t": "X", "flag": 1}]
        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 0.0
        )

    def test_numeric_widening_does_not_round(self):
        expected = [{"t": "X", "v": 10.0}]
        actual = [{"t": "X", "v": 10.0000001}]
        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 0.0
        )

    def test_shared_column_projection_still_catches_wrong_values(self):
        """Projection must not become blindness to the values that remain."""
        expected = [{"ticker": "NVDA", "revenue_growth": 0.852, "eps": 6.53}]
        actual = [{"ticker": "NVDA", "revenue_growth": 0.111}]

        assert (
            SQLEvaluator._topk_membership(actual, expected, applicable=True)
            == 0.0
        )

    def test_membership_counts_duplicates(self):
        expected = [{"s": "T"}, {"s": "T"}, {"s": "F"}]
        actual = [{"s": "T"}, {"s": "F"}]
        assert SQLEvaluator._topk_membership(
            actual, expected, applicable=True
        ) == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Benchmark classification
# ---------------------------------------------------------------------------


class TestQuestionClassification:
    @pytest.mark.parametrize(
        "question_set,question_id,expected",
        [
            ("valuation", "valuation_002", "top_k"),
            ("growth", "growth_001", "top_k"),
            ("mixed", "mixed_001", "none"),
        ],
    )
    def test_questions_are_classified_explicitly(
        self, question_set, question_id, expected
    ):
        """
        Every SQL-backed question states its own contract rather than
        inheriting the default, so the default can never silently relax an
        existing ranking question.
        """
        question = next(
            q
            for q in get_question_set(question_set)
            if q.question_id == question_id
        )
        assert question.sql_order_requirement == expected

    def test_default_is_the_non_claiming_mode(self):
        """
        A new question claims no ordering contract until someone states
        one — the opposite would assert a requirement nobody wrote down.
        """
        from backend.evaluation.schemas import EvalQuestion, IntentType

        question = EvalQuestion(
            question_id="x",
            question="x",
            expected_intent=IntentType.VALUATION,
        )
        assert question.sql_order_requirement == "none"

    def test_requirement_is_validated(self):
        from pydantic import ValidationError

        from backend.evaluation.schemas import EvalQuestion, IntentType

        with pytest.raises(ValidationError):
            EvalQuestion(
                question_id="x",
                question="x",
                expected_intent=IntentType.VALUATION,
                sql_order_requirement="sorted",
            )
