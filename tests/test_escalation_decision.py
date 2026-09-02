"""
A report nobody should act on has to say so.

The reviewer already had two exits: approved, or forced_pass after three
retries. Both return a report the console renders identically, so a run
that ended at 0.18 confidence after exhausting its retries looked exactly
like one that ended at 0.91 -- same layout, same ranking, and a number in
the corner that nobody reads as a verdict.

Escalation is the third exit. Below ESCALATION_THRESHOLD the ranking is
withheld -- not hidden by the console, but absent from the response -- the
reader is told in words why, and an administrator gets a row to look at.

WHY THE SERVER WITHHOLDS RATHER THAN THE CONSOLE
    A report the console declines to draw is still a report: it is in the
    JSON, in the network tab, and in anything else that calls the endpoint.
    Withholding it here means there is one answer to "what did the system
    say about this query" rather than one per client.

WHY THE CHECK IS NOT "retry limit reached"
    The architecture sketch says "confidence < 0.30, retry limit reached",
    and that misses the quiet case. Retries only happen on a quality
    failure -- hallucinations, missing evidence, bad citations. A draft
    with none of those and 0.2 confidence never retries, so a condition
    requiring an exhausted retry limit would approve it silently. The
    condition is instead "the reviewer has stopped retrying", which covers
    the forced pass and the quiet approval alike.
"""
import pytest

from backend.nodes.reviewer_node import (
    ESCALATION_THRESHOLD,
    build_final_output,
    decide_escalation,
)


class TestTheThreshold:
    def test_it_is_the_number_the_sketch_names(self):
        assert ESCALATION_THRESHOLD == 0.30


class TestWhenToEscalate:
    def test_low_confidence_and_finished_escalates(self):
        assert decide_escalation(
            overall_confidence=0.18,
            should_retry=False,
        ) is True

    def test_a_forced_pass_at_the_boundary_does_not(self):
        """
        Strictly below. 0.30 exactly is the floor, not a failure of it --
        otherwise the threshold reads differently in the code than it does
        in the message shown to the reader.
        """
        assert decide_escalation(
            overall_confidence=0.30,
            should_retry=False,
        ) is False

    def test_a_confident_report_does_not(self):
        assert decide_escalation(
            overall_confidence=0.86,
            should_retry=False,
        ) is False

    def test_a_pending_retry_does_not_escalate_yet(self):
        """
        Mid-loop the number is not final. Escalating here would file one
        row per attempt for a run that goes on to fix itself, and an
        administrator would open three rows describing one query.
        """
        assert decide_escalation(
            overall_confidence=0.11,
            should_retry=True,
        ) is False

    @pytest.mark.parametrize("missing", [None, ""])
    def test_a_missing_confidence_is_treated_as_zero(self, missing):
        """
        A draft that never set the field is the worst case, not an exempt
        one. `None < 0.30` raises in Python 3, so this would have been a
        500 rather than an escalation.
        """
        assert decide_escalation(
            overall_confidence=missing,
            should_retry=False,
        ) is True


class TestWhatTheReaderIsTold:
    """
    The console renders `review`. Anything the reader must see has to
    arrive inside it.
    """

    def _output(self, confidence: float, decision: str = "forced_pass"):
        return build_final_output(
            draft_report={
                "query_summary": "Rank three semiconductor companies",
                "companies": [
                    {"ticker": "INTC", "confidence": confidence},
                    {"ticker": "NVDA", "confidence": confidence},
                ],
                "overall_confidence": confidence,
            },
            review_result={"decision": decision, "total_flags": 4},
        )

    def test_an_escalated_report_is_flagged(self):
        review = self._output(0.17)["review"]

        assert review["escalated"] is True

    def test_the_ranking_is_withheld(self):
        """
        The point of the feature. A ranking the system does not stand
        behind must not be readable as though it did.
        """
        assert self._output(0.17)["top_companies"] == []

    def test_the_response_says_it_withheld_something(self):
        """
        An empty list is ambiguous -- it also means "nothing matched".
        The reader and the console both need to tell those apart.
        """
        assert self._output(0.17)["withheld"] is True

    def test_a_healthy_report_still_carries_its_ranking(self):
        healthy = self._output(0.88, decision="approved")

        assert [c["ticker"] for c in healthy["top_companies"]] == ["INTC", "NVDA"]
        assert healthy["withheld"] is False

    def test_the_notice_is_a_sentence_not_a_number(self):
        """
        "0.17" in a corner is not a warning. The reader is told what it
        means and what happens next.
        """
        notice = self._output(0.17)["review"]["notice"]

        assert isinstance(notice, str)
        assert len(notice.split()) >= 12

    def test_the_notice_carries_the_actual_confidence(self):
        assert "0.17" in self._output(0.17)["review"]["notice"]

    def test_the_notice_says_a_human_will_look_at_it(self):
        notice = self._output(0.17)["review"]["notice"].lower()

        assert "review" in notice

    def test_the_notice_says_the_answer_is_being_withheld(self):
        """
        Without this the reader sees an empty screen and a confidence
        number, and concludes the corpus has nothing on the question.
        """
        notice = self._output(0.17)["review"]["notice"].lower()

        assert "withheld" in notice or "not shown" in notice

    def test_a_healthy_report_carries_no_notice(self):
        review = self._output(0.88, decision="approved")["review"]

        assert review["escalated"] is False
        assert review["notice"] is None

    def test_the_existing_review_fields_survive(self):
        """
        The console already reads decision, flags and hallucination_rate.
        Escalation adds keys; it must not move any.
        """
        review = self._output(0.17)["review"]

        for key in ("decision", "hallucination_rate", "total_flags", "flags"):
            assert key in review
