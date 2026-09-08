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
ESCALATION_THRESHOLD = 0.30 # below → withhold the ranking, escalate to admin


def decide_escalation(
    overall_confidence: Any,
    should_retry: bool,
) -> bool:
    """
    Whether this report is too weak to show and should go to a human.

    Deliberately not "retry limit reached". Retries only happen on a
    quality failure — hallucinations, missing evidence, bad citations — so
    a draft with none of those and 0.2 confidence never retries at all,
    and a condition keyed on an exhausted retry limit would approve it
    silently. The question that matters is whether the reviewer has
    stopped, which covers the forced pass and the quiet approval alike.
    """
    if should_retry:
        # Mid-loop the number is not final. Escalating here would file one
        # row per attempt for a run that goes on to fix itself.
        return False

    try:
        confidence = float(overall_confidence)
    except (TypeError, ValueError):
        # A draft that never set the field is the worst case, not an
        # exempt one — and `None < 0.30` raises rather than escalating.
        confidence = 0.0

    return confidence < ESCALATION_THRESHOLD


# Flag kinds a rewrite can act on. confidence_flags is deliberately absent:
# "confidence is low" restates the problem rather than naming a claim, so
# sending it back spends an attempt and changes nothing.
_ACTIONABLE_FLAG_KINDS = (
    "hallucination_flags",
    "evidence_flags",
    "citation_flags",
    "company_flags",
)


def actionable_feedback(review_result: dict[str, Any]) -> list[str]:
    """
    The flags carried into the next attempt.

    Only hallucination flags used to be forwarded, and quality_failure is
    set by any of three predicates -- a hallucination rate above threshold,
    any evidence flag, any citation flag. So two of the three triggers
    produced an empty feedback list, and analysis re-ran on a prompt
    identical to the one that had just failed. At temperature zero that is
    not a resample, it is a repeat: the "hello" run spent 97 of its 111
    seconds on three attempts that could not differ.

    Every predicate that can trigger a retry populates a list named here,
    so a retry can no longer be dispatched with nothing to say.
    """
    feedback: list[str] = []

    for kind in _ACTIONABLE_FLAG_KINDS:
        feedback.extend(review_result.get(kind) or [])

    return feedback


def unresolved_flag_notice(total_flags: int) -> str:
    """What the reader is shown when the reviewer ran out of attempts."""
    return (
        f"This ranking is being withheld. The reviewer raised {total_flags} "
        "unresolved issue(s) with the draft and could not clear them within "
        "its retry limit, so the result has been sent for human review "
        "rather than shown as reviewed."
    )


def build_escalation_notice(overall_confidence: float) -> str:
    """
    What the reader is shown in place of the ranking.

    A bare number in a corner is not a warning: 0.17 and 0.91 render
    identically to someone who is reading the answer rather than auditing
    it. This says what happened, why, and what comes next.
    """
    return (
        f"Confidence in this answer is {overall_confidence:.2f}, below the "
        f"{ESCALATION_THRESHOLD:.2f} floor this system will stand behind. "
        "The ranking has been withheld and sent to an administrator for "
        "review rather than shown to you as though it were reliable."
    )


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


# Intents whose answer comes out of the metrics table by design.
#
# "healthcare companies with the strongest revenue growth" is answered from
# financial_metrics -- there is no filing to cite for a revenue-growth
# number, because it is a column. Demanding a document chunk for a database
# fact flagged every company, which set has_missing_evidence, which forced
# three retries and then a pass. Once the forced pass became a withhold,
# that turned every metrics-only question into a refusal -- including two
# of the four questions the console offers as examples.
#
# This is the same mistake the retrieval-precision metric made: judging a
# structured result by document-retrieval criteria.
_METRICS_DRIVEN_INTENTS = frozenset({"VALUATION", "GROWTH"})


