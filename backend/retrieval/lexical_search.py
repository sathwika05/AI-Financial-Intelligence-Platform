"""
Independent lexical retrieval over the whole chunk corpus.

Distinct from bm25_rerank in vector_search, which reorders what pgvector
already returned and therefore cannot surface anything dense retrieval
missed. RRF needs lists that can disagree, so this ranks every chunk.

In-memory, deliberately. The corpus is 327 chunks and 70 kB of text, so the
index builds in milliseconds and holding it costs nothing. That is a bet on
corpus size rather than a general design: somewhere in the tens of
thousands of chunks this stops being the right answer and the ranking
belongs in Postgres as a tsvector with a GIN index.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from rank_bm25 import BM25Plus
from sqlalchemy import text

from backend.services.postgres_service import engine


logger = logging.getLogger(__name__)

# The whole corpus, loaded once. Ingest must call invalidate_corpus_cache,
# or newly added chunks are never ranked.
_corpus: list[Any] | None = None
_index: BM25Plus | None = None


async def load_corpus() -> list[Any]:
    """Every chunk, in the row shape the dense query returns."""
    sql = text(
        """
        SELECT
            dc.id,
            dc.document_id,
            dc.content,
            dc.chunk_index,
            d.doc_type,
            d.source,
            d.company_id
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE dc.content IS NOT NULL
        """
    )

    async with engine.connect() as conn:
        result = await conn.execute(sql)
        return result.fetchall()


def invalidate_corpus_cache() -> None:
    """Drop the cached corpus and index, so the next query reloads."""
    global _corpus, _index

    _corpus = None
    _index = None


def _tokenize(value: str) -> list[str]:
    return (value or "").lower().split()


async def _ensure_corpus(
    loader: Callable[[], Awaitable[list[Any]]],
) -> tuple[list[Any], BM25Plus | None]:
    global _corpus, _index

    if _corpus is None:
        _corpus = await loader()

        _index = (
            BM25Plus([_tokenize(row.content) for row in _corpus])
            if _corpus
            else None
        )

        logger.info(
            "[LEXICAL_SEARCH] corpus loaded chunks=%s",
            len(_corpus),
        )

    return _corpus, _index


def _matches_filters(row: Any, filters: dict | None) -> bool:
    if not filters:
        return True

    company_ids = filters.get("company_ids")

    if not company_ids and filters.get("company_id"):
        company_ids = [filters["company_id"]]

    if company_ids and row.company_id not in company_ids:
        return False

    if "doc_type" in filters and row.doc_type != filters["doc_type"]:
        return False

    if "source" in filters and row.source != filters["source"]:
        return False

    return True


async def search_chunks_lexical(
    *,
    keywords: list[str],
    top_k: int,
    filters: dict | None = None,
    loader: Callable[[], Awaitable[list[Any]]] | None = None,
) -> list[Any]:
    """
    Rank the corpus by keyword relevance, best first.

    Returns nothing when there are no keywords. BM25 scores every document
    zero against an empty query, so any slice of that would be an arbitrary
    order presented as a ranking — and an empty list makes RRF fall back to
    the dense result, which is the honest degradation.
    """
    if not keywords:
        return []

    corpus, index = await _ensure_corpus(loader or load_corpus)

    if not corpus or index is None:
        return []

    query_tokens = _tokenize(" ".join(keywords))
    scores = index.get_scores(query_tokens)

    ranked = sorted(
        zip(corpus, scores),
        key=lambda pair: pair[1],
        reverse=True,
    )

    selected = [
        row
        for row, _ in ranked
        if _matches_filters(row, filters)
    ][:top_k]

    logger.info(
        "[LEXICAL_SEARCH] keywords=%s corpus=%s returned=%s",
        len(keywords),
        len(corpus),
        len(selected),
    )

    return selected
