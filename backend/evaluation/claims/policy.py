"""
What counts as a factual claim.

An LLM splits an answer into candidate assertions, because prose does not
decompose deterministically. Everything after that split is policy, and it
lives here rather than in the prompt so that it can be tested, argued with,
and changed without re-running a judge.

Three rules, in the order they are applied to each candidate:

    speculation      dropped, and counted
    intensifiers     stripped from the text that gets checked
    figures          extracted, which turns on the strict numeric check

The counting matters as much as the dropping. An extractor that discards
two thirds of an answer reports a flattering support rate, and the only
defence is publishing the size of the discard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Hedges belonging to the *analyst*, not to anything the filings said.
#
# "NVDA may benefit from AI demand" cannot be falsified by any evidence, so
# scoring it would move the headline rate without informing anyone. But
# "Management expects acceleration" asserts something about the corpus --
# either they said it or they did not -- so reporting verbs are absent from
# this list on purpose. The distinction is between a hedge about the world
# and a report of someone else's expectation.
SPECULATIVE_MARKERS: tuple[str, ...] = (
    r"\bmay\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\bwould\s+likely\b",
    r"\bappears?\b",
    r"\bseems?\b",
    r"\bis\s+likely\s+to\b",
    r"\bwell\s+positioned\b",
    r"\bpotential\s+to\b",
    r"\bpossibly\b",
    r"\bperhaps\b",
)

# Unquantified degree adverbs.
#
# Stripped rather than failed: "margins improved significantly" contains a
# checkable claim and a word the corpus does not define. Failing the whole
# assertion would fill the unsupported rate with disagreements about
# wording rather than about facts. What is checked is "margins improved";
# the adverb survives in `original` so a reader can see the real sentence.
INTENSIFIERS: tuple[str, ...] = (
    "significantly",
    "substantially",
    "dramatically",
    "markedly",
    "considerably",
    "sharply",
    "modestly",
    "slightly",
    "notably",
    "meaningfully",
)

# Sentences whose subject is the evidence rather than a company.
#
# "The available evidence supports the size ranking of NVIDIA" is a
# tautology once scored -- the evidence supports what the evidence
# supports -- and it says nothing about a company. Measured on run
# 22347774, 15 of 130 extracted claims were this shape, 11%, and every one
# landed on SUPPORTED or INSUFFICIENT_EVIDENCE while carrying no financial
# assertion at all.
#
# Anchored at the start of the sentence, deliberately. Keying on the words
# appearing anywhere would swallow "Intel supports a lower valuation
# multiple than NVIDIA", which is a real comparison.
_ABOUT_EVIDENCE = re.compile(
    r"""
    ^\s*
    (?:
        (?:the\s+)?
        (?:available|retrieved|limited|provided|supplied)?\s*
        (?:evidence|context|documents?|filings?|sources?)\b
      | no\s+(?:document|documents|evidence|data|filing|filings)\b
      | there\s+(?:is|are)\s+no\s+(?:evidence|documents?|data)\b
      | nothing\s+(?:in\s+the\s+)?(?:retrieved|evidence|documents?)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# A figure the claim asserts: percentage, currency amount, or bare decimal.
#
# Ordered longest-form-first so "$2.9" is not read as a bare "2.9", and
# anchored so a ticker or a year inside a word is not swept up.
_NUMERIC = re.compile(
    r"""
    (?<![\w.])
    (?:
        \$\s?\d+(?:[.,]\d+)*        # $2.9, $1,200
      | \d+(?:[.,]\d+)*\s?%         # 12%, 8.5 %
      | \d+\.\d+                    # 33.2
    )
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Claim:
    """One checkable assertion, as extracted and as written."""

    index: int

    # What the judge is asked about: intensifiers removed.
    text: str

    # What the answer actually said, kept so a reader validating a label
    # can see the sentence rather than the reduction.
    original: str

    is_numeric: bool = False

    # Tuple rather than list: the record is frozen so that the text scored
    # and the text stored cannot drift apart.
    numeric_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimSet:
    """The claims from one answer, and what was left out."""

    claims: list[Claim] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def is_speculative(text: str) -> bool:
    """Whether this candidate hedges rather than asserts."""
    lowered = (text or "").lower()

    return any(
        re.search(marker, lowered)
        for marker in SPECULATIVE_MARKERS
    )


def is_about_the_evidence(text: str) -> bool:
    """
    Whether this sentence describes the evidence rather than a company.

    The answer narrates its own sourcing, and those sentences are not
    facts anyone can check about a business. Scoring them inflates the
    support rate with statements that are true by construction.
    """
    return bool(_ABOUT_EVIDENCE.match(text or ""))


def strip_intensifiers(text: str) -> str:
    """
    Remove unquantified degree adverbs, leaving the checkable assertion.

    The surrounding whitespace and punctuation have to close up behind the
    removed word, or the stored claim reads "Margins improved ." and no
    longer matches what a human would write down.
    """
    result = text or ""

    for word in INTENSIFIERS:
        result = re.sub(
            rf"\s*\b{word}\b",
            "",
            result,
            flags=re.IGNORECASE,
        )

    # Collapse the gap the removal left, including before punctuation.
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"\s+([.,;:])", r"\1", result)

    return result.strip()


def numeric_values(text: str) -> list[str]:
    """Every figure the claim asserts, in the order written."""
    return [
        match.group(0).strip()
        for match in _NUMERIC.finditer(text or "")
    ]


def classify_candidates(candidates: list[str]) -> ClaimSet:
    """
    Apply the policy to a split answer.

    Blank candidates are ignored rather than dropped: a blank is not a
    hedge, and counting it would overstate how much of the answer was
    discarded.
    """
    claims: list[Claim] = []
    dropped: list[str] = []

    for candidate in candidates:
        text = (candidate or "").strip()

        if not text:
            continue

        if is_speculative(text) or is_about_the_evidence(text):
            dropped.append(text)
            continue

        checked = strip_intensifiers(text)
        figures = numeric_values(checked)

        claims.append(
            Claim(
                index=len(claims),
                text=checked,
                original=text,
                is_numeric=bool(figures),
                numeric_values=tuple(figures),
            )
        )

    return ClaimSet(claims=claims, dropped=dropped)
