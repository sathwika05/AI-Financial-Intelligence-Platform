"""
News ingestion data quality.

Covers the two defects that let one AMD bond-sale article be stored five
times, under AMD, JPM, BAC, MS and C:

  - the queried ticker was assumed to be the article's subject
  - there was no duplicate detection of any kind

These tests are provider-shaped: the Alpha Vantage cases carry a
`ticker_sentiment` list because that is what the real feed returns, and the
Finnhub cases do not, because company-news does not.
"""
import pytest

from seeds.seed_data import (
    MIN_NEWS_RELEVANCE,
    canonicalize_url,
    fetch_company_news,
    get_ticker_relevance,
    hash_content,
    normalize_content,
)


AMD_ARTICLE = (
    "Advanced Micro Devices Inc. is planning to raise as much $5 billion "
    "in what could be the chipmaker's biggest-ever investment-grade bond "
    "sale, adding to a wave of debt tied to the artificial intelligence boom."
)


def av_item(ticker_sentiment, *, summary=AMD_ARTICLE, url="https://ex.com/amd"):
    """One Alpha Vantage feed entry, shaped like the real response."""
    return {
        "title": "AMD plans record bond sale",
        "summary": summary,
        "url": url,
        "source": "Bloomberg",
        "ticker_sentiment": ticker_sentiment,
    }


# ---------------------------------------------------------------------------
# A. Alpha Vantage relevance
# ---------------------------------------------------------------------------


class TestAlphaVantageRelevance:
    def test_relevance_is_parsed_from_the_string_alpha_vantage_sends(self):
        sentiment = [{"ticker": "AMD", "relevance_score": "0.85"}]
        assert get_ticker_relevance(sentiment, "AMD") == pytest.approx(0.85)

    def test_ticker_match_is_case_insensitive(self):
        sentiment = [{"ticker": "amd", "relevance_score": "0.85"}]
        assert get_ticker_relevance(sentiment, "AMD") == pytest.approx(0.85)

    def test_absent_ticker_returns_none_not_zero(self):
        """
        None and 0.0 mean different things: the provider having no opinion
        must not be recorded as an opinion of zero relevance.
        """
        sentiment = [{"ticker": "AMD", "relevance_score": "0.85"}]
        assert get_ticker_relevance(sentiment, "JPM") is None

    def test_unparseable_score_is_treated_as_absent(self):
        sentiment = [{"ticker": "AMD", "relevance_score": "n/a"}]
        assert get_ticker_relevance(sentiment, "AMD") is None

    def test_missing_or_malformed_sentiment_list_is_safe(self):
        assert get_ticker_relevance(None, "AMD") is None
        assert get_ticker_relevance("not-a-list", "AMD") is None
        assert get_ticker_relevance([None, 42], "AMD") is None

    def test_high_relevance_article_is_accepted_for_its_own_ticker(self, monkeypatch):
        """The AMD article, queried as AMD, is genuinely about AMD."""
        feed = [av_item([{"ticker": "AMD", "relevance_score": "0.82"}])]
        _stub_alpha_vantage(monkeypatch, feed)

        articles = _alpha_only(monkeypatch, "AMD")

        assert len(articles) == 1
        assert articles[0]["relevance_score"] == pytest.approx(0.82)
        assert articles[0]["url"] == "https://ex.com/amd"
        assert articles[0]["title"] == "AMD plans record bond sale"

    def test_same_article_is_rejected_for_a_bank_with_low_relevance(
        self, monkeypatch
    ):
        """
        The exact regression: this article came back for JPM and was stored
        as a JPM document.
        """
        feed = [
            av_item(
                [
                    {"ticker": "AMD", "relevance_score": "0.82"},
                    {"ticker": "JPM", "relevance_score": "0.08"},
                ]
            )
        ]
        _stub_alpha_vantage(monkeypatch, feed)

        assert _alpha_only(monkeypatch, "JPM") == []

    def test_rejected_when_queried_ticker_absent_from_sentiment(self, monkeypatch):
        feed = [av_item([{"ticker": "AMD", "relevance_score": "0.82"}])]
        _stub_alpha_vantage(monkeypatch, feed)

        assert _alpha_only(monkeypatch, "BAC") == []

    def test_threshold_boundary_is_inclusive(self, monkeypatch):
        feed = [
            av_item(
                [{"ticker": "AMD", "relevance_score": str(MIN_NEWS_RELEVANCE)}]
            )
        ]
        _stub_alpha_vantage(monkeypatch, feed)

        assert len(_alpha_only(monkeypatch, "AMD")) == 1

    def test_just_below_threshold_is_rejected(self, monkeypatch):
        feed = [
            av_item(
                [
                    {
                        "ticker": "AMD",
                        "relevance_score": str(MIN_NEWS_RELEVANCE - 0.01),
                    }
                ]
            )
        ]
        _stub_alpha_vantage(monkeypatch, feed)

        assert _alpha_only(monkeypatch, "AMD") == []

    def test_empty_content_is_rejected_before_relevance_matters(self, monkeypatch):
        feed = [
            av_item(
                [{"ticker": "AMD", "relevance_score": "0.99"}],
                summary="   ",
            )
        ]
        # A blank summary falls back to the title, so blank both.
        feed[0]["title"] = ""
        _stub_alpha_vantage(monkeypatch, feed)

        assert _alpha_only(monkeypatch, "AMD") == []


