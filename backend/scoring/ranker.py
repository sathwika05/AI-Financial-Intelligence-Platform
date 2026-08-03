







import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from backend.services.postgres_service import engine
from sqlalchemy import text

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model = "gpt-5.4-mini",temperature=0)

# ── Normalization ──────────────────────────────────────────

def normalize_pe_ratio(pe_ratio: float) -> float:
    """
    Lower PE = better value = higher score.
    PE <= 0  → 0.0 (losing money)
    PE = 200 → 0.0 (very expensive)
    PE = 10  → 0.95 (very cheap)   
    """
    if not pe_ratio or pe_ratio <= 0:
        return 0.0
    return round(1.0 - min(pe_ratio/200.0,1.0),3)


def normalize_revenue_growth(revenue_growth: float) -> float:
    """
    Higher growth = higher score.
    Negative growth → 0.0
    100%+ growth    → 1.0
    """
    if revenue_growth is None:
        return 0.0
    return round(min(max(revenue_growth, 0.0), 1.0), 3)

def normalize_price_change(price_change: float) -> float:
    """
    Maps price change % to 0-1.
    -10% → 0.0
     0%  → 0.5
    +10% → 1.0
    """
    if price_change is None:
        return 0.5
    return round(
        min(max((price_change + 10) / 20, 0.0), 1.0), 3
    )

# ── Fetch Companies from DB ────────────────────────────────

async def get_companies_from_db(tickers: list[str] = None) -> list[dict]:
    """
    Fetch company financial metrics from DB.
    If tickers provided → fetch only those companies.
    Otherwise → fetch top 20 by revenue growth.
    """
    try:
        async with engine.connect() as conn:
            if tickers:
                placeholders = ",".join(
                    f":t{i}" for i in range(len(tickers))
                )
                params = {
                    f"t{i}": t for i, t in enumerate(tickers)
                }
                where = (
                    f"WHERE UPPER(c.ticker) IN ({placeholders})"
                )
            else:
                params = {}
                where  = ""

            result = await conn.execute(text(f"""
                SELECT
                    c.id,
                    c.name,
                    c.ticker,
                    c.sector,
                    c.market_cap,
                    fm.pe_ratio,
                    fm.eps,
                    fm.revenue_growth
                FROM companies c
                JOIN financial_metrics fm
                    ON c.id = fm.company_id
                {where}
                ORDER BY fm.revenue_growth DESC NULLS LAST
                LIMIT 20
            """), params)

            rows = result.fetchall()

        return [dict(row._mapping) for row in rows]

    except Exception as e:
        logger.error(f"[RANKER] DB fetch failed: {e}")
        return []


# ── Per Company Scoring ────────────────────────────────────

def score_company_valuation(
    company:       dict,
    market_result: dict = None
) -> float:
    """
    Valuation score for one company.
    70% PE ratio + 30% live price momentum.
    """
    pe_score    = normalize_pe_ratio(company.get("pe_ratio"))
    price_score = 0.5  # neutral default

    if market_result:
        ticker      = company.get("ticker", "").upper()
        market_data = market_result.get("data", {}).get(ticker)
        if market_data:
            price_score = normalize_price_change(
                market_data.get("price_change")
            )

    return round((pe_score * 0.7) + (price_score * 0.3), 3)

def score_company_growth(company: dict) -> float:
    """
    Growth score for one company.
    70% revenue growth + 30% EPS profitability.
    """
    growth_score     = normalize_revenue_growth(
        company.get("revenue_growth")
    )
    profitable_score = 1.0 if (
        company.get("eps") and company.get("eps") > 0
    ) else 0.0

    return round(
        (growth_score * 0.7) + (profitable_score * 0.3), 3
    )

def score_company_relevance(
    company:       dict,
    vector_result: dict = None
) -> float:
    """
    Relevance score for one company.
    Reuses cosine similarity scores already computed
    by pgvector during vector retrieval.
    Groups chunks by company → averages their scores.
    """
    if not vector_result:
        return 0.0

    chunks = vector_result.get("chunks", [])
    if not chunks:
        return 0.0

    company_id = company.get("id")
    name       = company.get("name", "").lower()
    ticker     = company.get("ticker", "").lower()

    # find chunks belonging to this company
    company_chunks = [
        c for c in chunks
        if c.get("company_id") == company_id
        or name   in c.get("content", "").lower()
        or ticker in c.get("content", "").lower()
    ]

    if not company_chunks:
        # no specific chunks → use avg of all (lower weight)
        all_similarities = [
            c.get("similarity", 0.0) for c in chunks
        ]
        return round(
            sum(all_similarities) / len(all_similarities) * 0.5,
            3
        )

    similarities = [
        c.get("similarity", 0.0) for c in company_chunks
    ]
    return round(sum(similarities) / len(similarities), 3)


