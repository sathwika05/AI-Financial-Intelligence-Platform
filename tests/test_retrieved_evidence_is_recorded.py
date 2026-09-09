"""
An ablation that produces only a number cannot be interpreted.

`retrieved_evidence` has existed since the schema was written and has
never had a writer. That matters now, because the next thing to run is a
comparison between retrieval arms -- RRF on against off, the LLM blend at
0.0 against 0.3 -- and a metric delta on its own does not settle
anything. ndcg moving 0.71 to 0.73 sits inside the measured 0.04 judge
noise floor.

What settles it is being able to name the chunk: "the hybrid arm surfaced
this filing, which dense retrieval ranked fourteenth". That is a row, not
an average, and it is per question -- which is why question_id was added
alongside this writer.

WHAT IS RECORDED
    One row per reranked context per question: which branch it came from,
    where it ranked, its score, and enough of the text to recognise it.
    Written only during benchmark runs, so live traffic pays nothing.

NOT EVERY CHUNK RETRIEVED
    The reranked set, not the raw candidate pool. The raw pool is
    top_k * 4 per question and mostly discarded; what the answer was
    actually built from is the reranked list, and that is the thing an
    arm-to-arm diff should compare.
"""
from __future__ import annotations

import pytest

from backend.evaluation.evidence_recorder import build_evidence_rows


def _record(source_type: str, content: str, score: float, **meta) -> dict:
    return {
        "source_type": source_type,
        "content": content,
        "original_score": score,
        "metadata": meta,
    }


class TestOneRowPerContext:
    def test_every_record_becomes_a_row(self):
        rows = build_evidence_rows(
            question_id="growth_001",
            records=[
                _record("vector", "AI investment accelerated", 0.81),
                _record("sql", "NVDA revenue_growth=0.94", 0.77),
            ],
        )

        assert len(rows) == 2

    def test_rank_position_follows_the_reranked_order(self):
        """
        The order is the finding. A chunk ranked first by one arm and
        fourteenth by another is exactly what the diff is looking for.
        """
        rows = build_evidence_rows(
            question_id="q1",
            records=[
                _record("vector", "first", 0.9),
                _record("vector", "second", 0.8),
                _record("vector", "third", 0.7),
            ],
        )

        assert [row["rank_position"] for row in rows] == [1, 2, 3]

    def test_the_question_is_recorded(self):
        rows = build_evidence_rows(
            question_id="sentiment_004",
            records=[_record("vector", "text", 0.5)],
        )

        assert rows[0]["question_id"] == "sentiment_004"

    def test_the_branch_is_recorded(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[
                _record("vector", "a", 0.5),
                _record("market", "b", 0.5),
            ],
        )

        assert [row["source_type"] for row in rows] == ["vector", "market"]


class TestTheChunkIsIdentifiable:
    def test_a_document_is_named_by_its_source(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[
                _record(
                    "vector", "text", 0.5,
                    source="AAPL-10K-2025.pdf", document_id=12,
                )
            ],
        )

        assert rows[0]["filename"] == "AAPL-10K-2025.pdf"

    def test_it_falls_back_to_the_document_id(self):
        """
        Unnamed is still identifiable. A row that cannot be matched
        across two arms is a row that cannot be diffed.
        """
        rows = build_evidence_rows(
            question_id="q1",
            records=[_record("vector", "text", 0.5, document_id=12,
                             chunk_index=3)],
        )

        assert "12" in rows[0]["filename"]

    def test_a_row_with_no_identity_at_all_still_records(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[_record("market", "NVDA price 141.2", 0.5)],
        )

        assert len(rows) == 1
        assert rows[0]["snippet"]


class TestTheSnippetIsBounded:
    def test_long_content_is_truncated(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[_record("vector", "x" * 5000, 0.5)],
        )

        assert len(rows[0]["snippet"]) <= 1000

    def test_short_content_is_kept_whole(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[_record("vector", "a short chunk", 0.5)],
        )

        assert rows[0]["snippet"] == "a short chunk"


class TestItIsQuietWhenThereIsNothing:
    @pytest.mark.parametrize("records", [[], None])
    def test_no_records_writes_no_rows(self, records):
        assert build_evidence_rows(question_id="q1", records=records) == []

    def test_a_record_with_no_content_is_skipped(self):
        """
        An empty chunk is not evidence, and a row for one would make the
        counts disagree with what the answer was built from.
        """
        rows = build_evidence_rows(
            question_id="q1",
            records=[
                _record("vector", "", 0.5),
                _record("vector", "real", 0.5),
            ],
        )

        assert len(rows) == 1
        assert rows[0]["rank_position"] == 1


class TestTheScoreIsCarried:
    def test_the_rerank_score_wins_when_present(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[{
                "source_type": "vector",
                "content": "t",
                "original_score": 0.4,
                "rerank_score": 0.92,
            }],
        )

        assert rows[0]["relevance_score"] == 0.92

    def test_it_falls_back_to_the_original_score(self):
        rows = build_evidence_rows(
            question_id="q1",
            records=[_record("vector", "t", 0.4)],
        )

        assert rows[0]["relevance_score"] == 0.4
