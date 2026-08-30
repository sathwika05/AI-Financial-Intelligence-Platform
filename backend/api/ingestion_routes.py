"""
The endpoints behind the Ingestion screen.

Two of these three need no AWS at all, which is deliberate. The S3 path
cannot be exercised on a laptop -- there is no bucket and no queue -- but
the two things most likely to be wrong can be: what SEC EDGAR -- the
Securities and Exchange Commission's public filing archive -- actually
returns for a ticker, and whether Docling can read the file you have.
Both are testable here before anything is deployed.

Uploading writes to the corpus and spends embedding credit, and listing
exposes what the corpus holds, so all three are admin-only and none is
mounted on the public deployment.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.config import settings
from backend.ingestion.handler import SkippedObject, document_from_bytes
from backend.models.db_models import Company, Document, DocumentChunk
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ingestion",
    tags=["ingestion"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


# What Docling can read. Checked by name before the bytes are touched,
# because loading a layout model to discover the file is a spreadsheet
# costs seconds and tells the user nothing they could not be told now.
SUPPORTED = (".pdf", ".htm", ".html")

# An upload is parsed in memory and embedded in one request's lifetime.
# A 10-K is a few megabytes; this is generous for that and still refuses
# something that was never a filing.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def _edgar_headers(user_agent: str) -> dict[str, str]:
    """
    The headers for an EDGAR call, or a clear refusal.

    SEC rejects anonymous requests outright, so saying which setting is
    missing beats forwarding a 403 from EDGAR that reads like the service
    is down.
    """
    from backend.ingestion.edgar import MissingUserAgent, request_headers

    try:
        return request_headers(user_agent)
    except MissingUserAgent as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "SEC_USER_AGENT is not set on this deployment. EDGAR "
                "requires a User-Agent naming the caller and a contact "
                'address, for example "Example Research you@example.com".'
            ),
        ) from exc


async def _preview(
    ticker: str,
    *,
    forms: tuple[str, ...],
    limit: int,
    fetch,
    headers: dict,
) -> list[dict]:
    """
    What EDGAR holds for a ticker. Reads only; downloads nothing.

    This is the whole of the EDGAR integration that can be checked without
    a bucket, so it is worth having on its own rather than only as a step
    inside collection.
    """
    from backend.ingestion.edgar import (
        UnknownCompany,
        cik_for_ticker,
        filing_url,
        recent_filings,
    )

    try:
        cik = await cik_for_ticker(ticker, fetch=fetch, headers=headers)
    except UnknownCompany as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filings = await recent_filings(
        cik,
        fetch=fetch,
        forms=forms,
        ticker=ticker.strip().upper(),
        limit=limit,
        headers=headers,
    )

    return [
        {
            "accession": filing.accession,
            "form": filing.form,
            "filing_date": filing.filing_date,
            "document": filing.primary_document,
            "url": filing_url(filing),
            # Sent back up when one of these is indexed, so the client
            # never has to construct a URL and the server never has to
            # trust one.
            "cik": filing.cik,
            "ticker": filing.ticker,
        }
        for filing in filings
    ]


async def _prepare_upload(
    *,
    filename: str,
    body: bytes,
    ticker: str | None,
) -> dict:
    """
    Turn an uploaded file into the document row the corpus stores.

    Parsed through the same function the queue worker uses, so a file
    uploaded in the browser becomes exactly the document it would have
    become arriving through S3. A second implementation would drift, and
    the drift would show as a document that answers differently depending
    on how it was loaded.
    """
    name = (filename or "").strip()

    if not name.lower().endswith(SUPPORTED):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{name or 'That file'} cannot be read. Upload a PDF or an "
                "HTML filing."
            ),
        )

    if not body:
        raise HTTPException(status_code=400, detail=f"{name} is empty.")

    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{name} is larger than "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
            ),
        )

    cleaned = (ticker or "").strip().upper() or None

    try:
        document = await document_from_bytes(
            filename=name,
            body=body,
            provenance={
                "source": "upload",
                "ticker": cleaned,
                "title": name.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            },
        )
    except SkippedObject as exc:
        # A wrong file is a bad request with a reason, not a stack trace.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not (document.get("content") or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{name} has no text to index. A scanned document is read "
                "by optical character recognition, but a blank one has "
                "nothing to read."
            ),
        )

    return document


@router.get("/edgar/filings")
async def preview_filings(
    ticker: str,
    forms: str = "10-K,10-Q",
    limit: int = 5,
    session: AsyncSession = Depends(get_db),
):
    """List a company's recent filings. Downloads nothing."""
    from backend.ingestion.edgar import http_fetch

    ticker = _require_known_ticker(ticker, await _known_tickers(session))

    headers = _edgar_headers(settings.SEC_USER_AGENT)

    wanted = _require_known_forms(forms.split(","))

    try:
        return {
            "ticker": ticker.strip().upper(),
            "filings": await _preview(
                ticker,
                forms=wanted,
                limit=max(1, min(limit, 50)),
                fetch=http_fetch,
                headers=headers,
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[INGEST] EDGAR preview failed for %s", ticker)

        raise HTTPException(
            status_code=502,
            detail=f"EDGAR did not answer: {exc}",
        ) from exc


@router.post("/documents", status_code=202)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    ticker: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
):
    """
    Parse an uploaded filing, store it, and index it.

    The direct path, with no S3 in it. On a deployment that has the bucket
    this is still the honest way to check that a particular document can
    be read at all, because it fails in the response rather than in a log
    on another machine.

    Indexing runs in the background: embedding a 10-K is many API calls
    and the browser should not be holding a request open for them.
    """
    from backend.ingestion.queue_worker import _mark_ready, _persist_document

    # Optional, but if given it has to be a company that exists -- a
    # typo would otherwise store the document with no company at all and
    # say nothing about it.
    if (ticker or "").strip():
        ticker = _require_known_ticker(ticker, await _known_tickers(session))

    body = await file.read()

    document = await _prepare_upload(
        filename=file.filename or "", body=body, ticker=ticker
    )

    try:
        document_id = await _persist_document(document)
    except SkippedObject as exc:
        # Already in the corpus. Not an error -- it is the answer.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def index() -> None:
        from backend.ingestion.indexing_service import embed_document

        result = await embed_document(document_id)

        if result.get("success"):
            await _mark_ready(document_id)
            logger.info(
                "[INGEST] Indexed uploaded document %s (%s chunks)",
                document_id,
                result.get("chunks"),
            )
        else:
            # The row stays `processing`, which is what makes this
            # findable afterwards instead of silently absent.
            logger.error(
                "[INGEST] Uploaded document %s failed to index: %s",
                document_id,
                result.get("error"),
            )

    background.add_task(index)

    return {
        "document_id": document_id,
        "title": document.get("title"),
        "characters": len(document["content"]),
        "status": "processing",
        "message": (
            "Stored. Indexing runs in the background; refresh the list to "
            "see it become ready."
        ),
    }


@router.get("/documents")
async def list_documents(
    limit: int = 25,
    session: AsyncSession = Depends(get_db),
):
    """
    The most recent documents, with their status and chunk count.

    The chunk count is the honest measure of whether indexing worked: a
    document can be `ready` and useless if it produced nothing.
    """
    chunk_counts = (
        select(
            DocumentChunk.document_id.label("document_id"),
            func.count().label("chunks"),
        )
        .group_by(DocumentChunk.document_id)
        .subquery()
    )

    # The total, so the screen can say "25 of 296" rather than leaving
    # someone to wonder whether 25 is the page size or the whole corpus.
    total = await session.scalar(select(func.count()).select_from(Document))

    rows = await session.execute(
        select(Document, Company.ticker, chunk_counts.c.chunks)
        .outerjoin(Company, Document.company_id == Company.id)
        .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
        .order_by(desc(Document.id))
        .limit(max(1, min(limit, 200)))
    )

    return {
        "total": total or 0,
        "documents": [
            {
                "id": document.id,
                "title": document.title,
                "doc_type": document.doc_type,
                "source": document.source,
                "status": document.status,
                "ticker": ticker,
                "chunks": chunks or 0,
                "created_at": (
                    document.created_at.isoformat()
                    if document.created_at
                    else None
                ),
            }
            for document, ticker, chunks in rows
        ]
    }

class EdgarFilingRequest(BaseModel):
    """
    One filing, identified the way EDGAR identifies it.

    Deliberately not a URL. The client sends the fields, and the URL is
    rebuilt and validated here -- accepting a URL would let any caller
    have the contents of any host downloaded and stored as an SEC filing.
    """

    cik: str = Field(min_length=1, max_length=20)
    accession: str = Field(min_length=1, max_length=32)
    form: str = Field(min_length=1, max_length=20)
    filing_date: str = Field(min_length=1, max_length=20)
    primary_document: str = Field(min_length=1, max_length=200)
    ticker: str | None = Field(default=None, max_length=12)


async def _prepare_edgar_filing(fields: dict, *, fetch, headers: dict) -> dict:
    """
    Download one filing and turn it into the row the corpus stores.

    The same provenance the collector would attach on its way through S3,
    so a filing indexed from this screen and the same filing arriving
    through the queue become one row rather than two the duplicate check
    cannot see are the same.
    """
    from backend.ingestion.edgar import Filing, download_filing, filing_url

    filing = Filing(
        cik=fields["cik"],
        accession=fields["accession"],
        form=fields["form"],
        filing_date=fields["filing_date"],
        primary_document=fields["primary_document"],
        ticker=(fields.get("ticker") or "").strip().upper() or None,
    )

    url = filing_url(filing)

    try:
        body = await download_filing(filing, fetch=fetch, headers=headers)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[INGEST] EDGAR download failed for %s", filing.accession)

        raise HTTPException(
            status_code=502,
            detail=f"EDGAR did not return {filing.primary_document}: {exc}",
        ) from exc

    label = f"{filing.ticker or filing.cik} {filing.form} {filing.filing_date}"

    try:
        document = await document_from_bytes(
            filename=filing.primary_document,
            body=body,
            provenance={
                "source": "sec_edgar",
                "source_url": url,
                "ticker": filing.ticker,
                "form": filing.form,
                "filing_date": filing.filing_date,
                "title": label,
            },
        )
    except SkippedObject as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not (document.get("content") or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{label} downloaded, but no text could be read from it."
            ),
        )

    return document


