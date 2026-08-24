"""
Embeddings are a pure function of (text, model), so they can be cached
without a freshness question.

Every query is embedded on every run, and every chunk is re-embedded on
every reseed — 327 today. The vector never changes for the same input, so a
miss is the only call that needs to reach the provider.

Deliberately not semantic caching. The benchmark contains pairs like
growth_market_24 and growth_market_25, 99% textually identical — "the 5
companies with the strongest revenue growth" against "the 10" — with
different correct answers. Nothing that matches on similarity can separate
those, so this cache keys on the exact text.
"""
import pytest

from backend.retrieval import embedding_cache


class _Recorder:
    """Stands in for the embedder, counting calls."""

    def __init__(self, vector=None):
        self.calls = []
        self.vector = vector or [0.1, 0.2, 0.3]

    async def aembed_query(self, text):
        self.calls.append(text)
        return self.vector


class TestTheKey:
    def test_it_includes_the_model(self):
        """A vector from one model is meaningless to another."""
        a = embedding_cache.make_embedding_key("hello", "text-embedding-3-small")
        b = embedding_cache.make_embedding_key("hello", "text-embedding-3-large")

        assert a != b

    def test_it_is_a_hash_not_the_text(self):
        """A chunk can be hundreds of characters; a key should not be."""
        key = embedding_cache.make_embedding_key("x" * 5000, "m")

        assert "xxxx" not in key
        assert len(key) < 120

    def test_the_same_text_gives_the_same_key(self):
        assert embedding_cache.make_embedding_key(
            "same", "m"
        ) == embedding_cache.make_embedding_key("same", "m")

    def test_different_text_gives_a_different_key(self):
        assert embedding_cache.make_embedding_key(
            "the 5 companies", "m"
        ) != embedding_cache.make_embedding_key("the 10 companies", "m")


class TestTheCache:
    @pytest.mark.asyncio
    async def test_a_miss_calls_the_embedder_and_stores(self, monkeypatch):
        stored = {}
        monkeypatch.setattr(embedding_cache, "cache_get", lambda k: None)
        monkeypatch.setattr(
            embedding_cache,
            "cache_set",
            lambda k, v, ttl: stored.update({k: v}) or True,
        )
        recorder = _Recorder()

        result = await embedding_cache.embed_query_cached(
            "a question", embedder=recorder, model="m"
        )

        assert result == [0.1, 0.2, 0.3]
        assert recorder.calls == ["a question"]
        assert len(stored) == 1

    @pytest.mark.asyncio
    async def test_a_hit_does_not_call_the_embedder(self, monkeypatch):
        monkeypatch.setattr(
            embedding_cache, "cache_get", lambda k: {"embedding": [9.0, 8.0]}
        )
        monkeypatch.setattr(embedding_cache, "cache_set", lambda k, v, ttl: True)
        recorder = _Recorder()

        result = await embedding_cache.embed_query_cached(
            "a question", embedder=recorder, model="m"
        )

        assert result == [9.0, 8.0]
        assert recorder.calls == []

    @pytest.mark.asyncio
    async def test_redis_being_down_still_returns_an_embedding(self, monkeypatch):
        """
        A cache is an optimisation. Losing it must cost latency, never the
        answer — the market node already treats Redis this way.
        """
        def explode(*args, **kwargs):
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(embedding_cache, "cache_get", explode)
        monkeypatch.setattr(embedding_cache, "cache_set", explode)
        recorder = _Recorder()

        result = await embedding_cache.embed_query_cached(
            "a question", embedder=recorder, model="m"
        )

        assert result == [0.1, 0.2, 0.3]
        assert recorder.calls == ["a question"]

    @pytest.mark.asyncio
    async def test_a_corrupt_entry_is_ignored(self, monkeypatch):
        """A cached value that is not a vector must not reach pgvector."""
        monkeypatch.setattr(
            embedding_cache, "cache_get", lambda k: {"embedding": "not a list"}
        )
        monkeypatch.setattr(embedding_cache, "cache_set", lambda k, v, ttl: True)
        recorder = _Recorder()

        result = await embedding_cache.embed_query_cached(
            "a question", embedder=recorder, model="m"
        )

        assert result == [0.1, 0.2, 0.3]
        assert recorder.calls == ["a question"]