def score_company_sentiment(
    company:       dict,
    vector_result: dict = None
) -> float:
    """
    Sentiment score for one company.
    Keyword analysis on chunks mentioning this company.
    positive keywords / total keywords = sentiment score
    """
    if not vector_result:
        return 0.5

    chunks = vector_result.get("chunks", [])
    if not chunks:
        return 0.5

    name   = company.get("name",   "").lower()
    ticker = company.get("ticker", "").lower()

    positive_keywords = [
        "strong", "growth", "exceeded", "beat", "record",
        "positive", "surge", "gain", "outperform", "robust",
        "momentum", "bullish", "upgrade", "raised",
        "accelerating", "breakthrough", "demand", "innovative"
    ]
    negative_keywords = [
        "decline", "miss", "loss", "weak", "concern",
        "negative", "drop", "fail", "downgrade", "risk",
        "slowdown", "bearish", "cut", "warning",
        "disappointing", "layoff", "lawsuit", "recall"
    ]

    positive_count = 0
    negative_count = 0

    for chunk in chunks:
        content = chunk.get("content", "").lower()
        if name not in content and ticker not in content:
            continue
        positive_count += sum(
            1 for kw in positive_keywords if kw in content
        )
        negative_count += sum(
            1 for kw in negative_keywords if kw in content
        )

    total = positive_count + negative_count
    if total == 0:
        return 0.5  # neutral

    return round(positive_count / total, 3)

# ── Dynamic Weights ────────────────────────────────────────

def get_dynamic_weights(
    has_sql:    bool,
    has_vector: bool,
    has_market: bool = False
) -> dict:
    """
    Adjust weights based on intent-driven source availability.
    Normalizes automatically when a source is missing.

    VALUATION / GROWTH (SQL only):
        val=0.57, growth=0.43, rel=0.00, sent=0.00

    SENTIMENT (Vector only):
        val=0.00, growth=0.00, rel=0.67, sent=0.33

    MIXED (SQL + Vector + Market):
        val=0.40, growth=0.30, rel=0.20, sent=0.10
    """
    base = {
        "valuation": 0.40 if has_sql    else 0.0,
        "growth":    0.30 if has_sql    else 0.0,
        "relevance": 0.20 if has_vector else 0.0,
        "sentiment": 0.10 if has_vector else 0.0
    }

    # Market API (MIXED only) boosts sentiment with live price/news signal
    if has_market:
        base["sentiment"] += 0.10

    total = sum(base.values())
    if total == 0:
        return base

    return {
        dim: round(w / total, 3)
        for dim, w in base.items()
    }


# ── LLM Reranker ──────────────────────────────────────────

def llm_rerank_companies(
    companies:     list[dict],
    query:         str,
    sql_answer:    str  = None,
    vector_chunks: list = None,
    market_data:   dict = None
) -> dict[str, float]:
    """
    Optional LLM-based holistic scoring per company.
    LLM reads all evidence and scores each company 0-1.
    Returns dict of ticker → llm_score.
    Falls back to empty dict if LLM fails.
    market_data structure:
    {
        "NVDA": {"ticker": "NVDA", "name": ..., "current_price": ...,
                 "price_change": ..., "volume": ..., "pe_ratio": ..., "sector": ...},
        "AAPL": {...},
    }

    """
    if not companies:
        return {}

    company_list = "\n".join([
        f"- {c['name']} ({c['ticker']}): "
        f"PE={c.get('pe_ratio')}, "
        f"Growth={c.get('revenue_growth')}, "
        f"EPS={c.get('eps')}"
        for c in companies[:10]
    ])

    chunk_text = ""
    if vector_chunks:
        chunk_text = "\n".join([
            f"- {c.get('content', '')[:200]}"
            for c in vector_chunks[:5]
        ])

    sql_text = sql_answer or "No SQL data available"

    # Only populated for MIXED intent — loops over multiple tickers
    market_text = ""
    if market_data:
        lines = []
        for ticker, info in market_data.items():
            lines.append(
                f"- {ticker} ({info.get('name', 'N/A')}): "
                f"price=${info.get('current_price', 'N/A')}, "
                f"change={info.get('price_change', 'N/A')}%, "
                f"volume={info.get('volume', 'N/A')}, "
                f"PE={info.get('pe_ratio', 'N/A')}, "
                f"sector={info.get('sector', 'N/A')}"
            )
        market_text = "Live market data:\n" + "\n".join(lines)
    
    system = SystemMessage(content="""
You are a financial analyst scoring companies.
Score each company from 0.0 to 1.0 based on:
- Financial strength (PE ratio, revenue growth, EPS)
- News sentiment from provided chunks
- Overall investment attractiveness for the query

Return ONLY a valid JSON object like:
{"NVDA": 0.87, "AAPL": 0.64, "MSFT": 0.71}
No explanation. No markdown. Just the JSON.
""")

    user = HumanMessage(content=f"""
Query: {query}

Companies to score:
{company_list}

SQL analysis:
{sql_text[:500]}

News context:
{chunk_text[:500]}

{market_text}

Score each company 0.0 to 1.0:
""")

    try:
        import json
        response = llm.invoke([system, user])
        content  = response.content.strip()
        content  = content.replace("```json", "").replace("```", "").strip()
        scores   = json.loads(content)
        return {k.upper(): float(v) for k, v in scores.items()}

    except Exception as e:
        logger.error(f"[RANKER] LLM scoring failed: {e}")
        return {}

