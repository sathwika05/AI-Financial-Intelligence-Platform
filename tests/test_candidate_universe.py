"""
One candidate universe, shared by every retrieval branch.

Before this, each branch discovered its own set. For "the five best
AI-related stocks" SQL manufactured a filter from document text and
returned EOG, JPM and GS; the market branch resolved
NVDA/MSFT/GOOGL/AMZN/META from the planner's rewritten wording; and vector
search retrieved whatever was nearest in embedding space, which turned out
to be articles about Intel, Nike and a pharmaceutical upgrade. The scorer
then ranked the union, so an energy company won a query about AI.

These tests pin the plumbing that keeps the three branches on one set, and
the fallback behaviour when no theme is recognised — which must stay
unfiltered, because most questions name no category at all.
"""
import inspect

import pytest

from backend.retrieval import hybrid_retrieval
from backend.retrieval.theme_resolver import (
    resolve_candidates,
    resolve_sector_companies,
)
from backend.scoring.ranker import rerank
from backend.state.financial_state import FinancialState
from backend.state.state_factory import build_initial_financial_state


class TestStateCarriesTheCandidateSet:
    def test_state_declares_the_fields(self):
        annotations = FinancialState.__annotations__

        assert "theme_slug" in annotations
        assert "candidate_tickers" in annotations
        assert "candidate_company_ids" in annotations

    def test_initial_state_starts_empty_not_missing(self):
        """
        LangGraph drops keys absent from the schema, and `.get` on a missing
        key would silently look identical to "no theme" — so they have to be
        initialised.
        """
        state = build_initial_financial_state("any question")

        assert state["theme_slug"] is None
        assert state["candidate_tickers"] == []
        assert state["candidate_company_ids"] == []


class TestBranchesAcceptCandidates:
    """Each branch must be able to receive the set, or it cannot honour it."""

    def test_hybrid_retrieve_accepts_both_forms(self):
        params = inspect.signature(
            hybrid_retrieval.hybrid_retrieve_async
        ).parameters

        assert "candidate_tickers" in params
        assert "candidate_company_ids" in params

    def test_vector_retrieval_accepts_company_ids(self):
        """Vector filters on documents.company_id, not on tickers."""
        for fn in (
            hybrid_retrieval.run_vector_retrieval,
            hybrid_retrieval.run_vector_retrieval_async,
        ):
            params = inspect.signature(fn).parameters
            assert "candidate_company_ids" in params, fn.__name__
            assert params["candidate_company_ids"].default is None

    def test_ranker_accepts_candidates(self):
        params = inspect.signature(rerank).parameters

        assert "candidate_tickers" in params
        assert params["candidate_tickers"].default is None


@pytest.fixture(scope="module")
def source():
    """
    The body of hybrid_retrieve_async decides what each branch is asked.
    Asserted on the source because calling it would run three live
    retrievals against external APIs.
    """
    return inspect.getsource(hybrid_retrieval.hybrid_retrieve_async)


@pytest.fixture(scope="module")
def ranker_source():
    return inspect.getsource(rerank)


class TestDistribution:
    def test_sql_is_told_to_restrict_to_the_candidates(self, source):
        assert "Restrict the results to exactly these companies" in source
        assert "c.ticker IN (...)" in source

    def test_market_query_is_replaced_by_the_candidates(self, source):
        """
        The market branch resolves tickers from free text with an LLM call,
        which is a third independent guess at the candidate set — it once
        answered a question about AMD with AMZN.
        """
        assert 'market_q = ", ".join(candidate_tickers)' in source

    def test_vector_receives_company_ids(self, source):
        assert "candidate_company_ids=candidate_company_ids" in source

    def test_nothing_is_constrained_when_no_theme_resolves(self, source):
        """
        The whole block is guarded, so a question naming no category
        behaves exactly as before.
        """
        assert "if candidate_tickers:" in source


