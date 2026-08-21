"""
The SQL-derived question sets.

Sixty questions whose expected rows are read from the database rather than
written by hand, because a reseed moves every fundamental and rebuilding
them manually is not slow, it is infeasible.

Two properties matter more than the count. The queries must respect the
companies/financial_metrics split, since getting that wrong is what broke
two benchmark runs. And the questions must differ in SHAPE: this session
found four bugs and each needed a structurally different question — the one
that caught fm.market_cap was the only one joining both tables, and no
number of extra top-K-by-metric variants would have found it.
"""
import json
from pathlib import Path

import pytest

from backend.evaluation.datasets.question_bank import (
    COMPANY_COLUMNS,
    GROWTH_SPECS,
    METRIC_COLUMNS,
    RANKABLE_SECTORS,
    SPEC_SETS,
    VALUATION_SPECS,
    build_sql,
)


ALL_SPECS = VALUATION_SPECS + GROWTH_SPECS


class TestSpecInventory:
    def test_thirty_of_each(self):
        assert len(VALUATION_SPECS) == 30
        assert len(GROWTH_SPECS) == 30

    def test_ids_are_unique(self):
        ids = [spec.question_id for spec in ALL_SPECS]
        assert len(set(ids)) == len(ids)

    def test_questions_are_distinct(self):
        texts = [spec.question for spec in ALL_SPECS]
        assert len(set(texts)) == len(texts)

    def test_shapes_are_varied_not_permuted(self):
        """
        Twenty-five questions of one shape give twenty-five samples of one
        failure mode. Diversity is the point, so a majority of specs must
        not share a single shape.
        """
        from collections import Counter

        counts = Counter(spec.shape for spec in ALL_SPECS)
        assert len(counts) >= 12
        assert counts.most_common(1)[0][1] <= len(ALL_SPECS) // 2

    def test_consumer_defensive_is_excluded(self):
        """
        It holds one company in the seed, so "the three largest" there is
        not a question that can be answered.
        """
        assert "Consumer Defensive" not in RANKABLE_SECTORS


class TestSchemaSplitIsRespected:
    """
    The two mistakes that broke real runs: c.eps, which PostgreSQL rejects,
    and fm.market_cap, which it also rejects. No generated query may
    contain either.
    """

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_no_metric_column_on_companies(self, spec):
        for column in METRIC_COLUMNS:
            assert f"c.{column}" not in spec.expected_sql

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_no_company_column_on_metrics(self, spec):
        for column in COMPANY_COLUMNS:
            assert f"fm.{column}" not in spec.expected_sql

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_join_present_exactly_when_needed(self, spec):
        uses_metrics = "fm." in spec.expected_sql
        has_join = "JOIN financial_metrics" in spec.expected_sql
        assert uses_metrics == has_join

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_ticker_is_always_projected(self, spec):
        """Later stages match rows to companies by ticker."""
        assert "c.ticker" in spec.expected_sql

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_read_only(self, spec):
        lowered = spec.expected_sql.lower()
        assert lowered.startswith("select")
        for forbidden in ("insert", "update", "delete", "drop", "alter", ";"):
            assert forbidden not in lowered


class TestOrderingContracts:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_every_query_is_ordered(self, spec):
        assert "ORDER BY" in spec.expected_sql

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.question_id)
    def test_contract_matches_the_limit(self, spec):
        """
        A LIMIT means the sort selects the members, which is top_k. No
        LIMIT means the query orders a population it already has, which is
        ranking. Neither is ever "none" here — SQL owns the order in both
        sets.
        """
        has_limit = " LIMIT " in spec.expected_sql

        if has_limit:
            assert spec.sql_order_requirement == "top_k"
        else:
            assert spec.sql_order_requirement == "ranking"

    def test_descending_questions_exist(self):
        """
        A generator that hardcoded ASC for P/E would pass a set that only
        ever asked for the cheapest.
        """
        assert any("DESC" in s.expected_sql for s in VALUATION_SPECS)
        assert any("ASC" in s.expected_sql for s in GROWTH_SPECS)

    def test_growth_keeps_negative_values(self):
        """
        revenue_growth goes negative in the seed. The weakest-growth
        questions must not filter negatives out — that would answer a
        different question.
        """
        slowest = [s for s in GROWTH_SPECS if "weakest" in s.question]
        assert slowest

        for spec in slowest:
            assert "revenue_growth > 0" not in spec.expected_sql


