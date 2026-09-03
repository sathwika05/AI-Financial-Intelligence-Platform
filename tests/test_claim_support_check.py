"""
Deciding whether the run's own evidence supports a claim.

Three labels, and the middle one carries most of the weight:

    SUPPORTED               the evidence states or entails the claim
    UNSUPPORTED             the evidence contradicts it, or is silent on a
                            point it should have covered
    INSUFFICIENT_EVIDENCE   nothing relevant was retrieved at all

Collapsing the last two would make a retrieval failure indistinguishable
from a fabrication, and those need different fixes: one is an index
problem, the other is a generation problem.

THE STRICT NUMERIC RULE
    "Revenue grew 12%" is not supported by evidence that discusses
    revenue, or that says revenue grew. The figure must appear, or the
    arithmetic that produces it must be present and stated in the
    reasoning. This is the rule the whole evaluator exists for: a
    confident wrong number is the failure mode that matters in finance,
    and it is exactly what a semantic-similarity judge waves through.

The judge is an LLM, so these tests drive it with a stub. What is being
tested is the contract around it: how a response becomes labels, what
happens when the judge misbehaves, and that the strict rule is actually
carried into the prompt.
"""
import pytest

from backend.evaluation.claims.checker import (
    LABELS,
    ClaimVerdict,
    build_prompt,
    parse_judge_response,
    verdicts_for,
)
from backend.evaluation.claims.policy import Claim


def claim(text, index=0, numeric=(), original=None):
    return Claim(
        index=index,
        text=text,
        original=original or text,
        is_numeric=bool(numeric),
        numeric_values=tuple(numeric),
    )


class TestTheLabels:
    def test_there_are_exactly_three(self):
        assert LABELS == (
            "SUPPORTED",
            "UNSUPPORTED",
            "INSUFFICIENT_EVIDENCE",
        )


class TestThePromptCarriesTheRules:
    def test_the_evidence_reaches_the_judge(self):
        prompt = build_prompt(
            claims=[claim("Revenue grew 12%.", numeric=["12%"])],
            evidence=["NVDA revenue rose from $50.0B to $56.0B."],
        )

        assert "56.0B" in prompt

    def test_a_numeric_claim_is_marked_as_one(self):
        prompt = build_prompt(
            claims=[claim("Revenue grew 12%.", numeric=["12%"])],
            evidence=["some evidence"],
        )

        assert "12%" in prompt

    def test_the_strict_arithmetic_rule_is_stated(self):
        """
        The rule cannot live only in a docstring. If it is not in the
        prompt, the judge does not apply it.
        """
        prompt = build_prompt(
            claims=[claim("Revenue grew 12%.", numeric=["12%"])],
            evidence=["evidence"],
        )
        lowered = prompt.lower()

        assert "arithmetic" in lowered or "calculation" in lowered
        assert "discuss" in lowered or "mention" in lowered

    def test_all_three_labels_are_offered(self):
        prompt = build_prompt(
            claims=[claim("Margins improved.")],
            evidence=["evidence"],
        )

        for label in LABELS:
            assert label in prompt

    def test_claims_are_numbered_so_answers_can_be_matched_back(self):
        prompt = build_prompt(
            claims=[
                claim("Margins improved.", index=0),
                claim("Revenue declined.", index=1),
            ],
            evidence=["evidence"],
        )

        assert "0" in prompt and "1" in prompt


