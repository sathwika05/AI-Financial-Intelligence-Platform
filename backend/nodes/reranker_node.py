
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.scoring.evidence_builder import (
    attach_company_evidence,
    extract_sql_rows,
    record_matches_company,
)


logger = logging.getLogger(__name__)

# Evidence budget. The reranker runs after company scoring, so the
# budget scales with the number of companies that will actually be
# reported instead of a fixed global top-k.
TOP_K_FLOOR = 8
# Paired with CHUNKS_PER_COMPANY in vector_search: these are sequential
# caps, not alternatives. This budgets how many chunks the reranker may
# SELECT, and it selects from vector_result.retrieved_chunks, so whichever
# is smaller decides.
#
# Raising this alone did nothing (run 97a171a1) because the pool was nine.
# Raising the pool alone did nothing either (run 8a6c17f8): retrieval
# returned top_k 25 and the reranker still selected 15, discarding what had
# just been fetched. Both have to move.
EVIDENCE_PER_COMPANY = 5
MIN_EVIDENCE_PER_COMPANY = 2

# How many retrieved documents each reported company must keep, when the
# candidate pool actually holds one for it.
#
# MIN_EVIDENCE_PER_COMPANY above counts evidence of any source, so a
# company holding one SQL row and one market row already met the floor and
# its document was never pulled back in. On mixed_001 the pool offered five
# documents, one per cohort company, and the LLM reranker kept exactly one:
# the selection was 5 SQL rows, 5 market rows and 1 document. RAGAS then
# scored context_precision 1.0 — the single document was relevant — against
# context_recall 0.1429, because a reference answer covering five companies'
# coverage cannot be supported by one company's article.
#
# The question asks for "sentiment from recent company documents", so a
# selection that drops four of the five available documents is
# under-retrieval rather than a ranking preference.
MIN_DOCUMENTS_PER_COMPANY = 1


class RankedEvidenceItem(BaseModel):
    """One evidence item selected by the hybrid reranker"""

    candidate_id: int = Field(
        description="Zero-based ID of the selected candidate."
    )
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Relevance of this evidence to the user question.",
    )
    reason: str = Field(
        default="",
        description="Brief reason this evidence is useful."
    )

class RerankerOutput(BaseModel):
    """Structured output returned by the reranker LLM."""

    ranked_evidence: list[RankedEvidenceItem]

def _serialize_value(
        value: Any,
)-> str:
    """Convert structured evidence into readable text."""
    if isinstance(value, str):
        return value

    try:
        return json.dumps(
            value,
            sort_keys=True,
            default=str
        )
    except Exception:
        return str(value)