# ---------------------------------------------------------------------------
# B. Finnhub
# ---------------------------------------------------------------------------


class TestFinnhub:
    def test_company_news_is_accepted_without_relevance_logic(self, monkeypatch):
        """
        company-news?symbol= is scoped by the endpoint, so there is no
        ticker_sentiment to consult and none is required.
        """
        _stub_alpha_vantage(monkeypatch, [])
        _stub_finnhub(
            monkeypatch,
            [
                {
                    "headline": "AMD plans record bond sale",
                    "summary": AMD_ARTICLE,
                    "url": "https://ex.com/finnhub-amd",
                    "source": "Reuters",
                }
            ],
        )

        articles = fetch_company_news("AMD")

        assert len(articles) == 1
        assert articles[0]["source"] == "Reuters"
        assert articles[0]["url"] == "https://ex.com/finnhub-amd"
        assert articles[0]["title"] == "AMD plans record bond sale"
        # Nothing to report, and nothing invented.
        assert articles[0]["relevance_score"] is None

    def test_empty_finnhub_content_is_rejected(self, monkeypatch):
        _stub_alpha_vantage(monkeypatch, [])
        _stub_finnhub(
            monkeypatch,
            [{"headline": "", "summary": "  ", "url": "https://ex.com/x"}],
        )

        assert fetch_company_news("AMD") == []


# ---------------------------------------------------------------------------
# C. Deduplication
# ---------------------------------------------------------------------------


class TestCanonicalUrl:
    def test_identical_urls_match(self):
        url = "https://ex.com/a/b?id=7"
        assert canonicalize_url(url) == canonicalize_url(url)

    def test_tracking_parameters_are_removed(self):
        plain = canonicalize_url("https://ex.com/a")
        tracked = canonicalize_url(
            "https://ex.com/a?utm_source=x&utm_medium=y&utm_campaign=z"
            "&fbclid=abc&gclid=def&utm_term=t&utm_content=c"
        )
        assert plain == tracked

    def test_meaningful_query_parameters_are_preserved(self):
        """
        A query string is often the document identity. Dropping it would
        collapse distinct articles into one, which is worse than a duplicate.
        """
        a = canonicalize_url("https://ex.com/story?id=1")
        b = canonicalize_url("https://ex.com/story?id=2")
        assert a != b
        assert "id=1" in a

    def test_meaningful_parameter_survives_alongside_tracking(self):
        cleaned = canonicalize_url("https://ex.com/s?id=9&utm_source=news")
        assert "id=9" in cleaned
        assert "utm_source" not in cleaned

    def test_trailing_slash_is_normalized(self):
        assert canonicalize_url("https://ex.com/a/") == canonicalize_url(
            "https://ex.com/a"
        )

    def test_scheme_and_host_case_is_normalized(self):
        assert canonicalize_url("HTTPS://EX.COM/a") == canonicalize_url(
            "https://ex.com/a"
        )

    def test_path_case_is_preserved(self):
        """Paths are case-sensitive on most servers; do not fold them."""
        assert canonicalize_url("https://ex.com/A") != canonicalize_url(
            "https://ex.com/a"
        )

    def test_fragment_is_dropped(self):
        assert canonicalize_url("https://ex.com/a#part2") == canonicalize_url(
            "https://ex.com/a"
        )

    def test_whitespace_is_stripped(self):
        assert canonicalize_url("  https://ex.com/a  ") == canonicalize_url(
            "https://ex.com/a"
        )

    def test_missing_url_is_none(self):
        assert canonicalize_url(None) is None
        assert canonicalize_url("") is None
        assert canonicalize_url("   ") is None


