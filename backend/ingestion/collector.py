"""
From an EDGAR filing to an object in the raw bucket.

The collection half of the pipeline. Everything after the write to S3 is
the path that already exists -- the bucket notification, the queue, the
worker, chunk, embed -- and none of it knows a document came from EDGAR
rather than from someone's upload. That is the point of going through S3
rather than writing to Postgres here: one ingestion path, one place where
parsing and indexing live, however a document arrived.

The duplicate check happens before the download. EDGAR gives every filing
an accession number unique for all time, and the URL built from it is the
same source_url the database already enforces a unique constraint on, so
"do we hold this already" is answerable before a byte is transferred.
Checking afterwards would be equally correct and would still spend the
bandwidth against a rate-limited public archive, the S3 write, the queue
message, and the parse.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

from backend.ingestion.dedupe import find_duplicate_document
from backend.ingestion.edgar import (
    DEFAULT_FORMS,
    Filing,
    cik_for_ticker,
    download_filing,
    filing_url,
    recent_filings,
)


logger = logging.getLogger(__name__)


SOURCE = "sec_edgar"


class Store(Protocol):
    async def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> None: ...


AlreadyHave = Callable[[str], Awaitable[bool]]


def object_key(filing: Filing) -> str:
    """
    Where one filing lives in the raw bucket.

    Grouped source/ticker so a prefix listing answers "what do we have for
    AAPL from EDGAR" without a scan, and deterministic on the accession
    number so re-collecting overwrites rather than accumulating.

    The document's own extension is kept, because it is what tells the
    worker how to parse the bytes.
    """
    suffix = filing.primary_document.rsplit(".", 1)[-1].lower() or "htm"

    return f"{SOURCE}/{filing.ticker or filing.cik}/{filing.accession}.{suffix}"


async def collect_filing(
    filing: Filing,
    *,
    store: Store,
    fetch,
    already_have: AlreadyHave,
    headers: dict | None = None,
) -> str | None:
    """
    Collect one filing, or return None if the corpus already holds it.

    Metadata travels on the object rather than only in the key. The worker
    sees nothing but what it reads back from S3, so anything the key does
    not encode -- the filing URL that is its duplicate identity, the form,
    the date -- is lost by the time the document is stored unless it is
    written alongside the bytes.
    """
    url = filing_url(filing)

    if await already_have(url):
        logger.info(
            "[EDGAR] Already holding %s %s; not downloading",
            filing.ticker or filing.cik,
            filing.accession,
        )
        return None

    body = await download_filing(filing, fetch=fetch, headers=headers)

    key = object_key(filing)

    await store.put_bytes(
        key,
        body,
        content_type=_content_type(filing.primary_document),
        metadata={
            "source": SOURCE,
            "source_url": url,
            "ticker": filing.ticker or "",
            "form": filing.form,
            "filing_date": filing.filing_date,
            "title": f"{filing.ticker or filing.cik} {filing.form} {filing.filing_date}",
        },
    )

    logger.info("[EDGAR] Collected %s to %s", filing.accession, key)

    return key


def _content_type(document: str) -> str:
    lowered = document.lower()

    if lowered.endswith(".pdf"):
        return "application/pdf"

    if lowered.endswith((".htm", ".html")):
        return "text/html"

    if lowered.endswith(".txt"):
        return "text/plain"

    return "application/octet-stream"


async def collect_filings(
    ticker: str,
    *,
    store: Store,
    fetch,
    already_have: AlreadyHave,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    limit: int = 10,
    headers: dict | None = None,
) -> list[str]:
    """
    Collect every recent filing of the requested forms for one company.

    Returns the keys written, which is not the same as the filings found:
    one already held is skipped, and one that fails is skipped too.

    A single filing's failure does not abandon the rest. Ten filings and
    one 404 should leave nine documents collected rather than none -- and
    the failed one is picked up by the next run, because nothing recorded
    it as held.

    An unknown ticker is the exception, and it propagates: returning an
    empty list for a typo reads like "this company has filed nothing".
    """
    cik = await cik_for_ticker(ticker, fetch=fetch, headers=headers)

    filings = await recent_filings(
        cik,
        fetch=fetch,
        forms=forms,
        ticker=ticker.strip().upper(),
        limit=limit,
        headers=headers,
    )

    logger.info(
        "[EDGAR] %s (CIK %s): %s filing(s) matching %s",
        ticker,
        cik,
        len(filings),
        ", ".join(forms),
    )

    collected: list[str] = []

    for filing in filings:
        try:
            key = await collect_filing(
                filing,
                store=store,
                fetch=fetch,
                already_have=already_have,
                headers=headers,
            )
        except Exception:
            logger.exception(
                "[EDGAR] Failed on %s %s; continuing with the rest",
                ticker,
                filing.accession,
            )
            continue

        if key:
            collected.append(key)

    return collected


def stored_documents(*, session_factory=None) -> AlreadyHave:
    """
    The real "do we hold this already", asked of the database.

    Matched on the filing's URL, which embeds the accession number and is
    therefore unique to one filing of one company. Matching on the company
    instead would collect its first filing and skip every later one.

    Asked of the database rather than an in-process set, because the
    unique constraint lives there and a set is authoritative for one run
    of one process.
    """
    from backend.services.postgres_service import AsyncSessionLocal

    factory = session_factory or AsyncSessionLocal

    async def already_have(url: str) -> bool:
        async with factory() as session:
            return await find_duplicate_document(session, url, None) is not None

    return already_have


async def run(
    tickers: list[str],
    *,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    limit: int = 10,
) -> int:
    """
    Collect filings for each ticker, and report how many objects landed.

    Refuses to start rather than failing partway: without a User-Agent
    SEC rejects every request, and without a bucket there is nowhere for
    a filing to go. Both are worth saying before the first download.
    """
    from backend.config import settings
    from backend.ingestion.aws import ObjectStore, aws_ingestion_configured
    from backend.ingestion.edgar import edgar_configured, http_fetch

    if not edgar_configured():
        raise SystemExit(
            "SEC_USER_AGENT is unset. SEC EDGAR requires a User-Agent "
            "naming the caller and a contact address, for example "
            '"Example Research team@example.com".'
        )

    if not aws_ingestion_configured():
        raise SystemExit(
            "RAW_BUCKET and INGESTION_QUEUE_URL are unset, so there is "
            "nowhere to put a filing. This command only runs against a "
            "deployment with the AWS ingestion path configured."
        )

    from backend.ingestion.edgar import request_headers

    store = ObjectStore()
    headers = request_headers(settings.SEC_USER_AGENT)
    already_have = stored_documents()

    total = 0

    for ticker in tickers:
        try:
            keys = await collect_filings(
                ticker,
                store=store,
                fetch=http_fetch,
                already_have=already_have,
                forms=forms,
                limit=limit,
                headers=headers,
            )
        except Exception:
            # One bad ticker should not end a run over twenty of them.
            logger.exception("[EDGAR] %s failed; continuing", ticker)
            continue

        logger.info("[EDGAR] %s: collected %s new filing(s)", ticker, len(keys))
        total += len(keys)

    logger.info("[EDGAR] Done. %s object(s) written to the raw bucket.", total)

    return total


def main() -> None:
    """
    python -m backend.ingestion.collector AAPL MSFT --forms 10-K --limit 5

    Writing the objects is all this does. The bucket notification turns
    each one into a queue message and the ingestion worker indexes it, so
    this command finishes long before the documents are searchable.
    """
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Collect SEC EDGAR filings into the raw bucket.",
    )
    parser.add_argument("tickers", nargs="+", help="e.g. AAPL MSFT")
    parser.add_argument(
        "--forms",
        nargs="+",
        default=list(DEFAULT_FORMS),
        help=f"default: {' '.join(DEFAULT_FORMS)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="most recent filings per company (default: 10)",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    asyncio.run(
        run(
            [t.strip().upper() for t in args.tickers],
            forms=tuple(f.upper() for f in args.forms),
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