class TestRankerEligibility:
    def test_resolved_candidates_are_not_re_derived_from_retrieval(
        self, ranker_source
    ):
        assert "from resolved theme" in ranker_source

    def test_union_of_branches_is_the_fallback_only(self, ranker_source):
        """
        The old path stays for questions with no theme, but must no longer
        be reachable when eligibility was resolved — otherwise a degraded
        branch drops the pipeline back to get_companies_from_db(None),
        which returns the top 20 by revenue growth regardless of theme.
        """
        assert "dict.fromkeys(market_tickers + sql_tickers)" in ranker_source
        assert "else:" in ranker_source


class TestEndToEndResolution:
    async def test_the_benchmark_question_resolves_to_its_cohort(self):
        result = await resolve_candidates(
            "Rank the five best AI-related stocks using valuation, revenue "
            "growth, current market performance, and sentiment from recent "
            "company documents."
        )

        assert result["candidate_tickers"] == [
            "AMD",
            "GOOGL",
            "META",
            "MSFT",
            "NVDA",
        ]
        # Vector needs ids, SQL and market need tickers — same companies.
        assert len(result["candidate_company_ids"]) == 5
        assert all(
            isinstance(i, int) for i in result["candidate_company_ids"]
        )

    async def test_excluded_companies_are_genuinely_absent(self):
        """
        EOG, JPM and GS are the companies the old text filter admitted.
        """
        result = await resolve_candidates("best AI-related stocks")

        for ticker in ("EOG", "JPM", "GS", "PYPL", "BAC", "COP"):
            assert ticker not in result["candidate_tickers"]

    async def test_a_question_with_no_theme_constrains_nothing(self):
        result = await resolve_candidates(
            "Which five profitable technology companies have the smallest "
            "market capitalizations?"
        )

        assert result["candidate_tickers"] == []
        assert result["candidate_company_ids"] == []


class TestSectorIsTheLastResortBeforeTheWholeCorpus:
    """
    "Which healthcare companies show the strongest revenue growth and margin
    expansion?" came back NVDA, EOG, CVX and AMD — semiconductors and oil,
    in descending revenue-growth order. That ordering is the signature of
    get_companies_from_db(None), which returns the top 20 by revenue growth
    regardless of what was asked.

    The sector lookup that would have answered it correctly already exists.
    resolve_candidates only reaches it for SENTIMENT and MIXED, because
    narrowing a VALUATION or GROWTH question from outside would rewrite the
    filter sql_equivalence grades the generated query against. That
    reasoning holds while SQL actually expresses a population — it did not
    here, and the alternative to consulting sector is ranking every company
    in the corpus.

    So the fallback stays in the ranker, where "SQL produced nothing" is
    known, rather than in resolve_candidates, where it is not.
    """

    def test_the_ranker_consults_sector_before_the_whole_corpus(
        self, ranker_source
    ):
        assert "resolve_sector_companies" in ranker_source

    def test_sector_is_tried_only_after_market_and_sql_come_back_empty(
        self, ranker_source
    ):
        """
        Guarded, so a question whose branches did resolve is untouched and
        a question naming no category at all still ranks unfiltered.
        """
        union = ranker_source.index(
            "dict.fromkeys(market_tickers + sql_tickers)"
        )
        sector = ranker_source.index("resolve_sector_companies")

        assert union < sector, (
            "sector must be consulted after the union, not instead of it"
        )
        assert "if not resolved_candidates:" in ranker_source


class TestSectorLookupAnswersTheQuestionThatFailed:
    async def test_a_healthcare_question_resolves_to_healthcare(self):
        companies = await resolve_sector_companies(
            "Which healthcare companies show the strongest revenue growth "
            "and margin expansion?"
        )

        assert companies, "healthcare is a sector in the corpus"

        tickers = {company["ticker"] for company in companies}

        # The four the fallback actually returned. None is a healthcare
        # company, and every one of them outranks healthcare on revenue
        # growth — which is exactly why the unfiltered path chose them.
        for wrong in ("NVDA", "EOG", "CVX", "AMD"):
            assert wrong not in tickers
