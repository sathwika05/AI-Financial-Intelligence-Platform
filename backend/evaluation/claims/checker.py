"""
Whether the run's own evidence supports each claim.

The judge sees only what the pipeline actually retrieved for that question
-- document chunks, SQL rows, market rows. Not the corpus, not its own
training. A claim that happens to be true of the world but absent from the
evidence is UNSUPPORTED here, and that is the point: the system is
accountable for what it can show, not for what it can guess.

THE STRICT NUMERIC RULE
    A figure must appear in the evidence, or the arithmetic that produces
    it must be present and stated in the reasoning. Evidence that
    discusses revenue does not support "revenue grew 12%". This is the
    rule the evaluator exists for -- a confident wrong number is the
    failure mode that matters in finance, and semantic-similarity scoring
    waves it straight through.

FAILURE IS NOT SILENT, BUT IT IS NOT FATAL
    Every path that cannot produce a real verdict returns
    INSUFFICIENT_EVIDENCE with the reason attached, rather than raising or
    returning a short list. A missing verdict would shrink the
    denominator, which turns a judge outage into a better-looking support
    rate.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.evaluation.claims.policy import Claim

logger = logging.getLogger(__name__)


LABELS: tuple[str, ...] = (
    "SUPPORTED",
    "UNSUPPORTED",
    "INSUFFICIENT_EVIDENCE",
)

# A judge that takes a prompt and returns its raw text.
Judge = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class ClaimVerdict:
    """One claim's outcome, as decided by the judge."""

    index: int
    label: str
    reasoning: str

    @property
    def is_unsupported(self) -> bool:
        """
        Defined once here because both the rate maths and the dashboard's
        colouring ask the question, and INSUFFICIENT_EVIDENCE is easy to
        fold into the wrong side of it.
        """
        return self.label == "UNSUPPORTED"


_INSTRUCTIONS = """\
You are auditing a financial analyst's answer against the evidence that was \
actually retrieved to produce it.

For each numbered claim, decide one label:

  SUPPORTED             The evidence states the claim, or entails it directly.
  UNSUPPORTED           The evidence contradicts the claim, or is silent on a
                        point the claim asserts as fact.
  INSUFFICIENT_EVIDENCE Nothing relevant to the claim was retrieved at all.

Rules:

- Judge ONLY against the evidence below. Do not use outside knowledge. A
  claim that is true in the world but absent from the evidence is
  UNSUPPORTED, not SUPPORTED.
- Numeric claims are strict. A figure must appear in the evidence, or the
  arithmetic that produces it must be present -- and if you derive it, show
  the calculation in your reasoning. Evidence that merely discusses or
  mentions the quantity does NOT support a specific number.
- UNSUPPORTED means the answer asserted something the evidence does not
  carry. INSUFFICIENT_EVIDENCE means nothing on the topic was retrieved.
  Use the second only when the evidence is genuinely silent on the subject.

Reply with JSON only:

{"verdicts": [{"index": <int>, "label": "<one of the three>",
               "reasoning": "<one sentence>"}]}
"""


def build_prompt(*, claims: list[Claim], evidence: list[str]) -> str:
    """Render the judge call for one question's claims."""
    evidence_block = "\n".join(
        f"[E{position}] {text}"
        for position, text in enumerate(evidence)
    )

    claim_lines = []

    for item in claims:
        # The figures are repeated out of the sentence so the judge is
        # told which numbers carry the strict rule, rather than having to
        # find them itself.
        marker = (
            f"  (NUMERIC — must verify: {', '.join(item.numeric_values)})"
            if item.is_numeric
            else ""
        )
        claim_lines.append(f"[{item.index}] {item.text}{marker}")

    return (
        f"{_INSTRUCTIONS}\n"
        f"EVIDENCE:\n{evidence_block}\n\n"
        f"CLAIMS:\n" + "\n".join(claim_lines) + "\n"
    )


def parse_judge_response(raw: str) -> list[ClaimVerdict]:
    """
    Read the judge's JSON back, refusing anything unrecognisable.

    Raising rather than returning [] on bad output: an empty list is
    indistinguishable from an answer that made no claims, and would record
    a perfect support rate for a broken judge.
    """
    text = (raw or "").strip()

    # Judges add preambles and fences however firmly the prompt forbids it.
    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError(f"No JSON object in judge response: {text[:120]!r}")

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge response was not valid JSON: {exc}") from exc

    verdicts = []

    for entry in payload.get("verdicts", []):
        label = str(entry.get("label", "")).strip().upper()

        if label not in LABELS:
            raise ValueError(f"Unknown claim label from judge: {label!r}")

        verdicts.append(
            ClaimVerdict(
                index=int(entry.get("index", -1)),
                label=label,
                reasoning=str(entry.get("reasoning", "")).strip(),
            )
        )

    if not verdicts:
        raise ValueError("Judge returned no verdicts")

    return verdicts


def _insufficient(claims: list[Claim], reason: str) -> list[ClaimVerdict]:
    return [
        ClaimVerdict(index=item.index, label="INSUFFICIENT_EVIDENCE", reasoning=reason)
        for item in claims
    ]


async def verdicts_for(
    *,
    claims: list[Claim],
    evidence: list[str],
    judge: Judge,
) -> list[ClaimVerdict]:
    """
    One verdict per claim, in claim order.

    Never raises. The audit is additional to the benchmark, so a judge
    outage must not fail a question the benchmark itself scored fine.
    """
    if not claims:
        return []

    if not evidence:
        # Nothing was retrieved, so there is nothing to reason about.
        # Asking anyway spends a call to be told what the caller already
        # knows, and invites the judge to answer from its own knowledge.
        return _insufficient(claims, "No evidence was retrieved for this question.")

    try:
        raw = await judge(build_prompt(claims=claims, evidence=evidence))
        parsed = parse_judge_response(raw)
    except Exception as exc:
        logger.warning("[CLAIMS] Judge failed; recording insufficient: %s", exc)
        return _insufficient(claims, f"Claim judge failed: {exc}")

    by_index = {verdict.index: verdict for verdict in parsed}

    # Rebuilt against the claim list rather than returned as received: a
    # claim the judge skipped has to stay in the denominator.
    return [
        by_index.get(
            item.index,
            ClaimVerdict(
                index=item.index,
                label="INSUFFICIENT_EVIDENCE",
                reasoning="The judge returned no verdict for this claim.",
            ),
        )
        for item in claims
    ]
