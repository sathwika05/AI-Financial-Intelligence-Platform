"""
How the two flags reshape the retrieval pipeline — and, most importantly,
that with both off nothing changes.

    both off   dense -> bm25_rerank                     (today, untouched)
    rrf        dense + corpus BM25 -> RRF
    ce         dense -> bm25_rerank -> cross-encoder
    both       dense + corpus BM25 -> RRF -> cross-encoder

RRF replaces bm25_rerank rather than stacking on it: once a corpus-wide
lexical list is being fused in, reordering the dense list by the same
signal adds nothing.

These assert the call sequence because the behaviour under test *is* the
sequence. The ranking itself is covered in test_rrf_fusion,
test_lexical_search and test_cross_encoder_rerank against real inputs.
"""
from dataclasses import dataclass

import pytest

from backend.retrieval import cross_encoder, lexical_search, vector_search


@dataclass(frozen=True)
class _Row:
    id: int
    content: str
    company_id: int = 1
    doc_type: str = "news"
    source: str = "av"
    chunk_index: int = 0
    similarity: float = 0.5


DENSE = [_Row(1, "dense one"), _Row(2, "dense two")]
LEXICAL = [_Row(3, "lexical three"), _Row(1, "dense one")]


@pytest.fixture
def calls(monkeypatch):
    """Record which stage ran, without touching the database."""
    log = []

    async def fake_dense(query, top_k=20, filters=None):
        log.append(("dense", top_k))
        return list(DENSE)

    def fake_bm25(rows, keywords, top_k=5):
        log.append(("bm25_rerank", len(rows)))
        return list(rows)[:top_k]

    async def fake_lexical(*, keywords, top_k, filters=None, loader=None):
        log.append(("lexical", top_k))
        return list(LEXICAL)

    def fake_cross_encoder(*, query, rows, top_k, model=None, loader=None):
        log.append(("cross_encoder", len(rows)))
        return list(rows)[:top_k]

    monkeypatch.setattr(
        vector_search, "search_similar_chunks_raw", fake_dense
    )
    monkeypatch.setattr(vector_search, "bm25_rerank", fake_bm25)
    monkeypatch.setattr(
        lexical_search, "search_chunks_lexical", fake_lexical
    )
    monkeypatch.setattr(cross_encoder, "rerank", fake_cross_encoder)

    return log


def _stages(log):
    return [name for name, _ in log]


class TestBothFlagsOff:
    async def test_the_pipeline_is_exactly_what_it_is_today(self, calls):
        """The guarantee: adding these features changed nothing by default."""
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
        )

        assert _stages(calls) == ["dense", "bm25_rerank"]

    async def test_the_corpus_is_never_loaded(self, calls):
        """An unused feature must not cost a corpus scan per query."""
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
        )

        assert "lexical" not in _stages(calls)

    async def test_the_model_is_never_loaded(self, calls):
        """...nor torch, nor a model download."""
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
        )

        assert "cross_encoder" not in _stages(calls)

    async def test_it_still_over_fetches_four_times_top_k(self, calls):
        """The dense pool feeds whatever reranks it; that budget stands."""
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
        )

        assert calls[0] == ("dense", 20)


class TestRrfOnly:
    async def test_it_fuses_dense_with_the_corpus_wide_lexical_list(self, calls):
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"], rrf_enabled=True,
        )

        assert _stages(calls) == ["dense", "lexical"]

    async def test_it_replaces_the_bm25_rerank_rather_than_adding_to_it(
        self, calls
    ):
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"], rrf_enabled=True,
        )

        assert "bm25_rerank" not in _stages(calls)

    async def test_it_returns_chunks_from_both_retrievers(self, calls):
        rows = await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"], rrf_enabled=True,
        )

        assert 3 in [row.id for row in rows]

    async def test_a_chunk_found_by_both_appears_once(self, calls):
        rows = await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"], rrf_enabled=True,
        )

        ids = [row.id for row in rows]

        assert len(ids) == len(set(ids))


class TestCrossEncoderOnly:
    async def test_it_reranks_after_the_existing_bm25_stage(self, calls):
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
            cross_encoder_enabled=True,
        )

        assert _stages(calls) == ["dense", "bm25_rerank", "cross_encoder"]


class TestBothOn:
    async def test_the_cross_encoder_reranks_the_fused_list(self, calls):
        await vector_search.search_similar_chunks(
            query="q", top_k=5, keywords=["intel"],
            rrf_enabled=True, cross_encoder_enabled=True,
        )

        assert _stages(calls) == ["dense", "lexical", "cross_encoder"]


class TestFlagsReachRetrievalFromRunConfig:
    async def test_the_tool_reads_the_flags_off_the_runnable_config(
        self, calls, monkeypatch
    ):
        """
        configurable is how per-run state already reaches every node, the
        same channel llm_runtime uses. The benchmark sets it per run.
        """
        async def fake_filters(query, config):
            return {}

        async def fake_keywords(query, config):
            return ["intel"]

        monkeypatch.setattr(vector_search, "extract_filters", fake_filters)
        monkeypatch.setattr(
            vector_search, "generate_ranking_keywords", fake_keywords
        )

        await vector_search.retrieve_similar.ainvoke(
            {"query": "q", "top_k": 5},
            config={
                "configurable": {
                    "retrieval_flags": {
                        "rrf_enabled": True,
                        "cross_encoder_enabled": True,
                    }
                }
            },
        )

        assert _stages(calls) == ["dense", "lexical", "cross_encoder"]

    async def test_no_flags_in_config_means_todays_behaviour(
        self, calls, monkeypatch
    ):
        async def fake_filters(query, config):
            return {}

        async def fake_keywords(query, config):
            return ["intel"]

        monkeypatch.setattr(vector_search, "extract_filters", fake_filters)
        monkeypatch.setattr(
            vector_search, "generate_ranking_keywords", fake_keywords
        )

        await vector_search.retrieve_similar.ainvoke(
            {"query": "q", "top_k": 5},
            config={"configurable": {}},
        )

        assert _stages(calls) == ["dense", "bm25_rerank"]
