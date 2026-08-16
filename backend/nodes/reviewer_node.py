"""

Checks draft_report from analysis_node fro:
1. Low confidence    — companies scored below 0.70
2. Missing evidence  — no chunks supporting a claim
3. Hallucinations    — claims not grounded in evidence
4. Retry decision    — routes back to retrieval if quality too low

Input  (from state):
    draft_report  : dict  — from analysis_node
    sql_result    : dict  — evidence to verify against
    vector_result : dict  — evidence to verify against
    retry_count   : int   — how many retries so far

Output (to state):
    review_result : dict  — reviewer decision + all flags
    final_report  : dict  — final output (if approved)
    should_retry  : bool  — True → route back to retrieval
    retry_count   : int   — incremented on retry

"""

# ---------------- Constants ----------------------------------------------------

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier


logger = logging.getLogger(__name__)


CONFIDENCE_THRESHOLD = 0.70 # below → flag as low confidence
HALLUCINATION_THRESHOLD = 0.30 # above → trigger retry
MAX_RETRIES = 3    # max retries before forced pass
TOP_N_FINAL = 5  # companies in final output


def _check_confidence(
    draft_report: dict[str, Any],
) -> list[str]:
    """Flag companies and reports below the confidence threshold."""
    flags: list[str] = []

    overall_confidence = float(
        draft_report.get("overall_confidence", 0.0)
    )

    if overall_confidence < CONFIDENCE_THRESHOLD:
        flags.append(
            f"Overall confidence {overall_confidence:.2f} "
            f"is below threshold {CONFIDENCE_THRESHOLD:.2f}"
        )

    for company in draft_report.get("companies", []):
        confidence = float(
            company.get("confidence", 0.0)
        )
        ticker = company.get("ticker", "?")

        if confidence < CONFIDENCE_THRESHOLD:
            flags.append(
                f"{ticker}: confidence {confidence:.2f} "
                f"is below threshold "
                f"{CONFIDENCE_THRESHOLD:.2f}"
            )

    return flags


def _check_missing_evidence(
    draft_report: dict[str, Any],
) -> list[str]:
    """Flag companies with no attached evidence."""
    flags: list[str] = []

    for company in draft_report.get("companies", []):
        ticker = company.get("ticker", "?")
        evidence = company.get("evidence", [])

        if not evidence:
            flags.append(
                f"{ticker}: no evidence snippets provided"
            )

    return flags


def _check_retrieval_evidence(
    ranked_companies: list[dict[str, Any]],
) -> list[str]:
    """
    Flag companies backed only by their own DB metrics.

    Every ranked company now carries a metrics evidence item, so the
    draft-level check above can always be satisfied. This one looks at
    the attached evidence and asks whether retrieval actually found
    anything about the company — if not, that is a retrieval failure.
    """
    flags: list[str] = []

    for company in ranked_companies:
        ticker = company.get("ticker", "?")

        sources = {
            str(evidence.get("source", "")).lower()
            for evidence in company.get("evidence", [])
        }

        # Empty counts too: no evidence at all is worse than metrics-only.
        if not (sources - {"metrics"}):
            flags.append(
                f"{ticker}: no retrieval evidence — "
                f"backed only by database metrics"
            )

    return flags


def _check_company_flags(
    draft_report: dict[str, Any],
) -> list[str]:
    """Collect flags raised by the analysis node."""
    flags: list[str] = []

    for company in draft_report.get("companies", []):
        ticker = company.get("ticker", "?")

        for flag in company.get("flags", []):
            flags.append(
                f"{ticker}: {flag}"
            )

    return flags


def _build_attached_evidence_text(
    ranked_companies: list[dict[str, Any]],
) -> str:
    """Build evidence text for the reviewer LLM."""
    lines: list[str] = []

    for company in ranked_companies:
        ticker = company.get("ticker", "?")

        for evidence in company.get("evidence", []):
            lines.append(
                f"{ticker} "
                f"[{evidence.get('citation_id', 'missing')}]: "
                f"source={evidence.get('source', 'unknown')} | "
                f"supports={evidence.get('supports', '')} | "
                f"text={evidence.get('text', '')}"
            )

    return "\n".join(lines)


