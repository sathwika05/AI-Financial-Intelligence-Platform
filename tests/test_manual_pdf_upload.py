"""
A PDF uploaded to the raw bucket by hand.

    aws s3 cp apple-10k.pdf s3://raw/manual/AAPL/apple-10k-2024.pdf

From there it is the same path every other document takes: the bucket
notification, the queue, the worker, chunk, embed, pgvector. What differs
is that nothing wrote a JSON body alongside it, so everything the
pipeline needs to know about the document has to come from the key and
from the file itself.
"""
import json
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestReadingMetadataFromTheKey:
    """
    The inverse of object_key. A fetcher puts source and ticker in the JSON
    body; a hand-uploaded PDF has no body, so the key prefix is the only
    place that information can live.
    """

    def test_the_source_and_ticker_come_from_the_prefix(self):
        from backend.ingestion.publisher import metadata_from_key

        meta = metadata_from_key("manual/AAPL/apple-10k-2024.pdf")

        assert meta["source"] == "manual"
        assert meta["ticker"] == "AAPL"
        assert meta["title"] == "apple-10k-2024"

    def test_an_unassigned_document_has_no_ticker(self):
        from backend.ingestion.publisher import metadata_from_key

        assert metadata_from_key("manual/_unassigned/outlook.pdf")["ticker"] is None

    def test_a_key_with_no_prefix_still_yields_a_document(self):
        """
        Someone will drop a file at the top of the bucket. It should index
        as an unattributed document rather than fail.
        """
        from backend.ingestion.publisher import metadata_from_key

        meta = metadata_from_key("apple-10k.pdf")

        assert meta["ticker"] is None
        assert meta["title"] == "apple-10k"

    def test_a_published_key_round_trips(self):
        """
        The two functions describe one layout. If they ever disagree, the
        fetcher's documents lose their ticker on the way back in.
        """
        from backend.ingestion.publisher import metadata_from_key, object_key

        meta = metadata_from_key(
            object_key(source="alpha_vantage", ticker="MSFT", identifier="abc")
        )

        assert meta["source"] == "alpha_vantage"
        assert meta["ticker"] == "MSFT"


class TestHandlingAnUploadedPdf:
    @pytest.mark.asyncio
    async def test_the_filing_text_becomes_the_document_content(self):
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {("raw", "manual/AAPL/10k.pdf"): _fixture("filing_with_text_layer.pdf")}
        )
        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key="manual/AAPL/10k.pdf"),
            store=store,
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert "revenue above consensus" in persisted[0]["content"]

    @pytest.mark.asyncio
    async def test_the_ticker_and_title_come_from_the_key(self):
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {
                ("raw", "manual/AAPL/10k-2024.pdf"): _fixture(
                    "filing_with_text_layer.pdf"
                )
            }
        )
        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key="manual/AAPL/10k-2024.pdf"),
            store=store,
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert persisted[0]["ticker"] == "AAPL"
        assert persisted[0]["title"] == "10k-2024"

    @pytest.mark.asyncio
    async def test_a_scanned_filing_is_indexed_rather_than_skipped(self):
        """
        The reason for Docling. This fixture is a rendered image of a page
        with no text layer; OCR is what makes it a document at all.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {
                ("raw", "manual/AAPL/scan.pdf"): _fixture(
                    "filing_scanned_no_text_layer.pdf"
                )
            }
        )
        persisted, indexed = [], []

        await handle_object(
            ObjectRef(bucket="raw", key="manual/AAPL/scan.pdf"),
            store=store,
            persist=_persister(persisted, document_id=9),
            index=_indexer(indexed),
        )

        assert "revenue above consensus" in persisted[0]["content"].lower()
        assert indexed == [9]

    @pytest.mark.asyncio
    async def test_an_unreadable_pdf_is_skipped_rather_than_retried(self):
        """
        Corrupt bytes will not become readable on the tenth delivery.
        Failing would hold the message until the redrive policy parks it,
        delaying every upload behind it.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import SkippedObject, handle_object

        store = _FakeStore({("raw", "manual/AAPL/broken.pdf"): b"not a pdf"})
        indexed = []

        with pytest.raises(SkippedObject):
            await handle_object(
                ObjectRef(bucket="raw", key="manual/AAPL/broken.pdf"),
                store=store,
                persist=_persister([], document_id=1),
                index=_indexer(indexed),
            )

        assert indexed == []

    @pytest.mark.asyncio
    async def test_a_password_protected_filing_is_skipped(self):
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import SkippedObject, handle_object

        store = _FakeStore(
            {
                ("raw", "manual/AAPL/locked.pdf"): _fixture(
                    "filing_password_protected.pdf"
                )
            }
        )

        with pytest.raises(SkippedObject):
            await handle_object(
                ObjectRef(bucket="raw", key="manual/AAPL/locked.pdf"),
                store=store,
                persist=_persister([], document_id=1),
                index=_indexer([]),
            )

    @pytest.mark.asyncio
    async def test_the_extracted_text_is_normalized_before_it_is_stored(self):
        """
        Normalising after chunking would be too late: the chunk boundaries
        would already have been drawn around the page furniture.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {("raw", "manual/AAPL/10k.pdf"): _fixture("filing_with_text_layer.pdf")}
        )
        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key="manual/AAPL/10k.pdf"),
            store=store,
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert "\n\n\n" not in persisted[0]["content"]

    @pytest.mark.asyncio
    async def test_a_json_object_still_takes_the_original_path(self):
        """The fetcher's path is unchanged; PDFs are an addition to it."""
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {
                ("raw", "alpha_vantage/AAPL/1.json"): json.dumps(
                    {
                        "title": "Apple beats estimates",
                        "content": "Apple reported revenue above consensus.",
                        "ticker": "AAPL",
                    }
                ).encode("utf-8")
            }
        )
        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key="alpha_vantage/AAPL/1.json"),
            store=store,
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert persisted[0]["title"] == "Apple beats estimates"


def _persister(sink, *, document_id):
    async def persist(document: dict) -> int:
        sink.append(document)
        return document_id

    return persist


def _indexer(sink):
    async def index(document_id: int) -> None:
        sink.append(document_id)

    return index


class _FakeStore:
    """Bytes in, bytes out -- what S3 actually returns."""

    def __init__(self, objects: dict[tuple[str, str], bytes]):
        self._objects = objects

    async def get_object(self, bucket: str, key: str) -> tuple[bytes, dict]:
        # A hand-uploaded file carries no S3 metadata: the key is the only
        # provenance there is.
        return self._objects[(bucket, key)], {}

    async def get_json(self, bucket: str, key: str) -> dict:
        return json.loads(self._objects[(bucket, key)].decode("utf-8"))
