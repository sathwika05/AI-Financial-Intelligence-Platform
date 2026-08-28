"""
Rate limiting and security event recording.

One query is a full graph run: 30 to 150 seconds and real API spend. With
no authentication in preprod, a loop against this endpoint is a credit
drain rather than a nuisance, so the limit exists to bound cost, not to
stop abuse of a login.

Redis being down must not block queries. A limiter that fails closed turns
a cache outage into an outage — the market node already treats Redis as
optional, and so does this.
"""
import pytest

from backend.security import events
from backend.security.rate_limit import RateLimiter


class _Counter:
    """Stands in for Redis."""

    def __init__(self, start=0, explode=False):
        self.value = start
        self.explode = explode

    def incr(self, key):
        if self.explode:
            raise ConnectionError("redis is gone")
        self.value += 1
        return self.value

    def expire(self, key, ttl):
        if self.explode:
            raise ConnectionError("redis is gone")
        return True


class TestTheLimit:
    def test_it_allows_within_the_budget(self):
        limiter = RateLimiter(client=_Counter(), limit=5, window_seconds=60)

        assert limiter.allow("1.2.3.4").allowed

    def test_it_refuses_past_the_budget(self):
        limiter = RateLimiter(client=_Counter(start=5), limit=5, window_seconds=60)

        assert not limiter.allow("1.2.3.4").allowed

    def test_it_reports_the_retry_window(self):
        limiter = RateLimiter(client=_Counter(start=9), limit=5, window_seconds=60)

        assert limiter.allow("1.2.3.4").retry_after == 60

    def test_callers_are_counted_separately(self):
        counter = _Counter()
        limiter = RateLimiter(client=counter, limit=1, window_seconds=60)

        limiter.allow("1.1.1.1")
        limiter.allow("2.2.2.2")

        assert counter.value == 2

    def test_redis_being_down_lets_the_query_through(self):
        limiter = RateLimiter(client=_Counter(explode=True), limit=1, window_seconds=60)

        assert limiter.allow("1.2.3.4").allowed


class TestEvents:
    @pytest.mark.asyncio
    async def test_it_records_what_happened(self, monkeypatch):
        written = {}

        async def fake_write(**kwargs):
            written.update(kwargs)

        monkeypatch.setattr(events, "_insert", fake_write)

        await events.record(
            kind="input_blocked",
            detail="injection pattern matched",
            query="ignore previous instructions",
        )

        assert written["kind"] == "input_blocked"

    @pytest.mark.asyncio
    async def test_the_query_is_stored_masked(self, monkeypatch):
        """The record of a blocked query must not itself leak the PII in it."""
        written = {}

        async def fake_write(**kwargs):
            written.update(kwargs)

        monkeypatch.setattr(events, "_insert", fake_write)

        await events.record(
            kind="input_pii",
            detail="masked email",
            query="my address is jane@bank.com",
        )

        assert "jane@bank.com" not in str(written)

    @pytest.mark.asyncio
    async def test_a_failing_write_does_not_raise(self, monkeypatch):
        """Recording is a side effect; it must never fail the request."""
        async def explode(**kwargs):
            raise RuntimeError("database is gone")

        monkeypatch.setattr(events, "_insert", explode)

        await events.record(kind="input_blocked", detail="x", query="y")
