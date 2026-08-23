"""
Resolve a theme to the companies that belong to it.

This answers "who qualifies?", which is a different question from "how good
are they?" and has to be settled first. Tangling the two is what let an
energy company win an AI ranking: SQL was asked to both discover the AI
cohort and rank it, could not express the first, invented a text filter, and
the scorer then faithfully ranked the wrong candidate pool.

Deliberately not an LLM call. The eligibility decision was made once, by a
person, in seeds/themes.py; this only looks it up. Every failure this module
exists to prevent came from a model deciding membership at query time.

An unknown theme returns no candidates rather than guessing. Failing visibly
beats confidently ranking Goldman Sachs as an AI stock — the caller can then
choose to proceed unfiltered, which is an explicit decision rather than an
accident.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import text

from backend.services.postgres_service import engine


logger = logging.getLogger(__name__)


# Wording a question might use for a theme, mapped to its canonical slug.
# Kept here rather than in the database because these are properties of
# language, not of the data, and a miss is harmless — it falls through to
# "unknown theme" and the caller proceeds unfiltered.
THEME_ALIASES: dict[str, str] = {
    "ai": "ai",
    "a.i.": "ai",
    "artificial intelligence": "ai",
    "genai": "ai",
    "generative ai": "ai",
    "machine learning": "ai",

    "semiconductor": "semiconductors",
    "semiconductors": "semiconductors",
    "chip": "semiconductors",
    "chips": "semiconductors",
    "chipmaker": "semiconductors",
    "chipmakers": "semiconductors",

    "cloud": "cloud",
    "cloud computing": "cloud",
    "hyperscaler": "cloud",
    "hyperscalers": "cloud",
}


def extract_theme_slug(question: str) -> str | None:
    """
    The canonical theme a question is asking about, if any.

    Longest alias first, so "generative ai" is not matched as the shorter
    "ai" and "cloud computing" is not matched as "cloud". Word boundaries
    matter as much: without them "ai" matches inside "maintains", which is
    precisely the bug that motivated this module — only relocated from SQL
    into Python.
    """
    if not question:
        return None

    haystack = question.lower()

    for alias in sorted(THEME_ALIASES, key=len, reverse=True):
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"

        if re.search(pattern, haystack):
            return THEME_ALIASES[alias]

    return None


async def resolve_theme_companies(
    slug: str | None,
) -> list[dict]:
    """
    Companies belonging to a theme, alphabetically by ticker.

    Both the id and the ticker are returned because the branches key on
    different things: vector search filters `documents.company_id`, while
    SQL and the market API work in tickers. Resolving once and carrying
    both is what keeps the three branches on one candidate set.

    Empty for an unknown or absent theme. The order is stable so a benchmark
    run is reproducible; ranking happens later and does not depend on it.
    """
    if not slug:
        return []

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT c.id, c.ticker
                    FROM companies c
                    JOIN company_themes ct ON ct.company_id = c.id
                    JOIN themes t ON t.id = ct.theme_id
                    WHERE t.slug = :slug
                    ORDER BY c.ticker
                    """
                ),
                {"slug": slug},
            )
            companies = [
                {"company_id": row[0], "ticker": row[1]}
                for row in result.fetchall()
            ]

    except Exception as exc:
        # A resolver failure must degrade to "no theme filter", never take
        # the query down: an unfiltered answer is worse than a correct one
        # and far better than none.
        logger.error(
            "[THEME_RESOLVER] lookup failed slug=%s: %s",
            slug,
            exc,
        )
        return []

    if not companies:
        logger.warning(
            "[THEME_RESOLVER] no companies for slug=%s — the question asks "
            "for a category the taxonomy does not define, so no candidate "
            "filter will be applied",
            slug,
        )

    return companies


async def resolve_theme_tickers(slug: str | None) -> list[str]:
    """Just the tickers, for callers that do not need the ids."""
    return [
        company["ticker"]
        for company in await resolve_theme_companies(slug)
    ]


# Words that end a company's legal name without identifying it. Stripped so
# "Merck & Company, Inc." can be recognised from "Merck".
_LEGAL_SUFFIXES = frozenset({
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "group", "holdings", "plc", "ltd", "nv", "sa", "ag", "&",
})


def _core_name(name: str) -> str:
    """The identifying part of a registered name."""
    text = re.sub(r"\(the\)", " ", name, flags=re.IGNORECASE)
    text = re.sub(r"[.,]", " ", text)

    words = [word for word in text.split() if word]

    while words and words[0].lower() == "the":
        words.pop(0)

    while words and words[-1].lower() in _LEGAL_SUFFIXES:
        words.pop()

    return " ".join(words)


def _squash(text: str) -> str:
    """Letters and digits only, lowercased.

    "JPMorgan" and "JP Morgan", "Exxon Mobil" and "ExxonMobil" are the same
    company written two ways, and a question uses whichever it likes.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _name_aliases(name: str) -> set[str]:
    """Every contiguous run of words in the core name.

    "Walt Disney" yields "Walt", "Disney" and "Walt Disney", because a
    question says "Disney" and the register says "Walt Disney Company
    (The)". Ambiguous aliases are discarded later, by the caller, once every
    company has been expanded — "Morgan" belongs to both Morgan Stanley and
    JP Morgan Chase and identifies neither.
    """
    words = _core_name(name).split()

    return {
        " ".join(words[start:end])
        for start in range(len(words))
        for end in range(start + 1, len(words) + 1)
    }


async def _all_companies() -> list[dict]:
    """Every company, for name matching. Fifty rows; not worth caching."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id, ticker, name FROM companies ORDER BY ticker")
            )

            return [
                {"company_id": row[0], "ticker": row[1], "name": row[2]}
                for row in result.fetchall()
            ]

    except Exception as exc:
        logger.error("[THEME_RESOLVER] company lookup failed: %s", exc)
        return []


