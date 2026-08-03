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
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.llm.llm_factory import llm_mini

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70   # below → flag as low confidence
HALLUCINATION_THRESHOLD = 0.30   # above → trigger retry
MAX_RETRIES             = 3      # max retries before forced pass
TOP_N_FINAL             = 5      # companies in final output

# ----------------- Individual checks ------------------------------------------

def _check_confidence(draft_report: dict) -> list[str]:
    """Flag companies and overall report with confidence below threshold."""
    flags = []
    overall = draft_report.get("overall_confidence",0.0)

    if overall <CONFIDENCE_THRESHOLD:
        flags.append(
            f"Overall confidence {overall: .2f} below threshold {CONFIDENCE_THRESHOLD}"
        )
    
    for company in draft_report.get("companies", []):
        conf = company.get("confidence", 0.0)
        ticker = company.get("ticker", "?")
        if conf < CONFIDENCE_THRESHOLD:
            flags.append(
                f"{ticker}: confidence {conf:.2f} below threshold {CONFIDENCE_THRESHOLD}"
            )
    return flags



def _check_missing_evidence(draft_report: dict) -> list[str]:
    """Flag companies with no evidence snippets."""

    flags = []
    for company in draft_report.get("companies",[]):
        ticker = company.get("ticker","?")
        evidence = company.get("evidence", [])
        if not evidence:
            flags.append(f"{ticker}: no evidence snippets provided")

    return flags

def _check_company_flags(draft_report: dict) -> list[str]:
    """Collect flags the LLM itself raised per company."""
    flags = []
    for company in draft_report.get("companies", []):
        ticker = company.get("ticker", "?")
        for flag in company.get("flags", []):
            flags.append(f"{ticker}: {flag}")
    return flags




def _build_attached_evidence_text(ranked_companies: list[dict]) -> str:
    lines = []

    for company in ranked_companies:
        ticker = company.get("ticker", "?")

        for e in company.get("evidence", []):
            lines.append(
                f"{ticker} [{e.get('citation_id')}]: "
                f"source={e.get('source')} | "
                f"supports={e.get('supports')} | "
                f"text={e.get('text')}"
            )

    return "\n".join(lines)


def _llm_hallucination_check(
    draft_report: dict,
    ranked_companies: list[dict],
) -> dict:
    source_evidence = _build_attached_evidence_text(ranked_companies)

    claims = [
        f"{c.get('ticker')}: {c.get('summary', '')}"
        for c in draft_report.get("companies", [])
    ]

    if not claims:
        return {"hallucination_rate": 0.0, "flagged_claims": []}

    if not source_evidence:
        return {
            "hallucination_rate": 1.0,
            "flagged_claims": ["No attached company-level evidence available"]
        }

    system = SystemMessage(content="""
You are a fact-checker for financial reports.

Given report claims and company-level source evidence, classify only truly unsupported or contradicted claims as hallucinations.

Rules:
- Use only the provided company-level evidence.
- Claims directly matching SQL, metrics, market, or vector evidence are supported.
- Claims reasonably inferred from provided metrics are supported, but may be considered weak evidence.
- Do not require separate news, analyst, or earnings-call evidence unless the claim explicitly mentions news, analysts, earnings calls, estimate revisions, or transcripts.
- Do not flag a claim only because stronger evidence could exist.
- Flag only claims that are absent from the evidence or contradicted by the evidence.

Return ONLY valid JSON:
{
  "hallucination_rate": 0.0,
  "flagged_claims": []
}

hallucination_rate = unsupported_or_contradicted_claims / total_claims.
If all claims are supported or reasonably inferred -> hallucination_rate: 0.0, flagged_claims: []
No markdown. No explanation. Just JSON.
""")

    user = HumanMessage(content=f"""
CLAIMS TO VERIFY:
{chr(10).join(claims)}

COMPANY-LEVEL SOURCE EVIDENCE:
{source_evidence}

Return JSON.
""")

    try:
        response = llm_mini.invoke([system, user])
        content = response.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)

        return {
            "hallucination_rate": float(result.get("hallucination_rate", 0.0)),
            "flagged_claims": result.get("flagged_claims", []),
        }

    except Exception as e:
        logger.error(f"[REVIEWER] LLM hallucination check failed: {e}")
        return {"hallucination_rate": 0.0, "flagged_claims": []}

def _check_citations(
    draft_report: dict,
    ranked_companies: list[dict]  
) -> list[str]:
    
    flags = []

    allowed_by_ticker = {}

    for company in ranked_companies:
        ticker = company.get("ticker", "").upper()
        allowed_by_ticker[ticker] = {
            e.get("citation_id")
            for e in company.get("evidence", [])
            if e.get("citation_id")
        }
    
    for company in draft_report.get("companies",[]):
        ticker = company.get("ticker","").upper()
        allowed_ids = allowed_by_ticker.get(ticker, set())

        for ev in company.get("evidence", []):
            citation_id = ev.get("citation_id")

            if not citation_id:
                flags.append(f"{ticker}: missing citation_id")
            elif citation_id not in allowed_ids:
                flags.append(f"{ticker}: invalid citation_id {citation_id}")
    

    return flags

    
    


# ------------ Main reviewer function -------------------------------------------------------

