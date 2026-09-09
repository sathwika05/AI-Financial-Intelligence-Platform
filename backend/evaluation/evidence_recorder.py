"""
Keep what a benchmark answer was actually built from.

`retrieved_evidence` has existed since the schema was written and never
had a writer, which was tolerable while the only question being asked of
a benchmark was "what score did it get". It stops being tolerable the
moment two retrieval arms are compared.

A metric delta does not settle an ablation. ndcg moving from 0.71 to 0.73
sits inside the 0.04 judge noise floor measured on this corpus, so on its
own it means nothing. What settles it is naming the chunk: the hybrid arm
surfaced this filing, and dense retrieval ranked it fourteenth. That is a
row, and it is per question -- hence question_id, added in d3f81c26a5e4.

Scope, deliberately narrow:

    The reranked set, not the raw candidate pool. The pool is top_k * 4
    per question and mostly discarded; the reranked list is what analysis
    saw, so it is what an arm-to-arm diff should compare.

    Benchmark runs only. Nothing here is on the live query path, so a
    demo query pays none of it.
"""
from __future__ import annotations

from typing import Any

# Enough to recognise a chunk in a diff, not enough to duplicate the
# corpus into a second table. The chunks themselves are in
# document_chunks; this is a pointer with a human-readable label.
SNIPPET_LIMIT = 1000


def _identify(record: dict[str, Any]) -> str:
    """
    A label stable enough to match the same chunk across two runs.

    Source name first, because it is what a person recognises in a diff.
    Falls back to the document and chunk index, which is unlovely but
    still joins -- a row that cannot be matched across arms is a row that
    cannot be diffed, which would defeat the point of storing it.
    """
    metadata = record.get("metadata") or {}

    for key in ("source", "filename", "document_name"):
        value = metadata.get(key) or record.get(key)

        if value:
            return str(value)

    document_id = metadata.get("document_id")

    if document_id is not None:
        chunk_index = metadata.get("chunk_index")

        return (
            f"document:{document_id}"
            + (f"#{chunk_index}" if chunk_index is not None else "")
        )

    # Market rows and anything else without document identity. Recorded
    # rather than dropped: "this arm spent four of its eight slots on
    # market data" is itself a finding.
    return str(record.get("source_type") or "unknown")


def _score(record: dict[str, Any]) -> float | None:
    """
    The rerank score if the reranker assigned one, else the retrieval
    score it arrived with.
    """
    for key in ("rerank_score", "score", "original_score"):
        value = record.get(key)

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)

    return None


def build_evidence_rows(
    *,
    question_id: str,
    records: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    One row per reranked context, in the order the reranker put them.

    rank_position counts only rows that are kept, so it always describes
    the list analysis actually received. Numbering the skipped ones would
    make the positions disagree with the answer.
    """
    rows: list[dict[str, Any]] = []

    for record in records or []:
        if not isinstance(record, dict):
            continue

        content = str(record.get("content") or "").strip()

        if not content:
            continue

        rows.append({
            "question_id": question_id,
            "filename": _identify(record),
            "snippet": content[:SNIPPET_LIMIT],
            "relevance_score": _score(record),
            "source_type": record.get("source_type"),
            "rank_position": len(rows) + 1,
        })

    return rows
