"""
One question's audit, end to end.

    answer  --split-->  candidates  --policy-->  claims
                                                   |
    execution --------> evidence -----------------judge--> labels

Two LLM calls per question, not one per claim: the splitter sees the whole
answer, the judge sees every claim and the whole evidence set at once. A
hundred questions costs about two hundred judge-model calls, against
roughly a thousand if each claim were asked separately — and the judge
reasons better with the full evidence in front of it.

Nothing here raises. The audit is additional to the benchmark, so a
splitter outage or a judge outage records an empty or insufficient audit
and lets the question keep the score the benchmark gave it.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.evaluation.claims.audit import ClaimAudit, ClaimRecord
from backend.evaluation.claims.checker import verdicts_for
from backend.evaluation.claims.extractor import (
    evidence_from,
    parse_candidates,
    split_prompt,
)
from backend.evaluation.claims.policy import classify_candidates

logger = logging.getLogger(__name__)

Caller = Callable[[str], Awaitable[str]]


async def audit_answer(
    *,
    answer: str,
    execution: Any,
    splitter: Caller,
    judge: Caller,
    evaluator_model: str,
) -> ClaimAudit:
    """Extract, filter and label one answer's claims."""
    text = (answer or "").strip()

    if not text:
        return ClaimAudit()

    try:
        raw = await splitter(split_prompt(text))
        candidates = parse_candidates(raw)
    except Exception as exc:
        logger.warning("[CLAIMS] Splitter failed; recording no claims: %s", exc)
        return ClaimAudit()

    claim_set = classify_candidates(candidates)
    evidence = evidence_from(execution)

    verdicts = await verdicts_for(
        claims=claim_set.claims,
        evidence=evidence,
        judge=judge,
    )

    by_index = {verdict.index: verdict for verdict in verdicts}

    return ClaimAudit(
        claims=[
            ClaimRecord(
                index=claim.index,
                claim=claim.text,
                original=claim.original,
                is_numeric=claim.is_numeric,
                numeric_values=claim.numeric_values,
                # Stored per claim because PipelineExecution is not
                # persisted anywhere, and the validation page has to show
                # the evidence beside the claim being judged.
                evidence=evidence,
                label=by_index[claim.index].label,
                reasoning=by_index[claim.index].reasoning,
                evaluator_model=evaluator_model,
            )
            for claim in claim_set.claims
        ],
        dropped=claim_set.dropped,
    )