def run_reviewer(
    draft_report: dict,
    ranked_companies: list[dict],
    retry_count: int = 0    
) -> dict:
    """
    Review the draft report and decide: approve or retry.
    """

    logger.info(
        f"[REVIEWER] Reviewing draft report - "
        f"retry_count={retry_count}, "
        f"companies={len(draft_report.get('companies', []))}"
    )

    confidence_flags = _check_confidence(draft_report)
    evidence_flags = _check_missing_evidence(draft_report)
    company_flags = _check_company_flags(draft_report)

    llm_hall = _llm_hallucination_check(
        draft_report, ranked_companies
    )

    hallucination_rate = llm_hall["hallucination_rate"]
    llm_flagged_claims = llm_hall["flagged_claims"]

    citation_flags = _check_citations(
    draft_report,
    ranked_companies
    )

    all_flags = (
        confidence_flags +
        evidence_flags +
        company_flags + 
        citation_flags+
        llm_flagged_claims
    )

    total_flags = len(all_flags)

    has_hallucinations = (hallucination_rate > HALLUCINATION_THRESHOLD or bool(llm_flagged_claims))
    has_missed_evidence = bool(evidence_flags)
    has_invalid_citations = bool(citation_flags)

    should_retry = (
        (has_hallucinations or has_missed_evidence or has_invalid_citations) and 
        retry_count < MAX_RETRIES
    )

    if retry_count >= MAX_RETRIES:
        decision = "forced_pass"
        passed = True
        logger.warning(
            f"[REVIEWER] Max retries reached - "
            f"forcing pass with {total_flags} flags"
        )

    elif should_retry:
        decision = "retry"
        passed = False
        logger.info(
            f"[REVIEWER] retry triggered - "
            f"hallucination_rate={hallucination_rate:.2f}, "
            f"flags={total_flags}"
        )

    else:
        decision = "approved"
        passed = True
        logger.info(
            f"[REVIEWER] Approved - "
            f"confidence={draft_report.get('overall_confidence')}, "
            f"flags={total_flags}"
        )

    return {
        "passed": passed,
        "should_retry": should_retry,
        "decision": decision,
        "confidence_flags": confidence_flags,
        "evidence_flags": evidence_flags,
        "hallucination_flags": llm_flagged_claims,
        "company_flags": company_flags,
        "hallucination_rate": hallucination_rate,
        "citation_flags": citation_flags,
        "total_flags": total_flags
    }

#---------------------- Final Output Builder -------------------------------------------------------------------
def build_final_output(
        draft_report: dict,
        review_result: dict,
)-> dict:
    """
    Merge draft_report + review_result into the final output
    """

    companies = draft_report.get("companies",[])

    return {
       "query_summary": draft_report.get("query_summary"),
       "intent": draft_report.get("intent"),
       "top_companies": companies[:TOP_N_FINAL],
       "overall_confidence": draft_report.get("overall_confidence"),
       "evidence_quality": draft_report.get("evidence_quality"),
       "review":{
           "decision": review_result["decision"],
           "hallucination_rate": review_result["hallucination_rate"],
           "total_flags": review_result["total_flags"],
           "flags": (
               review_result["confidence_flags"] +
               review_result["evidence_flags"] +
               review_result["citation_flags"] +
               review_result["company_flags"] +
               review_result["hallucination_flags"]
           ),
       },
       "sources_used": draft_report.get("_meta",{}).get("sources_used", {}),
       }


#-------------------------- LangGraph node ------------------------------------------------------------------------

async def reviewer_node(state: dict) -> dict:
    """
    LangGraph node - Reviewer.

    Reads : draft_report, ranked_companies,retry_count
    Writes: review_result, final_report, should_retry, retry_count
    """

    draft_report = state.get("draft_report", {})
    retry_count = state.get("retry_count",0)
    ranked_companies = state.get("ranked_companies", [])

    if not draft_report or not draft_report.get("companies"):
        logger.warning("[REVIEWER_NODE] Empty draft report - skipping review")
        return {
            **state,
            "review_result": {"decision": "forced_pass", "total_flags":0},
            "final_report": draft_report,
            "should_retry": False,
            "retry_count": retry_count
        }    
    
    review_result = run_reviewer(
        draft_report = draft_report,
        ranked_companies=ranked_companies,
        retry_count = retry_count
    )

    should_retry = review_result["should_retry"]

    final_report = None
    if not should_retry:
        final_report = build_final_output(draft_report, review_result)
        logger.info(
            f"[REVIEWER_NODE] Final report ready - "
            f"decison={review_result['decision']}"
            f"companies={len(final_report.get('top_companies',[]))}"
        )

    return {
        **state,
        "review_result": review_result,
        "final_report": final_report,
        "should_retry": should_retry,
        "retry_count": retry_count + (1 if should_retry else 0)
    }
    
# ------------------------ LangGraph conditional edge -------------------------------------------------------

def route_after_review(state:dict):
    """
    Conditional edge after reviewer_node.
    "retrieval" -> retry
    "output" -> approved / forced_pass
    """

    if state.get("should_retry",False):
        logger.info("[ROUTER] Routing back to retrieval for retry")
        return "retrieval"
    
    logger.info("[ROUTER] Routing to final output")
    return "output"
    

    