@router.post("/edgar/documents", status_code=202)
async def index_filing(
    request: EdgarFilingRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """
    Download one filing from EDGAR and index it. No bucket involved.

    The collector's route to the same place goes through S3, so that a
    scheduled run leaves the raw document in object storage. This one is
    for the person looking at the list who wants that filing in the
    corpus now, and it works on a deployment that has no bucket at all.
    """
    from backend.ingestion.edgar import http_fetch
    from backend.ingestion.queue_worker import _mark_ready, _persist_document

    _require_known_ticker(request.ticker or "", await _known_tickers(session))

    headers = _edgar_headers(settings.SEC_USER_AGENT)

    document = await _prepare_edgar_filing(
        request.model_dump(), fetch=http_fetch, headers=headers
    )

    try:
        document_id = await _persist_document(document)
    except SkippedObject as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def index() -> None:
        from backend.ingestion.indexing_service import embed_document

        result = await embed_document(document_id)

        if result.get("success"):
            await _mark_ready(document_id)
            logger.info(
                "[INGEST] Indexed EDGAR filing %s as document %s (%s chunks)",
                request.accession,
                document_id,
                result.get("chunks"),
            )
        else:
            logger.error(
                "[INGEST] EDGAR filing %s failed to index: %s",
                request.accession,
                result.get("error"),
            )

    background.add_task(index)

    return {
        "document_id": document_id,
        "title": document.get("title"),
        "characters": len(document["content"]),
        "status": "processing",
        "message": (
            "Downloaded and stored. Indexing runs in the background; "
            "refresh the list to see it become ready."
        ),
    }


# ── Long-running jobs ───────────────────────────────────────
#
# Two buttons, doing very different things.
#
# Collecting EDGAR filings adds to the corpus. A duplicate is skipped, a
# failure loses nothing, and running it twice changes nothing.
#
# Reseeding replaces the corpus. seeds/seed_data.py TRUNCATEs documents,
# document_chunks, financial_metrics and companies with RESTART IDENTITY,
# then refetches live data -- which will not match what was there, because
# market caps move and news is replaced. The benchmark corpus and the SQL
# ground truth derived from it do not survive it.
#
# So one is a button and the other needs a phrase typed out. The
# difference in cost between a wrong click on each is the difference
# between nothing and a day's work.

RESEED_CONFIRMATION = "replace the corpus"


# How many filings one run may fetch.
#
# Measured on Apple's 2024 10-K: 1.5MB downloaded, 1.6s in Docling, 1,458
# chunks, roughly 120,000 tokens to embed -- about a fifth of a cent. So
# this is not a limit about money.
#
# It is about volume. The corpus is 327 chunks. Twenty-five filings adds
# something like thirty-five thousand, which is already a different
# corpus; the maxima this replaced allowed eight hundred filings, or
# around 1.2 million chunks, from one press of a button. Every benchmark
# in this repository was measured against the 327, and a change of that
# size should be a decision rather than a side effect.
MAX_FILINGS_PER_RUN = 25

# The forms worth asking for, and the only ones accepted.
#
# A bad form is the quietest mistake available here: recent_filings
# matches nothing, the run reports success having done nothing, and the
# only trace is a log line. Restricting the field is cheaper than
# explaining the silence afterwards.
SUPPORTED_FORMS = ("10-K", "10-Q", "8-K")


class CollectRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=MAX_FILINGS_PER_RUN)
    forms: list[str] = Field(default=["10-K", "10-Q"], max_length=8)
    limit: int = Field(default=2, ge=1, le=MAX_FILINGS_PER_RUN)