class TestBuilder:
    def test_it_skips_the_join_when_only_company_columns_are_used(self):
        sql = build_sql(
            select=("market_cap",),
            order_by="market_cap",
            direction="DESC",
            limit=3,
            sector="Energy",
        )
        assert "JOIN" not in sql

    def test_it_joins_for_a_metric_filter_on_a_company_sort(self):
        sql = build_sql(
            select=("market_cap",),
            order_by="market_cap",
            direction="ASC",
            limit=5,
            sector="Technology",
            extra_where=("fm.eps > 0",),
        )
        assert "JOIN financial_metrics fm ON fm.company_id = c.id" in sql

    def test_it_does_not_repeat_a_null_guard(self):
        """`> 0` already implies NOT NULL; stating both is noise."""
        sql = build_sql(
            select=("pe_ratio",),
            order_by="pe_ratio",
            direction="ASC",
            limit=3,
            extra_where=("fm.pe_ratio > 0",),
        )
        assert sql.count("pe_ratio IS NOT NULL") == 0

    def test_it_guards_an_unconstrained_sort_key(self):
        """
        pe_ratio is a positive-only measure, so the guard is `> 0` rather
        than a null check — see TestRankingGuards for why.
        """
        sql = build_sql(
            select=("pe_ratio",),
            order_by="pe_ratio",
            direction="ASC",
            limit=3,
        )
        assert "fm.pe_ratio > 0" in sql

    def test_a_signed_sort_key_gets_a_null_guard(self):
        sql = build_sql(
            select=("eps",),
            order_by="eps",
            direction="DESC",
            limit=3,
        )
        assert "fm.eps IS NOT NULL" in sql

    def test_an_unknown_column_is_rejected(self):
        """
        Silently guessing a table for an unknown column is how fm.market_cap
        got written in the first place.
        """
        with pytest.raises(ValueError, match="Unknown column"):
            build_sql(
                select=("dividend_yield",),
                order_by="dividend_yield",
                direction="ASC",
                limit=3,
            )


class TestGeneratedFile:
    """
    Skipped when the generator has not been run — a fresh checkout has no
    database.
    """

    @pytest.fixture
    def payload(self):
        path = (
            Path(__file__).parent.parent
            / "backend/evaluation/datasets/generated_ground_truth.json"
        )

        if not path.exists():
            pytest.skip("run generate_ground_truth first")

        return json.loads(path.read_text())

    def test_every_spec_produced_ground_truth(self, payload):
        assert set(payload["questions"]) == {
            spec.question_id for spec in ALL_SPECS
        }

    def test_no_question_has_empty_rows(self, payload):
        """
        An empty expected_sql_result scores a spurious sql_accuracy of 1.0,
        so the generator must never emit one.
        """
        for qid, entry in payload["questions"].items():
            assert entry["expected_sql_result"], qid

    def test_rankings_match_the_rows(self, payload):
        for qid, entry in payload["questions"].items():
            tickers = [
                row["ticker"] for row in entry["expected_sql_result"]
            ]
            assert entry["expected_ranking"] == tickers, qid

    def test_non_binding_limits_are_flagged(self, payload):
        """
        Recorded rather than hidden: a LIMIT the filters never reach proves
        only the ordering, not the selection.
        """
        for entry in payload["questions"].values():
            assert isinstance(entry["limit_non_binding"], bool)


