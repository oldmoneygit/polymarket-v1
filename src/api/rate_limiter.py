"""Rate limiter middleware to prevent Cloudflare throttling on Polymarket APIs.

# [MERGED FROM polymarket-v1] New module — token bucket rate limiting.

Limits based on documented Polymarket rate limits:
- GET /price: 100 req / 10s
- GET /markets: 50 req / 10s
- POST /order: 500 burst / 10s, 3000 sustained / 10min
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter with sliding window.

    Tracks request timestamps and blocks when approaching limits.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        name: str = "default",
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._name = name
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    def _trim_old(self, now: float) -> None:
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def current_count(self) -> int:
        self._trim_old(time.monotonic())
        return len(self._timestamps)

    @property
    def remaining(self) -> int:
        return max(0, self._max - self.current_count)

    async def acquire(self) -> None:
        """Wait until a request slot is available, then consume it."""
        async with self._lock:
            while True:
                now = time.monotonic()
                self._trim_old(now)

                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return

                # Calculate wait time until oldest request expires
                oldest = self._timestamps[0]
                wait = (oldest + self._window) - now + 0.01
                if wait > 0:
                    logger.debug(
                        "Rate limit [%s]: %d/%d used, waiting %.2fs",
                        self._name, len(self._timestamps), self._max, wait,
                    )
                    # Release lock while waiting
                    self._lock.release()
                    await asyncio.sleep(wait)
                    await self._lock.acquire()


class PolymarketRateLimiter:
    """Composite rate limiter for all Polymarket API endpoints."""

    def __init__(self) -> None:
        # GET endpoints: conservative limits (80% of documented)
        self.get_price = RateLimiter(80, 10.0, "GET/price")
        self.get_markets = RateLimiter(40, 10.0, "GET/markets")
        # POST order: burst and sustained
        self.post_order_burst = RateLimiter(400, 10.0, "POST/order-burst")
        self.post_order_sustained = RateLimiter(2400, 600.0, "POST/order-sustained")
        # General: catch-all for unclassified requests
        self.general = RateLimiter(50, 10.0, "general")

    async def acquire_get(self) -> None:
        """Acquire a GET request slot."""
        await self.general.acquire()

    async def acquire_market_info(self) -> None:
        """Acquire a GET /markets request slot."""
        await self.get_markets.acquire()

    async def acquire_price(self) -> None:
        """Acquire a GET /price request slot."""
        await self.get_price.acquire()

    async def acquire_order(self) -> None:
        """Acquire a POST /order slot (checks both burst and sustained)."""
        await self.post_order_burst.acquire()
        await self.post_order_sustained.acquire()
