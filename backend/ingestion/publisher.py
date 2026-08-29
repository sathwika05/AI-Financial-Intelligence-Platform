"""
The producer end: writing a fetched document to the raw bucket.

This is the step that starts the path. Terraform's bucket notification
turns the resulting ObjectCreated into a queue message, the worker picks it
up, and chunk -> embed -> store runs from there. Nothing else has to be
called.

Kept separate from the fetcher so the fetcher can write to Postgres
directly where there is no AWS path — which is every local run, and the
way the corpus in this repo was actually built.
"""
from __future__ import annotations

import logging
import re
from typing import Protocol


logger = logging.getLogger(__name__)


# Anything outside this is replaced. Identifiers come from a third party:
# a slash would silently create a prefix, and a space arrives URL-encoded
# in the notification, so neither is passed through.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Documents belonging to no company still need a home in the layout.
_UNASSIGNED = "_unassigned"

# What a document is credited to when its key does not name a source --
# which is the case for anything uploaded by hand.
_MANUAL = "manual"


class Store(Protocol):
    async def put_json(self, key: str, payload: dict) -> None: ...


def _safe(value: str) -> str:
    cleaned = _UNSAFE.sub("-", value).strip("-")

    return cleaned or "unknown"


def object_key(*, source: str, ticker: str | None, identifier: str) -> str:
    """
    Where one document lives in the raw bucket.

    Grouped source/ticker/identifier so a prefix listing answers "what do
    we have for AAPL from Alpha Vantage" without a scan. Deterministic, so
    re-fetching the same article overwrites rather than accumulating -- the
    fetcher runs on a schedule and sees the same articles repeatedly.
    """
    return (
        f"{_safe(source)}/"
        f"{_safe(ticker) if ticker else _UNASSIGNED}/"
        f"{_safe(identifier)}.json"
    )


async def publish_document(
    *,
    store: Store,
    source: str,
    ticker: str | None,
    identifier: str,
    document: dict,
) -> str:
    """
    Write one document to the raw bucket and return its key.

    Refuses an empty document rather than writing it: it would still fire a
    notification, still cost a queue message, and still be skipped at the
    far end.
    """
    if not (document.get("content") or "").strip():
        raise ValueError(
            f"Refusing to publish {identifier}: it has no content."
        )

    # The worker reads only the object, so what the key encodes has to be
    # in the body too or it is lost by the time the document is stored.
    payload = {
        **document,
        "source": source,
        "ticker": ticker,
    }

    key = object_key(source=source, ticker=ticker, identifier=identifier)

    await store.put_json(key, payload)

    return key


def metadata_from_key(key: str) -> dict:
    """
    What a key says about the document stored under it.

    The inverse of object_key, and the only source of this information for
    a PDF uploaded by hand: a fetcher writes source and ticker into the
    JSON body, but nobody types a JSON body alongside an `aws s3 cp`.

    Tolerant of a key that does not follow the layout. Someone will drop a
    file at the top of the bucket, and that should index as an
    unattributed document rather than fail -- an unknown ticker already
    stores fine, it just cannot be filtered by company.
    """
    segments = [part for part in key.split("/") if part]

    if not segments:
        return {"source": _MANUAL, "ticker": None, "title": ""}

    # The filename without its extension: what a person named the upload,
    # and the most useful title available for one.
    title = segments[-1].rsplit(".", 1)[0]

    source = segments[0] if len(segments) >= 2 else _MANUAL
    ticker = segments[1] if len(segments) >= 3 else None

    if ticker == _UNASSIGNED:
        ticker = None

    return {"source": source, "ticker": ticker, "title": title}
