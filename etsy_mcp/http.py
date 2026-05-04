"""HTTP wrapper for the Etsy Open API v3.

All API-driven tools call etsy_request(). The wrapper handles:
- in-process rate limiting (token bucket, default 10 req/s)
- 401 → automatic token refresh + one retry
- 429 → honor Retry-After, retry up to 3 times
- 5xx → exponential backoff, retry up to 3 times
- network errors → one retry after 1s
- terminal failure → raise the right EtsyMCPError subclass
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket limiter. Default 10/s matches Etsy's per-app limit.

    Note on the lock: we acquire-and-release the internal lock per iteration
    rather than holding it across asyncio.sleep() so other coroutines can
    refill the bucket independently. The loop will re-check tokens after
    sleeping.
    """

    def __init__(self, rate_per_second: float = 10.0, capacity: int = 10):
        self.rate = rate_per_second
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity,
                    self._tokens + (now - self._last) * self.rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait)
