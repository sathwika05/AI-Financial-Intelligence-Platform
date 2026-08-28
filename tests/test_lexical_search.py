"""
Corpus-wide BM25, which is a different thing from the BM25 already here.

bm25_rerank in vector_search reorders the rows pgvector returned, so it can
only ever permute the dense result — it cannot surface a chunk the vector
search missed. RRF needs two lists that genuinely disagree, so this one
ranks the whole corpus independently.

At 327 chunks and 70 kB the index builds in milliseconds, which is what
makes an in-memory approach reasonable here and would not at 100x the size.
"""
from dataclasses import dataclass

import pytest

from backend.retrieval import lexical_search


@dataclass(frozen=True)
class _Chunk:
    """Stands in for the row shape the dense query returns."""

    id: int
    content: str
    company_id: int = 1
    doc_type: str = "news"
    source: str = "alphavantage"
    chunk_index: int = 0


CORPUS = [
    _Chunk(1, "NVIDIA data centre revenue beat estimates", company_id=10),
    _Chunk(2, "Intel foundry losses widened this quarter", company_id=20),
    _Chunk(3, "AMD gained server share against Intel", company_id=30),
    _Chunk(4, "Broadcom guidance mentions AI networking", company_id=40,
           doc_type="filing"),
]


async def _loader():
    return list(CORPUS)


class TestRanking:
    async def test_it_ranks_the_chunk_that_matches_the_keywords(self):
        rows = await lexical_search.search_chunks_lexical(
            keywords=["foundry", "losses"],
            top_k=2,
            loader=_loader,
        )

        assert rows[0].id == 2

    async def test_it_can_return_a_chunk_no_vector_search_supplied(self):
        """The whole reason this exists: an independent candidate source."""
        rows = await lexical_search.search_chunks_lexical(
            keywords=["Broadcom", "networking"],
            top_k=1,
            loader=_loader,
        )

        assert rows[0].id == 4

    async def test_it_returns_at_most_top_k(self):
        rows = await lexical_search.search_chunks_lexical(
            keywords=["Intel"],
            top_k=2,
            loader=_loader,
        )

        assert len(rows) == 2

    async def test_no_keywords_returns_nothing_rather_than_a_random_order(self):
        """
        BM25 with no query terms scores every document zero, so returning
        top_k would be an arbitrary slice presented as a ranking. An empty
        lexical list makes RRF degrade to the dense list, which is honest.
        """
        rows = await lexical_search.search_chunks_lexical(
            keywords=[],
            top_k=5,
            loader=_loader,
        )

        assert rows == []


class TestFilters:
    async def test_it_honours_company_ids(self):
        """Must match the dense path, or fusion compares different scopes."""
        rows = await lexical_search.search_chunks_lexical(
            keywords=["Intel"],
            top_k=5,
            filters={"company_ids": [20]},
            loader=_loader,
        )

        assert [row.id for row in rows] == [2]

    async def test_it_honours_doc_type(self):
        rows = await lexical_search.search_chunks_lexical(
            keywords=["AI", "revenue", "Intel"],
            top_k=5,
            filters={"doc_type": "filing"},
            loader=_loader,
        )

        assert all(row.doc_type == "filing" for row in rows)

    async def test_a_filter_matching_nothing_is_empty_not_an_error(self):
        rows = await lexical_search.search_chunks_lexical(
            keywords=["Intel"],
            top_k=5,
            filters={"company_ids": [999]},
            loader=_loader,
        )

        assert rows == []


class TestTheCorpusCache:
    def setup_method(self):
        lexical_search.invalidate_corpus_cache()

    async def test_the_corpus_is_loaded_once_not_per_query(self):
        calls = []

        async def counting_loader():
            calls.append(1)
            return list(CORPUS)

        for _ in range(3):
            await lexical_search.search_chunks_lexical(
                keywords=["Intel"],
                top_k=1,
                loader=counting_loader,
            )

        assert len(calls) == 1

    async def test_invalidating_forces_a_reload(self):
        """Ingest adds chunks; a stale index would never rank them."""
        calls = []

        async def counting_loader():
            calls.append(1)
            return list(CORPUS)

        await lexical_search.search_chunks_lexical(
            keywords=["Intel"], top_k=1, loader=counting_loader,
        )
        lexical_search.invalidate_corpus_cache()
        await lexical_search.search_chunks_lexical(
            keywords=["Intel"], top_k=1, loader=counting_loader,
        )

        assert len(calls) == 2

    async def test_an_empty_corpus_is_empty_not_an_error(self):
        async def empty_loader():
            return []

        rows = await lexical_search.search_chunks_lexical(
            keywords=["Intel"],
            top_k=5,
            loader=empty_loader,
        )

        assert rows == []
