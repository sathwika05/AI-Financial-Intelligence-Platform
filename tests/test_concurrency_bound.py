"""
A per-IP rate limit does not bound concurrent work.

The public demo has a rate limiter, and it does what it was built for:
one caller cannot send twenty queries a minute. It says nothing about how
many queries run at the same time, because five testers clicking at once
are five different addresses, each comfortably inside its own limit.

Each of those queries runs six graph stages on a 0.5-CPU, 512MB instance,
against a Groq free tier whose ceiling is 8000 tokens per minute shared
across all of them. Both failure modes have been observed:

    OOM restart mid-query, returning 502 to whoever was waiting
    groq.RateLimitError: 429 -- TPM Limit 8000, Used 5638, Requested 3618

The second one used to be worse than it looked: an unreachable judge was
reported as hallucination_rate 1.0, which triggered a retry, which spent
more tokens against the limit that had just refused it. That is fixed
separately; this bounds the load that produced it.

WAITING IS NOT THE ANSWER
    Queueing behind a 45-second query means the browser waits 90 seconds
    with no explanation, which is indistinguishable from a hang. A caller
    that cannot be served now is told so, with a Retry-After, in the same
    shape the rate limiter already uses.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.security.concurrency import ConcurrencyBound


class TestItAdmitsUpToTheLimit:
    def test_the_first_callers_are_admitted(self):
        bound = ConcurrencyBound(limit=2)

        assert bound.try_acquire() is True
        assert bound.try_acquire() is True

    def test_the_one_past_the_limit_is_refused(self):
        bound = ConcurrencyBound(limit=2)

        bound.try_acquire()
        bound.try_acquire()

        assert bound.try_acquire() is False

    def test_releasing_admits_the_next(self):
        bound = ConcurrencyBound(limit=1)

        assert bound.try_acquire() is True
        assert bound.try_acquire() is False

        bound.release()

        assert bound.try_acquire() is True


class TestItNeverLeaksAPermit:
    """
    A permit held by a request that raised is a permit gone for the life
    of the process. Two of those and the demo answers nothing, forever.
    """

    async def test_the_permit_is_returned_when_the_body_raises(self):
        bound = ConcurrencyBound(limit=1)

        with pytest.raises(ValueError):
            async with bound.slot():
                raise ValueError("pipeline blew up")

        assert bound.in_flight == 0
        assert bound.try_acquire() is True

    async def test_the_permit_is_returned_on_success(self):
        bound = ConcurrencyBound(limit=1)

        async with bound.slot():
            assert bound.in_flight == 1

        assert bound.in_flight == 0

    async def test_a_refused_caller_raises_before_entering(self):
        bound = ConcurrencyBound(limit=1)

        async with bound.slot():
            with pytest.raises(bound.Busy):
                async with bound.slot():
                    pytest.fail("should not have been admitted")

    async def test_a_refusal_does_not_consume_a_permit(self):
        """
        The bug that turns a busy moment into a permanent outage.
        """
        bound = ConcurrencyBound(limit=1)

        async with bound.slot():
            for _ in range(5):
                with pytest.raises(bound.Busy):
                    async with bound.slot():
                        pass

        assert bound.in_flight == 0
        assert bound.try_acquire() is True


class TestItHoldsUnderRealConcurrency:
    async def test_only_the_limit_runs_at_once(self):
        bound = ConcurrencyBound(limit=2)
        peak = 0
        admitted = 0

        async def caller():
            nonlocal peak, admitted
            try:
                async with bound.slot():
                    admitted += 1
                    peak = max(peak, bound.in_flight)
                    await asyncio.sleep(0.05)
            except bound.Busy:
                pass

        await asyncio.gather(*[caller() for _ in range(10)])

        assert peak <= 2, f"{peak} ran concurrently against a limit of 2"
        assert admitted == 2, "the other eight should have been refused"
        assert bound.in_flight == 0


class TestTheRefusalCarriesRetryAfter:
    def test_busy_names_a_wait(self):
        bound = ConcurrencyBound(limit=1, retry_after_seconds=30)

        bound.try_acquire()

        with pytest.raises(bound.Busy) as raised:
            bound.acquire_or_raise()

        assert raised.value.retry_after == 30


class TestItIsWiredIntoTheRoute:
    def test_the_route_module_bounds_itself(self):
        import inspect

        from backend.api import financial_routes

        source = inspect.getsource(financial_routes)

        assert "ConcurrencyBound" in source
        assert "_concurrency" in source
