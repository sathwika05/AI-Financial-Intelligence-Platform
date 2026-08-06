






import logging
from typing import List

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langsmith import traceable
from pydantic import BaseModel
from sqlalchemy import text
from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.services.postgres_service import engine

logger = logging.getLogger(__name__)



# ── Pydantic Schemas ───────────────────────────────────────

class DocumentFilters(BaseModel):
    company_name: str | None = None
    doc_type:     str | None = None
    source:       str | None = None

class RankingKeywords(BaseModel):
    keywords: List[str]

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
                        - Extract company_name ONLY if a specific company is mentioned
                        - Extract source ONLY if a specific source is mentioned
                        - Do NOT extract doc_type — all documents are the same type
                        - Return None for any field not explicitly mentioned

                    EXAMPLES:
                            "What did Apple say in earnings calls?"
                            → company_name: "Apple Inc.", source: None

                            "NVIDIA news about AI chips"
                            → company_name: "NVIDIA Corporation", source: None

                            "Microsoft filings revenue growth"
                            → company_name: "Microsoft Corporation", source: None

                            "Bloomberg news about Tesla"
                            → company_name: "Tesla Inc.", source: "bloomberg"

                            "Reuters article about Amazon AI"
                            → company_name: "Amazon.com Inc.", source: "reuters"

                            "AI growth sentiment across all companies"
                            → company_name: None, source: None

                            "What are analysts saying about the tech sector?"
                            → company_name: None, source: None

                    Extract filters:

        """

        result = llm_structured.invoke(prompt)
        logger.info(f"[FILTERS] Result: {result}")
        filters = result.model_dump(exclude_none=True)
       
        # map company_name -> company_id
        if "company_name" in filters:
            company_id = await get_company_id(filters["company_name"])
            if company_id:
                filters["company_id"] = company_id
            del filters["company_name"]

        logger.info(f"[FILTERS] Extracted: {filters}")
        return filters
    
    except Exception as e:
        logger.error(f"[FILTERS] Extraction failed: {e}")
        return {}
    
# ── Generate Ranking Keywords ──────────────────────────────

def generate_ranking_keywords(query: str,config: RunnableConfig) -> list[str]:
    """
    Generate 5 financial keywords from the query.
    Keywords filter document content before MMR search.
    Only chunks containing at least one keyword are returned.
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

        result = llm_structured.invoke(prompt)
        logger.info(f"[FILTERS] Keywords: {result.keywords}")
        return result.keywords
    
    except Exception as e:
        logger.error(f"[FILTERS] Keyword generation failed: {e}")
        return []
    
