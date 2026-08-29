"""
Whether a document is one this corpus already holds.

Two writers reach the documents table -- the seeding script and the queue
worker -- and both have to answer this question the same way. Two
implementations of one identity would silently stop recognising each
other's rows: the seed would skip an article the worker had already
stored under a different shape, or worse, not skip it. So the identity
lives here, in the package both import, and neither defines its own.

Two independent identities, because either alone leaks. A canonical URL
misses the same article syndicated to a second address; a content hash
misses nothing but is only available once the body has been fetched.
"""
from __future__ import annotations

import hashlib
import re

from sqlalchemy import select

from backend.models.db_models import Document


def normalize_content(content: str | None) -> str:
    """
    Collapse a body of text to the form that gets hashed.

    Whitespace differences -- re-wrapping, a stray tab, a trailing newline
    -- are not editorial differences, so they must not produce a second
    copy of the same article. Re-parsing one PDF can re-wrap a line, which
    makes this the difference between recognising a re-upload and storing
    it twice.

    Not the same as normalizing a document for storage, which preserves
    structure because the chunker splits on it. This throws structure away
    on purpose: it is only ever fed to a hash.
    """
    if not content:
        return ""

    return re.sub(r"\s+", " ", content).strip()


def hash_content(content: str | None) -> str | None:
    """
    SHA-256 of the normalised content, or None when there is no content.

    The second duplicate identity, which catches the same article
    republished under a different URL -- common with syndicated newswire
    copy, which is most of this corpus.
    """
    normalized = normalize_content(content)

    if not normalized:
        return None

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def find_duplicate_document(
    db,
    canonical_url: str | None,
    content_hash: str | None,
) -> str | None:
    """
    Why this document is a duplicate, or None if it is new.

    Returns "url" or "content_hash" so the caller can say which identity
    matched.

    Queried against the database rather than an in-process set, because
    the unique constraints live there and a set would only be
    authoritative for one run of one process. Inside a single transaction
    this also sees rows added earlier in the same run, since they are
    flushed on insert -- so an article fetched again under a later ticker
    is recognised without waiting for the commit.
    """
    if canonical_url:
        existing = await db.execute(
            select(Document.id)
            .where(Document.source_url == canonical_url)
            .limit(1)
        )

        if existing.scalar_one_or_none() is not None:
            return "url"

    if content_hash:
        existing = await db.execute(
            select(Document.id)
            .where(Document.content_hash == content_hash)
            .limit(1)
        )

        if existing.scalar_one_or_none() is not None:
            return "content_hash"

    return None
