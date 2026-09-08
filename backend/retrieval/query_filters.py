






import json
import logging
import re
from typing import List

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langsmith import traceable
from pydantic import BaseModel, Field
from sqlalchemy import text
from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.services.postgres_service import engine

logger = logging.getLogger(__name__)



# ── Pydantic Schemas ───────────────────────────────────────

class DocumentFilters(BaseModel):
    # A comparison query names several companies. Extracting only one of
    # them filters the other's documents out at the database level, so
    # the report ends up with no evidence for it.
    company_names: List[str] = Field(default_factory=list)
    doc_type:      str | None = None
    source:        str | None = None

class RankingKeywords(BaseModel):
    """Financial keywords extracted from a query, for lexical ranking."""

    keywords: List[str] = Field(
        description=(
            "Exactly 5 financial keywords or short phrases, written as "
            "they appear in earnings calls, SEC filings and news "
            "articles -- for example \"revenue growth\", \"gross "
            "margin\", \"guidance\"."
        )
    )

async def get_company_mappings() -> str:
    """Load all companies from DB as LLM-readable string."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(
                """
              SELECT name, ticker FROM companies
              ORDER BY name
             """
            ))
            rows = result.fetchall()
        mappings = [
            f"- {row.name} / {row.ticker}" for row in rows
        ]
        return "\n".join(mappings)
    except Exception as e:
        logger.error(f"[FILTERS] Failed to load companies: {e}")
        return ""

# ── Company ID Lookup ──────────────────────────────────────

@traceable(
    name="company_id_lookup",
    run_type="tool",
    tags=["retrieval", "db"],
)
async def get_company_id(company_name: str) -> int | None:
    """Map company name or tocker to company_id in DB."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT id FROM companies
                WHERE LOWER(name) LIKE :name
                OR LOWER(ticker) = :ticker
                LIMIT 1
             """),{
                 "name": f"%{company_name.lower()}%",
                 "ticker": company_name.lower()
             })
            
            row = result.fetchone()
            return row.id if row else None
    except Exception as e:
        logger.error(f"[FILTERS] Company lookup failed: {e}")
        return None
    
# ── Extract Filters ────────────────────────────────────────

async def extract_filters(query: str,config: RunnableConfig) -> dict:
    """
    Extract metadata filters from natural language query.
    Loads company mappings dynamically from DB.
    Maps company_name to compnay_id using DB lookup.
    Returns empty dict if no filters found.
    """
    try:
        llm = get_llm_client(
                config,
                LLMTier.SMALL,
            )
        
        llm_structured = llm.with_structured_output(DocumentFilters)
        company_mappings = await get_company_mappings()
       
        prompt = f"""Extract metadata filters from the query.
                        Return None for fields not mentioned.

                    USER QUERY: {query}

                    COMPANY MAPPINGS (name / ticker):
                    {company_mappings}

                    SOURCE MAPPINGS:
                        - bloomberg -> bloomberg
                        - reuters   -> reuters
                        - sec.gov   -> sec
                        - alpha vantage -> alphavantage

                    RULES:
                        - Extract EVERY company mentioned into company_names
                        - A comparison mentions two or more companies —
                          list ALL of them, never just the first
                        - Return an empty list if no specific company is mentioned
                        - Extract source ONLY if a specific source is mentioned
                        - Do NOT extract doc_type — all documents are the same type
                        - Return None for any field not explicitly mentioned

                    EXAMPLES:
                            "What did Apple say in earnings calls?"
                            → company_names: ["Apple Inc."], source: None

                            "NVIDIA news about AI chips"
                            → company_names: ["NVIDIA Corporation"], source: None

                            "Compare NVDA and AMD on valuation and sentiment"
                            → company_names: ["NVIDIA Corporation",
                              "Advanced Micro Devices, Inc."], source: None

                            "Microsoft vs Google cloud growth"
                            → company_names: ["Microsoft Corporation",
                              "Alphabet Inc."], source: None

                            "Bloomberg news about Tesla"
                            → company_names: ["Tesla Inc."], source: "bloomberg"

                            "Reuters article about Amazon AI"
                            → company_names: ["Amazon.com Inc."], source: "reuters"

                            "AI growth sentiment across all companies"
                            → company_names: [], source: None

                            "What are analysts saying about the tech sector?"
                            → company_names: [], source: None

                    Extract filters:

        """

        result = await llm_structured.ainvoke(prompt)
        logger.info(f"[FILTERS] Result: {result}")
        filters = result.model_dump(exclude_none=True)

        # map company_names -> company_ids
        company_names = filters.pop("company_names", []) or []

        company_ids: list[int] = []

        for company_name in company_names:
            company_id = await get_company_id(company_name)

            if company_id and company_id not in company_ids:
                company_ids.append(company_id)

        if company_ids:
            filters["company_ids"] = company_ids

        if company_names and not company_ids:
            logger.warning(
                "[FILTERS] None of %s resolved to a company_id; "
                "searching without a company filter",
                company_names,
            )

        logger.info(f"[FILTERS] Extracted: {filters}")
        return filters
    
    except Exception as e:
        logger.error(f"[FILTERS] Extraction failed: {e}")
        return {}
    
# ── Generate Ranking Keywords ──────────────────────────────

def _recover_keywords_from_tool_failure(exc: Exception) -> list[str]:
    """
    Salvage the keywords Groq generated and then refused to return.

    Groq's small tier reliably produces the right answer for this prompt
    and then emits it as message content instead of a tool call, so the
    provider rejects its own response:

        400 tool_use_failed
        "Tool choice is required, but model did not call a tool"
        failed_generation: '["revenue growth", "year over year", ...]'

    The generation is right there in the rejection. Measured over five
    serial attempts on gpt-oss-20b at temperature zero: structured output
    alone succeeded twice; with this recovery, five out of five. Neither
    a larger model nor a described schema nor rewriting the prompt's
    examples changed the failure rate -- all three were measured at 0/5.

    This costs no extra call. The alternative, a second plain invocation
    parsed as JSON, also measured 5/5, and is what to fall back to if the
    provider ever stops including failed_generation.
    """
    body = getattr(exc, "body", None)

    text = None

    if isinstance(body, dict):
        error = body.get("error")

        if isinstance(error, dict):
            text = error.get("failed_generation")

    if not text:
        # Some SDK versions surface the payload only in the message.
        match = re.search(
            r"'failed_generation':\s*'(.*?)'\}", str(exc), re.S
        )
        text = match.group(1) if match else None

    if not text:
        return []

    match = re.search(r"\[.*?\]", text, re.S)

    if not match:
        return []

    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(parsed, list):
        return []

    return [str(keyword) for keyword in parsed if keyword]


async def generate_ranking_keywords(
    query: str,
    config: RunnableConfig,
) -> list[str]:
    """
    Generate 5 financial keywords from the query.

    Feeds bm25_rerank, which reorders the pgvector result, and -- when
    rrf_enabled -- search_chunks_lexical, which ranks the whole corpus.
    Both treat an empty list as "no lexical signal" and fall back to the
    dense order, so a failure here is a silent quality loss rather than
    an error.

    The schema above carries a docstring and a field description for a
    reason. Without them Groq's small tier returns the list as message
    content instead of calling the tool, and rejects its own response
    with 400 tool_use_failed. Measured on gpt-oss-20b at temperature
    zero: the bare schema fails, the described one does not.
    """
    try:
        llm = get_llm_client(
                        config,
                        LLMTier.SMALL,
                    )
        llm_structured = llm.with_structured_output(RankingKeywords)

        prompt = f""" Generate EXACTLY 5 financial keywords from the query.

        Use exact terms found in earnings calls, SEC filings, and news.

        USER QUERY: {query}

        EARNINGS CALL TERMS:
        "revenue growth", "gross margin", "operating income",
        "net income", "earnings per share", "guidance",
        "year over year", "quarter over quarter", "beat expectations"

        SEC FILING TERMS:
        "consolidated statements of operations",
        "consolidated balance sheets",
        "cash flows from operating activities",
        "total assets", "stockholders equity",
        "long-term debt", "capital expenditures",
        "net cash provided by operating activities"

        NEWS/SENTIMENT TERMS:
        "artificial intelligence", "data center", "cloud computing",
        "market share", "competitive advantage", "growth outlook",
        "investment", "acquisition", "partnership"

        VALUATION TERMS:
        "price to earnings", "revenue multiple", "valuation",
        "undervalued", "overvalued", "fair value"
        
        RULES:
        - Return EXACTLY 5 keywords
        - Match the topic of the query
        - Use exact phrases from financial documents

        EXAMPLES:
        "What did Apple say about AI growth?"
        -> ["artificial intelligence", "revenue growth",
          "growth outlook", "year over year", "guidance"]

        "NVIDIA earnings and revenue"
        → ["revenue", "net income", "earnings per share",
        "consolidated statements of operations", "gross margin"]

        "undervalued tech companies with strong growth"
        → ["revenue growth", "undervalued", "valuation",
        "operating income", "year over year"]

        Generate EXACTLY 5 keywords:

        """

        result = await llm_structured.ainvoke(prompt)
        logger.info(f"[FILTERS] Keywords: {result.keywords}")
        return result.keywords
    
    except Exception as e:
        recovered = _recover_keywords_from_tool_failure(e)

        if recovered:
            logger.warning(
                "[FILTERS] Provider rejected its own tool call; "
                "recovered %s keywords from the payload",
                len(recovered),
            )
            return recovered

        # Fail open. An empty list means bm25_rerank returns the pgvector
        # order and RRF falls back to dense -- degraded retrieval, not a
        # failed query. Logged at error because it is invisible otherwise.
        logger.error(f"[FILTERS] Keyword generation failed: {e}")
        return []
    
