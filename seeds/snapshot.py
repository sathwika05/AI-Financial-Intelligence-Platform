"""
Freeze and restore the benchmark's data.

Why this exists
---------------
The seed pulls live data — Yahoo fundamentals and news from Alpha Vantage
and Finnhub — so every reseed changes the ground under the benchmark.
Market caps move, articles are replaced, and the membership of a "top five"
changes outright: one reseed dropped NVDA out of the five smallest
technology market caps and brought CRM in, so the pipeline answered
correctly and the benchmark marked it wrong.

That makes a score meaningless on its own. A drop could mean the code got
worse or that Yahoo repriced a stock overnight, and there is no way to tell
which from the number. Freezing the data separates the two: with the
snapshot restored, a score change can only have come from the code.

What is captured
----------------
companies, financial_metrics, documents and document_chunks — including
each chunk's embedding, so a restored snapshot needs no embedding API call
and vector search returns the same chunks every run.

Primary keys are preserved. documents.company_id and
document_chunks.document_id are foreign keys, so ids have to survive the
round trip or the graph of references breaks. Sequences are reset
afterwards, or the next insert would collide with a restored id.

What is NOT captured
--------------------
Live market data. run_market_retrieval calls an external API at query time
and is not part of these tables, so a MIXED question still varies between
runs by however much prices moved. Freezing that means recording API
responses, which is a separate piece of work.

Usage
-----
    python -m seeds.snapshot create      # freeze the current database
    python -m seeds.snapshot restore     # load the frozen data back
    python -m seeds.snapshot verify      # compare database against file

`restore` is destructive: it truncates the four tables before loading. It
is meant to be run immediately before a benchmark, not against a database
holding anything you want to keep.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.services.postgres_service import engine


SNAPSHOT_PATH = Path(__file__).parent / "benchmark_snapshot.json"


# Ordered parent-first so a restore satisfies foreign keys as it goes.
# Truncation walks this in reverse.
TABLES: dict[str, list[str]] = {
    "companies": [
        "id",
        "name",
        "ticker",
        "sector",
        "market_cap",
    ],
    "themes": [
        "id",
        "name",
        "slug",
    ],
    "company_themes": [
        "id",
        "company_id",
        "theme_id",
    ],
    "financial_metrics": [
        "id",
        "company_id",
        "pe_ratio",
        "eps",
        "revenue_growth",
    ],
    "documents": [
        "id",
        "company_id",
        "title",
        "content",
        "doc_type",
        "source",
        "source_url",
        "content_hash",
        "relevance_score",
    ],
    "document_chunks": [
        "id",
        "document_id",
        "chunk_index",
        "content",
        "embedding",
    ],
}

# pgvector does not round-trip through JSON on its own. Reading it as text
# gives "[0.1,0.2,...]", which is also the literal form the CAST on write
# accepts, so the vector survives unchanged in both directions.
VECTOR_COLUMNS = {"embedding"}


def _select_clause(table: str) -> str:
    return ", ".join(
        f"{column}::text AS {column}"
        if column in VECTOR_COLUMNS
        else column
        for column in TABLES[table]
    )


def _insert_statement(table: str) -> str:
    columns = TABLES[table]

    values = ", ".join(
        f"CAST(:{column} AS vector)"
        if column in VECTOR_COLUMNS
        else f":{column}"
        for column in columns
    )

    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({values})"
    )


async def create(path: Path = SNAPSHOT_PATH) -> dict[str, int]:
    """Write the current contents of the benchmark tables to `path`."""
    payload: dict[str, Any] = {}
    counts: dict[str, int] = {}

    async with engine.connect() as conn:
        for table in TABLES:
            result = await conn.execute(
                text(
                    f"SELECT {_select_clause(table)} "
                    f"FROM {table} ORDER BY id"
                )
            )

            rows = [dict(row._mapping) for row in result.fetchall()]

            payload[table] = rows
            counts[table] = len(rows)

    path.write_text(
        json.dumps(payload, indent=2, default=str)
    )

    return counts


async def restore(path: Path = SNAPSHOT_PATH) -> dict[str, int]:
    """
    Replace the benchmark tables with the contents of `path`.

    Destructive by design — the point is that the database matches the file
    exactly afterwards, so anything currently in these tables is discarded.
    Everything happens in one transaction, so a failure leaves the previous
    data intact rather than an empty database.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No snapshot at {path}. Run `python -m seeds.snapshot create` first."
        )

    payload = json.loads(path.read_text())
    counts: dict[str, int] = {}

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(reversed(list(TABLES)))
                + " RESTART IDENTITY CASCADE"
            )
        )

        for table, columns in TABLES.items():
            rows = payload.get(table, [])
            statement = text(_insert_statement(table))

            for row in rows:
                await conn.execute(
                    statement,
                    {column: row.get(column) for column in columns},
                )

            counts[table] = len(rows)

            # Ids were restored explicitly, so the sequence still points at
            # 1 and the next insert would collide with a restored row.
            if rows:
                await conn.execute(
                    text(
                        f"SELECT setval("
                        f"pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT max(id) FROM {table}))"
                    )
                )

    return counts


async def verify(path: Path = SNAPSHOT_PATH) -> dict[str, dict[str, int]]:
    """
    Compare row counts in the database against the snapshot.

    A cheap check that the restore took, and that nothing has written to
    these tables since — a benchmark run against drifted data is exactly
    what this module exists to prevent.
    """
    if not path.exists():
        raise FileNotFoundError(f"No snapshot at {path}.")

    payload = json.loads(path.read_text())
    report: dict[str, dict[str, int]] = {}

    async with engine.connect() as conn:
        for table in TABLES:
            result = await conn.execute(
                text(f"SELECT count(*) FROM {table}")
            )

            report[table] = {
                "database": result.scalar_one(),
                "snapshot": len(payload.get(table, [])),
            }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze and restore the benchmark's data.",
    )
    parser.add_argument(
        "command",
        choices=["create", "restore", "verify"],
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=SNAPSHOT_PATH,
    )

    args = parser.parse_args()

    if args.command == "create":
        counts = asyncio.run(create(args.path))
        size_kb = args.path.stat().st_size / 1024

        print(f"Wrote {args.path} ({size_kb:.0f} KB)")

        for table, count in counts.items():
            print(f"  {table:<20} {count}")

    elif args.command == "restore":
        counts = asyncio.run(restore(args.path))

        print(f"Restored from {args.path}")

        for table, count in counts.items():
            print(f"  {table:<20} {count}")

    else:
        report = asyncio.run(verify(args.path))
        drifted = False

        for table, numbers in report.items():
            match = numbers["database"] == numbers["snapshot"]
            drifted = drifted or not match

            print(
                f"  {table:<20} db={numbers['database']:<6} "
                f"snapshot={numbers['snapshot']:<6} "
                f"{'ok' if match else 'DRIFTED'}"
            )

        if drifted:
            raise SystemExit(
                "Database does not match the snapshot. "
                "Run `python -m seeds.snapshot restore` before benchmarking."
            )

        print("Database matches the snapshot.")


if __name__ == "__main__":
    main()
