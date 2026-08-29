"""
The queue consumer: receive, index, delete.

Tested against fakes rather than AWS. What matters is the contract with
the queue, and getting that wrong is expensive in a way a unit test can
catch: deleting a message whose work failed loses a document silently,
and not deleting one whose work succeeded reprocesses it on every poll
until the retention period expires.
"""
import json

import pytest


def _s3_event(bucket: str, key: str) -> str:
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


class TestConsumeOnce:
    @pytest.mark.asyncio
    async def test_a_handled_message_is_deleted(self):
        from backend.ingestion.consumer import consume_once

        queue = _FakeQueue([_Message("m1", _s3_event("raw", "a.json"))])
        handled = []

        await consume_once(
            queue=queue,
            handle=_recorder(handled),
        )

        assert [ref.key for ref in handled] == ["a.json"]
        assert queue.deleted == ["m1"]

    @pytest.mark.asyncio
    async def test_a_failed_message_is_left_on_the_queue(self):
        """
        Deleting it would lose the document silently. Leaving it lets the
        queue redeliver, and the redrive policy eventually parks it in the
        dead-letter queue where someone can look at it.
        """
        from backend.ingestion.consumer import consume_once

        queue = _FakeQueue([_Message("m1", _s3_event("raw", "a.json"))])

        async def explode(_ref):
            raise RuntimeError("embedding API is down")

        await consume_once(queue=queue, handle=explode)

        assert queue.deleted == []

    @pytest.mark.asyncio
    async def test_a_malformed_message_is_deleted_not_retried(self):
        """
        A body this code cannot parse will not parse on the tenth attempt
        either. Retrying it burns the redrive count and delays every
        message behind it; it is dropped with a loud log instead.
        """
        from backend.ingestion.consumer import consume_once

        queue = _FakeQueue([_Message("m1", "{not json")])
        handled = []

        await consume_once(queue=queue, handle=_recorder(handled))

        assert handled == []
        assert queue.deleted == ["m1"]

    @pytest.mark.asyncio
    async def test_the_test_event_is_deleted_without_work(self):
        from backend.ingestion.consumer import consume_once

        body = json.dumps({"Event": "s3:TestEvent", "Bucket": "raw"})
        queue = _FakeQueue([_Message("m1", body)])
        handled = []

        await consume_once(queue=queue, handle=_recorder(handled))

        assert handled == []
        assert queue.deleted == ["m1"]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_the_other_messages(self):
        """A poison message must not stop the batch behind it."""
        from backend.ingestion.consumer import consume_once

        queue = _FakeQueue(
            [
                _Message("m1", _s3_event("raw", "bad.json")),
                _Message("m2", _s3_event("raw", "good.json")),
            ]
        )
        handled = []

        async def selective(ref):
            if ref.key == "bad.json":
                raise RuntimeError("nope")

            handled.append(ref)

        await consume_once(queue=queue, handle=selective)

        assert [ref.key for ref in handled] == ["good.json"]
        assert queue.deleted == ["m2"]

    @pytest.mark.asyncio
    async def test_a_partially_failed_batch_keeps_the_message(self):
        """
        One message can reference several objects. If any of them fails the
        message stays, because deleting it would lose the failed one.
        """
        from backend.ingestion.consumer import consume_once

        body = json.dumps(
            {
                "Records": [
                    {
                        "s3": {
                            "bucket": {"name": "raw"},
                            "object": {"key": k},
                        }
                    }
                    for k in ("ok.json", "bad.json")
                ]
            }
        )

        queue = _FakeQueue([_Message("m1", body)])

        async def selective(ref):
            if ref.key == "bad.json":
                raise RuntimeError("nope")

        await consume_once(queue=queue, handle=selective)

        assert queue.deleted == []

    @pytest.mark.asyncio
    async def test_an_empty_poll_is_not_an_error(self):
        from backend.ingestion.consumer import consume_once

        queue = _FakeQueue([])

        processed = await consume_once(queue=queue, handle=_recorder([]))

        assert processed == 0


def _recorder(sink):
    async def handle(ref):
        sink.append(ref)

    return handle


class _Message:
    def __init__(self, receipt: str, body: str):
        self.receipt_handle = receipt
        self.body = body


class _FakeQueue:
    def __init__(self, messages):
        self._messages = messages
        self.deleted: list[str] = []

    async def receive(self, max_messages: int = 10):
        batch, self._messages = self._messages, []
        return batch

    async def delete(self, receipt_handle: str) -> None:
        self.deleted.append(receipt_handle)
