"""
The only module that imports boto3.

boto3 is synchronous, and everything calling into it here is async, so
each call is handed to a worker thread. That is what asyncio.to_thread is
for and it keeps the event loop free while S3 or SQS is answering.

Kept behind the Queue and ObjectStore protocols the consumer depends on,
so the consumer is testable without AWS and this file stays the only place
that has to change if the transport ever does.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from backend.config import settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _client(service: str) -> Any:
    """
    One client per service, reused.

    boto3 clients are thread-safe and expensive to build -- constructing
    one per message would spend more time on setup than on the call.
    """
    import boto3

    return boto3.client(service, region_name=settings.AWS_REGION)


@dataclass(frozen=True)
class SqsMessage:
    receipt_handle: str
    body: str


class SqsQueue:
    """The ingestion queue, as the consumer expects it."""

    def __init__(self, queue_url: str | None = None):
        self.queue_url = queue_url or settings.INGESTION_QUEUE_URL

        if not self.queue_url:
            raise ValueError(
                "INGESTION_QUEUE_URL is unset; the AWS ingestion path is "
                "not configured for this deployment."
            )

    async def receive(self, max_messages: int = 10) -> list[SqsMessage]:
        """
        Long-poll for up to max_messages.

        WaitTimeSeconds=20 is long polling: without it an empty queue
        answers immediately and the loop spins, paying for a request per
        iteration and finding nothing.
        """
        response = await asyncio.to_thread(
            _client("sqs").receive_message,
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=min(max_messages, 10),
            WaitTimeSeconds=20,
        )

        return [
            SqsMessage(
                receipt_handle=message["ReceiptHandle"],
                body=message.get("Body", ""),
            )
            for message in response.get("Messages", [])
        ]

    async def delete(self, receipt_handle: str) -> None:
        await asyncio.to_thread(
            _client("sqs").delete_message,
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
        )


class ObjectStore:
    """Raw documents, as the fetcher writes them and the consumer reads them."""

    def __init__(self, bucket: str | None = None):
        self.bucket = bucket or settings.RAW_BUCKET

        if not self.bucket:
            raise ValueError(
                "RAW_BUCKET is unset; the AWS ingestion path is not "
                "configured for this deployment."
            )

    async def put_json(self, key: str, payload: dict) -> None:
        """
        Write one raw document.

        This is what triggers the whole path: the bucket notification turns
        the resulting ObjectCreated into a queue message.
        """
        await asyncio.to_thread(
            _client("s3").put_object,
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info("[INGEST] Wrote s3://%s/%s", self.bucket, key)

    async def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        Write one raw document exactly as it was collected.

        Metadata rides on the object because the worker reads nothing
        else: the filing URL that is its duplicate identity, the form and
        the date are all lost otherwise. S3 requires those values to be
        strings, so they are coerced rather than left to fail at the call.
        """
        await asyncio.to_thread(
            _client("s3").put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
            Metadata={
                str(k): str(v) for k, v in (metadata or {}).items() if v
            },
        )

        logger.info("[INGEST] Wrote s3://%s/%s (%s bytes)", self.bucket, key, len(body))

    async def get_object(self, bucket: str, key: str) -> tuple[bytes, dict]:
        """
        One object's bytes and whatever provenance was stored with it.

        S3 lowercases metadata keys and returns them without the
        x-amz-meta- prefix, so what comes back here is what the collector
        put in.
        """
        response = await asyncio.to_thread(
            _client("s3").get_object,
            Bucket=bucket,
            Key=key,
        )

        body = await asyncio.to_thread(response["Body"].read)

        return body, dict(response.get("Metadata") or {})

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        """
        Read one object back, by the reference the event carried.

        Bytes rather than text, because a PDF is not text and decoding one
        as UTF-8 raises before it can be parsed.
        """
        response = await asyncio.to_thread(
            _client("s3").get_object,
            Bucket=bucket,
            Key=key,
        )

        return await asyncio.to_thread(response["Body"].read)

    async def get_json(self, bucket: str, key: str) -> dict:
        """One raw document, as the fetcher wrote it."""
        return json.loads((await self.get_bytes(bucket, key)).decode("utf-8"))


def aws_ingestion_configured() -> bool:
    """
    Whether this deployment has the AWS path at all.

    Local runs and the portfolio deployment do not: the fetcher writes
    straight to Postgres there, which is the path every benchmark in this
    repo was produced on.
    """
    return bool(settings.RAW_BUCKET and settings.INGESTION_QUEUE_URL)
