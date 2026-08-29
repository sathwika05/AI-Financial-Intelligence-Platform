"""
What happens to one object once the queue points at it.

The chunk -> embed -> store path already exists and is unchanged: this
only gets a raw document from S3 into the documents table so that path has
something to index. Writing that row is the step that was missing, because
until now the only writer to documents was the seeding script.
"""
import pytest


class TestHandlingOneObject:
    @pytest.mark.asyncio
    async def test_a_raw_document_is_stored_then_indexed(self):
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {
                ("raw", "news/AAPL/1.json"): {
                    "title": "Apple beats estimates",
                    "content": "Apple reported revenue above consensus.",
                    "source": "alpha_vantage",
                    "ticker": "AAPL",
                }
            }
        )
        persisted = []
        indexed = []

        await handle_object(
            ObjectRef(bucket="raw", key="news/AAPL/1.json"),
            store=store,
            persist=_persister(persisted, document_id=42),
            index=_indexer(indexed),
        )

        assert persisted[0]["title"] == "Apple beats estimates"
        assert indexed == [42]

    @pytest.mark.asyncio
    async def test_a_document_with_no_content_is_not_indexed(self):
        """
        Chunking empty text produces nothing, and embedding nothing is a
        paid API call that returns nothing. Rejected before either.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import SkippedObject, handle_object

        store = _FakeStore(
            {("raw", "empty.json"): {"title": "Nothing", "content": "   "}}
        )
        indexed = []

        with pytest.raises(SkippedObject):
            await handle_object(
                ObjectRef(bucket="raw", key="empty.json"),
                store=store,
                persist=_persister([], document_id=1),
                index=_indexer(indexed),
            )

        assert indexed == []

    @pytest.mark.asyncio
    async def test_a_failure_to_index_propagates(self):
        """
        The consumer decides whether to delete the message, and it can only
        decide correctly if the failure reaches it.
        """
        from backend.ingestion.events import ObjectRef
        from backend.ingestion.handler import handle_object

        store = _FakeStore(
            {("raw", "a.json"): {"title": "T", "content": "some text"}}
        )

        async def failing_index(_document_id):
            raise RuntimeError("embedding API is down")

        with pytest.raises(RuntimeError):
            await handle_object(
                ObjectRef(bucket="raw", key="a.json"),
                store=store,
                persist=_persister([], document_id=7),
                index=failing_index,
            )


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

    async def get_json(self, bucket: str, key: str) -> dict:
        return self._objects[(bucket, key)]


class TestIndexResultIsNotSilent:
    """
    embed_document reports failure by returning {"success": False}, not by
    raising. Passed to the consumer unchanged, a failed embed would look
    like success and the message would be deleted -- losing the document.
    """

    @pytest.mark.asyncio
    async def test_a_failed_embed_raises(self):
        from backend.ingestion.queue_worker import _raise_on_failed_index

        async def embed(_document_id):
            return {"success": False, "error": "Embedding API failed"}

        with pytest.raises(RuntimeError, match="Embedding API failed"):
            await _raise_on_failed_index(7, embed=embed)

    @pytest.mark.asyncio
    async def test_a_successful_embed_returns_quietly(self):
        from backend.ingestion.queue_worker import _raise_on_failed_index

        async def embed(_document_id):
            return {"success": True, "chunks": 12}

        await _raise_on_failed_index(7, embed=embed)
