import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.scoring.evidence_builder import (
    attach_company_evidence,
)
from backend.scoring.ranker import (
    ORDERED_BY_COMPOSITE,
)
from backend.scoring.ranker import rerank
from backend.scoring.score_normalizer import (
    build_score_breakdown,
    interpret_score,
)


logger = logging.getLogger(__name__)

TOP_COMPANIES_LIMIT = 5


def ordering_basis(ranked_companies: list[dict]) -> str:
    """
    Which rule decided the rank order.

    Read off the ranking rather than recomputed, so the console can never
    disagree with the ranker about what the ranker did. Absent means the
    composite: it is the default on every other path, and claiming SQL
    chose an order it did not choose is the failure worth avoiding.
    """
    if not ranked_companies:
        return ORDERED_BY_COMPOSITE

    return ranked_companies[0].get(
        "ordered_by",
        ORDERED_BY_COMPOSITE,
    )



async def scoring_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    LangGraph scoring node.

    Steps:
    1. Read retrieval results from state.
    2. Rerank companies across available data sources.
    3. Apply intent-specific scoring weights.
    4. Attach evidence and scoring explanations.
    5. Return the top-ranked companies.

    MIXED is the exception to step 4: reranker_node runs after this node
    and attaches evidence there, so the evidence reranker can target the
    companies chosen here instead of guessing before they exist.
    """
    try:
        sql_result    = state.get("sql_result")
        vector_result = state.get("vector_result")
        market_result = state.get("market_result")

        if not any((sql_result, vector_result, market_result)):
            logger.warning(
                "[SCORING] No retrieval result found in state"
            )

            return {
                "ranked_companies": [],
                "scoring_result": None,
            }

        query = state.get(
            "original_query",
            "",
        )
        
        intent = state.get(
            "intent",
            "MIXED",
        )

        is_mixed = str(intent).strip().upper() == "MIXED"

        logger.info(
            "[SCORING] Scoring query=%r intent=%s",
            query,
            intent,
        )

        ranked_companies = await rerank(
            query=query,
            intent=intent,
            sql_result=sql_result,
            vector_result=vector_result,
            market_result=market_result,
            config=config,
            # Resolved by the planner from the curated taxonomy. Passed
            # through so eligibility survives a degraded retrieval branch
            # rather than being re-derived from whatever came back.
            candidate_tickers=state.get("candidate_tickers") or [],
        )

        if not ranked_companies:
            logger.warning(
                "[SCORING] No companies were ranked"
            )

            return {
                "ranked_companies": [],
                "scoring_result": {
                    "top_companies": [],
                    "total_ranked": 0,
                    "weights_used": {},
                    "intent": intent,
                    "reranked_context_count": 0,
                },
            }

        top_companies = ranked_companies[
            :TOP_COMPANIES_LIMIT
        ]

        for company in top_companies:
            if is_mixed:
                # reranker_node attaches MIXED evidence downstream.
                company["evidence"] = []
                company["evidence_count"] = 0
                evidence = []
            else:
                evidence = attach_company_evidence(
                    company=company,
                    intent=intent,
                    sql_result=sql_result,
                    vector_result=vector_result,
                    market_result=market_result,
                )

                company["evidence"] = evidence
                company["evidence_count"] = len(
                    evidence
                )

            scores = company.get(
                "scores",
                {},
            )
            weights = company.get(
                "weights",
                {},
            )
            final_score = float(
                company.get(
                    "final_score",
                    0.0,
                )
            )

            company["explainability"] = (
                build_score_breakdown(
                    scores=scores,
                    weights=weights,
                    final_score=final_score,
                )
            )

            company["interpretation"] = (
                interpret_score(
                    final_score
                )
            )

            citation_ids = [
                item.get("citation_id")
                for item in evidence
                if item.get("citation_id")
            ]

            logger.info(
                "[SCORING] ticker=%s score=%.4f "
                "evidence_count=%s citations=%s",
                company.get("ticker", "?"),
                final_score,
                len(evidence),
                citation_ids,
            )

        scoring_result = {
            "top_companies": top_companies,
            "total_ranked": len(
                ranked_companies
            ),
            "weights_used": top_companies[
                0
            ].get(
                "weights",
                {},
            ),
            "intent": intent,
            "reranked_context_count": 0,
            # A ranking whose scores disagree with its own order is not
            # broken, but it looks broken unless it says which rule it
            # used. See ORDERED_BY_SQL in ranker.py.
            "ordering": ordering_basis(ranked_companies),
        }

        top_company = top_companies[0]

        logger.info(
            "[SCORING] Complete top_company=%s "
            "score=%.4f interpretation=%s",
            top_company.get(
                "name",
                top_company.get(
                    "ticker",
                    "unknown",
                ),
            ),
            float(
                top_company.get(
                    "final_score",
                    0.0,
                )
            ),
            top_company.get(
                "interpretation",
                "",
            ),
        )

        return {
            "scoring_result": scoring_result,
            "ranked_companies": top_companies,
        }

    except Exception:
        logger.exception(
            "[SCORING] Scoring node failed"
        )

        return {
            "ranked_companies": [],
            "scoring_result": None,
        }