class TestContentHash:
    def test_identical_content_hashes_identically(self):
        assert hash_content(AMD_ARTICLE) == hash_content(AMD_ARTICLE)

    def test_whitespace_differences_do_not_create_a_second_copy(self):
        """
        Different URLs, identical text — the syndicated-newswire case that
        dominates this corpus.
        """
        rewrapped = AMD_ARTICLE.replace(" ", "\n  ")
        assert hash_content(AMD_ARTICLE) == hash_content(rewrapped)
        assert hash_content(f"  {AMD_ARTICLE}\t\n") == hash_content(AMD_ARTICLE)

    def test_different_content_hashes_differently(self):
        assert hash_content(AMD_ARTICLE) != hash_content("Intel posted growth.")

    def test_empty_content_has_no_hash(self):
        assert hash_content("") is None
        assert hash_content("   \n\t ") is None
        assert hash_content(None) is None

    def test_hash_is_sha256_shaped(self):
        digest = hash_content(AMD_ARTICLE)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_normalize_content_collapses_whitespace(self):
        assert normalize_content("  a \n\t b  ") == "a b"
        assert normalize_content(None) == ""


# ---------------------------------------------------------------------------
# D. Provider fallback
# ---------------------------------------------------------------------------


class TestProviderFallback:
    def test_finnhub_not_called_when_alpha_vantage_succeeds(self, monkeypatch):
        _stub_alpha_vantage(
            monkeypatch,
            [av_item([{"ticker": "AMD", "relevance_score": "0.9"}])],
        )
        called = _stub_finnhub(monkeypatch, [], track=True)

        assert len(fetch_company_news("AMD")) == 1
        assert called == []

    def test_finnhub_called_when_all_alpha_articles_fail_relevance(
        self, monkeypatch
    ):
        """
        Requirement 9: raw response length is not success. Three articles
        that all fail validation means Alpha Vantage produced nothing.
        """
        _stub_alpha_vantage(
            monkeypatch,
            [
                av_item([{"ticker": "AMD", "relevance_score": "0.01"}], url="u1"),
                av_item([{"ticker": "AMD", "relevance_score": "0.02"}], url="u2"),
                av_item([{"ticker": "NVDA", "relevance_score": "0.9"}], url="u3"),
            ],
        )
        called = _stub_finnhub(
            monkeypatch,
            [{"headline": "h", "summary": "Fallback body", "url": "https://f/1"}],
            track=True,
        )

        articles = fetch_company_news("AMD")

        assert called == ["AMD"]
        assert len(articles) == 1
        assert articles[0]["content"] == "Fallback body"

    def test_finnhub_called_when_alpha_vantage_returns_nothing(self, monkeypatch):
        _stub_alpha_vantage(monkeypatch, [])
        called = _stub_finnhub(
            monkeypatch,
            [{"headline": "h", "summary": "Body", "url": "https://f/2"}],
            track=True,
        )

        assert len(fetch_company_news("AMD")) == 1
        assert called == ["AMD"]

    def test_no_articles_when_both_providers_are_empty(self, monkeypatch):
        _stub_alpha_vantage(monkeypatch, [])
        _stub_finnhub(monkeypatch, [])

        assert fetch_company_news("AMD") == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _stub_alpha_vantage(monkeypatch, feed):
    """Replace the Alpha Vantage HTTP call with a fixed feed."""
    import seeds.seed_data as seed

    monkeypatch.setattr(seed, "ALPHA_VANTAGE_KEY", "test-key")
    monkeypatch.setattr(seed, "ALPHA_VANTAGE_AVAILABLE", True)

    def fake_get(url, params=None, timeout=None, **kwargs):
        assert "apikey" in (params or {}), "request must be authenticated"
        return _Response({"feed": feed})

    monkeypatch.setattr(seed.requests, "get", fake_get)


def _stub_finnhub(monkeypatch, items, track=False):
    """Replace fetch_finnhub_news; returns a list of tickers it was called with."""
    import seeds.seed_data as seed

    calls = []

    def fake_finnhub(ticker):
        calls.append(ticker)
        return [
            {
                "title": item.get("headline") or None,
                "content": item.get("summary") or item.get("headline") or "",
                "doc_type": "news",
                "source": item.get("source") or "Finnhub",
                "url": item.get("url") or None,
                "relevance_score": None,
            }
            for item in items
            if (item.get("summary") or item.get("headline") or "").strip()
        ]

    monkeypatch.setattr(seed, "fetch_finnhub_news", fake_finnhub)
    return calls


def _alpha_only(monkeypatch, ticker):
    """Run only the Alpha Vantage branch, with Finnhub stubbed to nothing."""
    import seeds.seed_data as seed

    return seed.fetch_alpha_vantage_news(ticker)
