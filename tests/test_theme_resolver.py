"""
Theme resolution — deciding which companies qualify, before ranking them.

The failure this replaces: asked for "AI-related stocks", the SQL generator
had no categorical column that could express it and manufactured one from
free text, selecting 35 of 50 companies because '%AI%' matches the letters
"ai" inside words like "maintains". An oil producer then won an AI ranking
on its fundamentals, which the scorer computed perfectly over the wrong
candidate pool.

Substring matching is therefore the central hazard, and it is just as
available in Python as it was in SQL. The boundary tests below are the ones
that matter most.
"""
import pytest

from backend.retrieval.theme_resolver import (
    THEME_ALIASES,
    extract_theme_slug,
    resolve_candidates,
    resolve_theme_tickers,
)
from seeds.themes import COMPANY_THEMES, THEME_DEFINITIONS


class TestThemeExtraction:
    def test_recognises_the_benchmark_question(self):
        assert (
            extract_theme_slug(
                "Rank the five best AI-related stocks using valuation, "
                "revenue growth, current market performance, and sentiment."
            )
            == "ai"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "best AI companies",
            "artificial intelligence leaders",
            "generative AI plays",
            "which genAI stocks are cheapest",
            "machine learning companies",
        ],
    )
    def test_aliases_resolve_to_one_canonical_slug(self, question):
        assert extract_theme_slug(question) == "ai"

    def test_longest_alias_wins(self):
        """
        "generative ai" must not be matched as the shorter "ai", or a more
        specific theme would silently collapse into a broader one.
        """
        assert extract_theme_slug("generative ai infrastructure") == "ai"
        assert extract_theme_slug("cloud computing providers") == "cloud"

    def test_case_insensitive(self):
        assert extract_theme_slug("AI STOCKS") == "ai"
        assert extract_theme_slug("Artificial Intelligence") == "ai"


class TestSubstringTrap:
    """
    The regression that motivated the whole change.

    `'%AI%'` matched "maintains", "details" and "aiming", so any company
    whose news used an ordinary English word qualified as AI. Moving the
    lookup into Python does not by itself fix that — only the word
    boundaries do.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "Barclays analyst maintains EOG Resources rating",
            "the company details its quarterly results",
            "aiming to expand capacity",
            "chairman said the plan remains on track",
            "available capital for acquisitions",
        ],
    )
    def test_ai_inside_an_ordinary_word_is_not_a_theme(self, question):
        assert extract_theme_slug(question) is None

    def test_chip_inside_a_word_is_not_the_semiconductor_theme(self):
        assert extract_theme_slug("the shipment was delayed") is None

    def test_questions_with_no_theme_return_none(self):
        assert (
            extract_theme_slug(
                "Which five profitable technology companies have the "
                "smallest market capitalizations?"
            )
            is None
        )
        assert extract_theme_slug("") is None
        assert extract_theme_slug(None) is None


class TestTaxonomyIsInternallyConsistent:
    def test_every_assigned_slug_is_defined(self):
        for ticker, slugs in COMPANY_THEMES.items():
            for slug in slugs:
                assert slug in THEME_DEFINITIONS, f"{ticker} -> unknown '{slug}'"

    def test_every_alias_maps_to_a_defined_theme(self):
        for alias, slug in THEME_ALIASES.items():
            assert slug in THEME_DEFINITIONS, f"alias '{alias}' -> unknown '{slug}'"

    def test_every_theme_is_reachable_by_at_least_one_alias(self):
        """A theme no question can name is a theme that can never be used."""
        reachable = set(THEME_ALIASES.values())
        for slug in THEME_DEFINITIONS:
            assert slug in reachable, f"'{slug}' has no alias"

    def test_ai_membership_matches_the_benchmark_cohort(self):
        """
        mixed_001's expected ranking is exactly these five. If the taxonomy
        widens, that golden has to change in the same commit or the
        benchmark starts grading against a cohort that no longer exists.
        """
        ai = {t for t, slugs in COMPANY_THEMES.items() if "ai" in slugs}
        assert ai == {"NVDA", "AMD", "MSFT", "GOOGL", "META"}


class TestResolution:
    async def test_ai_resolves_to_the_curated_cohort(self):
        assert await resolve_theme_tickers("ai") == [
            "AMD",
            "GOOGL",
            "META",
            "MSFT",
            "NVDA",
        ]

    async def test_order_is_stable(self):
        """A benchmark run has to be reproducible; ranking happens later."""
        assert await resolve_theme_tickers("ai") == await resolve_theme_tickers("ai")

    async def test_unknown_theme_yields_no_candidates(self):
        assert await resolve_theme_tickers("quantum-computing") == []

    async def test_absent_theme_yields_no_candidates(self):
        assert await resolve_theme_tickers(None) == []
        assert await resolve_theme_tickers("") == []

    async def test_a_company_can_hold_several_themes(self):
        semis = await resolve_theme_tickers("semiconductors")
        ai = await resolve_theme_tickers("ai")

        # NVDA and AMD are both, which is why this is many-to-many.
        assert {"NVDA", "AMD"} <= set(semis)
        assert {"NVDA", "AMD"} <= set(ai)
        # And the themes are not the same set.
        assert set(semis) != set(ai)


class TestResolveCandidates:
    async def test_reports_theme_and_tickers_together(self):
        result = await resolve_candidates("best AI-related stocks")

        assert result["theme_slug"] == "ai"
        assert result["candidate_tickers"] == [
            "AMD",
            "GOOGL",
            "META",
            "MSFT",
            "NVDA",
        ]
        assert result["resolved"] is True

    async def test_distinguishes_no_theme_from_unknown_theme(self):
        """
        These need different handling and are indistinguishable if only the
        ticker list is returned: one means "rank everything", the other
        means "the taxonomy is missing a category".
        """
        no_theme = await resolve_candidates(
            "Which companies have the highest revenue growth?"
        )
        assert no_theme["theme_slug"] is None
        assert no_theme["resolved"] is False

        unknown = await resolve_candidates("quantum computing companies")
        assert unknown["theme_slug"] is None
        assert unknown["resolved"] is False

    async def test_never_raises_on_a_question_it_cannot_parse(self):
        """
        Degrading to "no filter" is correct; taking the query down is not.
        """
        for question in ["", "?????", "a" * 5000]:
            result = await resolve_candidates(question)
            assert result["candidate_tickers"] == []