def build_hybrid_candidates(
        *,
        db_result: Any,
        generated_sql: str,
        retrieved_chunks: list[dict[str,Any]],
        market_data: dict[str, Any],
        market_metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Normalize SQL, vector, and market outputs into one common
    evidence structure for reranking.
    """
    candidates: list[dict[str, Any]] = []

    # ---------------------------------------------------------
    # SQL evidence
    # ---------------------------------------------------------

    for row_index, row in enumerate(extract_sql_rows(db_result)):
        content = _serialize_value(row)

        if not content.strip():
            continue

        row_dict = (
            row
            if isinstance(row, dict)
            else {}
        )

        candidates.append(
            {
                "source_type": "sql",
                "content": content,
                "original_score": 1.0,
                "metadata": {
                    "row_index": row_index,
                    "generated_sql": generated_sql,
                    "company_id": row_dict.get(
                        "company_id"
                ),
                "ticker": row_dict.get(
                    "ticker"
                ),
                "company_name": (
                    row_dict.get("name")
                    or row_dict.get(
                        "company_name"
                    )
                ),
                }
            }
        )

    # ---------------------------------------------------------
    # Vector evidence
    # ---------------------------------------------------------

    for chunk in retrieved_chunks:
        content = str(
            chunk.get("content") or ""
        ).strip()

        if not content:
            continue

        candidates.append(
            {
                "source_type": "vector",
                "content": content,
                "original_score": float(
                    chunk.get("similarity") or 0.0
                ),
                "metadata": {
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get(
                        "document_id"
                    ),
                    "chunk_index": chunk.get(
                        "chunk_index"
                    ),
                    "company_id": chunk.get(
                        "company_id"
                    ),
                    "doc_type": chunk.get("doc_type"),
                    "source": chunk.get("source"),
                },

            }
        )
    # ---------------------------------------------------------
    # Market evidence
    # ---------------------------------------------------------
    market_data = market_data or {}
    market_metadata = market_metadata or {}

    for ticker, data in market_data.items():
        if not isinstance(data, dict):
            continue

        content = (
            f"{ticker}: "
            f"name={data.get('name')}, "
            f"current_price={data.get('current_price')}, "
            f"price_change={data.get('price_change')}, "
            f"volume={data.get('volume')}, "
            f"market_cap={data.get('market_cap')}, "
            f"pe_ratio={data.get('pe_ratio')}, "
            f"52_week_high={data.get('52w_high')}, "
            f"52_week_low={data.get('52w_low')}, "
            f"sector={data.get('sector')}."
        )

        candidates.append(
            {
                "source_type": "market",
                "content": content,
                "original_score": float(
                    market_metadata.get(
                        "confidence",
                        0.0,
                    )
                ),
                "metadata": {
                    "ticker": ticker,
                    "cached": market_metadata.get(
                        "cached",
                        False,
                    ),
                    "stale": market_metadata.get(
                        "stale",
                        False,
                    ),
                    "degraded": market_metadata.get(
                        "degraded",
                        False,
                    ),
                },
            }
        )

        # Give every candidate a stable ID that the LLM can return.
    for candidate_id, candidate in enumerate(
        candidates
    ):
        candidate["candidate_id"] = candidate_id

    return candidates


def _fallback_rerank(
        candidates: list[dict[str, Any]],
        top_k: int,
)-> list[dict[str, Any]]:
    """
    Fall back to source-provided scores when the LLM reranker fails.
    """
    ranked = sorted(
        candidates,
        key=lambda item: float(
            item.get("original_score") or 0.0
        ),
        reverse=True,
    )[:top_k]

    return [
        {
            **candidate,
            "rerank_score": float(
                candidate.get("original_score") or 0.0
            ),
            "rerank_reason": (
                "Fallback ordering using the original score."
            ),
        }
        for candidate in ranked
    ]

def _backfill_company_coverage(
    *,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    target_companies: list[dict[str, Any]],
    min_per_company: int,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Guarantee every reported company keeps some evidence.

    The LLM ranks evidence globally, so it can spend every slot on one
    company and leave the rest of the reported companies uncited. For
    each company short of the floor, pull its best unselected
    candidates back in, ordered by the source's own score.

    `source_type` narrows both the count and the refill pool to one kind of
    evidence. Without it a company is covered by any two candidates, which
    is how a company could hold a SQL row and a market row while its
    document went unselected — see MIN_DOCUMENTS_PER_COMPANY.
    """
    if not target_companies or min_per_company <= 0:
        return selected

    selected_ids = {
        record["candidate_id"]
        for record in selected
    }

    for company in target_companies:
        matched = sum(
            1
            for record in selected
            if record_matches_company(record, company)
            and (
                source_type is None
                or record.get("source_type") == source_type
            )
        )

        shortfall = min_per_company - matched

        if shortfall <= 0:
            continue

        pool = sorted(
            (
                candidate
                for candidate in candidates
                if candidate["candidate_id"] not in selected_ids
                and record_matches_company(candidate, company)
                and (
                    source_type is None
                    or candidate.get("source_type") == source_type
                )
            ),
            key=lambda item: float(
                item.get("original_score") or 0.0
            ),
            reverse=True,
        )

        label = (
            company.get("ticker")
            or company.get("name")
            or "unknown company"
        )

        for candidate in pool[:shortfall]:
            record = dict(candidate)

            record["rerank_score"] = float(
                candidate.get("original_score") or 0.0
            )
            record["rerank_reason"] = (
                "Backfilled to keep "
                f"{source_type + ' ' if source_type else ''}"
                f"evidence coverage for {label}."
            )
            record["backfilled"] = True

            selected.append(record)
            selected_ids.add(record["candidate_id"])

        logger.info(
            "[CONTEXT_RERANKER] backfilled %s/%s items for %s",
            min(shortfall, len(pool)),
            shortfall,
            label,
        )

    return selected


def _apply_coverage_floors(
    *,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    target_companies: list[dict[str, Any]],
    min_per_company: int,
    min_documents_per_company: int,
) -> list[dict[str, Any]]:
    """
    Apply the general evidence floor, then the document-specific one.

    Order matters. The general pass runs first so a company with no
    evidence at all is filled from the best candidates of any source; the
    document pass then runs over that result, so a company whose floor was
    met entirely by SQL and market rows still gets its article back.
    Running only the general pass is what left mixed_001 with one document
    out of the five its pool contained.
    """
    selected = _backfill_company_coverage(
        selected=selected,
        candidates=candidates,
        target_companies=target_companies,
        min_per_company=min_per_company,
    )

    return _backfill_company_coverage(
        selected=selected,
        candidates=candidates,
        target_companies=target_companies,
        min_per_company=min_documents_per_company,
        source_type="vector",
    )


def _format_target_companies(
    target_companies: list[dict[str, Any]],
) -> str:
    """Describe the companies the report will cover."""
    return "\n".join(
        f"- {company.get('name', 'Unknown')} "
        f"({company.get('ticker', '?')})"
        for company in target_companies
    )


async def rerank_hybrid_contexts(
    *,
    query: str,
    candidates: list[dict[str, Any]],
    config: RunnableConfig,
    top_k: int = 8,
    target_companies: list[dict[str, Any]] | None = None,
    min_per_company: int = 0,
    min_documents_per_company: int = 0,
) -> list[dict[str, Any]]:
    """
    Rank hybrid SQL, vector, and market evidence by relevance
    to the original question.

    When target_companies is supplied the ranking is steered toward the
    companies the report will actually cover, and min_per_company is
    enforced afterwards so none of them ends up uncited.
    """
    if not candidates:
        return []

    target_companies = target_companies or []

    candidate_text = "\n\n".join(
        (
            f"Candidate ID: {candidate['candidate_id']}\n"
            f"Source type: {candidate['source_type']}\n"
            f"Original score: "
            f"{candidate.get('original_score', 0.0)}\n"
            f"Content:\n"
            f"{candidate['content'][:1500]}"
        )
        for candidate in candidates
    )

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )

    structured_llm = llm.with_structured_output(
        RerankerOutput
    )

    coverage_rules = ""

    if target_companies and min_per_company > 0:
        coverage_rules = (
            f"\n        - The report covers every company listed under "
            f"\"Companies to cover\". Select at least "
            f"{min_per_company} pieces of evidence for EACH of them "
            f"whenever such evidence exists among the candidates.\n"
            f"        - Spread the selection across those companies "
            f"instead of spending every slot on one company."
        )

    if target_companies and min_documents_per_company > 0:
        # Without this the model reliably prefers SQL and market rows,
        # which read as harder evidence, and returns a single document for
        # a five-company question whose pool held five.
        coverage_rules += (
            f"\n        - Retrieved documents (source type \"vector\") "
            f"carry the only sentiment and narrative evidence available; "
            f"SQL and market rows cannot substitute for them. Select at "
            f"least {min_documents_per_company} document for EACH covered "
            f"company whenever one exists among the candidates, even if "
            f"its relevance looks lower than another company's numbers."
        )

    system_message = SystemMessage(
        content=f"""
        You are a financial evidence reranker.

        Your task is to rank evidence from:
            - SQL database results
            - Financial documents
            - Current market data

        Rank evidence according to how directly and reliably it helps answer
        the user's financial question.

        Rules:
        - Aim to return {top_k} pieces of evidence. The number is a
          target, not a limit. Return fewer only when there is genuinely
          nothing left to add, because what remains is duplicated or says
          nothing about the question. An answer can only cite what you
          keep, so evidence you drop is evidence it cannot use.
        - Do not invent facts.
        - Do not rewrite or modify evidence.
        - Prefer specific evidence over generic evidence.
        - Prefer evidence directly related to the named companies and metrics.
        - Remove duplicates, and anything irrelevant to the question.
        - relevance_score must be between 0.0 and 1.0.
        - Return each candidate at most once.{coverage_rules}
        """.strip()
    )

    companies_block = ""

    if target_companies:
        companies_block = (
            "Companies to cover:\n"
            f"{_format_target_companies(target_companies)}\n\n"
        )

    try:
        response = await structured_llm.ainvoke(
            [
                system_message,
                HumanMessage(
                    content=(
                        f"Question:\n{query}\n\n"
                        f"{companies_block}"
                        f"Evidence candidates:\n"
                        f"{candidate_text}"
                    )
                ),
            ],
            config=config,
        )

        reranked: list[dict[str, Any]] = []
        seen_candidate_ids: set[int] = set()

        for ranked_item in response.ranked_evidence:
            candidate_id = ranked_item.candidate_id

            if candidate_id in seen_candidate_ids:
                continue

            if not 0 <= candidate_id < len(candidates):
                continue

            candidate = dict(
                candidates[candidate_id]
            )

            candidate["rerank_score"] = round(
                ranked_item.relevance_score,
                4,
            )
            candidate["rerank_reason"] = (
                ranked_item.reason
            )

            reranked.append(candidate)
            seen_candidate_ids.add(candidate_id)

        reranked.sort(
            key=lambda item: item["rerank_score"],
            reverse=True,
        )

        if reranked:
            return _apply_coverage_floors(
                selected=reranked[:top_k],
                candidates=candidates,
                target_companies=target_companies,
                min_per_company=min_per_company,
                min_documents_per_company=min_documents_per_company,
            )

        logger.warning(
            "[CONTEXT_RERANKER] LLM returned no valid evidence"
        )

    except Exception:
        logger.exception(
            "[CONTEXT_RERANKER] LLM reranking failed"
        )

    return _apply_coverage_floors(
        selected=_fallback_rerank(
            candidates,
            top_k,
        ),
        candidates=candidates,
        target_companies=target_companies,
        min_per_company=min_per_company,
        min_documents_per_company=min_documents_per_company,
    )

