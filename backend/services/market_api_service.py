import logging
import re
from typing import Any

import yfinance as yf
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier


logger = logging.getLogger(__name__)


MAX_EXTRACTED_TICKERS = 10
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


@traceable(
    name="market_api_fetch",
    run_type="tool",
    tags=["market", "external-api"],
)
def fetch_market_data(
    ticker: str,
) -> dict[str, Any] | None:
    """
    Fetch market data for one ticker using yfinance.

    Returns structured market data or None when no valid
    market data is available.
    """
    normalized_ticker = ticker.strip().upper()

    if not normalized_ticker:
        return None

    try:
        stock = yf.Ticker(normalized_ticker)
        info = stock.info

        name = (
            info.get("longName")
            or info.get("shortName")
        )

        if not name:
            logger.warning(
                "[MARKET_API] No data found ticker=%s",
                normalized_ticker,
            )
            return None

        data = {
            "ticker": normalized_ticker,
            "name": name,
            "current_price": (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
            ),
            "price_change": info.get(
                "regularMarketChangePercent"
            ),
            "volume": info.get(
                "regularMarketVolume"
            ),
            "market_cap": info.get(
                "marketCap"
            ),
            "pe_ratio": info.get(
                "trailingPE"
            ),
            "52w_high": info.get(
                "fiftyTwoWeekHigh"
            ),
            "52w_low": info.get(
                "fiftyTwoWeekLow"
            ),
            "sector": info.get(
                "sector"
            ),
        }

        logger.info(
            "[MARKET_API] ticker=%s price=%s change=%s",
            normalized_ticker,
            data["current_price"],
            data["price_change"],
        )

        return data

    except Exception:
        logger.exception(
            "[MARKET_API] Failed to fetch ticker=%s",
            normalized_ticker,
        )
        return None


@traceable(
    name="market_api_fetch_bulk",
    run_type="tool",
    tags=["market", "external-api"],
)
def fetch_market_data_bulk(
    tickers: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Fetch market data for multiple ticker symbols.

    Failed ticker lookups are omitted from the result.
    """
    results: dict[str, dict[str, Any]] = {}

    normalized_tickers = list(
        dict.fromkeys(
            ticker.strip().upper()
            for ticker in tickers
            if ticker and ticker.strip()
        )
    )

    for ticker in normalized_tickers:
        data = fetch_market_data(ticker)

        if data is not None:
            results[ticker] = data

    return results


async def extract_tickers_from_query(
    market_query: str,
    config: RunnableConfig,
) -> str:
    """
    Convert a natural-language market query into a
    comma-separated ticker-symbol string.
    """
    normalized_query = market_query.strip()

    if not normalized_query:
        return ""

    # Avoid an LLM call when the input already appears to be
    # a comma-separated ticker list.
    directly_parsed = parse_tickers(
        normalized_query
    )

    raw_parts = [
        part.strip()
        for part in normalized_query.split(",")
        if part.strip()
    ]

    if (
        raw_parts
        and len(directly_parsed) == len(raw_parts)
        and all(
            TICKER_PATTERN.fullmatch(part.upper())
            for part in raw_parts
        )
    ):
        return ", ".join(directly_parsed)

    llm = get_llm_client(
        config,
        LLMTier.SMALL,
    )

    system_message = SystemMessage(
        content="""
You extract public stock ticker symbols from financial queries.

Rules:
- Return only a comma-separated list of ticker symbols.
- Do not return markdown or explanations.
- Use uppercase ticker symbols.
- Return no more than 10 tickers.
- Do not invent tickers when the company cannot be identified.
- If no public ticker can be identified, return an empty string.

Examples:
Query: AI technology companies live price trends
Output: NVDA, MSFT, GOOGL, META, AMD

Query: big tech prices
Output: AAPL, MSFT, GOOGL, AMZN, META

Query: AAPL, TSLA
Output: AAPL, TSLA
""".strip()
    )

    response = await llm.ainvoke(
        [
            system_message,
            HumanMessage(
                content=f"Query: {normalized_query}"
            ),
        ],
        config=config,
    )

    content = response.content

    if not isinstance(content, str):
        logger.warning(
            "[MARKET_API] Ticker extractor returned "
            "non-string content"
        )
        return ""

    tickers = parse_tickers(content)[
        :MAX_EXTRACTED_TICKERS
    ]

    logger.info(
        "[MARKET_API] query=%r resolved_tickers=%s",
        normalized_query,
        tickers,
    )

    return ", ".join(tickers)


def parse_tickers(
    ticker_text: str,
) -> list[str]:
    """
    Parse and validate comma-separated ticker symbols.

    Example:
        "AAPL, MSFT, NVDA"
        -> ["AAPL", "MSFT", "NVDA"]
    """
    if not ticker_text or not ticker_text.strip():
        return []

    normalized_tickers: list[str] = []

    for value in ticker_text.split(","):
        ticker = value.strip().upper()
        logging.info("[MARKET_API_SERVICE] ticker = %s",ticker)
        if not ticker:
            continue

        if not TICKER_PATTERN.fullmatch(ticker):
            logger.warning(
                "[MARKET_API] Ignoring invalid ticker=%r",
                ticker,
            )
            continue

        normalized_tickers.append(ticker)

    return list(
        dict.fromkeys(normalized_tickers)
    )