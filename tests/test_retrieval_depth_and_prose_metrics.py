"""
Two changes aimed at the one stable finding and one half-finished fix.

RETRIEVAL DEPTH. With the retrieved contexts now recorded, run a4f605f9
showed retrieval returning a median of about half the evidence its own
goldens cite — mixed_002 got 2 of its 17. CHUNKS_PER_COMPANY is the cap
that binds: the reranker selects from what this returns, which is why
raising EVIDENCE_PER_COMPANY changed nothing.

Unlike context_recall — which moved 0.289 on average between two identical
runs — coverage is a count of how many cited contexts appear in the
retrieved set, so a change in it is real rather than judge variance.

PROSE METRICS. Removing key_metrics from the report schema did not stop the
model emitting the numbers; it moved them into the summary text at full
float precision ("Its P/E ratio is 33.20827"). Every one is an entity
context_entity_recall will look for in a news article and never find.
"""
from backend.nodes.analysis_node import SYSTEM_PROMPT
from backend.retrieval.vector_search import CHUNKS_PER_COMPANY


class TestRetrievalIsDeepEnoughForTheGoldens:
    def test_a_three_company_cohort_can_reach_its_cited_evidence(self):
        """
        The sentiment goldens cite 7-15 contexts across three companies.
        At three per company the ceiling was nine.
        """
        assert CHUNKS_PER_COMPANY * 3 >= 15

    def test_it_stays_bounded(self):
        """
        Every chunk retrieved reaches the analysis prompt, and that node is
        already the slowest stage. Depth is not free.
        """
        assert CHUNKS_PER_COMPANY <= 6


class TestTheReportDoesNotReciteMetrics:
    def test_the_prompt_does_not_ask_for_financial_values_in_prose(self):
        assert "Use actual financial values" not in SYSTEM_PROMPT

    def test_it_says_where_the_numbers_come_from_instead(self):
        assert "key_metrics" in SYSTEM_PROMPT or "attached" in SYSTEM_PROMPT.lower()

    def test_it_still_demands_evidence(self):
        """Trimming what is written must not touch the grounded part."""
        assert "citation_id" in SYSTEM_PROMPT
        assert "noncommittal" in SYSTEM_PROMPT.lower()


class TestTheTwoCapsAgree:
    """
    Retrieval depth and the reranker's evidence budget are sequential caps.
    Whichever is smaller decides how much evidence reaches the answer, so
    raising one alone is invisible — which happened twice, in opposite
    directions: run 97a171a1 raised the budget against a pool of nine, and
    run 8a6c17f8 raised the pool to 25 while the budget still selected 15.
    """

    def test_the_reranker_can_use_what_retrieval_returns(self):
        from backend.nodes.reranker_node import EVIDENCE_PER_COMPANY
        from backend.retrieval.vector_search import CHUNKS_PER_COMPANY

        assert EVIDENCE_PER_COMPANY >= CHUNKS_PER_COMPANY
