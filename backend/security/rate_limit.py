"""A per-caller ceiling on how often the graph can be run.

One query costs roughly 10 to 45 seconds and real provider spend, and preprod has
no authentication, so the thing being limited is cost rather than login
abuse.

Fails open. Redis being unavailable must not stop analysts working — the
market node already treats it as optional, and a limiter that fails closed
turns a cache outage into an outage.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.services.redis_service import redis_client


logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int | None = None


class RateLimiter:
    def __init__(
        self,
        client=redis_client,
        limit: int = DEFAULT_LIMIT,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ):
        self._client = client
        self._limit = limit
        self._window = window_seconds

    def allow(self, caller: str) -> Decision:
        """Whether this caller may run another query now."""
        key = f"ratelimit:query:{caller}"

        try:
            count = self._client.incr(key)

            # Set on every call rather than only the first: a fixed window
            # that never expires would lock a caller out permanently.
            self._client.expire(key, self._window)
        except Exception:
            logger.warning(
                "[RATE_LIMIT] unavailable; allowing the request",
                exc_info=True,
            )
            return Decision(allowed=True)

        if count > self._limit:
            return Decision(allowed=False, retry_after=self._window)

        return Decision(allowed=True)
