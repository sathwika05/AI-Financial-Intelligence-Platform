"""
Check every golden question against the live database.

Reseeding invalidates ground truth silently. Fundamentals move, so a
"top five" changes membership; documents are replaced, so a reference
context that was verbatim last week is absent today. Neither shows up as an
error — the pipeline answers correctly and the benchmark marks it wrong,
which looks exactly like a regression.

Both failures have already happened here. A reseed dropped NVDA out of the
smallest-market-cap five and brought CRM in. A later one removed an AMD bond
story and a Microsoft data-centre story that two questions cited, and RAGAS
scored context precision, recall and entity recall at 0.0 for questions
whose retrieval was fine.

Run this after every reseed, before trusting a benchmark number:

    uv run python -m backend.evaluation.datasets.verify_ground_truth

It exits non-zero when anything drifted, so it can gate a benchmark run.
Nothing is written back: a mismatch needs a person to decide whether the
question or the ground truth is what changed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from backend.evaluation.datasets.question_sets import QUESTION_SETS


def _comparable(value: Any) -> Any:
    """
    Widen numerics so an int golden matches a double-precision column.

    market_cap is stored as double precision, and goldens have been written
    both ways. Booleans are excluded because bool is a subclass of int and
    True must never equal 1.
    """
    if isinstance(value, bool):
        # Tagged rather than returned as-is: bool subclasses int, so a bare
        # True still compares equal to 1.0 and a golden of True would match
        # a live column of 1. The tag makes the types compare unequal.
        return ("bool", value)

    if isinstance(value, (int, float)):
        return float(value)

    return value


def _row(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _comparable(val) for key, val in record.items()}


async def _connect():
    import asyncpg

    url = os.environ.get("DATABASE_URL", "")

    # asyncpg wants a bare postgresql:// URL, not SQLAlchemy's driver form.
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]

    if not url:
        url = "postgresql://finuser:finpass@localhost:5433/findb"

    return await asyncpg.connect(url)


async def verify(verbose: bool = False) -> int:
    conn = await _connect()

    chunks = {
        record["content"].strip()
        for record in await conn.fetch(
            "select content from document_chunks"
        )
    }

    problems: list[str] = []
    warnings: list[str] = []

    for question in QUESTION_SETS["all"]:
        qid = question.question_id

        # 1. The golden rows still reproduce.
        if question.expected_sql and question.expected_sql_result is not None:
            try:
                live = [
                    _row(dict(record))
                    for record in await conn.fetch(question.expected_sql)
                ]
            except Exception as exc:
                problems.append(
                    f"{qid}: expected_sql does not execute: {exc}"
                )
                live = None

            if live is not None:
                golden = [_row(r) for r in question.expected_sql_result]

                if golden != live:
                    problems.append(
                        f"{qid}: expected_sql_result is stale.\n"
                        f"    golden: {json.dumps(golden, default=str)}\n"
                        f"    live:   {json.dumps(live, default=str)}"
                    )
                elif verbose:
                    print(f"  {qid}: {len(live)} rows match")

                # 2. The ranking matches the rows, when SQL owns the order.
                if question.expected_ranking and question.sql_order_requirement != "none":
                    live_tickers = [
                        r.get("ticker") for r in live if r.get("ticker")
                    ]

                    if live_tickers and live_tickers != question.expected_ranking:
                        problems.append(
                            f"{qid}: expected_ranking disagrees with the rows.\n"
                            f"    ranking: {question.expected_ranking}\n"
                            f"    rows:    {live_tickers}"
                        )

                # 3. A LIMIT that no longer selects anything is not a test.
                if question.sql_order_requirement == "top_k":
                    stripped = question.expected_sql.rstrip().rstrip(";")
                    lowered = stripped.lower()

                    if " limit " in lowered:
                        head = stripped[: lowered.rindex(" limit ")]

                        try:
                            total = len(await conn.fetch(head))
                        except Exception:
                            total = None

                        if total is not None and total <= len(live):
                            warnings.append(
                                f"{qid}: LIMIT is non-binding — the filters "
                                f"yield {total} rows for a query asking for "
                                f"{len(live)}. top_k membership is satisfied "
                                f"by any query with the right filters, so it "
                                f"proves only the ordering."
                            )

        # 4. Every reference context is still in the corpus.
        for context in question.reference_contexts:
            if context.strip() not in chunks:
                problems.append(
                    f"{qid}: reference context is absent from "
                    f"document_chunks — RAGAS will score it 0.0:\n"
                    f"    {context[:110]}..."
                )

        if verbose and question.reference_contexts:
            present = sum(
                1
                for c in question.reference_contexts
                if c.strip() in chunks
            )
            print(
                f"  {qid}: {present}/{len(question.reference_contexts)} "
                f"contexts verbatim"
            )

    await conn.close()

    # Warnings describe a weak test, not a wrong one, so they do not gate a
    # run. valuation_002 sits here whenever Yahoo drops a market_cap.
    if warnings:
        print("\nWEAK, BUT NOT WRONG\n")
        for warning in warnings:
            print(f"  - {warning}")

    if problems:
        print("\nGROUND TRUTH DRIFTED\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            f"\n{len(problems)} problem(s). Re-run each expected_sql and "
            f"re-read the contexts from document_chunks."
        )
        return 1

    print("Ground truth is consistent with the database.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print each question as it checks out.",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return asyncio.run(verify(verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())
