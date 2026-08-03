




import logging
import yfinance as yf
from backend.llm.llm_factory import llm_nano

logger = logging.getLogger(__name__)

def fetch_market_data(ticker: str) -> dict | None:
    """
    Fetch real-time market data for a single ticker using yfinance.
    Returns structured market data or None if fetch fails.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        name = info.get("longName") or info.get("shortName")
        if not name:
            logger.warning(f"[MARKET_API] No data found for {ticker}")
            return None
        
        data = {
            "ticker": ticker,
            "name": name,
            "current_price": info.get("currentPrice")
                             or info.get("regularMarketPrice"),
            "price_change": info.get("regularMarketChangePercent"),
            "volume": info.get("regularMarketVolume"),
            "market_cap": info.get("marketCap"),
            "pe_ratio":      info.get("trailingPE"),
            "52w_high":      info.get("fiftyTwoWeekHigh"),
            "52w_low":       info.get("fiftyTwoWeekLow"),
            "sector":        info.get("sector"),
        }

        logger.info(
            f"[MARKET_API] {ticker}: "
            f"price={data['current_price']}, "
            f"change={data['price_change']}"
        )

        return data

    except Exception as e:
        logger.error(f"[MARKET_API] Failed to fetch {ticker}: {e}")
        return None
    
def fetch_market_data_bulk(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch market data for multiple tickers.
    Returns dict of tickers -> market data.
    Skips failed tickers silently.
    """

    results = {}
    for ticker in tickers:
        data = fetch_market_data(ticker)
        if data:
            results[ticker] = data
    return results



def extract_tickers_from_query(market_query: str) -> str:
    """
    Convert natural language market query → comma-separated tickers.
    Called BEFORE parse_tickers() when query isn't already symbols.
    """
    prompt = f"""Extract the most relevant stock ticker symbols for this query.
    Return ONLY a comma-separated list of ticker symbols, nothing else.

    Query: {market_query}

    Examples:
    - "AI technology companies live price trends" → "NVDA, MSFT, GOOGL, META, AMD"
    - "big tech prices" → "AAPL, MSFT, GOOGL, AMZN, META"
    - "AAPL, TSLA" → "AAPL, TSLA"

    Tickers:"""

    response = llm_nano.invoke(prompt)
    return response.content.strip()



def parse_tickers(market_query: str) -> list[str]:
    """
    Parse comma-separated ticker string into list.
    Example: "AAPL, MSFT, NVDA" -> ["AAPL", "MSFT", "NVDA]
    """
    if not market_query or not market_query.strip():
        return []
    
    return [
        t.strip().upper()
        for t in market_query.split(",")
        if t.strip()
    ]
