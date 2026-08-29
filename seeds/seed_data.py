import asyncio
import csv
import hashlib
import logging
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yfinance as yf
import requests

import os
from pathlib import Path

from backend.models.db_models import Company, Document, DocumentChunk, FinancialMetric
# Duplicate identity is shared with the queue worker rather than defined
# twice: two implementations would stop recognising each other's rows.
from backend.ingestion.dedupe import (
    find_duplicate_document,
    hash_content,
    normalize_content,
)

from sqlalchemy import select, text
from backend.services.postgres_service import AsyncSessionLocal
from dotenv import load_dotenv


# companies.csv is expected to be in the same directory as this seed script.
CSV_PATH = Path(__file__).parent / "companies.csv"

# seed_data.py lives inside the seeds/ directory.
# parents[1] therefore points to the project root directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Build an absolute path to the project's .env file.
# Using an absolute path avoids depending on the directory from which
# the seed command is executed.
ENV_PATH = PROJECT_ROOT / ".env"

# Load local environment variables before calling os.getenv().
load_dotenv(dotenv_path=ENV_PATH)

# Read the Alpha Vantage API key from the environment.
# Alpha Vantage is the primary provider for recent company news.
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# Read the Finnhub API key from the environment.
# Finnhub is used as the fallback provider when Alpha Vantage is
# unavailable, rate-limited, or returns no usable news.
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

# Print only whether each API key was loaded.
# Do not print the actual keys because API keys are secrets.
print("Environment file found =", ENV_PATH.exists())
print("Alpha Vantage key loaded =", bool(ALPHA_VANTAGE_KEY))
print("Finnhub key loaded =", bool(FINNHUB_API_KEY))

# Tracks whether Alpha Vantage should still be called during this seed run.
#
# It starts as True because Alpha Vantage is the primary news provider.
#
# If Alpha Vantage reports that its daily quota/rate limit has been reached,
# fetch_alpha_vantage_news() changes this value to False.
#
# After that, remaining companies skip Alpha Vantage and immediately use
# Finnhub instead of repeatedly making requests that we know will fail.
ALPHA_VANTAGE_AVAILABLE = True


logger = logging.getLogger(__name__)


# Minimum Alpha Vantage relevance for an article to be owned by the ticker
# that was queried for it.
#
# NEWS_SENTIMENT returns market news *related to* a ticker, not news *about*
# it, and the association can be very loose: one AMD bond-sale article came
# back for JPM, BAC, MS and C as well, presumably because banks underwrite
# such sales. Alpha Vantage grades each association in the article's
# `ticker_sentiment` list, which is exactly the signal needed to tell the
# real subject from an incidental mention.
#
# Set from the 2026-08-18 seed, not from the documentation. Measuring each
# stored article against whether its text actually names the company it was
# filed under showed the score is close to bimodal rather than a smooth
# gradient:
#
#     relevance    docs   names its company
#     0.56-0.59      5    40%
#     0.60-0.69     30    27%
#     0.71-0.73      3    33%
#     0.83           1    100%
#     0.91-1.00     20    100%
#
# Every article at 0.83 or above was genuinely about its company; below 0.73
# roughly seven in ten were not. The first threshold here was 0.35, chosen
# from the documented 0.0-1.0 range with no data to hand, and it let almost
# all of the topically-adjacent articles through — an article about Fabrinet
# filed under AMD, one about Netflix under GOOGL, one about Nike under META.
#
# 0.75 sits in the empty band between the two clusters, so it is not a knife
# edge: no observed article scored between 0.73 and 0.83.
MIN_NEWS_RELEVANCE = 0.75


# How many articles to keep per company, per provider, before filtering.
#
# Was 3, which left 1.4 documents per company once relevance filtering and
# deduplication had run, and twelve companies with none at all. RAGAS
# context recall and entity recall are bounded by that: retrieval cannot
# return what was never fetched.
#
# Raising it costs no additional Alpha Vantage quota. That quota is counted
# in requests, and this seed makes exactly one request per ticker whatever
# the limit — so twelve articles and three cost the same one request.
#
# The real Alpha Vantage constraint is requests per day. When it is
# reached, fetch_alpha_vantage_news sets ALPHA_VANTAGE_AVAILABLE to False
# and every remaining ticker falls through to Finnhub, which has no
# relevance score and therefore cannot be filtered. Watch the
# "Alpha Vantage unavailable" line in a seed run to see where that happened
# — companies after it get unfiltered articles.
MAX_ARTICLES_PER_COMPANY = 12


