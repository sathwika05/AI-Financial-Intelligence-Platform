
"""
Takes ranked companies from the scoring/reranker node and generates
a structured financial report with evidence, confidence scores,
and explainable reasoning per company.

Input  (from state):
    ranked_companies  : list[dict]   — from scoring_node/ranker
    query             : str          — original user query
    intent            : str          — VALUATION/GROWTH/SENTIMENT/MIXED
 
    
Output (to state):
    draft_report      : dict         — structured report for reviewer_node

"""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from backend.services.llm_service import llm_strong






logger = logging.getLogger(__name__)

#---------------------- constants ------------------------------------------

MAX_COMPANIES = 5 # top-N companies to include in report


# ------------------------- System prompt ----------------------------------

SYSTEM_PROMPT = """
You are a senior financial analyst generating a structured investment report.
 
Your report must:
1. Cover ONLY the companies provided — do NOT invent tickers or names
2. Base every claim on the evidence provided (SQL data, news chunks, market data)
3. Be specific — use actual numbers (PE ratios, growth %, EPS)
4. Assign a confidence score (0.0–1.0) reflecting how well evidence supports each claim
5. Flag any claim where evidence is weak or missing
 
Use ONLY the evidence attached under each company.
Every factual claim must cite one citation_id from that same company.
Do not use evidence from another company.
Do not use global SQL, news, or market data unless it is listed under that company evidence.
If a company has no direct evidence, lower confidence and add a flag.

Return ONLY valid JSON. No markdown. No preamble. No explanation outside the JSON.
 
JSON structure:
{
  "query_summary": "one sentence restatement of the user query",
  "intent": "VALUATION | GROWTH | SENTIMENT | MIXED",
  "companies": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "final_score": 0.87,
      "recommendation": "Strong Buy | Buy | Hold | Sell | Strong Sell",
      "summary": "2-3 sentence analysis grounded in evidence",
      "key_metrics": {
        "pe_ratio": 35.4,
        "revenue_growth": "38%",
        "eps": 2.5,
        "market_cap": "3.3T"
      },
      "evidence": [
        {
       "claim": "...",
       "citation_id": "..."
      }
      ],
      "confidence": 0.85,
      "flags": []
    }
  ],
  "overall_confidence": 0.82,
  "evidence_quality": "high | medium | low",
  "report_flags": []
}
"""

def _format_company_evidence(company: dict) -> str:
    evidence = company.get("evidence", [])

    if not evidence:
        return "No direct company-level evidence available."

    return "\n".join([
        f"[{e['citation_id']}] "
        f"source={e.get('source')} | "
        f"supports={e.get('supports')} | "
        f"text={e.get('text')}"
        for e in evidence
    ])

#----------------------- Prompt builder --------------------------------------

def _build_user_prompt(
        query:  str,
        intent: str,
        ranked: list[dict],
):
    """
    Assemble the full user prompt with all availabl evidence
    """

    top_companies = ranked[:MAX_COMPANIES]

    # ------------- Company block ----------------------------------------------
    company_sections = []

    for c in top_companies:
        scores = c.get("scores", {})
        metrics = c.get("metrics", {})

        company_sections.append(
            f"Rank #{c.get('rank')} - {c.get('name')} ({c.get('ticker')})\n"
            f"  Final score : {c.get('final_score')}\n"
            f"  Scores      : "
            f"valuation={scores.get('valuation', 0):.3f}, "
            f"growth={scores.get('growth', 0):.3f}, "
            f"relevance={scores.get('relevance', 0):.3f}, "
            f"sentiment={scores.get('sentiment', 0):.3f}\n"
            f"  Weights     : {c.get('weights', {})}\n"
            f"  Metrics     : "
            f"PE={metrics.get('pe_ratio')}, "
            f"EPS={metrics.get('eps')}, "
            f"Revenue Growth={metrics.get('revenue_growth')}, "
            f"Market Cap={metrics.get('market_cap')}\n"
            f"  LLM score   : {c.get('llm_score', 'N/A')}\n"
            f"  Evidence:\n{_format_company_evidence(c)}"
        )

    company_block = "\n".join(company_sections)
   


    return f"""
Query: {query}
Intent: {intent}

==== RANKED COMPANIES WITH ATTACHED EVIDENCE =========
{company_block}




Generate the financial report JSON now.
""".strip()


# ---------- Core analysis function -----------------------------------

def run_llm_analysis(
    query: str,
    intent: str,
    ranked: list[dict], 
) -> dict:
    """
    Generate a structured financial report from ranked companies.

    Returns
    ---------
    draft_report: dict
         Structured report ready for reviewer_node
         Always return a valid dict - never raises.
    """
    if not ranked:
        logger.warning("[ANALYSIS] No ranked companies - returning empty report")
        return _empty_report(query, intent, reason ="No companies ranked")
    
    

    user_prompt = _build_user_prompt(
        query, intent, ranked
    )

    logger.info(
        f"[ANALYSIS] Generating report - "
        f"companies={min(len(ranked), MAX_COMPANIES)}, "
        f"intent={intent}"
    )

    try:
        response = llm_strong.invoke([
              SystemMessage(content=SYSTEM_PROMPT),
              HumanMessage(content=user_prompt)
        ])

        content = response.content.strip()
        content = content.replace("```json","").replace("```","").strip()

        report = json.loads(content)
        

        # Attach metadata
        report["_meta"] = {
            "intent": intent,
            "companies_ranked": len(ranked),
            "sources_used": {
                "company_level_evidence": any(
                    c.get("evidence") for c in ranked
            )
            }
        }

        logger.info(
            f"[ANALYSIS] Report generated - "
            f"overall_confidence={report.get('overall_confidence')}, "
            f"companies={len(report.get('companies',[]))}"
        )

        return report
    
    except json.JSONDecodeError as e:
        logger.error(f"[ANALYSIS] JSON parse failed: {e}")
        return _empty_report(query, intent, reason=f"JSON parse error: {e}")
    
    except Exception as e:
        logger.error(f"[ANALYSIS] LLM call failed: {e}")
        return _empty_report(query, intent, reason=f"LLM error: {e}")

        
# ------------------ LangGraph node --------------------------------------------
async def analysis_node(state: dict)->dict:
    """
    LangGraph node - LLM Analysis

    Reads: query, intent, ranked_companies
    Writes: draft_report
    """   
    logger.info("[ANALYSIS_NODE] Node called")
    query = state.get("original_query", "")
    intent = state.get("intent", "MIXED")
    ranked = state.get("ranked_companies", [])
    

    logger.info(f"[ANALYSIS_NODE] ranked_companies count: {len(ranked)}")

    if not ranked:
        
        return {
            **state,
            "draft_report": _empty_report(
                query, intent, reason="No ranked companies in state"
            ),
        }
    
    draft_report = run_llm_analysis(
        query = query,
        intent = intent,
        ranked = ranked
    )
    logger.info(f"[ANALYSIS_NODE] ranked_companies count: {len(ranked)}")
    return {
        **state,
        "draft_report": draft_report
    }


#----------- Fallback --------------------------------------------------------------

def _empty_report(query: str, intent: str, reason: str ="") -> dict:
    """Safe fallback when analysis cannot be completed."""

    return {
        "query_summary":  query,
        "intent": intent,
        "companies": [],
        "overall_confidence": 0.0,
         "evidence_quality":   "low",
        "report_flags":       [reason or "Analysis failed"],
        "_meta": {
            "intent":          intent,
            "companies_ranked": 0,
            "sources_used": {
                "sql":    False,
                "vector": False,
                "market": False,
            },
        }

    }




