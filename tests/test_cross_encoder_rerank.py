"""
Cross-encoder reranking, with the model injected.

The model is loaded lazily and sentence_transformers is imported inside the
loader rather than at module scope, so these tests never pull torch into
the process. That is not only a test convenience: an import-time load would
cost every process that touches retrieval, including ones that never rerank.

Fail-open throughout. A reranker is an improvement to an answer the
pipeline can already produce, so a model that will not load must cost
ranking quality and nothing else — the same reasoning as RateLimiter and
llm_guard.
"""
from dataclasses import dataclass

import pytest

from backend.retrieval import cross_encoder


@dataclass(frozen=True)
class _Chunk:
    id: int
    content: str


ROWS = [
    _Chunk(1, "Intel foundry losses widened"),
    _Chunk(2, "NVIDIA data centre revenue beat estimates"),
    _Chunk(3, "AMD gained server share"),
]


class _Model:
    """Scores pairs in a fixed order, and records what it was asked."""

    def __init__(self, scores):
        self.scores = scores
        self.seen = None

    def predict(self, pairs):
        self.seen = list(pairs)
        return self.scores


class _BrokenModel:
    def predict(self, pairs):
        raise RuntimeError("model exploded")


class TestReranking:
    def test_it_orders_rows_by_the_model_score(self):
        model = _Model([0.1, 0.9, 0.5])

        ranked = cross_encoder.rerank(
            query="how is NVIDIA performing",
            rows=ROWS,
            top_k=3,
            model=model,
        )

        assert [row.id for row in ranked] == [2, 3, 1]

    def test_it_returns_at_most_top_k(self):
        model = _Model([0.1, 0.9, 0.5])

        ranked = cross_encoder.rerank(
            query="anything",
            rows=ROWS,
            top_k=2,
            model=model,
        )

        assert len(ranked) == 2

    def test_it_scores_the_query_against_each_chunk(self):
        """A cross-encoder reads the pair; that is what distinguishes it."""
        model = _Model([0.1, 0.9, 0.5])

        cross_encoder.rerank(
            query="how is NVIDIA performing",
            rows=ROWS,
            top_k=3,
            model=model,
        )

        assert model.seen == [
            ("how is NVIDIA performing", "Intel foundry losses widened"),
            ("how is NVIDIA performing",
             "NVIDIA data centre revenue beat estimates"),
            ("how is NVIDIA performing", "AMD gained server share"),
        ]


class TestFailingOpen:
    def test_a_model_that_raises_leaves_the_order_alone(self):
        ranked = cross_encoder.rerank(
            query="anything",
            rows=ROWS,
            top_k=3,
            model=_BrokenModel(),
        )

        assert [row.id for row in ranked] == [1, 2, 3]

    def test_a_model_that_will_not_load_leaves_the_order_alone(self):
        """Nothing installed, no network, wrong architecture — same answer."""
        def refuses():
            raise OSError("no such model")

        ranked = cross_encoder.rerank(
            query="anything",
            rows=ROWS,
            top_k=3,
            loader=refuses,
        )

        assert [row.id for row in ranked] == [1, 2, 3]

    def test_a_broken_model_still_respects_top_k(self):
        ranked = cross_encoder.rerank(
            query="anything",
            rows=ROWS,
            top_k=2,
            model=_BrokenModel(),
        )

        assert len(ranked) == 2

    def test_no_rows_is_empty_not_an_error(self):
        assert cross_encoder.rerank(
            query="anything",
            rows=[],
            top_k=5,
            model=_Model([]),
        ) == []


class TestTheModelCache:
    def setup_method(self):
        cross_encoder.invalidate_model_cache()

    def test_the_model_is_loaded_once_not_per_query(self):
        """Loading a cross-encoder is seconds; per-query would be absurd."""
        calls = []

        def counting_loader():
            calls.append(1)
            return _Model([0.1, 0.9, 0.5])

        for _ in range(3):
            cross_encoder.rerank(
                query="anything",
                rows=ROWS,
                top_k=3,
                loader=counting_loader,
            )

        assert len(calls) == 1

    def test_a_failed_load_is_not_retried_on_every_query(self):
        """Otherwise a missing model costs a failed load per question."""
        calls = []

        def failing_loader():
            calls.append(1)
            raise OSError("no such model")

        for _ in range(3):
            cross_encoder.rerank(
                query="anything",
                rows=ROWS,
                top_k=3,
                loader=failing_loader,
            )

        assert len(calls) == 1
