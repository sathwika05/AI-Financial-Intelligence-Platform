"""
A collection run has to be small enough to understand.

Measured on Apple's 2024 10-K: 1.5MB downloaded, 1.6s in Docling, 1,458
chunks, about 120,000 tokens to embed. Cheap per filing — a fifth of a
cent — which is exactly why the limit cannot be about money.

It is about volume. The corpus is 327 chunks. Twenty filings adds roughly
thirty thousand, which is a different corpus; the previous maxima allowed
eight hundred filings, or about 1.2 million chunks, from one click. Every
benchmark in this repository was measured against the 327.

So a run is capped on the total it will fetch, not on either field alone:
five companies and five filings each is the same work as twenty-five
companies and one.
"""
import pytest


class TestTheSizeOfARun:
    def test_a_small_run_is_allowed(self):
        from backend.api.ingestion_routes import _require_sane_run_size

        _require_sane_run_size(["AAPL", "MSFT"], limit=3)

    def test_the_cap_is_on_the_total_not_either_field(self):
        """
        Twenty-five companies at one filing each is the same amount of
        work as five at five, and both are the cap.
        """
        from backend.api.ingestion_routes import MAX_FILINGS_PER_RUN, _require_sane_run_size

        _require_sane_run_size(["X"] * MAX_FILINGS_PER_RUN, limit=1)
        _require_sane_run_size(["X", "Y", "Z", "W", "V"], limit=5)

    def test_too_large_a_run_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_sane_run_size

        with pytest.raises(HTTPException) as caught:
            _require_sane_run_size(["X"] * 20, limit=20)

        assert caught.value.status_code == 400

    def test_the_refusal_says_how_big_the_run_would_be(self):
        """
        "Too many" leaves someone guessing. The number they asked for, the
        cap, and what it would cost the corpus are all things they need to
        choose a smaller run.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_sane_run_size

        with pytest.raises(HTTPException) as caught:
            _require_sane_run_size(["X"] * 20, limit=20)

        detail = caught.value.detail

        assert "400" in detail
        assert "chunk" in detail.lower()


class TestTheRequestModelAgrees:
    def test_neither_field_alone_can_exceed_the_cap(self):
        """
        The per-field maxima were 40 companies and 20 filings, which
        multiplied to 800. They are now bounded by the same cap, so a
        request cannot be built that the size check must then reject.
        """
        from backend.api.ingestion_routes import MAX_FILINGS_PER_RUN, CollectRequest

        fields = CollectRequest.model_fields

        tickers_max = next(
            m.max_length for m in fields["tickers"].metadata
            if getattr(m, "max_length", None) is not None
        )

        assert tickers_max <= MAX_FILINGS_PER_RUN
