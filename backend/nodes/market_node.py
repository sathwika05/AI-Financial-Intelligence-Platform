import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.services.market_api_service import (
    extract_tickers_from_query,
    fetch_market_data_bulk,
    parse_tickers,
)
from backend.services.redis_service import (
    cache_get,
    cache_set,
    make_cache_key,
)


logger = logging.getLogger(__name__)


MARKET_CACHE_TTL = 300
MAX_RETRIES = 3


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(
        multiplier=1,
        min=2,
        max=8,
    ),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def fetch_with_retry(
    tickers: list[str],
) -> dict[str, Any]:
    """
    Fetch market data with retries.

    Retries failed requests up to three times using
    exponential backoff.
    """
    return fetch_market_data_bulk(tickers)


def empty_market_result() -> dict[str, Any]:
    """Return a consistent empty market-result structure."""
    return {
        "source": "market",
        "market_data": {},
        "confidence": 0.0,
        "cached": False,
        "stale": False,
        "degraded": False,
        "missing_tickers": [],
    }


async def run_market_retrieval(
    market_query: str,
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Fetch current market data for tickers in the query.

    Flow:
    1. Resolve the natural-language query into ticker symbols.
    2. Check Redis for each ticker.
    3. Fetch cache misses from the market-data provider.
    4. Cache fresh results.
    5. If the provider fails, try stale cached data.
    6. Mark the response degraded when any ticker is unavailable.
    """
    normalized_query = market_query.strip()

    logger.info(
        "[MARKET] Processing query=%r",
        normalized_query,
    )

    resolved_tickers = await extract_tickers_from_query(
        normalized_query, config
    )

    logger.info(
        "[MARKET] Resolved query=%r tickers=%r",
        normalized_query,
        resolved_tickers,
    )

    tickers = list(
        dict.fromkeys(
            ticker.upper()
            for ticker in parse_tickers(resolved_tickers)
            if ticker
        )
    )

    if not tickers:
        logger.info(
            "[MARKET] No ticker symbols resolved"
        )

        result = empty_market_result()
        result["degraded"] = True
        return result

    logger.info(
        "[MARKET] Requested tickers=%s",
        tickers,
    )

    results: dict[str, Any] = {}
    to_fetch: list[str] = []

    used_cache = False
    used_stale_cache = False
    api_failed = False

    # Check normal cache.
    for ticker in tickers:
        cache_key = make_cache_key(
            "market",
            ticker,
        )

        cached_value = cache_get(cache_key)

        if cached_value is not None:
            results[ticker] = cached_value
            used_cache = True

            logger.info(
                "[MARKET] Cache hit ticker=%s",
                ticker,
            )
        else:
            to_fetch.append(ticker)

            logger.info(
                "[MARKET] Cache miss ticker=%s",
                ticker,
            )

    # Fetch cache misses from the provider.
    if to_fetch:
        try:
            fresh_results = fetch_with_retry(
                to_fetch
            )

            if not isinstance(fresh_results, dict):
                raise TypeError(
                    "Market-data provider returned an invalid "
                    "response; expected a dictionary"
                )

            for ticker, data in fresh_results.items():
                normalized_ticker = ticker.upper()

                if data is None:
                    continue

                results[normalized_ticker] = data

                cache_key = make_cache_key(
                    "market",
                    normalized_ticker,
                )

                cache_set(
                    cache_key,
                    data,
                    ttl=MARKET_CACHE_TTL,
                )

                logger.info(
                    "[MARKET] Fresh data cached ticker=%s",
                    normalized_ticker,
                )

            missing_from_api = (
                set(to_fetch) - set(results)
            )

            for ticker in sorted(missing_from_api):
                logger.warning(
                    "[MARKET] Provider returned no data "
                    "ticker=%s",
                    ticker,
                )

        except Exception:
            api_failed = True

            logger.exception(
                "[MARKET] Provider failed after %s attempts; "
                "checking stale cache",
                MAX_RETRIES,
            )

            # This only works as stale fallback if cache_get can
            # retrieve expired values. Otherwise use a separate
            # stale-cache function or stale cache key.
            for ticker in to_fetch:
                cache_key = make_cache_key(
                    "market",
                    ticker,
                )

                stale_value = cache_get(cache_key)

                if stale_value is not None:
                    results[ticker] = stale_value
                    used_cache = True
                    used_stale_cache = True

                    logger.warning(
                        "[MARKET] Using stale cache ticker=%s",
                        ticker,
                    )
                else:
                    logger.error(
                        "[MARKET] No provider or cached data "
                        "ticker=%s",
                        ticker,
                    )

    missing_tickers = [
        ticker
        for ticker in tickers
        if ticker not in results
    ]

    # Degraded when one or more requested tickers are missing,
    # stale data was required, or the external API failed.
    degraded = bool(
        missing_tickers
        or used_stale_cache
        or api_failed
    )

    if not results:
        confidence = 0.0
    elif used_stale_cache:
        confidence = 0.5
    elif missing_tickers:
        confidence = 0.6
    elif used_cache:
        confidence = 0.8
    else:
        confidence = 0.9

    logger.info(
        "[MARKET] Completed retrieved=%s requested=%s "
        "cached=%s stale=%s degraded=%s missing=%s",
        len(results),
        len(tickers),
        used_cache,
        used_stale_cache,
        degraded,
        missing_tickers,
    )

    return {
        "source": "market",
        "market_data": results,
        "confidence": confidence,
        "cached": used_cache,
        "stale": used_stale_cache,
        "degraded": degraded,
        "missing_tickers": missing_tickers,
    }


async def market_node(
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    LangGraph node for market-data retrieval.

    Reads `market_query` from state and returns `market_result`
    as a partial update. Only the key this node owns is returned:
    echoing the whole state back would re-append any channel that
    carries a reducer.
    """
    market_query = state.get(
        "market_query",
        "",
    )

    if not isinstance(market_query, str):
        raise TypeError(
            "market_query must be a string"
        )

    normalized_query = market_query.strip()

    if not normalized_query:
        logger.info(
            "[MARKET_NODE] No market query; skipping"
        )

        return {
            "market_result": empty_market_result(),
        }

    logger.info(
        "[MARKET_NODE] market_query=%r",
        normalized_query,
    )

    # The market API and current Redis helpers are synchronous.
    # Running them in a worker thread avoids blocking the
    # LangGraph event loop.
    market_result = await asyncio.to_thread(
        run_market_retrieval,
        normalized_query,
    )

    return {
        "market_result": market_result,
    }