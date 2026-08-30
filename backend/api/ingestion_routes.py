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
):
    """List a company's recent filings. Downloads nothing."""
    from backend.ingestion.edgar import http_fetch

    headers = _edgar_headers(settings.SEC_USER_AGENT)

    wanted = tuple(
        part.strip().upper() for part in forms.split(",") if part.strip()
    )

    try:
        return {
            "ticker": ticker.strip().upper(),
            "filings": await _preview(
                ticker,
                forms=wanted or ("10-K",),
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

    rows = await session.execute(
        select(Document, Company.ticker, chunk_counts.c.chunks)
        .outerjoin(Company, Document.company_id == Company.id)
        .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
        .order_by(desc(Document.id))
        .limit(max(1, min(limit, 200)))
    )

    return {
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