class TestLoader:
    def test_sets_are_exactly_thirty_each(self):
        """
        Thirty, not thirty-one. The hand-written valuation_002 asks the same
        question as the generated valuation_profitable_15 — "five" for 5 and
        a redundant market_cap > 0 apart — so adding it on top would measure
        one question twice and weight it double in the pass rate.
        """
        from backend.evaluation.datasets.question_sets import QUESTION_SETS

        assert len(QUESTION_SETS["valuation"]) == 30
        assert len(QUESTION_SETS["growth"]) == 30
        assert len(QUESTION_SETS["smoke"]) == 4

    def test_the_originals_are_not_duplicated_into_the_generated_sets(self):
        from backend.evaluation.datasets.question_sets import QUESTION_SETS

        ids = {q.question_id for q in QUESTION_SETS["all"]}
        assert "valuation_002" not in ids
        assert "growth_001" not in ids

    def test_the_originals_survive_in_smoke(self):
        from backend.evaluation.datasets.question_sets import QUESTION_SETS

        ids = {q.question_id for q in QUESTION_SETS["smoke"]}
        assert {"valuation_002", "growth_001"} <= ids

    def test_the_authored_questions_are_in_both(self):
        """
        sentiment_001 and mixed_001 are the only questions of their kind, so
        they belong to smoke and to all. The two SQL originals deliberately
        do not.
        """
        from backend.evaluation.datasets.question_sets import QUESTION_SETS

        every = {q.question_id for q in QUESTION_SETS["all"]}
        assert {"sentiment_001", "mixed_001"} <= every

    def test_no_duplicate_ids_in_all(self):
        from backend.evaluation.datasets.question_sets import QUESTION_SETS

        ids = [q.question_id for q in QUESTION_SETS["all"]]
        assert len(set(ids)) == len(ids)

    def test_the_endpoint_accepts_the_new_sets(self):
        import typing

        from backend.api.evaluation_routes import RunRequest

        allowed = typing.get_args(
            RunRequest.model_fields["question_set"].annotation
        )
        assert "smoke" in allowed
        assert "all" in allowed


class TestRankingGuards:
    """
    The guard on a sort key must match rule 3 of the SQL generator's prompt
    — "if zero or negative values would make the ranking meaningless,
    exclude them" — or a generator following its instructions produces a
    query that differs from the golden. 25 of 31 valuation questions scored
    sql_equivalence 0.0 on exactly that mismatch while returning perfect
    rows.
    """

    def test_positive_only_measures_are_guarded_with_a_comparison(self):
        from backend.evaluation.datasets.question_bank import (
            POSITIVE_ONLY_MEASURES,
        )

        assert POSITIVE_ONLY_MEASURES == {"market_cap", "pe_ratio"}

    def test_growth_and_eps_keep_their_negatives(self):
        """
        Both go negative meaningfully in the seed. A `> 0` guard on
        revenue_growth would silently delete the contraction questions'
        whole subject.
        """
        from backend.evaluation.datasets.question_bank import (
            POSITIVE_ONLY_MEASURES,
        )

        assert "revenue_growth" not in POSITIVE_ONLY_MEASURES
        assert "eps" not in POSITIVE_ONLY_MEASURES

    def test_market_cap_rankings_exclude_nonpositive(self):
        sql = build_sql(
            select=("market_cap",),
            order_by="market_cap",
            direction="DESC",
            limit=3,
            sector="Energy",
        )
        assert "c.market_cap > 0" in sql
        assert "IS NOT NULL" not in sql

    def test_growth_rankings_use_a_null_guard_only(self):
        sql = build_sql(
            select=("revenue_growth",),
            order_by="revenue_growth",
            direction="ASC",
            limit=3,
            sector="Energy",
        )
        assert "fm.revenue_growth IS NOT NULL" in sql
        assert "revenue_growth > 0" not in sql


class TestJudgeAcceptsRedundantPredicates:
    def _instruction(self):
        from backend.evaluation.evaluators.sql_evaluator import (
            _STRICT_REGARDLESS,
        )

        return " ".join(_STRICT_REGARDLESS.split())

    def test_it_states_redundant_guards_are_not_a_filter_difference(self):
        text = self._instruction()
        assert "REDUNDANT PREDICATES ARE NOT A DIFFERENCE IN FILTERS" in text
        assert "a comparison against NULL is never true" in text

    def test_it_closes_the_loophole(self):
        """
        Leniency has to stay narrow: `> 0` and `>= 0` differ, and so do
        `> 0` and `IS NOT NULL` on a column holding negatives.
        """
        text = self._instruction()
        assert "`x > 0` and `x >= 0` differ" in text
        assert "provably interchangeable" in text
