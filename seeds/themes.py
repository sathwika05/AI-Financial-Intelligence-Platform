"""
The curated theme taxonomy, and the seeder that applies it.

This file is the source of truth for which companies belong to which
themes. It is hand-maintained on purpose: a theme is an editorial judgement
about what a company *is*, not something to be re-derived from whatever news
happened to be published this week. Deriving it per query is what produced
`documents.content ILIKE '%AI%'` and an oil producer ranked as an AI stock.

Keyed by ticker, not company_id, because seed_data truncates `companies`
with RESTART IDENTITY on every run — ids are not stable across reseeds and
these assignments must be.

    python -m seeds.themes            # apply the taxonomy
    python -m seeds.themes --report   # show what is currently assigned
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, text

from backend.models.db_models import Company, CompanyTheme, Theme
from backend.services.postgres_service import AsyncSessionLocal


# slug -> display name. The slug is what code and SQL match on, so wording
# differences in a question never reach the database.
THEME_DEFINITIONS: dict[str, str] = {
    "ai": "AI",
    "semiconductors": "Semiconductors",
    "cloud": "Cloud Computing",
}


# ticker -> theme slugs.
#
# The `ai` membership is deliberately the five companies mixed_001's golden
# answer already names. Widening it — AVGO, PLTR, ORCL and TSLA all have a
# credible claim — would change what a correct answer looks like, so the
# benchmark's expected ranking has to be regenerated in the same change.
# Keeping the two in step is the whole point of curating this by hand.
COMPANY_THEMES: dict[str, list[str]] = {
    "NVDA": ["ai", "semiconductors"],
    "AMD": ["ai", "semiconductors"],
    "MSFT": ["ai", "cloud"],
    "GOOGL": ["ai", "cloud"],
    "META": ["ai"],
    "INTC": ["semiconductors"],
    "AVGO": ["semiconductors"],
    "AMZN": ["cloud"],
    "ORCL": ["cloud"],
    "CRM": ["cloud"],
}


async def seed_themes(session) -> dict[str, int]:
    """
    Apply the taxonomy to an existing session, without committing.

    Idempotent: themes are matched on slug and memberships on the
    (company_id, theme_id) pair, so running it twice changes nothing. That
    matters because it runs at the end of every seed and can also be run on
    its own to re-apply the taxonomy after a reseed.

    Tickers with no matching company are skipped and counted rather than
    raising — companies.csv and this file are edited independently, and a
    stale entry here should not abort a seed.
    """
    theme_ids: dict[str, int] = {}

    for slug, name in THEME_DEFINITIONS.items():
        existing = await session.execute(
            select(Theme).where(Theme.slug == slug)
        )
        theme = existing.scalar_one_or_none()

        if theme is None:
            theme = Theme(name=name, slug=slug)
            session.add(theme)
            await session.flush()

        theme_ids[slug] = theme.id

    linked = 0
    skipped_tickers: list[str] = []

    for ticker, slugs in COMPANY_THEMES.items():
        found = await session.execute(
            select(Company.id).where(Company.ticker == ticker)
        )
        company_id = found.scalar_one_or_none()

        if company_id is None:
            skipped_tickers.append(ticker)
            continue

        for slug in slugs:
            theme_id = theme_ids[slug]

            already = await session.execute(
                select(CompanyTheme.id)
                .where(CompanyTheme.company_id == company_id)
                .where(CompanyTheme.theme_id == theme_id)
            )

            if already.scalar_one_or_none() is not None:
                continue

            session.add(
                CompanyTheme(
                    company_id=company_id,
                    theme_id=theme_id,
                )
            )
            linked += 1

    await session.flush()

    if skipped_tickers:
        print(
            "  [SEED_THEMES] no company row for: "
            + ", ".join(sorted(skipped_tickers))
        )

    return {
        "themes": len(theme_ids),
        "memberships_created": linked,
        "tickers_skipped": len(skipped_tickers),
    }


async def apply() -> dict[str, int]:
    """Apply the taxonomy in its own transaction."""
    async with AsyncSessionLocal() as session:
        counts = await seed_themes(session)
        await session.commit()
        return counts


async def report() -> list[tuple[str, str]]:
    """Every (slug, ticker) currently assigned, for eyeballing."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT t.slug, c.ticker
                FROM company_themes ct
                JOIN themes t ON t.id = ct.theme_id
                JOIN companies c ON c.id = ct.company_id
                ORDER BY t.slug, c.ticker
                """
            )
        )
        return [(row[0], row[1]) for row in result.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply the curated theme taxonomy.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="show current assignments instead of applying",
    )

    args = parser.parse_args()

    if args.report:
        rows = asyncio.run(report())

        if not rows:
            print("No theme memberships assigned.")
            return

        current = None
        for slug, ticker in rows:
            if slug != current:
                print(f"\n{slug}:")
                current = slug
            print(f"  {ticker}")
        return

    counts = asyncio.run(apply())

    for key, value in counts.items():
        print(f"  {key:<22} {value}")


if __name__ == "__main__":
    main()
