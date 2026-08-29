"""
The whole path, with only AWS faked.

Every other test in this package covers one module against fakes for its
neighbours. That leaves the seams: the key the collector writes has to be
the key the notification carries, which has to be the key the handler can
read, and the metadata hung on the object has to survive all three. A
mismatch anywhere there passes every unit test and moves no documents.

So this wires the real modules together -- collect_filings, the real S3
event shape, consume_once, handle_object -- and fakes only S3 and SQS,
which are the two things a test cannot have.
"""
import json

import pytest


COMPANY_TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

SUBMISSIONS = {
    "cik": "320193",
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-24-000123"],
            "filingDate": ["2024-11-01"],
            "form": ["10-K"],
            "primaryDocument": ["aapl-20240928.htm"],
        }
    },
}

FILING_HTML = (
    b"<html><body><h1>Item 1. Business</h1>"
    b"<p>Apple reported revenue above consensus for the quarter.</p>"
    b"</body></html>"
)

BUCKET = "raw-bucket"


class TestAFilingTravelsTheWholePath:
    @pytest.mark.asyncio
    async def test_an_edgar_filing_reaches_the_corpus(self):
        from backend.ingestion.collector import collect_filings
        from backend.ingestion.consumer import consume_once
        from backend.ingestion.handler import handle_object

        s3 = _FakeS3(BUCKET)

        # 1. Collect. This writes one object and nothing else.
        keys = await collect_filings(
            "AAPL",
            store=s3,
            fetch=_fake_edgar(),
            already_have=_never(),
            forms=("10-K",),
        )

        assert len(keys) == 1

        # The contract between the two modules that nothing else states:
        # the collector chooses the key, and the handler decides from that
        # key alone whether the object is something it can parse. A key
        # that loses its suffix is stored as raw bytes and never read.
        from backend.ingestion.handler import _needs_parsing

        assert _needs_parsing(keys[0]), (
            f"the collector wrote {keys[0]!r}, which the handler will not parse"
        )

        # 2. What the bucket notification would post for that write. Built
        #    from the key the collector actually chose, not a key this test
        #    made up -- that substitution is what would hide a mismatch.
        queue = _FakeQueue([_Message("m1", _notification(BUCKET, keys[0]))])

        persisted: list[dict] = []
        indexed: list[int] = []

        # 3. Drain the queue exactly as the worker does.
        deleted = await consume_once(
            queue=queue,
            handle=lambda ref: handle_object(
                ref,
                store=s3,
                persist=_persister(persisted, document_id=7),
                index=_indexer(indexed),
            ),
        )

        assert deleted == 1
        assert queue.deleted == ["m1"]

        document = persisted[0]

        assert "revenue above consensus" in document["content"]
        assert document["ticker"] == "AAPL"
        assert document["doc_type"] == "10-K"
        assert document["source"] == "sec_edgar"
        assert "000032019324000123" in document["source_url"]
        assert indexed == [7]

    @pytest.mark.asyncio
    async def test_the_key_the_collector_writes_is_the_key_the_worker_reads(self):
        """
        The seam most likely to break silently. S3 URL-encodes the key in
        the notification, so a key the collector wrote plainly comes back
        percent-encoded and must decode to the same string.
        """
        from backend.ingestion.collector import collect_filings
        from backend.ingestion.events import parse_s3_event
        from urllib.parse import quote

        s3 = _FakeS3(BUCKET)

        keys = await collect_filings(
            "AAPL",
            store=s3,
            fetch=_fake_edgar(),
            already_have=_never(),
            forms=("10-K",),
        )

        # Encoded the way S3 encodes it in a notification.
        body = json.dumps(
            {
                "Records": [
                    {
                        "s3": {
                            "bucket": {"name": BUCKET},
                            "object": {"key": quote(keys[0])},
                        }
                    }
                ]
            }
        )

        refs = parse_s3_event(body)

        assert refs[0].key == keys[0]
        assert (refs[0].bucket, refs[0].key) in s3.objects

    @pytest.mark.asyncio
    async def test_a_second_collection_run_moves_nothing(self):
        """
        The scheduled case. Running the collector again over a corpus that
        already holds the filing must not re-download, re-write, or
        re-index it.
        """
        from backend.ingestion.collector import collect_filings

        s3 = _FakeS3(BUCKET)
        downloads: list[str] = []

        held: set[str] = set()

        async def already_have(url: str) -> bool:
            return url in held

        first = await collect_filings(
            "AAPL",
            store=s3,
            fetch=_fake_edgar(downloads),
            already_have=already_have,
            forms=("10-K",),
        )

        assert len(first) == 1

        # The worker stored it, so the corpus now holds its URL.
        held.add(s3.objects[(BUCKET, first[0])][1]["source_url"])
        downloads.clear()

        second = await collect_filings(
            "AAPL",
            store=s3,
            fetch=_fake_edgar(downloads),
            already_have=already_have,
            forms=("10-K",),
        )

        assert second == []
        assert downloads == []


def _notification(bucket: str, key: str) -> str:
    return json.dumps(
        {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "s3": {
                        "bucket": {"name": bucket},
                        "object": {"key": key},
                    },
                }
            ]
        }
    )


def _fake_edgar(downloads: list | None = None):
    async def fetch(url: str, *, headers=None) -> bytes:
        if url.endswith("company_tickers.json"):
            return json.dumps(COMPANY_TICKERS).encode()

        if "submissions" in url:
            return json.dumps(SUBMISSIONS).encode()

        if downloads is not None:
            downloads.append(url)

        return FILING_HTML

    return fetch


def _never():
    async def already_have(_url: str) -> bool:
        return False

    return already_have


def _persister(sink, *, document_id):
    async def persist(document: dict) -> int:
        sink.append(document)
        return document_id

    return persist


def _indexer(sink):
    async def index(document_id: int) -> None:
        sink.append(document_id)

    return index


class _FakeS3:
    """Writes like the collector expects, reads like the handler expects."""

    def __init__(self, bucket: str):
        self.bucket = bucket
        self.objects: dict[tuple[str, str], tuple[bytes, dict]] = {}

    async def put_bytes(self, key, body, *, content_type=None, metadata=None):
        # S3 stores metadata values as strings and drops empty ones.
        stored = {str(k): str(v) for k, v in (metadata or {}).items() if v}
        self.objects[(self.bucket, key)] = (body, stored)

    async def get_object(self, bucket: str, key: str) -> tuple[bytes, dict]:
        return self.objects[(bucket, key)]


class _Message:
    def __init__(self, receipt_handle: str, body: str):
        self.receipt_handle = receipt_handle
        self.body = body


class _FakeQueue:
    def __init__(self, messages):
        self._messages = messages
        self.deleted: list[str] = []

    async def receive(self, max_messages: int = 10):
        messages, self._messages = self._messages, []
        return messages

    async def delete(self, receipt_handle: str) -> None:
        self.deleted.append(receipt_handle)
