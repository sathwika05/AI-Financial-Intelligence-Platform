"""
An upload answers before it parses.

Parsing is the slow part -- a 10-K measured at nine minutes -- and it ran
inside the request. Locally that merely felt wrong; behind a load
balancer it fails: an ALB closes a connection idle for 60 seconds, so the
browser is told the upload failed while the work carries on and the
document appears anyway. The worst kind of wrong answer.

So the request now does only what is cheap and certain, and everything
that takes time happens after the response.
"""
import pytest
from fastapi import HTTPException


class TestWhatStaysInTheRequest:
    def test_an_unsupported_extension_is_still_refused_immediately(self):
        """
        Reading a filename costs nothing, so there is no reason to make
        someone wait for a refusal that is already certain.
        """
        from backend.api.ingestion_routes import _reject_unusable_upload

        with pytest.raises(HTTPException) as caught:
            _reject_unusable_upload(filename="notes.xlsx", body=b"anything")

        assert caught.value.status_code == 400
        assert "pdf" in caught.value.detail.lower()

    def test_an_empty_file_is_refused_immediately(self):
        from backend.api.ingestion_routes import _reject_unusable_upload

        with pytest.raises(HTTPException):
            _reject_unusable_upload(filename="empty.pdf", body=b"")

    def test_an_oversized_file_is_refused_immediately(self):
        from backend.api.ingestion_routes import (
            MAX_UPLOAD_BYTES,
            _reject_unusable_upload,
        )

        with pytest.raises(HTTPException) as caught:
            _reject_unusable_upload(
                filename="huge.pdf", body=b"x" * (MAX_UPLOAD_BYTES + 1)
            )

        assert "MB" in caught.value.detail

    def test_a_plausible_file_passes_without_being_parsed(self):
        """
        The check must not open the file. If it parsed anything to decide,
        the slow work would be back inside the request.
        """
        from backend.api.ingestion_routes import _reject_unusable_upload

        # Not a real PDF. Nothing here should notice or care.
        _reject_unusable_upload(filename="filing.pdf", body=b"not really a pdf")


class TestWhatMovesToTheBackground:
    @pytest.mark.asyncio
    async def test_parsing_failure_is_recorded_rather_than_raised(self):
        """
        After the response there is nobody to raise to. A file that cannot
        be read has to leave a trace instead, or it fails in silence.
        """
        from backend.api.ingestion_routes import _ingest_uploaded_file

        recorded = []

        async def record(**kwargs):
            recorded.append(kwargs)

        await _ingest_uploaded_file(
            filename="broken.pdf",
            body=b"not a pdf at all",
            ticker=None,
            record=record,
        )

        assert recorded, "a failed parse left no trace"
        assert recorded[0]["outcome"] in {"unreadable", "empty", "failed"}
        assert recorded[0]["source"] == "upload"
        assert recorded[0]["reference"] == "broken.pdf"

    @pytest.mark.asyncio
    async def test_a_readable_file_is_stored_and_recorded(self):
        from pathlib import Path

        from backend.api.ingestion_routes import _ingest_uploaded_file

        recorded = []
        stored = []

        async def record(**kwargs):
            recorded.append(kwargs)

        async def persist(document):
            stored.append(document)
            return 999

        async def index(document_id):
            return {"success": True, "chunks": 12}

        async def mark_ready(document_id):
            stored.append(("ready", document_id))

        body = (
            Path(__file__).parent / "fixtures" / "filing_with_text_layer.pdf"
        ).read_bytes()

        await _ingest_uploaded_file(
            filename="filing.pdf",
            body=body,
            ticker="AAPL",
            record=record,
            persist=persist,
            index=index,
            mark_ready=mark_ready,
        )

        assert "revenue above consensus" in stored[0]["content"]
        assert ("ready", 999) in stored
        assert recorded[0]["outcome"] == "indexed"
        assert recorded[0]["chunks"] == 12
