"""
Indexing a filing answers before it downloads and parses.

The same reasoning as the upload route, arrived at later: the request did
the download and the parse, so it held a connection open for as long as
they took. EDGAR HTML is fast, which is why this was easy to miss -- but
a filing is a rate-limited download from a third party, and "usually
fast" is not a property a request can rely on.

The outcome moves where the upload's went: the processing log.
"""
import pytest


FIELDS = {
    "cik": "0000320193",
    "accession": "0000320193-24-000123",
    "form": "10-K",
    "filing_date": "2024-11-01",
    "primary_document": "aapl-20240928.htm",
    "ticker": "AAPL",
}

FILING_HTML = (
    b"<html><body><h1>Item 1. Business</h1>"
    b"<p>Apple reported revenue above consensus.</p></body></html>"
)


class TestTheWorkMovesOffTheRequest:
    @pytest.mark.asyncio
    async def test_a_filing_is_downloaded_stored_and_recorded(self):
        from backend.api.ingestion_routes import _ingest_edgar_filing

        recorded, stored = [], []

        async def fetch(_url, *, headers=None):
            return FILING_HTML

        async def record(**kwargs):
            recorded.append(kwargs)

        async def persist(document):
            stored.append(document)
            return 55

        async def index(_document_id):
            return {"success": True, "chunks": 9}

        async def mark_ready(document_id):
            stored.append(("ready", document_id))

        await _ingest_edgar_filing(
            FIELDS, headers={}, fetch=fetch,
            record=record, persist=persist, index=index, mark_ready=mark_ready,
        )

        assert "revenue above consensus" in stored[0]["content"]
        assert ("ready", 55) in stored
        assert recorded[0]["outcome"] == "indexed"
        assert recorded[0]["source"] == "sec_edgar"
        assert recorded[0]["chunks"] == 9

    @pytest.mark.asyncio
    async def test_a_download_failure_is_recorded_not_raised(self):
        """
        Nobody is left to raise to. EDGAR being unreachable has to leave a
        row, or the filing simply never appears and nothing says why.
        """
        from backend.api.ingestion_routes import _ingest_edgar_filing

        recorded = []

        async def fetch(_url, *, headers=None):
            raise RuntimeError("403 from EDGAR")

        async def record(**kwargs):
            recorded.append(kwargs)

        await _ingest_edgar_filing(FIELDS, headers={}, fetch=fetch, record=record)

        assert recorded, "a failed download left no trace"
        assert recorded[0]["outcome"] in {"failed", "unreadable"}
        assert "AAPL" in recorded[0]["reference"]

    @pytest.mark.asyncio
    async def test_a_filing_already_held_is_recorded_as_a_duplicate(self):
        from backend.api.ingestion_routes import _ingest_edgar_filing
        from backend.ingestion.handler import SkippedObject

        recorded = []

        async def fetch(_url, *, headers=None):
            return FILING_HTML

        async def record(**kwargs):
            recorded.append(kwargs)

        async def persist(_document):
            raise SkippedObject("already in the corpus (matched on url).")

        await _ingest_edgar_filing(
            FIELDS, headers={}, fetch=fetch, record=record, persist=persist
        )

        assert recorded[0]["outcome"] == "duplicate"
