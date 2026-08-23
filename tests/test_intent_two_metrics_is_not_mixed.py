"""
Two structured metrics in one question is not MIXED.

MIXED means the answer needs documents as well as metrics. A question that
filters on one number and ranks on another is still pure SQL.

growth_cheap_30 — "Among companies trading below a P/E ratio of 30, which
five have the strongest revenue growth?" — classified as MIXED in run
a88968e8. It was the only intent failure in 100 questions, and it cost the
tool evaluator too: the pipeline ran planner, sql AND vector, where the
question needs no documents at all. Overall 0.5375 against a set mean of
0.952.

The prompt already says MIXED requires document context. What it lacked was
a case showing that two metrics alone do not qualify — while carrying the
example "Low Price-to-Earnings companies with a strong growth narrative",
whose surface form is nearly identical and which IS mixed, because a
narrative lives in documents.
"""
from backend.nodes.intent_node import INTENT_SYSTEM_PROMPT


class TestTwoMetricsStaysSingleIntent:
    def test_it_says_two_metrics_alone_are_not_mixed(self):
        assert "two structured metrics" in INTENT_SYSTEM_PROMPT.lower()

    def test_it_carries_the_question_that_was_misrouted(self):
        assert "below a P/E ratio of 30" in INTENT_SYSTEM_PROMPT

    def test_mixed_still_requires_document_context(self):
        """The fix must not make MIXED unreachable."""
        assert "document context" in INTENT_SYSTEM_PROMPT

    def test_the_narrative_example_survives(self):
        """
        It is the near-miss that makes the distinction legible: a growth
        NARRATIVE is documents, revenue growth is a column.
        """
        assert "growth narrative" in INTENT_SYSTEM_PROMPT
