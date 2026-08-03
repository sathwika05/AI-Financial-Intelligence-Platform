import logging
from backend.scoring.ranker import rerank
from backend.scoring.score_normalizer import (
    interpret_score,
    build_score_breakdown
)
from backend.scoring.evidence_builder import (
    attach_company_evidence
)

logger = logging.getLogger(__name__)


async def scoring_node(state: dict) -> dict:
    """
    LangGraph scoring node.

    Steps:
    1. Get retrieval results from state
    2. Rerank companies using:
       - cosine similarity (reuses pgvector scores)
       - rule-based scoring (PE, growth, EPS)
       - optional LLM holistic score
    3. Apply dynamic weights (40/30/20/10)
    4. Build explainability for each company
    5. Return top 5 ranked companies
    """
    try:
        result = state.get("result", {})

        if not result:
            logger.warning("[SCORING] No result in state to score")
            return {
                **state,
                "ranked_companies": [],
                "scoring_result":   None,
            }

        query         = state.get("original_query", "")
        intent        = state.get("intent", "MIXED")
        sql_result    = result.get("sql_result")
        vector_result = result.get("vector_result")
        market_result = result.get("market_result")

        logger.info(f"[SCORING] Scoring query: {query}")

        # rerank companies across all dimensions
        ranked_companies = await rerank(
            query         = query,
            intent        = intent,
            sql_result    = sql_result,
            vector_result = vector_result,
            market_result = market_result
        )

        if not ranked_companies:
            logger.warning("[SCORING] No companies ranked")
            return {
                **state,
                "ranked_companies": [],
                "scoring_result": {
                    "top_companies": [],
                    "total_ranked":  0,
                    "intent":        intent
                }
            }

        # take top 5
        top_companies = ranked_companies[:5]

        # add evidence, explainability, and interpretation
        for company in top_companies:
            company["evidence"] = attach_company_evidence(
                            company=company,
                            sql_result=sql_result,
                            vector_result=vector_result,
                            market_result=market_result
            )

            company["evidence_count"] = len(company["evidence"])

            logger.info(
                f"[SCORING] {company['ticker']} "
                f"evidence_count={len(company['evidence'])} "
                f"citations={[e['citation_id'] for e in company['evidence']]}"
                )
            
            company["explainability"] = build_score_breakdown(
                scores      = company["scores"],
                weights     = company["weights"],
                final_score = company["final_score"]
            )
            company["interpretation"] = interpret_score(
                company["final_score"]
            )

        scoring_result = {
            "top_companies": top_companies,
            "total_ranked":  len(ranked_companies),
            "weights_used":  top_companies[0]["weights"],
            "intent":        intent
        }

        logger.info(
            f"[SCORING] Complete. "
            f"Top: {top_companies[0]['name']} "
            f"score={top_companies[0]['final_score']} "
            f"— {top_companies[0]['interpretation']}"
        )

        return {
            **state,
            "scoring_result":   scoring_result,
            "ranked_companies": top_companies,
        }

    except Exception as e:
        logger.error(f"[SCORING] EXCEPTION: {e}", exc_info=True)
        return {
            **state,
            "ranked_companies": [],
            "scoring_result":   None,
        }