async def reranker_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    LangGraph node used only for MIXED queries.

    Runs after scoring so it knows which companies the report covers,
    and owns MIXED evidence attachment.

    Reads:
        original_query
        ranked_companies
        sql_result    (db_result, generated_sql)
        vector_result (retrieved_chunks)
        market_result (market_data + confidence/cache flags)

    Writes:
        reranked_contexts
        reranked_context_records
        ranked_companies   (evidence attached)
        scoring_result     (reranked_context_count refreshed)
    """
    query = state.get("original_query", "")

    # Retrieval lands in state as the three nested result blobs the
    # FinancialState schema declares; LangGraph drops anything else.
    sql_result = state.get("sql_result") or {}
    vector_result = state.get("vector_result") or {}
    market_result = state.get("market_result") or {}

    # Scoring already picked the companies the report will cover, so the
    # evidence budget is sized against them rather than a fixed top-k.
    ranked_companies = state.get("ranked_companies") or []

    candidates = build_hybrid_candidates(
        db_result=sql_result.get(
            "db_result",
            [],
        ),
        generated_sql=(
            sql_result.get("generated_sql")
            or state.get("generated_sql", "")
        ),
        retrieved_chunks=vector_result.get(
            "retrieved_chunks",
            [],
        ),
        market_data=market_result.get(
            "market_data",
            {},
        ),
        market_metadata={
            "confidence": market_result.get(
                "confidence",
                0.0,
            ),
            "cached": market_result.get(
                "cached",
                False,
            ),
            "stale": market_result.get(
                "stale",
                False,
            ),
            "degraded": market_result.get(
                "degraded",
                False,
            ),
        },
    )

    top_k = max(
        TOP_K_FLOOR,
        EVIDENCE_PER_COMPANY * len(ranked_companies),
    )

    reranked_records = await rerank_hybrid_contexts(
        query=query,
        candidates=candidates,
        config=config,
        top_k=top_k,
        target_companies=ranked_companies,
        min_per_company=MIN_EVIDENCE_PER_COMPANY,
        min_documents_per_company=MIN_DOCUMENTS_PER_COMPANY,
    )

    # Exact list[str] passed to Analysis and RAGAS.
    reranked_contexts = [
        item["content"]
        for item in reranked_records
        if item.get("content")
    ]

    # Attach evidence here rather than in scoring: both rankings now
    # exist, so a reported company without reranked evidence can fall
    # back to the raw sources instead of reaching the reviewer uncited.
    for company in ranked_companies:
        evidence = attach_company_evidence(
            company=company,
            intent="MIXED",
            sql_result=sql_result,
            vector_result=vector_result,
            market_result=market_result,
            reranked_context_records=reranked_records,
        )

        company["evidence"] = evidence
        company["evidence_count"] = len(evidence)

        logger.info(
            "[CONTEXT_RERANKER] ticker=%s evidence_count=%s",
            company.get("ticker", "?"),
            len(evidence),
        )

    scoring_result = state.get("scoring_result")

    if isinstance(scoring_result, dict):
        scoring_result = {
            **scoring_result,
            "top_companies": ranked_companies,
            "reranked_context_count": len(
                reranked_records
            ),
        }

    logger.info(
        "[CONTEXT_RERANKER] candidates=%s top_k=%s selected=%s "
        "companies=%s uncited=%s",
        len(candidates),
        top_k,
        len(reranked_contexts),
        len(ranked_companies),
        sum(
            1
            for company in ranked_companies
            if not company.get("evidence")
        ),
    )

    return {
        "reranked_contexts": reranked_contexts,
        "reranked_context_records": reranked_records,
        "ranked_companies": ranked_companies,
        "scoring_result": scoring_result,
    }
    


    
