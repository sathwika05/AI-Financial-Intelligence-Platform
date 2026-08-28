"""
Cross-encoder reranking of retrieved chunks.

A bi-encoder embeds query and chunk separately and compares the vectors,
which is what pgvector does and why it can be indexed. A cross-encoder
reads the pair together and scores the relationship directly — more
accurate, and impossible to precompute, which is why it runs over a
shortlist rather than the corpus.

Deliberately chunk-level. The MIXED reranker in reranker_node ranks
heterogeneous evidence — serialized SQL rows and market-data strings
alongside document text — and a model trained on (query, passage) pairs
would score `{"ticker": "NVDA", "pe_ratio": 33.2}` as noise. This stays
where the candidates are prose.

sentence_transformers is imported inside the loader, not at module scope,
so a process that never reranks never pays for torch.
"""
from __future__ import annotations

import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)

# Small, CPU-friendly, and the standard baseline for passage reranking.
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model: Any = None

# Distinct from "not loaded yet". A load that failed must not be retried on
# every question: the failure is a missing model or a broken install, and
# neither fixes itself between two queries a few seconds apart.
_load_failed = False


def load_model() -> Any:
    """Build the cross-encoder. Imports torch, so call it at most once."""
    from sentence_transformers import CrossEncoder

    logger.info("[CROSS_ENCODER] loading model=%s", MODEL_NAME)

    return CrossEncoder(MODEL_NAME)


def invalidate_model_cache() -> None:
    """Drop the cached model, and any memory of a failed load."""
    global _model, _load_failed

    _model = None
    _load_failed = False


def _get_model(loader: Callable[[], Any]) -> Any | None:
    global _model, _load_failed

    if _model is not None:
        return _model

    if _load_failed:
        return None

    try:
        _model = loader()
    except Exception:
        _load_failed = True

        logger.warning(
            "[CROSS_ENCODER] model unavailable; "
            "ranking is left as retrieved",
            exc_info=True,
        )

        return None

    return _model


def rerank(
    *,
    query: str,
    rows: list[Any],
    top_k: int,
    model: Any = None,
    loader: Callable[[], Any] | None = None,
) -> list[Any]:
    """
    Reorder rows by cross-encoder relevance, best first.

    Fails open: if the model is missing or scoring raises, the rows come
    back in the order they arrived, trimmed to top_k. A reranker improves
    an answer the pipeline can already produce, so its failure must cost
    ranking quality and nothing else.
    """
    if not rows:
        return []

    scorer = model if model is not None else _get_model(
        loader or load_model
    )

    if scorer is None:
        return rows[:top_k]

    try:
        pairs = [(query, row.content) for row in rows]
        scores = scorer.predict(pairs)
    except Exception:
        logger.warning(
            "[CROSS_ENCODER] scoring failed; "
            "ranking is left as retrieved",
            exc_info=True,
        )

        return rows[:top_k]

    ranked = sorted(
        zip(rows, scores),
        key=lambda pair: pair[1],
        reverse=True,
    )

    logger.info(
        "[CROSS_ENCODER] scored=%s returned=%s",
        len(rows),
        min(top_k, len(ranked)),
    )

    return [row for row, _ in ranked[:top_k]]
