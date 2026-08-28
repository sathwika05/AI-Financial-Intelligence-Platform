"""
Reciprocal Rank Fusion.

Combines several ranked lists using only each item's rank. That is the
property this pipeline needs: pgvector returns cosine similarities bounded
in [0, 1] and BM25Plus returns unbounded relevance scores, so the two
cannot be summed, averaged or thresholded against each other. Their ranks
are directly comparable.

    score(d) = sum over lists of 1 / (k + rank(d))

Wraps rather than mutates. The dense list arrives as SQLAlchemy Row
objects, which are immutable and cannot carry an extra attribute, so the
fused score lives on the wrapper and callers unwrap to get their rows back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# Cormack et al. (2009). Large enough that the top few ranks do not swamp
# everything below them; small enough that rank still matters.
DEFAULT_K = 60


@dataclass(frozen=True)
class FusedResult:
    """One item's fused standing across every list it appeared in."""

    item: Any
    score: float

    # Where this item placed in each list that held it, keyed by the list's
    # position in the input. Kept for diagnosis: "the lexical retriever
    # ranked this first and the vector search never returned it" is the
    # kind of thing a low score needs explained.
    ranks: dict[int, int] = field(default_factory=dict)


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[Any]],
    *,
    key: Callable[[Any], Any],
    k: int = DEFAULT_K,
) -> list[FusedResult]:
    """
    Fuse ranked lists into one, best first.

    `key` gives each item its identity, so the same chunk found by two
    retrievers is scored once and returned once. The representative kept is
    the first one seen, which makes the earliest list the source of truth
    for an item's payload.
    """
    scores: dict[Any, float] = {}
    ranks: dict[Any, dict[int, int]] = {}
    representative: dict[Any, Any] = {}

    for list_index, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked, start=1):
            identity = key(item)

            scores[identity] = scores.get(identity, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(identity, {})[list_index] = rank
            representative.setdefault(identity, item)

    fused = [
        FusedResult(
            item=representative[identity],
            score=score,
            ranks=ranks[identity],
        )
        for identity, score in scores.items()
    ]

    fused.sort(key=lambda result: result.score, reverse=True)

    return fused