class ReseedRequest(BaseModel):
    confirm: str = Field(default="", max_length=64)


def _require_known_forms(forms: list[str]) -> tuple[str, ...]:
    """
    Normalise the requested forms, or refuse them.

    Refusing an empty list too: asking for nothing matches nothing, which
    is indistinguishable from a company having filed nothing.
    """
    cleaned = tuple(
        form.strip().upper() for form in forms if form and form.strip()
    )

    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail=(
                "Choose at least one form. Available: "
                + ", ".join(SUPPORTED_FORMS)
                + "."
            ),
        )

    unknown = [form for form in cleaned if form not in SUPPORTED_FORMS]

    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(unknown)} is not a form this fetches. "
                "Available: " + ", ".join(SUPPORTED_FORMS) + "."
            ),
        )

    return cleaned


def _require_sane_run_size(tickers: list[str], *, limit: int) -> int:
    """
    Refuse a run that would fetch more than the corpus can absorb quietly.

    Capped on the product rather than either field, because five companies
    at five filings each is the same work as twenty-five at one, and a
    limit that only looked at one of them would let the other carry the
    whole run.
    """
    total = len(tickers) * limit

    if total > MAX_FILINGS_PER_RUN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"That run would fetch {total} filings; the most in one go "
                f"is {MAX_FILINGS_PER_RUN}. A 10-K is around 1,500 chunks, "
                f"so {total} of them would add roughly "
                f"{total * 1500:,} chunks to a corpus that currently holds "
                "a few hundred. Fewer companies, or fewer filings each."
            ),
        )

    return total