# ── Main Reranker ──────────────────────────────────────────

async def rerank(
    query:         str,
    intent:        str,
    sql_result:    dict = None,
    vector_result: dict = None,
    market_result: dict = None
) -> list[dict]:
    """
    Main reranker — scores each company across all dimensions.

    Steps:
    1. Fetch companies from DB
    2. Get dynamic weights based on available results
    3. Score each company per dimension:
       - valuation  → PE ratio + price momentum
       - growth     → revenue growth + EPS
       - relevance  → avg chunk similarity (reuses pgvector scores)
       - sentiment  → keyword analysis on chunks
    4. Optional LLM holistic score
    5. Apply weighted sum → final score
    6. Sort descending → add rank number
    """
    has_sql    = (
        sql_result is not None and
        bool(sql_result.get("answer"))
    )
    has_vector = (
        vector_result is not None and
        bool(vector_result.get("chunks"))
    )

    has_market = (
        market_result is not None and
        bool(market_result.get("data"))   # or whatever key your market API returns
    )



    weights   = get_dynamic_weights(has_sql, has_vector, has_market)
    logger.info(f"[RANKER] Weights: {weights}")

    # fetch companies from DB
    market_tickers = list(
        market_result.get("data", {}).keys()
    ) if market_result else []

    companies = await get_companies_from_db(
        market_tickers if market_tickers else None
    )

    if not companies:
        logger.warning("[RANKER] No companies found in DB")
        return []

    # optional LLM scoring
    llm_scores = llm_rerank_companies(
        companies     = companies,
        query         = query,
        sql_answer    = sql_result.get("answer") if sql_result else None,
        vector_chunks = vector_result.get("chunks") if vector_result else None,
        market_data   = market_result.get("data") if market_result else None
    )

    # score each company
    ranked = []
    for company in companies:
        ticker = company.get("ticker", "").upper()
        name   = company.get("name", "")

        val_score = score_company_valuation(
            company, market_result
        ) if has_sql else 0.0

        growth_score = score_company_growth(
            company
        ) if has_sql else 0.0

        rel_score = score_company_relevance(
            company, vector_result
        ) if has_vector else 0.0

        sent_score = score_company_sentiment(
            company, vector_result
        ) if has_vector else 0.0

        scores = {
            "valuation":  val_score,
            "growth":     growth_score,
            "relevance":  rel_score,
            "sentiment":  sent_score
        }

        # weighted sum
        final_score = round(
            (scores["valuation"] * weights["valuation"]) +
            (scores["growth"]    * weights["growth"])    +
            (scores["relevance"] * weights["relevance"]) +
            (scores["sentiment"] * weights["sentiment"]),
            3
        )
        # blend with LLM score if available
        llm_score = llm_scores.get(ticker)
        if llm_score is not None:
            final_score = round(
                (final_score * 0.7) + (llm_score * 0.3), 3
            )

        ranked.append({
            "name":         name,
            "ticker":       ticker,
            "sector":       company.get("sector"),
            "final_score":  final_score,
            "llm_score":    llm_score,
            "scores":       scores,
            "weights":      weights,
            "metrics": {
                "pe_ratio":       company.get("pe_ratio"),
                "eps":            company.get("eps"),
                "revenue_growth": company.get("revenue_growth"),
                "market_cap":     company.get("market_cap")
            }
        })

    # sort by final score descending
    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    # add rank number
    for i, company in enumerate(ranked, 1):
        company["rank"] = i

    if ranked:
        logger.info(
            f"[RANKER] Ranked {len(ranked)} companies. "
            f"Top: {ranked[0]['name']} "
            f"({ranked[0]['final_score']})"
        )

    return ranked