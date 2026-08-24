"""
Cache for query and chunk embeddings.

An embedding is a pure function of (text, model), so unlike an answer it
has no freshness question: the vector for a given string never changes
while the model stays the same. Every query is embedded on every run, and
every chunk is re-embedded on every reseed.

Deliberately keyed on the exact text rather than on similarity. The
benchmark contains pairs like growth_market_24 and growth_market_25 —
"the 5 companies with the strongest revenue growth" against "the 10" —
which are 99% textually identical and have different correct answers. A
semantic cache would serve one for the other, and no similarity threshold
separates them, because the distinguishing token is a single digit. This is
the same reason theme_resolver looks membership up rather than inferring it.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from backend.services.redis_service import cache_get, cache_set


logger = logging.getLogger(__name__)


# Thirty days. The entry is only wrong if the model changes behind a stable
# name, and the model is in the key precisely so a switch misses rather than
# returns a vector from the wrong space.
EMBEDDING_CACHE_TTL = 60 * 60 * 24 * 30


def make_embedding_key(text: str, model: str) -> str:
    """A short, exact key for one (text, model) pair.

    Hashed because a chunk can run to hundreds of characters and a Redis key
    should not. The model is part of the digest, not decoration: a vector
    from text-embedding-3-small means nothing to text-embedding-3-large, and
    serving one for the other would corrupt every similarity downstream.
    """
    digest = hashlib.sha256(
        f"{model}\x00{text}".encode()
    ).hexdigest()

    return f"embedding:{digest}"


async def embed_query_cached(
    text: str,
    *,
    embedder: Any,
    model: str,
) -> list[float]:
    """The embedding for `text`, from cache when it is there.

    Redis failing costs latency, never the answer — every cache path falls
    through to the embedder, matching how market_node already treats it.
    """
    key = make_embedding_key(text, model)

    try:
        cached = cache_get(key)
    except Exception:
        logger.warning(
            "[EMBEDDING_CACHE] read failed; embedding directly",
            exc_info=True,
        )
        cached = None

    if cached is not None:
        vector = cached.get("embedding")

        # A stored value that is not a vector must not reach pgvector, which
        # would fail on it far from here with a much worse message.
        if isinstance(vector, list) and vector:
            return vector

        logger.warning(
            "[EMBEDDING_CACHE] ignoring a malformed entry for %s",
            key,
        )

    vector = await embedder.aembed_query(text)

    try:
        cache_set(
            key,
            {"embedding": vector},
            ttl=EMBEDDING_CACHE_TTL,
        )
    except Exception:
        logger.warning(
            "[EMBEDDING_CACHE] write failed; the vector is still returned",
            exc_info=True,
        )

    return vector