def _check_retrieval_evidence(
    ranked_companies: list[dict[str, Any]],
    intent: str | None = None,
) -> list[str]:
    """
    Flag companies backed only by their own DB metrics.

    Every ranked company now carries a metrics evidence item, so the
    draft-level check above can always be satisfied. This one looks at
    the attached evidence and asks whether retrieval actually found
    anything about the company — if not, that is a retrieval failure.
    """
    flags: list[str] = []

    metrics_are_the_answer = (
        str(intent or "").strip().upper() in _METRICS_DRIVEN_INTENTS
    )

    for company in ranked_companies:
        ticker = company.get("ticker", "?")

        sources = {
            str(evidence.get("source", "")).lower()
            for evidence in company.get("evidence", [])
        }

        retrieved = sources - {"metrics"}

        if retrieved:
            continue

        # No evidence at all is a failure for every intent.
        if not sources:
            flags.append(
                f"{ticker}: no evidence of any kind attached"
            )
            continue

        # Metrics-only. A failure when the question asked about narrative,
        # and the expected shape when it asked about numbers.
        if not metrics_are_the_answer:
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
- A qualitative characterisation of a supplied number is supported by
  that number. "Trades at a moderate earnings multiple" is supported by
  a supplied P/E, "large-cap" by a supplied market cap, "strong revenue
  growth" by a supplied revenue growth figure. Do not flag these for
  lacking a document that repeats the characterisation in words.
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
        *_check_retrieval_evidence(
            ranked_companies,
            intent=draft_report.get("intent"),
        ),
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

    # Every retry regenerates the draft, because nothing upstream would
    # differ on a second attempt. The query, the cohort and the corpus are
    # all unchanged by the time the reviewer runs, so an identical
    # retrieval returns identical documents and the same flags are raised
    # again — three times, and then a forced pass.
    #
    # The module already applied this reasoning to grounding failures ("re-
    # running the same queries cannot fix it") and then routed the other
    # two cases back to retrieval anyway. Run c3f5c44b: 58 retries across
    # 28 questions, 57 of them to retrieval, 17 questions exhausting
    # MAX_RETRIES and force-passing regardless. analysis ran 86 times for
    # 28 questions at ~26s a call.
    #
    # What can differ is the draft: the flagged claims go back to the
    # analysis prompt, so a second attempt writes around evidence it does
    # not have instead of asserting it.
    retry_target = "analysis"

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
        # Distinct from total_flags. Six of the twenty-one flags on one
        # withheld report were "confidence 0.45 is below threshold 0.70",
        # repeated per company -- derived from a self-reported score that
        # floors around 0.49 and never enters the retry decision. Counting
        # them told the reader the draft had three times as many problems
        # as the reviewer actually acted on.
        "actionable_flag_count": len(
            hallucination_flags
            + evidence_flags
            + citation_flags
            + company_flags
        ),
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

    overall_confidence = draft_report.get(
        "overall_confidence"
    )

    # Only ever called once the reviewer has stopped retrying, so the
    # number here is final by construction.
    low_confidence = decide_escalation(
        overall_confidence=overall_confidence,
        should_retry=False,
    )

    # The second reason to withhold, and the one that fires in practice.
    #
    # decide_escalation catches the quiet case it was written for: no
    # flags, low confidence, no retries. It cannot catch this one, because
    # the self-reported confidence floors around 0.49 on the weakest
    # evidence in the corpus -- the 0.30 branch has never triggered. A
    # live "hello" raised fourteen flags four times running, was force
    # passed at the retry limit, and rendered with a Reviewed badge at 52%.
    #
    # Additive on purpose: decide_escalation keeps its exact meaning, so a
    # draft with no flags and 0.18 confidence still withholds on confidence
    # alone.
    unresolved = review_result.get("decision") == "forced_pass"

    escalated = low_confidence or unresolved

    try:
        confidence_value = float(overall_confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    return {
        "query_summary": draft_report.get(
            "query_summary"
        ),
        "intent": draft_report.get(
            "intent"
        ),
        # Withheld here rather than hidden by the console. A report the
        # client declines to draw is still a report — it is in the JSON,
        # in the network tab, and in anything else that calls this
        # endpoint. Dropping it means there is one answer to "what did the
        # system say about this query" rather than one per caller.
        "top_companies": (
            [] if escalated else companies[:TOP_N_FINAL]
        ),
        # An empty list on its own is ambiguous: it also means "nothing
        # matched". This is what lets the two be told apart.
        "withheld": escalated,
        "overall_confidence": overall_confidence,
        "evidence_quality": draft_report.get(
            "evidence_quality"
        ),
        "review": {
            "escalated": escalated,
            # Two reasons to withhold, two different sentences. A reader
            # told "confidence was low" about a report that was actually
            # withheld for fourteen unresolved flags has been given the
            # wrong explanation, which is worse than none.
            "notice": (
                build_escalation_notice(confidence_value)
                if low_confidence
                else unresolved_flag_notice(
                    review_result.get(
                        "actionable_flag_count",
                        review_result.get("total_flags", 0),
                    )
                )
                if unresolved
                else None
            ),
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

        # Withheld, not passed. This branch returns before
        # build_final_output, so decide_escalation never ran and an empty
        # report could not be withheld at all -- it was returned with
        # passed True and a forced_pass decision, which the console draws
        # as a reviewed answer. An empty draft is the clearest possible
        # case for declining to stand behind a result.
        review_result = {
            "passed": False,
            "should_retry": False,
            "decision": "withheld_empty_draft",
            "confidence_flags": [],
            "evidence_flags": ["The analysis produced no draft report."],
            "hallucination_flags": [],
            "company_flags": [],
            "citation_flags": [],
            "hallucination_rate": 0.0,
            "total_flags": 1,
        }

        return {
            "review_result": review_result,
            "final_report": {
                "query_summary": (draft_report or {}).get("query_summary"),
                "intent": (draft_report or {}).get("intent"),
                "top_companies": [],
                "withheld": True,
                "overall_confidence": None,
                "evidence_quality": None,
                "review": {
                    "escalated": True,
                    "notice": unresolved_flag_notice(1),
                    "decision": "withheld_empty_draft",
                    "hallucination_rate": 0.0,
                    "total_flags": 1,
                    "flags": ["The analysis produced no draft report."],
                },
                "sources_used": {},
            },
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
        actionable_feedback(review_result)
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

    

