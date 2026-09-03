"""
One question's claim audit: what was asserted, and what the evidence held.

Deliberately not an EvaluatorResult. finalize_question_result averages
every applicable evaluator's score into overall_score and fails the
question if any reports passed=False, so anything placed in
`evaluator_results` re-scores questions that have already been
benchmarked. This carries no score and no pass flag, and rides in its own
field.

It is also the shape that gets persisted. One ClaimRecord becomes one row
in claim_evaluations, which is what the validation page reads and writes
human labels against.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimRecord(BaseModel):
    """One checkable assertion and the judge's verdict on it."""

    index: int

    # The text that was checked, with unquantified intensifiers removed.
    claim: str

    # What the answer actually said, so a human validating the label reads
    # the sentence rather than the reduction of it.
    original: str

    is_numeric: bool = False
    numeric_values: tuple[str, ...] = ()

    # Exactly what the judge was shown. Stored per claim rather than per
    # question because the validation page has to put the evidence beside
    # the claim, and PipelineExecution is not persisted anywhere.
    evidence: list[str] = Field(default_factory=list)

    label: str
    reasoning: str = ""

    # Which judge decided, so a change of judge is visible in the data
    # rather than being an unrecorded reason the numbers moved.
    evaluator_model: str = ""


class ClaimAudit(BaseModel):
    """Every claim from one answer, plus what was excluded."""

    claims: list[ClaimRecord] = Field(default_factory=list)

    # Hedged statements, kept so the size of the discard is auditable. An
    # extractor that drops most of an answer reports a flattering rate.
    dropped: list[str] = Field(default_factory=list)

    @property
    def total_claims(self) -> int:
        return len(self.claims)

    @property
    def supported(self) -> int:
        return self._count("SUPPORTED")

    @property
    def unsupported(self) -> int:
        return self._count("UNSUPPORTED")

    @property
    def insufficient_evidence(self) -> int:
        return self._count("INSUFFICIENT_EVIDENCE")

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def _count(self, label: str) -> int:
        return sum(1 for claim in self.claims if claim.label == label)

    def rows_for(
        self,
        *,
        run_id: Any,
        question_id: str,
        route: str | None,
    ) -> list[dict[str, Any]]:
        """Flatten to the column shape claim_evaluations stores."""
        return [
            {
                "run_id": run_id,
                "question_id": question_id,
                "route": route,
                "claim_index": claim.index,
                "claim": claim.claim,
                "original": claim.original,
                "is_numeric": claim.is_numeric,
                "numeric_values": list(claim.numeric_values),
                "evidence": claim.evidence,
                "evaluator_label": claim.label,
                "evaluator_reasoning": claim.reasoning,
                "evaluator_model": claim.evaluator_model,
            }
            for claim in self.claims
        ]