def _require_confirmation(confirm: str) -> None:
    """
    Refuse a reseed that was not typed out in full.

    Not a formality. Accepting "yes", or anything close, would make this a
    click -- and the click destroys the corpus every benchmark in this
    repository was measured against.
    """
    if (confirm or "").strip() != RESEED_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=(
                "Reseeding empties the documents, document_chunks, "
                "financial_metrics and companies tables and refetches live "
                "data, which will not match what was there. The benchmark "
                "corpus and the ground truth built from it do not survive "
                f'it. Type "{RESEED_CONFIRMATION}" to confirm.'
            ),
        )


async def _index_ticker(
    ticker: str,
    *,
    forms: tuple[str, ...],
    limit: int,
    headers: dict,
) -> int:
    """
    Index a company's recent filings, and report how many were stored.

    Takes the direct route rather than S3, so this works on a deployment
    with no bucket -- which is the one the button is being pressed on.
    """
    from backend.ingestion.edgar import cik_for_ticker, http_fetch, recent_filings
    from backend.ingestion.queue_worker import _mark_ready, _persist_document
    from backend.ingestion.indexing_service import embed_document

    cik = await cik_for_ticker(ticker, fetch=http_fetch, headers=headers)

    filings = await recent_filings(
        cik,
        fetch=http_fetch,
        forms=forms,
        ticker=ticker,
        limit=limit,
        headers=headers,
    )

    stored = 0

    for filing in filings:
        try:
            document = await _prepare_edgar_filing(
                {
                    "cik": filing.cik,
                    "accession": filing.accession,
                    "form": filing.form,
                    "filing_date": filing.filing_date,
                    "primary_document": filing.primary_document,
                    "ticker": filing.ticker,
                },
                fetch=http_fetch,
                headers=headers,
            )

            document_id = await _persist_document(document)
        except SkippedObject:
            # Already held. Not a failure -- it is the answer.
            continue
        except HTTPException as exc:
            logger.warning(
                "[INGEST] %s %s skipped: %s", ticker, filing.accession, exc.detail
            )
            continue

        result = await embed_document(document_id)

        if result.get("success"):
            await _mark_ready(document_id)
            stored += 1
        else:
            logger.error(
                "[INGEST] %s failed to index: %s", filing.accession, result.get("error")
            )

    return stored


async def _collect_many(
    tickers: list[str],
    *,
    forms: tuple[str, ...],
    limit: int,
    index_one,
    headers: dict | None = None,
) -> dict:
    """
    Run one ticker after another, and keep going when one fails.

    Twenty tickers and one typo should leave nineteen collected. Which
    failed is reported rather than logged, because whoever pressed the
    button is the person who can fix a typo.
    """
    indexed = 0
    failed: list[str] = []

    for ticker in tickers:
        try:
            indexed += await index_one(
                ticker, forms=forms, limit=limit, headers=headers or {}
            )
        except Exception:
            logger.exception("[INGEST] %s failed; continuing", ticker)
            failed.append(ticker)

    return {"indexed": indexed, "failed": failed}


