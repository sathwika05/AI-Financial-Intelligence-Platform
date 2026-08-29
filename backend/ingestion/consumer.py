"""
Draining the ingestion queue.

The contract with SQS is the whole of this module, and it is asymmetric:
deleting a message whose work failed loses a document with no trace, while
failing to delete one whose work succeeded reprocesses it on every poll
until retention expires. So a message is deleted only when every object it
references has been handled.

The one exception is a message this code cannot parse. It will not parse
on the tenth attempt either, and retrying it burns the redrive count and
delays everything behind it, so it is dropped with a loud log.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

from backend.ingestion.events import MalformedEvent, ObjectRef, parse_s3_event


logger = logging.getLogger(__name__)


class QueueMessage(Protocol):
    receipt_handle: str
    body: str


class Queue(Protocol):
    async def receive(self, max_messages: int = 10) -> list[QueueMessage]: ...

    async def delete(self, receipt_handle: str) -> None: ...


Handler = Callable[[ObjectRef], Awaitable[None]]


async def consume_once(
    *,
    queue: Queue,
    handle: Handler,
    max_messages: int = 10,
) -> int:
    """
    Poll once and process what comes back.

    Returns the number of messages deleted, which is the number fully
    handled -- not the number received.
    """
    messages = await queue.receive(max_messages=max_messages)

    if not messages:
        return 0

    deleted = 0

    for message in messages:
        try:
            refs = parse_s3_event(message.body)
        except MalformedEvent:
            logger.exception(
                "[INGEST] Dropping an unparseable message; it will not "
                "parse on a retry either",
            )
            await queue.delete(message.receipt_handle)
            deleted += 1
            continue

        # No refs means S3's test event: handled, nothing to do.
        every_ref_handled = True

        for ref in refs:
            try:
                await handle(ref)
            except Exception:
                # One object's failure keeps the whole message, because the
                # message is the unit SQS redelivers.
                logger.exception(
                    "[INGEST] Failed on s3://%s/%s; leaving the message "
                    "for redelivery",
                    ref.bucket,
                    ref.key,
                )
                every_ref_handled = False

        if every_ref_handled:
            await queue.delete(message.receipt_handle)
            deleted += 1

    return deleted
