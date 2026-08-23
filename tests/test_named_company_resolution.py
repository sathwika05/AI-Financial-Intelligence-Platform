"""
A question that names its companies must resolve to those companies.

The theme resolver knows three themes. Every other question resolved to
nothing, the pipeline proceeded unfiltered, and ranking fell back to
whichever companies dominate the corpus: across the 25 sentiment questions
of run c3f5c44b, GE appeared in 22 answers, GS in 19 and MS in 17,
regardless of what was asked. sentiment_006 asks about Merck, Amgen and
Pfizer and was answered with GE, GS, MS, BAC, NVDA. Ten of the 25 matched
nothing at all.

Membership stays a lookup, never a model decision — the names come from
the question and are matched against the companies table.
"""
import pytest

from backend.retrieval.theme_resolver import resolve_candidates


@pytest.mark.asyncio
class TestNamedCompaniesResolve:
    async def test_full_company_names_resolve(self):
        result = await resolve_candidates(
            "Rank Merck, Amgen and Pfizer by the sentiment of their recent "
            "coverage."
        )

        assert set(result["candidate_tickers"]) == {"MRK", "AMGN", "PFE"}
        assert result["resolved"] is True

    async def test_bare_tickers_resolve(self):
        result = await resolve_candidates(
            "Compare AXP, MA and PYPL on recent coverage."
        )

        assert set(result["candidate_tickers"]) == {"AXP", "MA", "PYPL"}

    async def test_company_ids_come_back_alongside_the_tickers(self):
        """
        Vector search filters documents.company_id, so a ticker-only answer
        cannot restrict retrieval.
        """
        result = await resolve_candidates("Rank Abbott, Thermo Fisher and Danaher.")

        assert len(result["candidate_company_ids"]) == 3
        assert all(isinstance(i, int) for i in result["candidate_company_ids"])

    async def test_a_theme_still_wins_over_name_matching(self):
        """
        sentiment_002 works today because "semiconductor" is a theme. The
        curated cohort must keep taking precedence over incidental mentions.
        """
        result = await resolve_candidates(
            "Which semiconductor companies have the most positive sentiment?"
        )

        assert result["theme_slug"] == "semiconductors"
        assert set(result["candidate_tickers"]) == {"NVDA", "AMD", "INTC"}

    async def test_a_question_naming_nobody_still_resolves_to_nothing(self):
        """
        Failing visibly beats guessing. No theme and no company named means
        no candidate filter, exactly as before.
        """
        result = await resolve_candidates("What happened in the market today?")

        assert result["candidate_tickers"] == []
        assert result["resolved"] is False

    async def test_a_company_named_inside_an_ordinary_word_is_not_a_match(self):
        """
        The same word-boundary discipline the theme aliases already keep:
        "V" must not match every capital V, and "MA" must not match inside
        "MAY".
        """
        result = await resolve_candidates("What may happen to the market?")

        assert "MA" not in result["candidate_tickers"]
        assert "V" not in result["candidate_tickers"]


@pytest.mark.asyncio
class TestAliasesDoNotBleedIntoLongerWords:
    """
    Matching ignores spacing so that "JPMorgan" finds "JP Morgan Chase".
    Done by substring it also finds companies nobody named: "America" sits
    inside "American Express", and "United" inside "UnitedHealth".
    """

    async def test_bank_of_america_is_not_found_in_american_express(self):
        result = await resolve_candidates(
            "Rank American Express, Mastercard and PayPal by sentiment."
        )

        assert set(result["candidate_tickers"]) == {"AXP", "MA", "PYPL"}

    async def test_united_parcel_is_not_found_in_unitedhealth(self):
        result = await resolve_candidates(
            "Which of Johnson & Johnson, Pfizer and UnitedHealth has the "
            "most positive recent news coverage?"
        )

        assert set(result["candidate_tickers"]) == {"JNJ", "PFE", "UNH"}

    async def test_spacing_variants_still_resolve(self):
        result = await resolve_candidates(
            "Compare JPMorgan and Exxon Mobil on recent coverage."
        )

        assert set(result["candidate_tickers"]) == {"JPM", "XOM"}


@pytest.mark.asyncio
class TestSectorCohorts:
    """
    Five mixed questions name a sector rather than its members. Every
    rankable sector's membership is a column on companies, so this is the
    same kind of lookup as a theme.
    """

    async def test_a_sector_resolves_to_its_members(self):
        result = await resolve_candidates(
            "Rank the energy sector companies using valuation, revenue "
            "growth, current market performance and sentiment.",
            intent="MIXED",
        )

        assert set(result["candidate_tickers"]) == {
            "XOM", "CVX", "COP", "EOG", "SLB",
        }

    async def test_a_two_word_sector_resolves(self):
        result = await resolve_candidates(
            "Rank the communication services companies on valuation.",
            intent="MIXED",
        )

        assert set(result["candidate_tickers"]) == {
            "DIS", "GOOGL", "META", "NFLX",
        }


@pytest.mark.asyncio
class TestSectorResolutionIsScopedToRankingIntents:
    """
    The candidate set reaches all three branches from one place in the
    planner, so widening it widens what SQL is handed too. A valuation
    question expresses its own filter — "profitable technology companies
    with the smallest market caps" is a WHERE clause, and sql_equivalence
    grades the query the generator writes. Constraining that cohort from
    outside would rewrite 60 generated goldens' worth of SQL for no gain.
    """

    async def test_a_valuation_question_is_not_narrowed_to_its_sector(self):
        result = await resolve_candidates(
            "Which five profitable technology companies have the smallest "
            "market capitalizations?",
            intent="VALUATION",
        )

        assert result["candidate_tickers"] == []

    async def test_the_same_words_do_narrow_a_mixed_question(self):
        result = await resolve_candidates(
            "Rank the technology sector companies on valuation, revenue "
            "growth, current market performance and sentiment.",
            intent="MIXED",
        )

        assert len(result["candidate_tickers"]) == 7

    async def test_named_companies_resolve_whatever_the_intent(self):
        """
        Only the sector fallback is scoped. A question that says who it
        means says so regardless of how it will be answered.
        """
        result = await resolve_candidates(
            "Rank Merck, Amgen and Pfizer.",
            intent="VALUATION",
        )

        assert set(result["candidate_tickers"]) == {"MRK", "AMGN", "PFE"}
