


import logging
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.services.market_api_service import extract_tickers_from_query, fetch_market_data_bulk, parse_tickers
from backend.services.redis_service import cache_get, cache_set, make_cache_key




logger = logging.getLogger(__name__)

# cache TTL - 5 minutes for market data

MARKET_CACHE_TTL = 300
MAX_RETRIES      = 3

@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=8)
)
def fetch_with_retry(tickers: list[str]) -> dict:
    """
    Fetch market data with retry on failure.
    Retries up to 3 times with exponential backoff.
    2s → 4s → 8s between retries.
    """
    return fetch_market_data_bulk(tickers)


def run_market_retrieval(market_query: str) -> dict:
    """
    Fetch live market data.

    Flow:
    1. Check Redis cache for each ticker
    2. Cache hit  → return cached data immediately
    3. Cache miss → fetch from yfinance (with 3 retries)
    4. API success → store in cache → return fresh data
    5. API fails after 3 retries → check stale cache
    6. Stale cache hit → return stale data (degraded warning)
    7. Cache also empty → degraded mode (no data available)
x
    Degraded mode ONLY when:
    cache empty AND API failed after all retries
    """
    logger.info(f"[MARKET_NODE] Market Query = {market_query}")
    
    # ── Resolve natural language → ticker symbols ──────────
    resolved = extract_tickers_from_query(market_query)
    logger.info(f"[MARKET] Resolved: '{market_query}' → '{resolved}'")
    
    tickers = parse_tickers(resolved)

    if not tickers:
        logger.info("[MARKET] No tickers to fetch")
        return {
            "source": "market",
            "data": {},
            "confidence": 0.0,
            "cached": False
        }
    
    logger.info(f"[MARKET] Fetching data for: {tickers}")

    results = {}
    is_cached = False
    to_fetch =[]

    # Step 1 - Check cache for each ticker
    for ticker in tickers:
        key = make_cache_key("market", ticker)
        cached_val = cache_get(key)
        if cached_val:
            results[ticker] = cached_val
            is_cached       = True
            logger.info(f"[MARKET] Cache hit: {ticker}")
        else:
            to_fetch.append(ticker)
            logger.info(f"[MARKET] Cache miss: {ticker}")

    # ── Step 2 — fetch from API for cache misses ───────────
    if to_fetch:
        try:
            # fetch with retry — 3 attempts with backoff
            fresh = fetch_with_retry(to_fetch)

            for ticker, data in fresh.items():
                results[ticker] = data
                key = make_cache_key("market", ticker)
                cache_set(key, data, ttl=MARKET_CACHE_TTL)
                logger.info(
                    f"[MARKET] Fresh data cached: {ticker}"
                )

            # log any tickers that returned no data
            failed = set(to_fetch) - set(fresh.keys())
            for ticker in failed:
                logger.warning(
                    f"[MARKET] No data returned for {ticker}"
                )

        except Exception as e:
            # ── Step 3 — API failed after all retries ─────
            # try stale cache as last fallback
            logger.error(
                f"[MARKET] yfinance failed after {MAX_RETRIES} "
                f"retries: {e}. Trying stale cache..."
            )

            for ticker in to_fetch:
                key       = make_cache_key("market", ticker)
                stale_val = cache_get(key)

                if stale_val:
                    results[ticker] = stale_val
                    is_cached       = True
                    logger.warning(
                        f"[MARKET] Using stale cache for {ticker}"
                    )
                else:
                    logger.error(
                        f"[MARKET] No cache for {ticker} — "
                        f"degraded for this ticker"
                    )

    # ── Step 4 — check if degraded ─────────────────────────
    # degraded ONLY when cache was empty AND API failed
    degraded   = len(results) == 0
    confidence = 0.8 if results else 0.0

    if degraded:
        logger.error(
            "[MARKET] Fully degraded — "
            "no data from API or cache"
        )
    else:
        logger.info(
            f"[MARKET] Complete. "
            f"{len(results)} tickers retrieved. "
            f"Cached: {is_cached}, Degraded: {degraded}"
        )

    return {
        "source":     "market",
        "data":       results,
        "confidence": confidence,
        "cached":     is_cached,
        "degraded":   degraded
    }

def market_node(state: dict) -> dict:
    """
    LangGraph node for market data retrieval.
    Reads market_query from state.
    Adds market_result to state.
    """
    market_query = state.get("market_query", "")

    if not market_query:
        logger.info("[MARKET_NODE] No market query - skipping")
        return {
            **state,
            "market_result": {
                "source": "market",
                "data": {},
                "confidence": 0.0,
                "cached": False,
                "degraded":   False
            }
        }
    
    logger.info(f"[MARKET_NODE ] market_query: {market_query}")
    market_result = run_market_retrieval(market_query)

    return {
        **state,
        "market_result": market_result
    }
