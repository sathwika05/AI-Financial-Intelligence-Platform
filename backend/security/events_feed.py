"""
Reading back what the guards did.

`events.py` is the write side: every guard records its decision into
system_logs under node "security". This is the read side, and until it
existed those rows had no reader -- the only way to find out whether an
injection had been blocked was a psql prompt.

The rows are already safe to display. events.record masks the query before
storing it, precisely so that a record of a blocked input does not become
a second copy of whatever personal data was in it.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# What each kind means in the interface, and whether the request survived.
#
# `action` is the distinction that matters to a reader: "blocked" refused
# the request outright, "masked" let it through with the personal data
# removed. Rendering both the same way would suggest the pipeline refuses
# anything it finds, which is the opposite of how it is tuned.
GUARDRAILS: dict[str, dict[str, str]] = {
    "input_blocked": {
        "label": "Prompt injection",
        "action": "blocked",
        "explains": "An instruction aimed at the model, not a question about the data.",
    },
    "input_pii": {
        "label": "PII masked",
        "action": "masked",
        "explains": "Personal data removed before the query reached the provider.",
    },
    "output_blocked": {
        "label": "Credential in output",
        "action": "blocked",
        "explains": "The report was withheld: no version of it is worth returning.",
    },
    "output_pii": {
        "label": "PII in output",
        "action": "masked",
        "explains": "Personal data removed from the report; the analysis still went out.",
    },
    "rate_limited": {
        "label": "Rate limited",
        "action": "blocked",
        "explains": "Each query runs the full pipeline, so the ceiling is about cost.",
    },
}


# Which fields a PII guard stripped, pulled out of the detail string.
#
# Two shapes, because the two guards format it differently. The input
# guard prints a sorted list -- "masked ['email', 'phone']" -- where only
# the first name follows the word "masked". The output validator joins its
# own findings -- "masked email; masked phone" -- where every name does.
# So the quoted form is read first and the bare form is the fallback.
_QUOTED_FIELD = re.compile(r"'([a-z_]+)'", re.IGNORECASE)
_BARE_FIELD = re.compile(r"masked\s+([a-z_]+)", re.IGNORECASE)


def fields_removed(kind: str, detail: str) -> list[str]:
    """
    The names of the fields a guard removed -- never their values.

    Storing the value would make this log a second copy of exactly the
    personal data the guard had just taken out, which is the thing
    events.record exists to prevent. The type is enough to show that
    masking happened and what it caught.

    Anything that did not mask returns an empty list rather than a guess:
    a blocked injection removed nothing, it refused the request whole.
    """
    if kind not in ("input_pii", "output_pii"):
        return []

    text_ = detail or ""
    found = _QUOTED_FIELD.findall(text_) or _BARE_FIELD.findall(text_)

    seen: list[str] = []

    for field in found:
        lowered = field.lower()

        if lowered not in seen:
            seen.append(lowered)

    return seen


async def read_security_events(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """The guard log, newest first."""
    rows = (
        await session.execute(
            text(
                "SELECT id, message, metadata, created_at "
                "FROM system_logs "
                "WHERE node = 'security' "
                # id, not created_at: rows written inside one second share a
                # timestamp at the database's resolution, and the table then
                # reorders itself between refreshes.
                "ORDER BY id DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()

    events: list[dict[str, Any]] = []

    for row in rows:
        metadata = row.metadata or {}
        kind = metadata.get("kind")

        if kind not in GUARDRAILS:
            # A row written by something that is not one of the five guards,
            # or by an older version that stored no kind. Skipping keeps the
            # table to rows the screen can actually label.
            continue

        message = row.message or ""
        # Everything after "kind: " -- the pattern that fired, the fields
        # that were masked, the caller that was limited.
        detail = message.split(": ", 1)[-1] if ": " in message else message

        events.append(
            {
                "id": row.id,
                "kind": kind,
                "label": GUARDRAILS[kind]["label"],
                "action": GUARDRAILS[kind]["action"],
                "explains": GUARDRAILS[kind]["explains"],
                "detail": detail,
                # Field names only. See fields_removed.
                "removed": fields_removed(kind, detail),
                # Already masked on the way in; see events.record.
                "query": metadata.get("query") or "",
                "created_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
            }
        )

    return events