def _build_claims(
    draft_report: dict[str, Any],
) -> list[str]:
    """Extract reviewable company claims from the draft."""
    claims: list[str] = []

    for company in draft_report.get("companies", []):
        ticker = company.get("ticker", "?")
        summary = company.get("summary", "")

        if summary:
            claims.append(
                f"{ticker}: {summary}"
            )

    return claims


async def _llm_hallucination_check(
    draft_report: dict[str, Any],
    ranked_companies: list[dict[str, Any]],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Check whether draft claims are supported by attached evidence.
    """
    source_evidence = _build_attached_evidence_text(
        ranked_companies
    )
    claims = _build_claims(
        draft_report
    )

    if not claims:
        return {
            "hallucination_rate": 0.0,
            "flagged_claims": [],
        }

    if not source_evidence:
        return {
            "hallucination_rate": 1.0,
            "flagged_claims": [
                "No company-level evidence is available"
            ],
        }

    llm = get_llm_client(
        config,
        LLMTier.LARGE,
    )

    system_message = SystemMessage(
        content="""
You are a fact-checker for financial reports.

Compare each report claim against the supplied company-level evidence.

Rules:
- Use only the supplied evidence.
- Claims directly supported by SQL, financial metrics, market data,
  filings, transcripts, or retrieved documents are supported.
- Reasonable conclusions directly derived from supplied metrics may
  be treated as supported but weak.
- Do not require news or analyst evidence unless the claim explicitly
  refers to news, analysts, earnings calls, estimate revisions, or
  management commentary.
- Flag claims that are unsupported or contradicted.
- Do not flag a claim merely because stronger evidence could exist.

Return only valid JSON with this structure:

{
  "hallucination_rate": 0.0,
  "flagged_claims": []
}

Calculate hallucination_rate as:

unsupported_or_contradicted_claims / total_claims

Do not return markdown or additional explanation.
""".strip()
    )

    human_message = HumanMessage(
        content=f"""
CLAIMS TO VERIFY:

{chr(10).join(claims)}

COMPANY-LEVEL EVIDENCE:

{source_evidence}

Return only JSON.
""".strip()
    )

    try:
        response = await llm.ainvoke(
            [
                system_message,
                human_message,
            ],
            config=config,
        )

        content = response.content

        if not isinstance(content, str):
            raise TypeError(
                "Reviewer LLM returned non-string content"
            )

        cleaned_content = (
            content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        result = json.loads(
            cleaned_content
        )

        hallucination_rate = float(
            result.get("hallucination_rate", 0.0)
        )

        hallucination_rate = min(
            max(hallucination_rate, 0.0),
            1.0,
        )

        flagged_claims = result.get(
            "flagged_claims",
            [],
        )

        if not isinstance(flagged_claims, list):
            flagged_claims = [
                str(flagged_claims)
            ]

        return {
            "hallucination_rate": hallucination_rate,
            "flagged_claims": [
                str(claim)
                for claim in flagged_claims
            ],
        }

    except Exception:
        logger.exception(
            "[REVIEWER] LLM hallucination check failed"
        )

        # Fail safely instead of silently approving.
        return {
            "hallucination_rate": 1.0,
            "flagged_claims": [
                "Hallucination review could not be completed"
            ],
        }


@traceable(
    name="citation_check",
    run_type="tool",
    tags=["review", "guardrail"],
)
def _check_citations(
    draft_report: dict[str, Any],
    ranked_companies: list[dict[str, Any]],
) -> list[str]:
    """Validate draft citation IDs against ranked evidence."""
    flags: list[str] = []

    allowed_by_ticker: dict[str, set[str]] = {}

    for company in ranked_companies:
        ticker = str(
            company.get("ticker", "")
        ).upper()

        allowed_by_ticker[ticker] = {
            str(evidence["citation_id"])
            for evidence in company.get("evidence", [])
            if evidence.get("citation_id")
        }

    for company in draft_report.get("companies", []):
        ticker = str(
            company.get("ticker", "")
        ).upper()

        allowed_ids = allowed_by_ticker.get(
            ticker,
            set(),
        )

        for evidence in company.get("evidence", []):
            citation_id = evidence.get(
                "citation_id"
            )

            if not citation_id:
                flags.append(
                    f"{ticker}: missing citation_id"
                )
            elif str(citation_id) not in allowed_ids:
                flags.append(
                    f"{ticker}: invalid citation_id "
                    f"{citation_id}"
                )

    return flags


async def run_reviewer(
    draft_report: dict[str, Any],
    ranked_companies: list[dict[str, Any]],
    retry_count: int,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Review the report and decide whether to approve or retry."""
    logger.info(
        "[REVIEWER] Reviewing report retry_count=%s companies=%s",
        retry_count,
        len(draft_report.get("companies", [])),
    )

    confidence_flags = _check_confidence(
        draft_report
    )
    evidence_flags = [
        *_check_missing_evidence(draft_report),
        *_check_retrieval_evidence(ranked_companies),
    ]
    company_flags = _check_company_flags(
        draft_report
    )
    citation_flags = _check_citations(
        draft_report,
        ranked_companies,
    )

    hallucination_result = (
        await _llm_hallucination_check(
            draft_report=draft_report,
            ranked_companies=ranked_companies,
            config=config,
        )
    )

    hallucination_rate = hallucination_result[
        "hallucination_rate"
    ]
    hallucination_flags = hallucination_result[
        "flagged_claims"
    ]

    all_flags = [
        *confidence_flags,
        *evidence_flags,
        *company_flags,
        *citation_flags,
        *hallucination_flags,
    ]

    # Rate only. ORing in `bool(hallucination_flags)` made the threshold
    # dead code: a single flagged claim out of twenty forced a retry.
    has_hallucinations = (
        hallucination_rate > HALLUCINATION_THRESHOLD
    )
    has_missing_evidence = bool(
        evidence_flags
    )
    has_invalid_citations = bool(
        citation_flags
    )

    quality_failure = (
        has_hallucinations
        or has_missing_evidence
        or has_invalid_citations
    )

    should_retry = (
        quality_failure
        and retry_count < MAX_RETRIES
    )

    # Missing evidence and bad citations are retrieval problems, so those
    # go back to retrieval. A grounding failure is not — re-running the
    # same queries cannot fix it, so the draft is regenerated instead,
    # with the rejected claims handed back to the analysis prompt.
    if has_missing_evidence or has_invalid_citations:
        retry_target = "retrieval"
    elif has_hallucinations:
        retry_target = "analysis"
    else:
        retry_target = "retrieval"

    if retry_count >= MAX_RETRIES and quality_failure:
        decision = "forced_pass"
        passed = True
        should_retry = False

        logger.warning(
            "[REVIEWER] Maximum retries reached; "
            "forcing pass flags=%s",
            len(all_flags),
        )

    elif should_retry:
        decision = "retry"
        passed = False

        logger.info(
            "[REVIEWER] Retry triggered target=%s "
            "hallucination_rate=%.2f flags=%s",
            retry_target,
            hallucination_rate,
            len(all_flags),
        )

    else:
        decision = "approved"
        passed = True

        logger.info(
            "[REVIEWER] Approved confidence=%s flags=%s",
            draft_report.get("overall_confidence"),
            len(all_flags),
        )

    return {
        "passed": passed,
        "should_retry": should_retry,
        "decision": decision,
        "retry_target": retry_target,
        "confidence_flags": confidence_flags,
        "evidence_flags": evidence_flags,
        "hallucination_flags": hallucination_flags,
        "company_flags": company_flags,
        "citation_flags": citation_flags,
        "hallucination_rate": hallucination_rate,
        "total_flags": len(all_flags),
    }


def build_final_output(
    draft_report: dict[str, Any],
    review_result: dict[str, Any],
) -> dict[str, Any]:
    """Build the final user-facing report."""
    companies = draft_report.get(
        "companies",
        [],
    )

    review_flags = [
        *review_result.get(
            "confidence_flags",
            [],
        ),
        *review_result.get(
            "evidence_flags",
            [],
        ),
        *review_result.get(
            "citation_flags",
            [],
        ),
        *review_result.get(
            "company_flags",
            [],
        ),
        *review_result.get(
            "hallucination_flags",
            [],
        ),
    ]

    return {
        "query_summary": draft_report.get(
            "query_summary"
        ),
        "intent": draft_report.get(
            "intent"
        ),
        "top_companies": companies[
            :TOP_N_FINAL
        ],
        "overall_confidence": draft_report.get(
            "overall_confidence"
        ),
        "evidence_quality": draft_report.get(
            "evidence_quality"
        ),
        "review": {
            "decision": review_result.get(
                "decision"
            ),
            "hallucination_rate": review_result.get(
                "hallucination_rate",
                0.0,
            ),
            "total_flags": review_result.get(
                "total_flags",
                0,
            ),
            "flags": review_flags,
        },
        "sources_used": (
            draft_report
            .get("_meta", {})
            .get("sources_used", {})
        ),
    }


async def reviewer_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    LangGraph reviewer node.

    Reads:
        draft_report
        ranked_companies
        retry_count

    Writes:
        review_result
        final_report
        should_retry
        retry_count
    """
    draft_report = state.get(
        "draft_report",
        {},
    )
    ranked_companies = state.get(
        "ranked_companies",
        [],
    )
    retry_count = state.get(
        "retry_count",
        0,
    )

    if not draft_report or not draft_report.get(
        "companies"
    ):
        logger.warning(
            "[REVIEWER_NODE] Empty draft report; "
            "returning forced pass"
        )

        review_result = {
            "passed": True,
            "should_retry": False,
            "decision": "forced_pass",
            "confidence_flags": [],
            "evidence_flags": [],
            "hallucination_flags": [],
            "company_flags": [],
            "citation_flags": [],
            "hallucination_rate": 0.0,
            "total_flags": 0,
        }

        return {
            "review_result": review_result,
            "final_report": draft_report,
            "should_retry": False,
            "retry_count": retry_count,
        }

    review_result = await run_reviewer(
        draft_report=draft_report,
        ranked_companies=ranked_companies,
        retry_count=retry_count,
        config=config,
    )

    should_retry = review_result[
        "should_retry"
    ]

    final_report = None

    if not should_retry:
        final_report = build_final_output(
            draft_report=draft_report,
            review_result=review_result,
        )

        logger.info(
            "[REVIEWER_NODE] Final report ready "
            "decision=%s companies=%s",
            review_result["decision"],
            len(
                final_report.get(
                    "top_companies",
                    [],
                )
            ),
        )
    retry_target = review_result.get(
        "retry_target",
        "retrieval",
    )

    # Only an analysis retry can act on the flags; a retrieval retry
    # rebuilds the evidence and starts from a clean draft.
    review_feedback = (
        review_result.get("hallucination_flags", [])
        if should_retry and retry_target == "analysis"
        else []
    )

    return {
        "review_result": review_result,
        "final_report": final_report,
        "should_retry": should_retry,
        "retry_target": retry_target,
        "review_feedback": review_feedback,
        "retry_count": (
            retry_count + 1
            if should_retry
            else retry_count
        ),
    }


def route_after_review(
    state: dict[str, Any],
) -> str:
    """
    Route a retry to whichever stage can actually fix the failure,
    otherwise to final output.
    """
    if state.get("should_retry", False):
        target = (
            state.get("retry_target")
            or "retrieval"
        )

        logger.info(
            "[REVIEWER_ROUTER] Routing to %s",
            target,
        )
        return target

    logger.info(
        "[REVIEWER_ROUTER] Routing to output"
    )
    return "output"

    

