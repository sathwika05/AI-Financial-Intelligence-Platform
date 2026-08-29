"""
Collecting filings from SEC EDGAR.

EDGAR is a public archive with rules attached: it requires a User-Agent
that identifies who is calling, it rate-limits, and it serves documents
from a path built out of three separate fields of a submissions index.
Get the URL wrong and you get a 404; get the User-Agent wrong and you get
blocked for everyone sharing the address.

Tested against the real response shapes, with the HTTP call injected.
None of these tests reach the network -- hammering a public archive to
prove a URL builder works is exactly what the rate limit is there to
stop.
"""
import pytest


COMPANY_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}

SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-24-000123",
                "0000320193-24-000081",
                "0000320193-24-000070",
            ],
            "filingDate": ["2024-11-01", "2024-08-02", "2024-05-03"],
            "form": ["10-K", "10-Q", "8-K"],
            "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm", "ex99.htm"],
        }
    },
}


class TestFindingACompany:
    @pytest.mark.asyncio
    async def test_a_ticker_resolves_to_a_padded_cik(self):
        """
        EDGAR's submissions endpoint wants a ten-digit zero-padded CIK.
        Apple's is 320193, and requesting CIK320193.json returns nothing.
        """
        from backend.ingestion.edgar import cik_for_ticker

        cik = await cik_for_ticker("AAPL", fetch=_fake_fetch())

        assert cik == "0000320193"

    @pytest.mark.asyncio
    async def test_the_lookup_is_case_insensitive(self):
        from backend.ingestion.edgar import cik_for_ticker

        assert await cik_for_ticker("aapl", fetch=_fake_fetch()) == "0000320193"

    @pytest.mark.asyncio
    async def test_an_unknown_ticker_is_reported_not_guessed(self):
        from backend.ingestion.edgar import UnknownCompany, cik_for_ticker

        with pytest.raises(UnknownCompany):
            await cik_for_ticker("NOTREAL", fetch=_fake_fetch())


class TestListingFilings:
    @pytest.mark.asyncio
    async def test_filings_are_read_from_the_parallel_arrays(self):
        """
        EDGAR does not return a list of filings. It returns several equal
        length arrays that have to be zipped by position, and a mistake
        here silently pairs one filing's date with another's document.
        """
        from backend.ingestion.edgar import recent_filings

        filings = await recent_filings("0000320193", fetch=_fake_fetch())

        assert filings[0].form == "10-K"
        assert filings[0].filing_date == "2024-11-01"
        assert filings[0].primary_document == "aapl-20240928.htm"
        assert filings[0].accession == "0000320193-24-000123"

    @pytest.mark.asyncio
    async def test_only_the_requested_forms_come_back(self):
        """
        An 8-K is a press release and a 10-K is an annual report. Indexing
        every form indiscriminately buries the filings worth answering
        from.
        """
        from backend.ingestion.edgar import recent_filings

        filings = await recent_filings(
            "0000320193", forms=("10-K", "10-Q"), fetch=_fake_fetch()
        )

        assert [f.form for f in filings] == ["10-K", "10-Q"]

    @pytest.mark.asyncio
    async def test_the_ticker_travels_with_the_filing(self):
        """
        The document is stored under its ticker, and the submissions
        response never mentions one.
        """
        from backend.ingestion.edgar import recent_filings

        filings = await recent_filings(
            "0000320193", ticker="AAPL", fetch=_fake_fetch()
        )

        assert filings[0].ticker == "AAPL"


class TestBuildingTheDocumentUrl:
    def test_the_accession_number_loses_its_dashes_in_the_path(self):
        """
        The directory is the accession number without dashes; the filing
        is listed with them. Using either form in both places 404s.
        """
        from backend.ingestion.edgar import Filing, filing_url

        url = filing_url(
            Filing(
                cik="0000320193",
                accession="0000320193-24-000123",
                form="10-K",
                filing_date="2024-11-01",
                primary_document="aapl-20240928.htm",
                ticker="AAPL",
            )
        )

        assert url == (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019324000123/aapl-20240928.htm"
        )


class TestValidatingTheSource:
    def test_an_edgar_url_is_accepted(self):
        from backend.ingestion.edgar import validate_source

        validate_source(
            "https://www.sec.gov/Archives/edgar/data/320193/x/aapl.htm"
        )

    def test_another_host_is_refused(self):
        """
        The collector downloads whatever URL it is handed and stores the
        result as a filing. A URL off sec.gov is not a filing.
        """
        from backend.ingestion.edgar import UntrustedSource, validate_source

        with pytest.raises(UntrustedSource):
            validate_source("https://example.com/not-a-filing.htm")

    def test_a_lookalike_host_is_refused(self):
        from backend.ingestion.edgar import UntrustedSource, validate_source

        with pytest.raises(UntrustedSource):
            validate_source("https://sec.gov.evil.example/filing.htm")

    def test_plain_http_is_refused(self):
        from backend.ingestion.edgar import UntrustedSource, validate_source

        with pytest.raises(UntrustedSource):
            validate_source("http://www.sec.gov/Archives/edgar/data/1/x.htm")


class TestIdentifyingOurselves:
    def test_every_request_carries_a_user_agent(self):
        """
        SEC requires a User-Agent naming who is calling. Without one the
        request is refused, and a generic one gets the whole IP blocked --
        which on a shared host means blocking strangers.
        """
        from backend.ingestion.edgar import request_headers

        headers = request_headers("Example Research team@example.com")

        assert "team@example.com" in headers["User-Agent"]

    def test_an_unset_user_agent_is_refused_before_the_call(self):
        from backend.ingestion.edgar import MissingUserAgent, request_headers

        with pytest.raises(MissingUserAgent):
            request_headers("")


def _fake_fetch():
    """Stands in for the HTTP call, keyed by the URLs EDGAR actually serves."""

    async def fetch(url: str, *, headers=None) -> bytes:
        import json

        if url.endswith("company_tickers.json"):
            return json.dumps(COMPANY_TICKERS).encode()

        if "submissions/CIK0000320193.json" in url:
            return json.dumps(SUBMISSIONS).encode()

        raise AssertionError(f"unexpected url: {url}")

    return fetch
