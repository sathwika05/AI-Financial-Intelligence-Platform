"""
Two levers on the RAGAS metrics that gate 30 questions.

response_relevancy is computed from the PIPELINE's answer, not from the
reference answer, and RAGAS multiplies it by zero when its judge calls that
answer noncommittal. Eight questions in run a88968e8 scored exactly 0.0
that way — including sentiment_003, 006, 009 and 024 — while their
faithfulness and precision were fine. The authoring guide already forbids
hedging in reference answers; nothing imposed it on the pipeline that has
to match them.

The companion attempt — raising the reranker's evidence budget to widen
the window — is not here because it did nothing: see the note on
EVIDENCE_PER_COMPANY.
"""
from backend.nodes.analysis_node import SYSTEM_PROMPT


class TestTheAnswerStatesItsConclusions:
    def test_the_prompt_forbids_hedging(self):
        assert "noncommittal" in SYSTEM_PROMPT.lower()

    def test_it_shows_what_hedging_looks_like(self):
        """A rule without an example is a rule that gets read past."""
        assert "may suggest" in SYSTEM_PROMPT

    def test_it_does_not_licence_overclaiming(self):
        """
        Telling a model to sound certain is how it starts inventing. The
        instruction has to say plainly-stated AND grounded, not confident.
        """
        assert "invent" in SYSTEM_PROMPT.lower()