class TestReadingTheJudgeBack:
    RESPONSE = """
    {"verdicts": [
      {"index": 0, "label": "SUPPORTED",
       "reasoning": "Evidence states revenue rose from 50.0 to 56.0, which is 12%."},
      {"index": 1, "label": "UNSUPPORTED",
       "reasoning": "No document mentions margins."}
    ]}
    """

    def test_each_verdict_is_returned(self):
        assert len(parse_judge_response(self.RESPONSE)) == 2

    def test_the_label_is_carried(self):
        assert parse_judge_response(self.RESPONSE)[0].label == "SUPPORTED"

    def test_the_reasoning_is_carried(self):
        """
        Stored so a human validating the label can see why the judge said
        it, rather than re-deriving the decision from scratch.
        """
        assert "12%" in parse_judge_response(self.RESPONSE)[0].reasoning

    def test_the_index_ties_the_verdict_to_its_claim(self):
        assert [v.index for v in parse_judge_response(self.RESPONSE)] == [0, 1]

    def test_json_wrapped_in_prose_is_still_read(self):
        """Judges add preambles however firmly the prompt forbids it."""
        wrapped = f"Here are my verdicts:\n```json\n{self.RESPONSE}\n```\nDone."

        assert len(parse_judge_response(wrapped)) == 2

    def test_an_unknown_label_is_refused_rather_than_stored(self):
        """
        A label outside the three would flow into the rates and into the
        agreement maths, where it would be silently miscounted.
        """
        with pytest.raises(ValueError):
            parse_judge_response(
                '{"verdicts": [{"index": 0, "label": "PROBABLY", "reasoning": "x"}]}'
            )

    def test_unparseable_output_raises_rather_than_returning_nothing(self):
        """
        Returning [] would look identical to an answer with no claims, and
        the run would record a perfect support rate for a broken judge.
        """
        with pytest.raises(ValueError):
            parse_judge_response("the judge was unwell today")


class TestVerdictsForAnAnswer:
    """
    The orchestration: claims plus evidence in, one verdict per claim out.
    The judge is stubbed, so this is about the contract rather than the
    model's opinion.
    """

    async def test_every_claim_gets_exactly_one_verdict(self):
        claims = [claim("A.", index=0), claim("B.", index=1)]

        async def judge(_prompt):
            return (
                '{"verdicts": ['
                '{"index": 0, "label": "SUPPORTED", "reasoning": "r"},'
                '{"index": 1, "label": "UNSUPPORTED", "reasoning": "r"}]}'
            )

        verdicts = await verdicts_for(
            claims=claims, evidence=["e"], judge=judge
        )

        assert [v.index for v in verdicts] == [0, 1]

    async def test_no_evidence_means_insufficient_without_calling_the_judge(self):
        """
        Nothing was retrieved, so there is nothing to reason about. Asking
        anyway spends a call to be told what the caller already knows, and
        invites the judge to answer from its own knowledge of the company.
        """
        called = False

        async def judge(_prompt):
            nonlocal called
            called = True
            return "{}"

        verdicts = await verdicts_for(
            claims=[claim("Revenue grew 12%.")],
            evidence=[],
            judge=judge,
        )

        assert called is False
        assert verdicts[0].label == "INSUFFICIENT_EVIDENCE"

    async def test_no_claims_means_no_judge_call(self):
        async def judge(_prompt):
            raise AssertionError("should not be called")

        assert await verdicts_for(
            claims=[], evidence=["e"], judge=judge
        ) == []

    async def test_a_claim_the_judge_skipped_is_not_silently_dropped(self):
        """
        A missing verdict must not shrink the denominator -- that would
        turn a judge failure into a better-looking support rate.
        """
        async def judge(_prompt):
            return '{"verdicts": [{"index": 0, "label": "SUPPORTED", "reasoning": "r"}]}'

        verdicts = await verdicts_for(
            claims=[claim("A.", index=0), claim("B.", index=1)],
            evidence=["e"],
            judge=judge,
        )

        assert len(verdicts) == 2
        assert verdicts[1].label == "INSUFFICIENT_EVIDENCE"
        assert "no verdict" in verdicts[1].reasoning.lower()

    async def test_a_judge_failure_does_not_raise_into_the_benchmark(self):
        """
        The audit is additional. A judge outage must not fail a question
        that the benchmark itself scored fine.
        """
        async def judge(_prompt):
            raise RuntimeError("judge is down")

        verdicts = await verdicts_for(
            claims=[claim("A.")], evidence=["e"], judge=judge
        )

        assert verdicts[0].label == "INSUFFICIENT_EVIDENCE"
        assert "judge is down" in verdicts[0].reasoning


class TestTheVerdictRecord:
    def test_a_verdict_knows_whether_it_is_a_failure(self):
        """
        Used by the rate maths and by the dashboard's colouring, so it is
        defined once here rather than at each call site.
        """
        assert ClaimVerdict(0, "UNSUPPORTED", "r").is_unsupported is True
        assert ClaimVerdict(0, "SUPPORTED", "r").is_unsupported is False
        assert ClaimVerdict(0, "INSUFFICIENT_EVIDENCE", "r").is_unsupported is False
