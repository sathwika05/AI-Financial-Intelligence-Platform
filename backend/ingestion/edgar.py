"""
Collecting filings from SEC EDGAR.

EDGAR -- Electronic Data Gathering, Analysis and Retrieval -- is the
Securities and Exchange Commission's public archive of everything US
public companies are required to file. It is a public archive with rules
attached. It requires a User-Agent
naming who is calling, it rate-limits by address, and it serves a
document from a path assembled out of three separate fields of a
submissions index -- each of which has to be reshaped first. None of that
is guesswork: it is published policy, and ignoring it gets an address
blocked, which on a shared host means blocking strangers too.

This module only *collects*. What it downloads goes to the raw bucket
through the publisher, and everything after that -- parse, normalise,
chunk, embed -- is the path that already exists and does not know or care
that a document came from EDGAR rather than from an upload.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Sequence
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)


class UnknownCompany(Exception):
    """No Central Index Key is published for that ticker."""


class UntrustedSource(Exception):
    """The URL is not an EDGAR document."""


class MissingUserAgent(Exception):
    """SEC requires a caller to identify itself, and none was configured."""


# EDGAR's ticker-to-CIK map, and the per-company submissions index.
#
# CIK is the Central Index Key: the permanent identifier the Securities
# and Exchange Commission assigns to every filer. Tickers change, get
# reused after a delisting, and one company can have several; a CIK is
# issued once and never reused, so EDGAR is addressed by it throughout
# and has no endpoint that takes a ticker.
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}"

# The forms worth indexing by default: the 10-K, which is a company's
# annual report, and the 10-Q, its quarterly one. An 8-K is a disclosure
# of a single material event -- closer to a press release -- and indexing
# every form indiscriminately buries the filings actually worth answering
# from.
DEFAULT_FORMS = ("10-K", "10-Q")

# SEC asks for no more than ten requests a second. One request every tenth
# of a second is the whole of the compliance, and it is cheap insurance
# against having the address blocked.
_MIN_SECONDS_BETWEEN_REQUESTS = 0.11

Fetch = Callable[..., Awaitable[bytes]]


@dataclass(frozen=True)
class Filing:
    """One filing, as EDGAR describes it."""

    cik: str
    accession: str
    form: str
    filing_date: str
    primary_document: str
    ticker: str | None = None


def request_headers(user_agent: str) -> dict[str, str]:
    """
    The headers every EDGAR request must carry.

    Refuses an empty User-Agent rather than sending a default one: SEC
    rejects anonymous traffic, and a generic string gets the address
    blocked for everyone behind it.
    """
    if not user_agent or not user_agent.strip():
        raise MissingUserAgent(
            "SEC EDGAR requires a User-Agent naming the caller and a "
            "contact address. Set SEC_USER_AGENT, for example "
            '"Example Research team@example.com".'
        )

    return {
        "User-Agent": user_agent.strip(),
        "Accept-Encoding": "gzip, deflate",
    }


def validate_source(url: str) -> None:
    """
    Refuse anything that is not an EDGAR document over HTTPS.

    The collector downloads whatever URL it is handed and stores the
    result as a filing, so this is the boundary that decides what may
    become one. Checked on the parsed host rather than with a substring
    test, because "sec.gov.evil.example" contains "sec.gov".
    """
    parts = urlsplit(url)

    if parts.scheme != "https":
        raise UntrustedSource(f"{url} is not served over HTTPS.")

    host = parts.hostname or ""

    if host != "sec.gov" and not host.endswith(".sec.gov"):
        raise UntrustedSource(f"{host or url} is not an SEC EDGAR host.")


def filing_url(filing: Filing) -> str:
    """
    Where EDGAR serves this filing's primary document.

    Two reshapings, both required: the Central Index Key loses its zero
    padding in the path, and the accession number loses its dashes in the folder name
    while keeping them everywhere else. Using either form in both places
    returns a 404.
    """
    return ARCHIVE_URL.format(
        cik=str(int(filing.cik)),
        folder=filing.accession.replace("-", ""),
        document=filing.primary_document,
    )


async def cik_for_ticker(ticker: str, *, fetch: Fetch, headers=None) -> str:
    """
    The ten-digit zero-padded Central Index Key for a ticker.

    The padding is not cosmetic: the submissions endpoint is addressed by
    the padded form, and CIK320193.json returns nothing at all.
    """
    payload = json.loads(await fetch(TICKERS_URL, headers=headers))

    wanted = ticker.strip().upper()

    for entry in payload.values():
        if str(entry.get("ticker", "")).upper() == wanted:
            return str(entry["cik_str"]).zfill(10)

    raise UnknownCompany(f"EDGAR publishes no CIK for {ticker!r}.")


async def recent_filings(
    cik: str,
    *,
    fetch: Fetch,
    forms: Iterable[str] = DEFAULT_FORMS,
    ticker: str | None = None,
    limit: int = 10,
    headers=None,
) -> list[Filing]:
    """
    A company's most recent filings of the requested forms.

    EDGAR does not return a list of filings. It returns several equal
    length arrays that have to be zipped by position, so a mistake here
    does not fail -- it silently pairs one filing's date with another's
    document.
    """
    payload = json.loads(
        await fetch(SUBMISSIONS_URL.format(cik=cik), headers=headers)
    )

    recent = (payload.get("filings") or {}).get("recent") or {}

    accessions: Sequence[str] = recent.get("accessionNumber") or []
    dates: Sequence[str] = recent.get("filingDate") or []
    form_types: Sequence[str] = recent.get("form") or []
    documents: Sequence[str] = recent.get("primaryDocument") or []

    wanted = {form.upper() for form in forms}

    filings: list[Filing] = []

    # zip() stops at the shortest, which is the safe behaviour here: a
    # truncated array means the remaining entries have no document to
    # pair with, and inventing one would produce a URL that 404s.
    for accession, date, form, document in zip(
        accessions, dates, form_types, documents
    ):
        if form.upper() not in wanted:
            continue

        filings.append(
            Filing(
                cik=cik,
                accession=accession,
                form=form,
                filing_date=date,
                primary_document=document,
                ticker=ticker,
            )
        )

        if len(filings) >= limit:
            break

    return filings


async def download_filing(
    filing: Filing,
    *,
    fetch: Fetch,
    headers=None,
) -> bytes:
    """
    The filing's primary document, validated before it is fetched.

    Validation happens on the URL this module built, not on one handed in
    from outside, which is the point: it is the last place the host is
    checked before bytes are trusted enough to store.
    """
    url = filing_url(filing)

    validate_source(url)

    body = await fetch(url, headers=headers)

    if not body:
        raise ValueError(f"{url} returned an empty document.")

    logger.info(
        "[EDGAR] Downloaded %s %s (%s bytes)",
        filing.ticker or filing.cik,
        filing.form,
        len(body),
    )

    return body


class RateLimiter:
    """
    One request at a time, no faster than SEC allows.

    A lock rather than a token bucket because the limit is low and the
    caller is a single worker: the simplest thing that cannot exceed the
    rate is a serialised queue with a floor on the gap between requests.
    """

    def __init__(self, min_interval: float = _MIN_SECONDS_BETWEEN_REQUESTS):
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            gap = now - self._last

            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)

            self._last = asyncio.get_running_loop().time()


_limiter = RateLimiter()


async def http_fetch(url: str, *, headers=None) -> bytes:
    """
    One EDGAR request, rate-limited and identified.

    requests is synchronous, so the call is handed to a worker thread --
    the same arrangement boto3 gets in backend.ingestion.aws, and for the
    same reason.
    """
    import requests

    await _limiter.wait()

    def _get() -> bytes:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        return response.content

    return await asyncio.to_thread(_get)


def edgar_configured() -> bool:
    """Whether this deployment may call EDGAR at all."""
    from backend.config import settings

    return bool(settings.SEC_USER_AGENT.strip())