async def resolve_named_companies(question: str) -> list[dict]:
    """
    Companies the question names outright, by name or by ticker.

    The theme resolver above answers "which companies are in this
    category?". This answers the commoner case: the question already said
    who it means. Without it a question naming its cohort resolved to
    nothing, the pipeline ran unfiltered, and the ranking fell back to
    whichever companies dominate the corpus — across the twenty-five
    sentiment questions of run c3f5c44b, GE appeared in 22 answers, GS in
    19 and MS in 17, whatever was asked. Ten matched nothing at all.

    Still a lookup, not a judgement. The names come from the question and
    are matched against the companies table, so the model never decides
    membership — the property the theme resolver exists to protect.
    """
    if not question:
        return []

    companies = await _all_companies()

    # An alias claimed by two companies identifies neither.
    owners: dict[str, set[str]] = {}

    for company in companies:
        for alias in _name_aliases(company["name"]):
            owners.setdefault(alias.lower(), set()).add(company["ticker"])

    # Every run of adjacent words in the question, squashed. Comparing
    # against these as whole values rather than searching for a substring is
    # what keeps "America" out of "American Express" and "United" out of
    # "UnitedHealth", while still letting the alias "JP Morgan" match the
    # single token "JPMorgan".
    tokens = re.findall(r"[A-Za-z0-9]+", question)
    question_runs = {
        _squash("".join(tokens[start:end]))
        for start in range(len(tokens))
        for end in range(start + 1, min(start + 5, len(tokens)) + 1)
    }

    found: dict[str, dict] = {}

    for company in companies:
        ticker = company["ticker"]

        # Tickers match case-sensitively. Lowercasing would make "MA" match
        # inside "may" and "C" match any stray capital.
        if re.search(
            r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])",
            question,
        ):
            found[ticker] = company
            continue

        for alias in _name_aliases(company["name"]):
            if len(owners.get(alias.lower(), set())) != 1:
                continue

            squashed_alias = _squash(alias)

            if len(squashed_alias) >= 4 and squashed_alias in question_runs:
                found[ticker] = company
                break

    return [found[ticker] for ticker in sorted(found)]

async def resolve_sector_companies(question: str) -> list[dict]:
    """
    Companies in a sector the question names.

    Five of the mixed questions ask for "the energy sector companies" or
    "the communication services companies" rather than listing members.
    Sector is a column on companies, so this is the same kind of lookup as a
    theme: decided by the data, not by a model at query time.
    """
    if not question:
        return []

    try:
        async with engine.connect() as conn:
            sectors = [
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT sector FROM companies "
                            "WHERE sector IS NOT NULL"
                        )
                    )
                ).fetchall()
            ]

            # Longest first, so "Consumer Cyclical" is not read as the
            # "Consumer Defensive"-sharing word "Consumer".
            for name in sorted(sectors, key=len, reverse=True):
                pattern = (
                    r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?![a-z0-9])"
                )

                if not re.search(pattern, question.lower()):
                    continue

                result = await conn.execute(
                    text(
                        "SELECT id, ticker FROM companies "
                        "WHERE sector = :sector ORDER BY ticker"
                    ),
                    {"sector": name},
                )

                return [
                    {"company_id": row[0], "ticker": row[1]}
                    for row in result.fetchall()
                ]

    except Exception as exc:
        logger.error("[THEME_RESOLVER] sector lookup failed: %s", exc)

    return []

# Intents whose answer is a ranking over a cohort, and which therefore need
# one. VALUATION and GROWTH express their own population in SQL, and are
# graded on the query they write — narrowing them from outside would rewrite
# the filter sql_equivalence compares against.
_COHORT_INTENTS = frozenset({"SENTIMENT", "MIXED"})


async def resolve_candidates(
    question: str,
    intent: str | None = None,
) -> dict:
    """
    Candidate companies for a question, with the reasoning attached.

    Returns the slug that was recognised and the tickers it resolved to, so
    a caller — and anyone reading a trace — can tell "no theme was asked
    for" apart from "a theme was asked for and is not in the taxonomy".
    Those need different handling and look identical if only the ticker list
    is returned.
    """
    slug = extract_theme_slug(question)
    companies = await resolve_theme_companies(slug)

    # A curated theme wins. Its membership was decided once, by a person, in
    # seeds/themes.py, and that beats whatever a question happens to mention
    # in passing.
    if not companies:
        companies = await resolve_named_companies(question)

    # Named companies before sector: a question that lists its cohort means
    # that cohort, even if a sector word appears elsewhere in the sentence.
    if not companies and (intent or "").upper() in _COHORT_INTENTS:
        companies = await resolve_sector_companies(question)

    tickers = [company["ticker"] for company in companies]
    company_ids = [company["company_id"] for company in companies]

    logger.info(
        "[THEME_RESOLVER] question_theme=%s tickers=%s",
        slug or "none",
        ",".join(tickers) or "none",
    )

    return {
        "theme_slug": slug,
        "candidate_tickers": tickers,
        "candidate_company_ids": company_ids,
        "resolved": bool(tickers),
    }
