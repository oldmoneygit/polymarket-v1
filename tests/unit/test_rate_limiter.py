"""Unit tests for src/api/rate_limiter.py."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.api.rate_limiter import PolymarketRateLimiter, RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_within_limit(self) -> None:
        rl = RateLimiter(5, 10.0, "test")
        for _ in range(5):
            await rl.acquire()
        assert rl.remaining == 0

    @pytest.mark.asyncio
    async def test_remaining_count(self) -> None:
        rl = RateLimiter(10, 10.0, "test")
        assert rl.remaining == 10
        await rl.acquire()
        assert rl.remaining == 9

    @pytest.mark.asyncio
    async def test_trims_old_entries(self) -> None:
        rl = RateLimiter(2, 0.1, "test")  # 0.1s window
        await rl.acquire()
        await rl.acquire()
        assert rl.remaining == 0
        await asyncio.sleep(0.15)  # Wait for window to expire
        assert rl.remaining == 2


class TestPolymarketRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_get(self) -> None:
        rl = PolymarketRateLimiter()
        await rl.acquire_get()  # Should not raise

    @pytest.mark.asyncio
    async def test_acquire_market_info(self) -> None:
        rl = PolymarketRateLimiter()
        await rl.acquire_market_info()

    @pytest.mark.asyncio
    async def test_acquire_order(self) -> None:
        rl = PolymarketRateLimiter()
        await rl.acquire_order()
