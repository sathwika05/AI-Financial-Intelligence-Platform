"""
Reciprocal Rank Fusion, on its own.

RRF combines several ranked lists using only each item's *rank*, never its
score. That is the whole reason it suits this pipeline: pgvector returns
cosine similarities in [0, 1] and BM25 returns unbounded relevance scores,
so the two cannot be added, averaged or compared directly. Ranks can.

score(d) = sum over lists of 1 / (k + rank(d)), rank counted from 1.
"""
import pytest

from backend.retrieval.fusion import reciprocal_rank_fusion


def _ids(fused):
    """RRF wraps rather than mutates: production rows are immutable."""
    return [result.item["id"] for result in fused]


class TestFusing:
    def test_an_item_ranked_high_in_both_lists_beats_one_high_in_only_one(self):
        """The point of fusing: agreement between retrievers wins."""
        dense = [{"id": "a"}, {"id": "b"}]
        lexical = [{"id": "a"}, {"id": "c"}]

        fused = reciprocal_rank_fusion(
            [dense, lexical],
            key=lambda item: item["id"],
        )

        assert _ids(fused)[0] == "a"

    def test_an_item_in_only_one_list_still_appears(self):
        """Fusion must not drop what only one retriever found."""
        dense = [{"id": "a"}]
        lexical = [{"id": "b"}]

        fused = reciprocal_rank_fusion(
            [dense, lexical],
            key=lambda item: item["id"],
        )

        assert sorted(_ids(fused)) == ["a", "b"]

    def test_an_item_in_both_lists_is_returned_once(self):
        """The fused list feeds a prompt; a duplicate would waste a slot."""
        dense = [{"id": "a"}, {"id": "b"}]
        lexical = [{"id": "b"}, {"id": "a"}]

        fused = reciprocal_rank_fusion(
            [dense, lexical],
            key=lambda item: item["id"],
        )

        assert len(fused) == 2
        assert sorted(_ids(fused)) == ["a", "b"]

    def test_one_list_comes_back_in_its_own_order(self):
        """With nothing to fuse against, RRF is order-preserving."""
        only = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        fused = reciprocal_rank_fusion(
            [only],
            key=lambda item: item["id"],
        )

        assert _ids(fused) == ["a", "b", "c"]

    def test_no_lists_at_all_is_empty_not_an_error(self):
        """Retrieval returning nothing is a normal outcome here."""
        assert reciprocal_rank_fusion([], key=lambda item: item["id"]) == []

    def test_empty_lists_are_skipped(self):
        """A lexical miss must not discard the dense list."""
        dense = [{"id": "a"}, {"id": "b"}]

        fused = reciprocal_rank_fusion(
            [dense, []],
            key=lambda item: item["id"],
        )

        assert _ids(fused) == ["a", "b"]


class TestTheKConstant:
    def test_a_smaller_k_widens_the_gap_between_ranks(self):
        """
        k damps the influence of the top ranks. The default of 60 comes
        from Cormack et al.; a small k makes rank 1 dominate, a large k
        flattens the list toward equality.
        """
        ranked = [[{"id": "a"}, {"id": "b"}]]

        def spread(k):
            fused = reciprocal_rank_fusion(
                ranked,
                key=lambda item: item["id"],
                k=k,
            )
            return fused[0].score - fused[1].score

        assert spread(1) > spread(60)

    def test_the_fused_score_is_attached_to_each_item(self):
        """A run that scores badly needs the ranking to be explicable."""
        fused = reciprocal_rank_fusion(
            [[{"id": "a"}]],
            key=lambda item: item["id"],
            k=60,
        )

        assert fused[0].score == pytest.approx(1 / 61)

    def test_the_original_item_is_preserved_not_replaced(self):
        """Downstream reads content, company_id and similarity off these."""
        fused = reciprocal_rank_fusion(
            [[{"id": "a", "content": "NVIDIA beat estimates"}]],
            key=lambda item: item["id"],
        )

        assert fused[0].item["content"] == "NVIDIA beat estimates"
