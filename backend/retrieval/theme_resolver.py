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


async def resolve_theme_tickers(slug: str | None) -> list[str]:
    """
    Tickers belonging to a theme, alphabetically.

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
                    SELECT c.ticker
                    FROM companies c
                    JOIN company_themes ct ON ct.company_id = c.id
                    JOIN themes t ON t.id = ct.theme_id
                    WHERE t.slug = :slug
                    ORDER BY c.ticker
                    """
                ),
                {"slug": slug},
            )
            tickers = [row[0] for row in result.fetchall()]

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

    if not tickers:
        logger.warning(
            "[THEME_RESOLVER] no companies for slug=%s — the question asks "
            "for a category the taxonomy does not define, so no candidate "
            "filter will be applied",
            slug,
        )

    return tickers


async def resolve_candidates(question: str) -> dict:
    """
    Candidate companies for a question, with the reasoning attached.

    Returns the slug that was recognised and the tickers it resolved to, so
    a caller — and anyone reading a trace — can tell "no theme was asked
    for" apart from "a theme was asked for and is not in the taxonomy".
    Those need different handling and look identical if only the ticker list
    is returned.
    """
    slug = extract_theme_slug(question)
    tickers = await resolve_theme_tickers(slug)

    logger.info(
        "[THEME_RESOLVER] question_theme=%s tickers=%s",
        slug or "none",
        ",".join(tickers) or "none",
    )

    return {
        "theme_slug": slug,
        "candidate_tickers": tickers,
        "resolved": bool(tickers),
    }