# Query parameters that identify a marketing campaign rather than a
# document. Two URLs differing only by these point at the same article.
TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    }
)


def canonicalize_url(url: str | None) -> str | None:
    """
    Reduce a URL to a stable identity for duplicate detection only.

    Deliberately conservative — this value is stored and compared, never
    fetched, so it only has to be consistent. Parameters that are not known
    tracking junk are preserved, because a query string frequently *is* the
    document (`?id=123`), and dropping it would collapse distinct articles
    into one.
    """
    if not url:
        return None

    cleaned = url.strip()

    if not cleaned:
        return None

    try:
        parts = urlsplit(cleaned)
    except ValueError:
        # Unparseable: fall back to the trimmed string so the article still
        # has some identity rather than none.
        return cleaned

    # Case-insensitive per RFC 3986; the path is left alone because it is
    # case-sensitive on most servers.
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    kept_params = [
        (key, value)
        for key, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
        if key.lower() not in TRACKING_QUERY_PARAMS
    ]

    query = urlencode(kept_params)

    # "example.com/a/" and "example.com/a" are the same article. The bare
    # root is left as-is, since "" and "/" both mean the root already.
    path = parts.path

    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # The fragment is a position within a page, not a different page.
    return urlunsplit((scheme, netloc, path, query, ""))




def get_ticker_relevance(
    ticker_sentiment: object,
    ticker: str,
) -> float | None:
    """
    Alpha Vantage's relevance for one ticker within one article.

    Returns None when the ticker is absent from the list, which is itself
    meaningful: the provider returned the article for this ticker but does
    not associate the two, so the article is not about this company.

    Alpha Vantage sends the score as a string, so it is parsed rather than
    compared directly; anything unparseable is treated as absent instead of
    being coerced to zero, keeping "no opinion" distinct from "no relevance".
    """
    if not isinstance(ticker_sentiment, list):
        return None

    wanted = (ticker or "").strip().upper()

    if not wanted:
        return None

    for entry in ticker_sentiment:
        if not isinstance(entry, dict):
            continue

        entry_ticker = str(
            entry.get("ticker") or ""
        ).strip().upper()

        if entry_ticker != wanted:
            continue

        raw_score = entry.get("relevance_score")

        try:
            return float(raw_score)
        except (TypeError, ValueError):
            return None

    return None