@router.post("/edgar/collect", status_code=202)
async def collect_filings_job(
    request: CollectRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """
    Index recent filings for several companies at once.

    Runs in the background: each filing is a rate-limited download and a
    round of embedding calls, and a browser should not hold a request open
    for that. Watch the document list to see them arrive.
    """
    # Input before configuration. A ticker that does not exist is the
    # caller's mistake and is wrong on every deployment; a missing
    # User-Agent is the deployment's, and reporting it first would tell
    # someone to go and set an environment variable when the actual
    # problem is a typo in front of them.
    #
    # Every ticker is checked before any is fetched, so a typo in the
    # tenth does not leave nine already collected and no clear reason why
    # the run stopped.
    known = await _known_tickers(session)
    tickers = [_require_known_ticker(t, known) for t in request.tickers]

    forms = _require_known_forms(request.forms)

    total = _require_sane_run_size(tickers, limit=request.limit)

    headers = _edgar_headers(settings.SEC_USER_AGENT)

    async def run() -> None:
        summary = await _collect_many(
            tickers,
            forms=forms,
            limit=request.limit,
            index_one=_index_ticker,
            headers=headers,
        )

        logger.info(
            "[INGEST] EDGAR collection finished: %s indexed, failed=%s",
            summary["indexed"],
            summary["failed"] or "none",
        )

    background.add_task(run)

    return {
        "tickers": tickers,
        "forms": list(forms),
        "message": (
            f"Collecting up to {total} filing(s) across "
            f"{len(tickers)} compan{'y' if len(tickers) == 1 else 'ies'}. "
            "A 10-K is around 1,500 chunks and takes a few seconds to "
            "parse plus an embedding round, so this runs in the "
            "background — refresh the document list to watch them arrive."
        ),
    }


@router.post("/seed", status_code=202)
async def reseed_job(request: ReseedRequest, background: BackgroundTasks):
    """
    Rebuild the corpus from Alpha Vantage and Finnhub.

    Destructive, and not undoable from here: the tables are emptied and
    refilled with data fetched now, which is not the data that was there.
    Restoring the previous corpus means seeds/snapshot.py, from a
    snapshot taken before this ran.

    The TRUNCATE and the inserts share one transaction, so a run that
    fails partway leaves the old corpus intact. A run that succeeds
    replaces it.
    """
    _require_confirmation(request.confirm)

    async def run() -> None:
        from seeds.seed_data import seed

        logger.warning("[INGEST] Reseeding the corpus from live sources")

        try:
            await seed()
            logger.warning("[INGEST] Reseed complete")
        except Exception:
            logger.exception("[INGEST] Reseed failed; the previous corpus stands")

    background.add_task(run)

    return {
        "message": (
            "Reseeding from Alpha Vantage and Finnhub. The previous corpus "
            "is gone once this succeeds. Regenerate the SQL ground truth "
            "afterwards, and take a fresh snapshot before benchmarking."
        ),
    }

# ── The companies this corpus covers ────────────────────────
#
# Fifty, seeded from seeds/companies.csv. Fetching filings for anything
# else produces documents that resolve to no company, cannot be filtered
# by one, and answer questions about a company the benchmark holds no
# metrics for.
#
# Read from the table rather than the file, because the table is what
# company_id resolves against -- a ticker present in the file but missing
# from the table would index with no company attached. A test asserts the
# two have not drifted.


async def _known_tickers(session: AsyncSession) -> set[str]:
    rows = await session.execute(select(Company.ticker))

    return {t.strip().upper() for (t,) in rows if t}


def _require_known_ticker(ticker: str, known: set[str]) -> str:
    """
    Normalise a ticker, or refuse it.

    Enforced here rather than only in the dropdown, because the dropdown
    is a convenience and anyone can post around it.
    """
    cleaned = (ticker or "").strip().upper()

    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail="Name a company. Only the companies this corpus covers can be fetched.",
        )

    if cleaned not in known:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{cleaned} is not one of the companies this corpus covers. "
                "The list is the fifty in seeds/companies.csv; adding one "
                "means seeding it, so that its financial metrics exist too."
            ),
        )

    return cleaned


@router.get("/companies")
async def list_companies(session: AsyncSession = Depends(get_db)):
    """The companies whose filings can be fetched."""
    rows = await session.execute(
        select(Company.ticker, Company.name).order_by(Company.ticker)
    )

    return {
        "companies": [
            {"ticker": ticker, "name": name} for ticker, name in rows
        ]
    }
