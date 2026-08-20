"""
Derive ground truth for the SQL sets by running their queries.

The specifications in question_bank.py carry a question and the query that
answers it. The rows are read from the database here, because a reseed moves
every fundamental — a golden written by hand is stale the moment the next
reseed runs, and rebuilding a hundred of them by hand is not slow, it is
infeasible.

    uv run python -m backend.evaluation.datasets.generate_ground_truth

Writes generated_ground_truth.json next to this module. Re-run it after
every reseed, then run verify_ground_truth to confirm the authored sets
(sentiment, mixed) still hold.

What this does NOT generate: reference_answer and reference_contexts. Those
need judgement about what a good answer says and which documents support it,
and a script that invents them would only ever confirm its own output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.evaluation.datasets.question_bank import SPEC_SETS, QuestionSpec


OUTPUT_PATH = Path(__file__).parent / "generated_ground_truth.json"


async def _connect():
    import asyncpg

    url = os.environ.get("DATABASE_URL", "")

    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]

    if not url:
        url = "postgresql://finuser:finpass@localhost:5433/findb"

    return await asyncpg.connect(url)


def _cell(value: Any) -> Any:
    """JSON-safe, and float rather than Decimal so goldens compare cleanly."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)

    return value


def _requested_count(sql: str) -> int | None:
    lowered = sql.lower()

    if " limit " not in lowered:
        return None

    try:
        return int(lowered.rsplit(" limit ", 1)[1].strip().rstrip(";"))
    except (ValueError, IndexError):
        return None


async def generate(verbose: bool = False) -> int:
    conn = await _connect()

    generated: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Derived from the database by generate_ground_truth.py. Do not "
            "edit by hand — re-run the generator after a reseed instead."
        ),
        "questions": {},
    }

    problems: list[str] = []

    for set_name, specs in SPEC_SETS.items():
        for spec in specs:
            try:
                rows = [
                    {
                        key: _cell(value)
                        for key, value in dict(record).items()
                    }
                    for record in await conn.fetch(spec.expected_sql)
                ]
            except Exception as exc:
                problems.append(f"{spec.question_id}: query failed: {exc}")
                continue

            # A question nobody can answer measures nothing. Empty results
            # are only acceptable where the spec said so.
            if not rows and not spec.allows_short_result:
                problems.append(
                    f"{spec.question_id}: returned no rows. Either the seed "
                    f"cannot support this question, or the filters are "
                    f"wrong. Narrow the question rather than shipping it."
                )
                continue

            wanted = _requested_count(spec.expected_sql)

            if (
                wanted is not None
                and len(rows) < wanted
                and not spec.allows_short_result
            ):
                problems.append(
                    f"{spec.question_id}: asks for {wanted} rows and the "
                    f"seed yields {len(rows)}. Lower the count, or mark the "
                    f"spec allows_short_result if a short answer is the "
                    f"point."
                )
                continue

            # A LIMIT the filters never reach is not a top_k test: any
            # query with the right filters satisfies membership, so only
            # the ordering is being graded.
            non_binding = False

            if wanted is not None and spec.sql_order_requirement == "top_k":
                stripped = spec.expected_sql.rstrip().rstrip(";")
                head = stripped[: stripped.lower().rindex(" limit ")]

                try:
                    non_binding = len(await conn.fetch(head)) <= len(rows)
                except Exception:
                    non_binding = False

            generated["questions"][spec.question_id] = {
                "set": set_name,
                "question": spec.question,
                "expected_intent": spec.expected_intent,
                "expected_tools": list(spec.expected_tools),
                "expected_sql": spec.expected_sql,
                "sql_order_requirement": spec.sql_order_requirement,
                "expected_sql_result": rows,
                "expected_ranking": [
                    row["ticker"]
                    for row in rows
                    if row.get("ticker")
                ],
                "shape": spec.shape,
                "row_count": len(rows),
                "limit_non_binding": non_binding,
            }

            if verbose:
                flag = "  [LIMIT non-binding]" if non_binding else ""
                print(
                    f"  {spec.question_id}: {len(rows)} rows{flag}"
                )

    await conn.close()

    if problems:
        print("\nNOT GENERATED\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            f"\n{len(problems)} specification(s) could not be turned into "
            f"ground truth. Nothing was written."
        )
        return 1

    OUTPUT_PATH.write_text(json.dumps(generated, indent=2) + "\n")

    weak = [
        qid
        for qid, entry in generated["questions"].items()
        if entry["limit_non_binding"]
    ]

    print(
        f"Wrote {len(generated['questions'])} questions to "
        f"{OUTPUT_PATH.name}"
    )

    if weak:
        print(
            f"\n{len(weak)} question(s) have a non-binding LIMIT — the "
            f"filters yield no more rows than requested, so top_k "
            f"membership proves only the ordering:"
        )
        for qid in weak:
            print(f"  - {qid}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return asyncio.run(generate(verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())