def fetch_yahoo_data(ticker: str) -> dict | None:
    """
    Fetch structured company and financial data from Yahoo Finance.

    yfinance is synchronous, so this function itself is blocking.
    Later, asyncio.to_thread() is used to run it in a worker thread.
    """

    try:
        # Create a yfinance Ticker object for the given stock symbol.
        # Example: ticker = "AAPL"
        # print(dir(yf))
        stock = yf.Ticker(ticker)

        # Fetch company/financial information from Yahoo Finance.
        info = stock.info

        print("info=", info)

        # Prefer longName. If it doesn't exist, use shortName.
        name = info.get("longName") or info.get("shortName")

        # If Yahoo Finance did not return a company name,
        # assume the ticker has no usable data and skip it.
        if not name:
            print(f" Skipping {ticker} - no data found")
            return None

        # Return only the fields needed by our database.
        return {
            "name": name,
            "sector": info.get("sector", "Unknown"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
        }

    except Exception as e:
        # Return None so the seed loop can skip this ticker
        # instead of stopping the entire seeding process.
        print(f"  Error fetching {ticker} from Yahoo: {e}")
        return None


def fetch_alpha_vantage_news(ticker: str) -> list[dict]:
    """
    Fetch recent news articles for a ticker from Alpha Vantage.

    requests is synchronous, so this function itself is blocking.
    Later, asyncio.to_thread() is used to run it in a worker thread.
    """

    global ALPHA_VANTAGE_AVAILABLE

    # If Alpha Vantage already hit its daily quota earlier in this seed run,
    # skip it and allow the fallback provider to handle the request.
    if not ALPHA_VANTAGE_AVAILABLE:
        return []

    # If the API key is not configured, skip Alpha Vantage.
    if not ALPHA_VANTAGE_KEY:
        print(f"Alpha Vantage key missing for {ticker}.")
        ALPHA_VANTAGE_AVAILABLE = False
        return []

    try:
        # NEWS_SENTIMENT returns news related to the requested ticker.
        url = "https://www.alphavantage.co/query"

        # Pass query parameters separately instead of manually concatenating
        # them into the URL. requests handles URL encoding safely.
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "limit": MAX_ARTICLES_PER_COMPANY,
            "apikey": ALPHA_VANTAGE_KEY,
        }

        # requests.get() is synchronous and waits for the HTTP response.
        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        # Raise an exception for HTTP errors such as 404 or 500.
        response.raise_for_status()

        # Convert the JSON response into a Python object.
        data = response.json()

        # Alpha Vantage's normal NEWS_SENTIMENT response is a dictionary.
        # If a different JSON shape is returned, treat it as unusable and
        # allow Finnhub to handle this ticker.
        if not isinstance(data, dict):
            print(
                f"Unexpected Alpha Vantage response for {ticker}: "
                f"{type(data).__name__}"
            )
            return []

        # Alpha Vantage can return HTTP 200 with an "Information" message
        # instead of the normal news feed.
        if "Information" in data:
            message = str(data["Information"])
            print(f"Alpha Vantage unavailable for {ticker}: {message}")

            # Disable Alpha Vantage for the remainder of this run only when
            # the message clearly indicates a request/rate-limit condition.
            normalized_message = message.lower()

            if (
                "rate limit" in normalized_message
                or "requests per day" in normalized_message
                or "call frequency" in normalized_message
            ):
                ALPHA_VANTAGE_AVAILABLE = False

            return []

        # Some Alpha Vantage throttling responses use a "Note" field.
        if "Note" in data:
            message = str(data["Note"])
            print(f"Alpha Vantage note for {ticker}: {message}")

            normalized_message = message.lower()

            if (
                "rate limit" in normalized_message
                or "requests per day" in normalized_message
                or "call frequency" in normalized_message
            ):
                ALPHA_VANTAGE_AVAILABLE = False

            return []

        # Handle explicit Alpha Vantage request errors.
        if "Error Message" in data:
            print(
                f"Alpha Vantage error for {ticker}: "
                f"{data['Error Message']}"
            )
            return []

        # Alpha Vantage stores returned news articles under "feed".
        feed = data.get("feed", [])

        # Validate the feed before iterating over it.
        if not isinstance(feed, list):
            print(f"Unexpected Alpha Vantage feed for {ticker}.")
            return []

        articles = []

        # Keep at most MAX_ARTICLES_PER_COMPANY articles.
        for item in feed[:MAX_ARTICLES_PER_COMPANY]:

            # Ignore malformed feed entries.
            if not isinstance(item, dict):
                continue

            # Prefer the article summary.
            # If summary is missing or null/empty, use the title.
            content = item.get("summary") or item.get("title") or ""

            # Do not create an empty Document row.
            if not content.strip():
                logger.info(
                    "[SEED_NEWS] provider=alpha_vantage ticker=%s "
                    "skipped reason=empty_content",
                    ticker,
                )
                continue

            # The article is only owned by the queried ticker if Alpha
            # Vantage says it is about that ticker. Without this check the
            # query ticker silently becomes the subject, which is how one
            # AMD article ended up filed under four banks.
            relevance = get_ticker_relevance(
                item.get("ticker_sentiment"),
                ticker,
            )

            if relevance is None:
                logger.info(
                    "[SEED_NEWS] provider=alpha_vantage ticker=%s "
                    "skipped reason=ticker_not_found",
                    ticker,
                )
                continue

            if relevance < MIN_NEWS_RELEVANCE:
                logger.info(
                    "[SEED_NEWS] provider=alpha_vantage ticker=%s "
                    "skipped reason=low_relevance relevance=%.4f",
                    ticker,
                    relevance,
                )
                continue

            logger.info(
                "[SEED_NEWS] provider=alpha_vantage ticker=%s "
                "accepted relevance=%.4f",
                ticker,
                relevance,
            )

            articles.append({
                "title": item.get("title") or None,
                "content": content,
                "doc_type": "news",

                # Store the original publisher/source when available.
                "source": item.get("source") or "Alpha Vantage",

                # Kept for duplicate detection; canonicalised at insert.
                "url": item.get("url") or None,

                # Recorded so the accepted association is auditable and the
                # threshold above can be retuned from real data.
                "relevance_score": relevance,
            })

        return articles

    except requests.RequestException as e:
        # Network/HTTP failure should not stop company/financial-data ingestion.
        # Return an empty list so Finnhub can be tried next.
        print(f" Alpha Vantage request failed for {ticker}: {e}")
        return []

    except ValueError as e:
        # response.json() raises ValueError if the response is not valid JSON.
        print(f" Alpha Vantage returned invalid JSON for {ticker}: {e}")
        return []

    except Exception as e:
        # Catch any other unexpected provider-specific issue without stopping
        # the entire company seed process.
        print(f" Alpha Vantage news failed for {ticker}: {e}")
        return []


