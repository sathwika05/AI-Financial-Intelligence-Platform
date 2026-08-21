"""
Print the seeded documents, so reference contexts can be copied exactly.

reference_contexts must match document_chunks character for character.
RAGAS matches retrieved contexts against them as text, so a paraphrase, a
trimmed sentence or a straightened quotation mark scores 0.0 — and it scores
0.0 silently, looking exactly like a retrieval failure. That is not
hypothetical: two questions cited an AMD bond story and a Microsoft data
centre story that a reseed had removed, and context precision, recall and
entity recall all read 0.0 while retrieval was working correctly.

So copy from this tool's output rather than retyping.

    uv run python -m backend.evaluation.datasets.read_corpus INTC
    uv run python -m backend.evaluation.datasets.read_corpus --sector Energy
    uv run python -m backend.evaluation.datasets.read_corpus --coverage
    uv run python -m backend.evaluation.datasets.read_corpus --themes

--python prints a chunk as a ready-to-paste quoted string, wrapped to the
file's line width.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import textwrap


async def _connect():
    import asyncpg

    url = os.environ.get("DATABASE_URL", "")

    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]

    return await asyncpg.connect(
        url or "postgresql://finuser:finpass@localhost:5433/findb"
    )


def _as_python(text: str) -> str:
    """Render a chunk as the quoted, wrapped string a spec file wants."""
    lines = textwrap.wrap(text, width=62)

    return "\n".join(
        f'    "{line} "' if index < len(lines) - 1 else f'    "{line}",'
        for index, line in enumerate(lines)
    )


async def show(
    *,
    tickers: list[str],
    sector: str | None,
    as_python: bool,
) -> int:
    conn = await _connect()

    where = "TRUE"
    args: list = []

    if tickers:
        where = "c.ticker = ANY($1)"
        args.append([t.upper() for t in tickers])
    elif sector:
        where = "c.sector = $1"
        args.append(sector)

    rows = await conn.fetch(
        f"""
        SELECT c.ticker,
               c.name,
               d.title,
               d.source,
               d.relevance_score,
               dc.id AS chunk_id,
               dc.content
        FROM companies c
        JOIN documents d ON d.company_id = c.id
        JOIN document_chunks dc ON dc.document_id = d.id
        WHERE {where}
        ORDER BY c.ticker, d.id, dc.id
        """,
        *args,
    )

    await conn.close()

    if not rows:
        print("No documents. Check the ticker or sector spelling.")
        return 1

    current = None

    for row in rows:
        if row["ticker"] != current:
            current = row["ticker"]
            print(f"\n{'=' * 70}\n{current} — {row['name']}\n{'=' * 70}")

        relevance = (
            f"{row['relevance_score']:.3f}"
            if row["relevance_score"] is not None
            else "unscored (Finnhub)"
        )

        print(f"\n[chunk {row['chunk_id']}] relevance {relevance}")
        print(f"  title: {row['title']}")

        if as_python:
            print(_as_python(row["content"]))
        else:
            print(textwrap.indent(textwrap.fill(row["content"], 68), "  "))

    print(f"\n{len(rows)} chunks.")
    return 0


async def coverage() -> int:
    """Which companies have enough documents to build a question around."""
    conn = await _connect()

    rows = await conn.fetch(
        """
        SELECT c.ticker,
               c.sector,
               count(DISTINCT d.id) AS docs,
               count(dc.id) AS chunks
        FROM companies c
        LEFT JOIN documents d ON d.company_id = c.id
        LEFT JOIN document_chunks dc ON dc.document_id = d.id
        GROUP BY c.ticker, c.sector
        ORDER BY count(dc.id) DESC, c.ticker
        """
    )

    await conn.close()

    print(f"{'ticker':8} {'sector':24} {'docs':>5} {'chunks':>7}")
    print("-" * 48)

    for row in rows:
        print(
            f"{row['ticker']:8} {(row['sector'] or '-'):24} "
            f"{row['docs']:>5} {row['chunks']:>7}"
        )

    thin = [r["ticker"] for r in rows if r["chunks"] < 2]

    if thin:
        print(
            f"\n{len(thin)} companies have fewer than 2 chunks — a question "
            f"comparing them measures the gap, not the pipeline:"
        )
        print("  " + ", ".join(thin))

    return 0


async def themes() -> int:
    """Cohorts available for MIXED questions."""
    conn = await _connect()

    theme_rows = await conn.fetch(
        """
        SELECT t.name, string_agg(c.ticker, ', ' ORDER BY c.ticker) AS members
        FROM themes t
        JOIN company_themes ct ON ct.theme_id = t.id
        JOIN companies c ON c.id = ct.company_id
        GROUP BY t.name ORDER BY t.name
        """
    )

    sector_rows = await conn.fetch(
        """
        SELECT c.sector,
               count(*) AS companies,
               count(*) FILTER (
                   WHERE NOT EXISTS (
                       SELECT 1 FROM documents d WHERE d.company_id = c.id
                   )
               ) AS uncovered
        FROM companies c
        WHERE c.sector IS NOT NULL
        GROUP BY c.sector ORDER BY count(*) DESC
        """
    )

    await conn.close()

    print("THEMES")
    for row in theme_rows:
        print(f"  {row['name']:20} {row['members']}")

    print("\nSECTORS — usable as MIXED cohorts too, and there are more of")
    print("them. A cohort needs every member to have documents, or the")
    print("question measures the gap rather than the ranking.")

    for row in sector_rows:
        flag = "" if row["uncovered"] == 0 else f"  ({row['uncovered']} with no docs)"
        usable = "" if row["companies"] >= 3 else "  [too small to rank]"
        print(f"  {row['sector']:24} {row['companies']:>3} companies{flag}{usable}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="e.g. INTC NVDA AMD")
    parser.add_argument("--sector", help="every company in a sector")
    parser.add_argument(
        "--python",
        action="store_true",
        help="print chunks as quoted, wrapped Python strings",
    )
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--themes", action="store_true")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if args.coverage:
        return asyncio.run(coverage())

    if args.themes:
        return asyncio.run(themes())

    if not args.tickers and not args.sector:
        parser.print_help()
        return 1

    return asyncio.run(
        show(
            tickers=args.tickers,
            sector=args.sector,
            as_python=args.python,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
