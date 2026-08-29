"""
From an EDGAR filing to an object in the raw bucket.

This is the collection half: find the filing, decide whether the corpus
already has it, download it, and write it to S3. Everything after that is
the path that already exists -- the bucket notification, the queue, the
worker -- and it does not know a document came from EDGAR rather than
from someone's upload.

The duplicate check happens before the download, not after. EDGAR gives
every filing an accession number that is unique for all time, so "do we
have this already" is answerable from the URL alone. Checking afterwards
would still be correct and would still spend the bandwidth, the S3 write,
the queue message and the parse.
"""
import pytest

from backend.ingestion.edgar import Filing


FILING = Filing(
    cik="0000320193",
    accession="0000320193-24-000123",
    form="10-K",
    filing_date="2024-11-01",
    primary_document="aapl-20240928.htm",
    ticker="AAPL",
)

FILING_HTML = b"<html><body><p>Apple reported revenue above consensus.</p></body></html>"


class TestCollectingOneFiling:
    @pytest.mark.asyncio
    async def test_a_new_filing_is_written_to_the_raw_bucket(self):
        from backend.ingestion.collector import collect_filing

        store = _FakeStore()

        key = await collect_filing(
            FILING,
            store=store,
            fetch=_fetch_ok(),
            already_have=_never(),
        )

        assert key in store.written
        assert store.written[key]["body"] == FILING_HTML

    @pytest.mark.asyncio
    async def test_the_key_identifies_the_filing(self):
        """
        Deterministic, so re-collecting the same filing overwrites rather
        than accumulating, and grouped so a prefix listing answers "what
        do we have for AAPL from EDGAR".
        """
        from backend.ingestion.collector import collect_filing

        key = await collect_filing(
            FILING, store=_FakeStore(), fetch=_fetch_ok(), already_have=_never()
        )

        assert key.startswith("sec_edgar/AAPL/")
        assert "0000320193-24-000123" in key
        assert key.endswith(".htm")

    @pytest.mark.asyncio
    async def test_a_filing_already_held_is_not_downloaded(self):
        """
        The point of checking first. A download that is going to be
        discarded still costs bandwidth against a rate-limited public
        archive.
        """
        from backend.ingestion.collector import collect_filing

        store = _FakeStore()
        downloads: list[str] = []

        key = await collect_filing(
            FILING,
            store=store,
            fetch=_fetch_recording(downloads),
            already_have=_always(),
        )

        assert key is None
        assert downloads == []
        assert store.written == {}

    @pytest.mark.asyncio
    async def test_the_filing_url_travels_with_the_object(self):
        """
        source_url is the duplicate identity the database enforces. If it
        does not survive to the worker, every re-collection inserts a
        second copy.
        """
        from backend.ingestion.collector import collect_filing

        store = _FakeStore()

        key = await collect_filing(
            FILING, store=store, fetch=_fetch_ok(), already_have=_never()
        )

        metadata = store.written[key]["metadata"]

        assert metadata["source_url"].startswith("https://www.sec.gov/Archives/")
        assert "000032019324000123" in metadata["source_url"]

    @pytest.mark.asyncio
    async def test_the_form_and_date_travel_with_the_object(self):
        """
        The worker sees only the object. A 10-K that arrives without its
        form or its date is stored as an undated document of no known type.
        """
        from backend.ingestion.collector import collect_filing

        store = _FakeStore()

        key = await collect_filing(
            FILING, store=store, fetch=_fetch_ok(), already_have=_never()
        )

        metadata = store.written[key]["metadata"]

        assert metadata["form"] == "10-K"
        assert metadata["filing_date"] == "2024-11-01"
        assert metadata["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_an_empty_download_is_not_written(self):
        """
        An empty object still fires a notification, still costs a queue
        message, and is skipped at the far end.
        """
        from backend.ingestion.collector import collect_filing

        store = _FakeStore()

        async def empty(_url, *, headers=None):
            return b""

        with pytest.raises(ValueError):
            await collect_filing(
                FILING, store=store, fetch=empty, already_have=_never()
            )

        assert store.written == {}


def _fetch_ok():
    async def fetch(_url, *, headers=None):
        return FILING_HTML

    return fetch


def _fetch_recording(sink):
    async def fetch(url, *, headers=None):
        sink.append(url)
        return FILING_HTML

    return fetch


def _never():
    async def already_have(_url) -> bool:
        return False

    return already_have


def _always():
    async def already_have(_url) -> bool:
        return True

    return already_have


class _FakeStore:
    def __init__(self):
        self.written: dict[str, dict] = {}

    async def put_bytes(self, key, body, *, content_type=None, metadata=None):
        self.written[key] = {
            "body": body,
            "content_type": content_type,
            "metadata": metadata or {},
        }