def fetch_finnhub_news(ticker: str) -> list[dict]:
    """
    Fetch recent company news from Finnhub.

    Finnhub is used only as a fallback when Alpha Vantage is unavailable,
    rate-limited, or returns no usable news.

    requests is synchronous, so this function is blocking.
    fetch_company_news() is later executed with asyncio.to_thread().
    """

    # If the Finnhub key is missing, no fallback request can be made.
    if not FINNHUB_API_KEY:
        print(f"Finnhub key missing for {ticker}.")
        return []

    try:
        # Finnhub's company-news endpoint requires a date range.
        # Search the most recent 7 calendar days.
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        url = "https://finnhub.io/api/v1/company-news"

        # Send parameters separately so requests handles URL encoding.
        params = {
            "symbol": ticker,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "token": FINNHUB_API_KEY,
        }

        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        # Raise an exception for HTTP errors such as 401, 403, 429, or 500.
        response.raise_for_status()

        # Finnhub returns company-news data as a JSON list.
        data = response.json()

        # Validate the response format before processing it.
        if not isinstance(data, list):
            print(f"Unexpected Finnhub response for {ticker}: {data}")
            return []

        articles = []

        # Keep at most MAX_ARTICLES_PER_COMPANY, matching Alpha Vantage.
        for item in data[:MAX_ARTICLES_PER_COMPANY]:

            # Ignore malformed entries.
            if not isinstance(item, dict):
                continue

            # Prefer the article summary.
            # If summary is unavailable/null/empty, use the headline.
            content = item.get("summary") or item.get("headline") or ""

            # Do not create an empty Document row.
            if not content.strip():
                logger.info(
                    "[SEED_NEWS] provider=finnhub ticker=%s "
                    "skipped reason=empty_content",
                    ticker,
                )
                continue

            # No relevance gate here, deliberately. Finnhub is queried
            # through company-news?symbol=<ticker>, which is scoped to the
            # company by the endpoint itself, so there is no cross-ticker
            # association to second-guess and no relevance field to read.
            logger.info(
                "[SEED_NEWS] provider=finnhub ticker=%s accepted",
                ticker,
            )

            articles.append({
                "title": item.get("headline") or None,
                "content": content,
                "doc_type": "news",

                # Preserve the publisher/source when available.
                "source": item.get("source") or "Finnhub",

                # Kept for duplicate detection; canonicalised at insert.
                "url": item.get("url") or None,

                # Finnhub reports no per-ticker relevance, and the endpoint
                # makes one unnecessary.
                "relevance_score": None,
            })

        return articles

    except requests.RequestException as e:
        # HTTP/network failure should not stop the rest of the seed process.
        print(f" Finnhub request failed for {ticker}: {e}")
        return []

    except ValueError as e:
        # response.json() raises ValueError if the response is not valid JSON.
        print(f" Finnhub returned invalid JSON for {ticker}: {e}")
        return []

    except Exception as e:
        # Catch any other provider-specific error without stopping the seed.
        print(f" Finnhub news failed for {ticker}: {e}")
        return []


