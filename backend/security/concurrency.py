"""
A ceiling on how many queries run at once.

The rate limiter next door bounds one caller over time. This bounds
everyone at an instant, and the two are not substitutes: five testers
clicking simultaneously are five addresses, each inside its own limit,
and all five pipelines start together.

That matters here more than the request count does. One query runs six
graph stages on preprod's 0.5-CPU, 512MB instance and spends real provider
budget, and both ceilings have been hit in practice -- an OOM restart
that returned 502 to whoever was mid-query, and

    groq.RateLimitError: 429 -- tokens per minute (TPM):
    Limit 8000, Used 5638, Requested 3618

Refusing rather than queueing. A caller made to wait behind a
45-second query waits 90 seconds with no explanation, and a browser
cannot tell that from a hang. Saying "not now, try in 30 seconds" is
worse service and a better experience, and it is the same shape the rate
limiter already returns.

Process-local, like the rate limiter's fallback. Preprod is one Render
instance, so this is the true ceiling there. Production runs ECS with
desired_count = 1 today, which makes it true there too -- but only
accidentally: raise that count and this bounds each task rather than the
service, and the honest fix is the same as for the rate limiter, move the
count to Redis.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


DEFAULT_LIMIT = 2
DEFAULT_RETRY_AFTER_SECONDS = 30


class ConcurrencyBound:
    """Admit up to `limit` concurrent callers; refuse the rest."""

    class Busy(Exception):
        """Raised instead of queueing, so the caller can be told."""

        def __init__(self, retry_after: int, limit: int):
            super().__init__(
                f"{limit} queries already running; retry in "
                f"{retry_after}s"
            )
            self.retry_after = retry_after
            self.limit = limit

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        retry_after_seconds: int = DEFAULT_RETRY_AFTER_SECONDS,
    ):
        if limit < 1:
            raise ValueError("A concurrency limit below 1 serves nobody")

        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def try_acquire(self) -> bool:
        """
        Take a permit if one is free.

        No lock: this runs on one event loop and there is no await
        between the read and the write, so the increment cannot be
        interleaved. A lock here would be ceremony, and asyncio.Semaphore
        would be the wrong primitive because its acquire() waits.
        """
        if self._in_flight >= self.limit:
            return False

        self._in_flight += 1
        return True

    def acquire_or_raise(self) -> None:
        if not self.try_acquire():
            raise self.Busy(
                retry_after=self.retry_after_seconds,
                limit=self.limit,
            )

    def release(self) -> None:
        # Never below zero. A double release would otherwise raise the
        # real ceiling above `limit` and quietly undo the whole point.
        self._in_flight = max(0, self._in_flight - 1)

    @asynccontextmanager
    async def slot(self):
        """
        Hold a permit for the duration of the block.

        The release is in `finally` because the failure that matters is a
        permit held by a request that raised: it is gone for the life of
        the process, and `limit` of those means the service answers
        nothing, forever. A busy demo recovers; a leaked permit does not.
        """
        self.acquire_or_raise()

        try:
            yield
        finally:
            self.release()
