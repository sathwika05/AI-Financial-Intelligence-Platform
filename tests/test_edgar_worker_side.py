"""
What the worker does with an EDGAR filing it finds in the bucket.

The collector writes the filing's bytes and hangs its provenance on the
object as S3 metadata. The worker sees nothing else -- not the Filing
object, not the submissions index -- so anything that did not travel on
the object is gone by the time the document is stored.
"""
import pytest


FILING_HTML = (
    b"<html><body><h1>Item 1. Business</h1>"
    b"<p>Apple reported revenue above consensus.</p>"
    b"<table><tr><td>Revenue</td><td>394328</td></tr></table>"
    b"</body></html>"
)

EDGAR_METADATA = {
    "source": "sec_edgar",
    "source_url": (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/aapl-20240928.htm"
    ),
    "ticker": "AAPL",
    "form": "10-K",
    "filing_date": "2024-11-01",
    "title": "AAPL 10-K 2024-11-01",
}

KEY = "sec_edgar/AAPL/0000320193-24-000123.htm"


class TestIndexingAnEdgarFiling:
    @pytest.mark.asyncio
    async def test_the_filing_text_becomes_the_content(self):
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key=KEY),
            store=_FakeStore({("raw", KEY): (FILING_HTML, EDGAR_METADATA)}),
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert "revenue above consensus" in persisted[0]["content"]

    @pytest.mark.asyncio
    async def test_the_document_structure_survives(self):
        """
        Headings and tables are what make a filing answerable. Docling
        recovers both from the HTML; losing them here would leave a wall
        of text with no section a chunk could be attributed to.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key=KEY),
            store=_FakeStore({("raw", KEY): (FILING_HTML, EDGAR_METADATA)}),
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        content = persisted[0]["content"]

        assert "# Item 1. Business" in content
        assert "394328" in content

    @pytest.mark.asyncio
    async def test_the_provenance_travels_from_the_object_metadata(self):
        """
        source_url is the identity the unique constraint enforces. Without
        it every re-collection inserts a second copy of the filing.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key=KEY),
            store=_FakeStore({("raw", KEY): (FILING_HTML, EDGAR_METADATA)}),
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        document = persisted[0]

        assert document["source_url"] == EDGAR_METADATA["source_url"]
        assert document["ticker"] == "AAPL"
        assert document["title"] == "AAPL 10-K 2024-11-01"

    @pytest.mark.asyncio
    async def test_the_form_becomes_the_document_type(self):
        """
        "10-K" says more than "filing", and doc_type is what the corpus is
        filtered by.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key=KEY),
            store=_FakeStore({("raw", KEY): (FILING_HTML, EDGAR_METADATA)}),
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert persisted[0]["doc_type"] == "10-K"

    @pytest.mark.asyncio
    async def test_an_object_with_no_metadata_still_indexes(self):
        """
        A hand-uploaded file has no S3 metadata at all. The key is then
        the only provenance there is, and it has to be enough.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        key = "manual/MSFT/10k-2024.htm"
        persisted = []

        await handle_object(
            ObjectRef(bucket="raw", key=key),
            store=_FakeStore({("raw", key): (FILING_HTML, {})}),
            persist=_persister(persisted, document_id=1),
            index=_indexer([]),
        )

        assert persisted[0]["ticker"] == "MSFT"
        assert persisted[0]["title"] == "10k-2024"


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
    def __init__(self, objects):
        self._objects = objects

    async def get_object(self, bucket: str, key: str):
        return self._objects[(bucket, key)]