def fetch_company_news(ticker: str) -> list[dict]:
    """
    Fetch recent company news using the first available provider.

    Provider order:
    1. Alpha Vantage
    2. Finnhub fallback

    Finnhub is called only when Alpha Vantage returns no usable articles.
    """

    # Try Alpha Vantage first.
    articles = fetch_alpha_vantage_news(ticker)

    if articles:
        print(
            f"  News provider for {ticker}: "
            f"Alpha Vantage ({len(articles)} articles)"
        )
        return articles

    # If Alpha Vantage is unavailable or returned no articles,
    # try Finnhub next.
    print(f"  Trying Finnhub fallback for {ticker}...")

    articles = fetch_finnhub_news(ticker)

    if articles:
        print(
            f"  News provider for {ticker}: "
            f"Finnhub ({len(articles)} articles)"
        )
        return articles

    # Neither provider returned usable news.
    print(f"  No news available for {ticker} from configured providers.")
    return []


async def seed():
    """
    Seed Company, FinancialMetric, and Document tables.

    Companies are processed sequentially:
    Yahoo -> Company -> FinancialMetric -> News -> Documents -> wait -> next ticker.
    """

    # Create one async database session for the seeding operation.
    # The session is automatically closed when this block finishes.
    async with AsyncSessionLocal() as db:

        try:
            print("Clearing existing data...")

            # Remove all existing records from these tables.
            # RESTART IDENTITY resets the auto-increment primary key sequences,
            # so new records will start again from ID 1.
            #
            # CASCADE handles foreign-key dependencies between the tables.
            await db.execute(
                 text(
                    """
                    TRUNCATE TABLE
                    document_chunks,
                    documents,
                    financial_metrics,
                    companies
                    RESTART IDENTITY
                    CASCADE
                    """
                )
            )

            # Do not commit the TRUNCATE here.
            #
            # PostgreSQL TRUNCATE is transactional. Keeping the TRUNCATE and
            # the new inserts in the same transaction means that if a later
            # database operation fails, db.rollback() can restore the previous
            # data instead of leaving the tables permanently empty.

            # Read all ticker rows from companies.csv.
            with open(CSV_PATH, newline="") as f:
                reader = csv.DictReader(f)

                # Convert the CSV reader into a list so we can
                # determine the number of companies before processing.
                companies = list(reader)

            print(f" Seeding {len(companies)} companies...\n")

            # Process companies ONE AT A TIME.
            # This loop itself is not parallel.
            for row in companies:

                # Example:
                # row = {"ticker": "AAPL"}
                # ticker = "AAPL"
                ticker = row["ticker"]

                print(f"  Processing {ticker}...")

                # yfinance is synchronous, so run it in a worker thread.
                #
                # await pauses THIS coroutine until the worker thread finishes,
                # but it does not block the asyncio event-loop thread.
                #
                # This does NOT make the company loop parallel.
                data = await asyncio.to_thread(
                    fetch_yahoo_data,
                    ticker
                )

                # If Yahoo Finance returned no usable data,
                # skip the rest of this iteration and move to the next ticker.
                if not data:
                    continue

                # Create the SQLAlchemy Company object.
                company = Company(
                    name=data["name"],
                    ticker=ticker,
                    sector=data["sector"],
                    market_cap=data["market_cap"],
                )

                # Add the object to the SQLAlchemy session.
                # This marks it as pending for insertion.
                db.add(company)

                # Send the company INSERT to PostgreSQL so company.id
                # becomes available.
                #
                # flush() does NOT permanently commit the transaction.
                await db.flush()

                # company.id is now available and can be used as
                # a foreign key in FinancialMetric.
                metrics = FinancialMetric(
                    company_id=company.id,
                    pe_ratio=data["pe_ratio"],
                    eps=data["eps"],
                    revenue_growth=data["revenue_growth"],
                )

                # Mark the FinancialMetric object for insertion.
                db.add(metrics)

                # Alpha Vantage and Finnhub both use synchronous requests,
                # so run the provider-selection/news-fetch operation
                # in a worker thread.
                #
                # Alpha Vantage is tried first. Finnhub is called only when
                # Alpha Vantage is unavailable or returns no usable articles.
                #
                # The current company waits for the news request to finish
                # before the loop moves to the next company.
                articles = await asyncio.to_thread(
                    fetch_company_news,
                    ticker,
                )

                # Create one Document database record for each news article
                # that survives duplicate detection.
                #
                # Ownership is assigned here and only here — after the
                # provider-specific validation above has established that
                # the article really belongs to this company.
                stored = 0

                for article in articles:

                    canonical_url = canonicalize_url(
                        article.get("url")
                    )
                    content_hash = hash_content(
                        article.get("content")
                    )

                    # Normalisation can empty an article that looked
                    # non-empty (whitespace only), leaving nothing to hash
                    # and nothing worth storing.
                    if not content_hash:
                        print(
                            "  [SEED_NEWS] skipped reason=empty_content"
                        )
                        continue

                    duplicate_reason = await find_duplicate_document(
                        db,
                        canonical_url,
                        content_hash,
                    )

                    if duplicate_reason:
                        # Not inserted, so it is never picked up by
                        # load_unindexed_documents() and therefore never
                        # chunked or embedded either.
                        print(
                            "  [SEED_NEWS] skipped duplicate "
                            f"reason={duplicate_reason}"
                        )
                        continue

                    doc = Document(
                        # Connect this document to the company
                        # using the company's primary key.
                        company_id=company.id,

                        title=article.get("title"),
                        content=article["content"],
                        doc_type=article["doc_type"],
                        source=article["source"],
                        source_url=canonical_url,
                        content_hash=content_hash,
                        relevance_score=article.get("relevance_score"),
                    )

                    # Mark the Document object for insertion.
                    db.add(doc)

                    # Flush so this row is visible to the duplicate lookup
                    # for the very next article, including articles fetched
                    # later for a different ticker in the same run.
                    await db.flush()

                    stored += 1

                print(
                    f"  {data['name']} | "
                    f"PE: {data['pe_ratio']} | "
                    f"EPS: {data['eps']} | "
                    f"Docs: {stored}"
                    + (
                        f" ({len(articles) - stored} duplicate)"
                        if stored != len(articles)
                        else ""
                    )
                )

                # Pause before processing the next ticker.
                # This helps avoid sending API requests too quickly.
                #
                # asyncio.sleep() pauses the coroutine without
                # blocking the event loop.
                await asyncio.sleep(12)

            # Reapply the curated theme taxonomy. It is keyed by ticker
            # rather than company_id precisely so it can be rebuilt here:
            # the TRUNCATE above resets the id sequence, so every
            # company_id from the previous run is now meaningless.
            from seeds.themes import seed_themes

            theme_counts = await seed_themes(db)

            print(
                f"\n  Themes: {theme_counts['themes']} | "
                f"memberships: {theme_counts['memberships_created']}"
            )

            # Commit the TRUNCATE plus all Company, FinancialMetric,
            # and Document inserts together only after the full seed succeeds.
            await db.commit()

            print("\n Done! Database seeded successfully.")

        except Exception as e:

            # If something unexpected fails during the transaction,
            # undo all changes that have not yet been committed.
            await db.rollback()

            print(f"Seeding failed: {e}")

            # Re-raise the exception so we can see the full traceback.
            raise


# This block runs only when this file is executed directly
# as the main Python module.
if __name__ == "__main__":

    # seed() is async, so asyncio.run() creates an event loop,
    # runs seed() until completion, and then closes the event loop.
    asyncio.run(seed())