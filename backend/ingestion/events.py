"""
Reading S3 event notifications off the ingestion queue.

Terraform wires s3:ObjectCreated:* on the raw bucket -- S3 is the Simple
Storage Service, where the documents themselves live -- to the ingestion
queue, so every message here is S3's notification envelope rather than
anything this codebase wrote. Its shape is S3's to define, which is why
the odd cases below are handled explicitly instead of assumed away.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import unquote_plus


logger = logging.getLogger(__name__)


class MalformedEvent(Exception):
    """The message body was not an S3 notification."""


@dataclass(frozen=True)
class ObjectRef:
    """One object a notification points at."""

    bucket: str
    key: str


def parse_s3_event(body: str) -> list[ObjectRef]:
    """
    Every object referenced by one queue message.

    Returns an empty list for S3's own test event, which it posts once when
    a bucket notification is created. It carries no Records, and treating
    that as a failure would send the very first message to the dead-letter
    queue.

    Raises MalformedEvent on anything unparseable, rather than returning
    nothing: an empty list means "handled, delete it", and a body this code
    does not understand has not been handled.
    """
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise MalformedEvent(f"Body is not JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MalformedEvent("Body is not a JSON object.")

    if payload.get("Event") == "s3:TestEvent":
        logger.info("[INGEST] Ignoring the S3 test event")
        return []

    records = payload.get("Records")

    if records is None:
        # Not a notification at all, and not the test event either.
        raise MalformedEvent("Body has no Records.")

    if not isinstance(records, list):
        raise MalformedEvent("Records is not a list.")

    refs: list[ObjectRef] = []

    for record in records:
        s3 = (record or {}).get("s3") or {}
        bucket = (s3.get("bucket") or {}).get("name")
        key = (s3.get("object") or {}).get("key")

        if not bucket or not key:
            # One odd record must not discard the rest of the batch.
            logger.warning(
                "[INGEST] Skipping a record with no bucket or key: %s",
                record,
            )
            continue

        # S3 URL-encodes the key: a space arrives as "+", a slash as %2F.
        # Fetching the raw form 404s on every key with a space in it.
        refs.append(ObjectRef(bucket=bucket, key=unquote_plus(key)))

    return refs
