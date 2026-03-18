"""Momentum / news edge detector — spots rapid price movements.

# [MERGED FROM polymarket-v1] New module — detects rapid price changes.

Can be bootstrapped with historical price data from CLOB API
for immediate detection without waiting for observation window.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MomentumSignal:
    """A detected rapid price movement suggesting new information."""

    condition_id: str
    question: str
    direction: str  # "UP" or "DOWN"
    price_start: float
    price_now: float
    change_pct: float
    minutes_elapsed: float
    slug: str


class MomentumDetector:
    """Tracks market prices over time and detects rapid movements.

    When a market moves >10% in <30 minutes, it likely means
    new information hit the market. This is an edge signal.
    """

    def __init__(
        self,
        min_change_pct: float = 0.10,
        window_minutes: float = 30.0,
    ) -> None:
        self._min_change = min_change_pct
        self._window_seconds = window_minutes * 60
        # Key: condition_id -> list of (timestamp, yes_price)
        self._price_history: dict[str, list[tuple[int, float]]] = {}

    def record_price(
        self,
        condition_id: str,
        yes_price: float,
        question: str = "",
        slug: str = "",
    ) -> MomentumSignal | None:
        """Record a price observation. Returns signal if momentum detected."""
        now = int(time.time())
        history = self._price_history.setdefault(condition_id, [])
        history.append((now, yes_price))

        # Trim old entries outside window
        cutoff = now - int(self._window_seconds)
        trimmed = [(ts, p) for ts, p in history if ts >= cutoff]
        self._price_history[condition_id] = trimmed

        if len(trimmed) < 2:
            return None

        oldest_ts, oldest_price = trimmed[0]
        if oldest_price <= 0:
            return None

        change_pct = (yes_price - oldest_price) / oldest_price
        minutes_elapsed = (now - oldest_ts) / 60

        if abs(change_pct) >= self._min_change:
            direction = "UP" if change_pct > 0 else "DOWN"
            signal = MomentumSignal(
                condition_id=condition_id,
                question=question,
                direction=direction,
                price_start=oldest_price,
                price_now=yes_price,
                change_pct=change_pct,
                minutes_elapsed=minutes_elapsed,
                slug=slug,
            )
            logger.info(
                "MOMENTUM [%s]: %s — %.1f%% in %.0f min (%.2f → %.2f)",
                direction,
                question[:50],
                change_pct * 100,
                minutes_elapsed,
                oldest_price,
                yes_price,
            )
            return signal

        return None

    def bootstrap_from_history(
        self, condition_id: str, history: list[dict[str, Any]], question: str = "", slug: str = ""
    ) -> MomentumSignal | None:
        """Load historical OHLC data from CLOB API into the price history.

        Expects list of dicts with 't' (timestamp) and 'p' (price) keys,
        as returned by the CLOB /prices-history endpoint.
        Returns a signal if momentum is detected in the historical data.
        """
        if not history:
            return None

        signal = None
        for point in history:
            ts = int(point.get("t", 0))
            price = float(point.get("p", 0))
            if ts > 0 and price > 0:
                entries = self._price_history.setdefault(condition_id, [])
                entries.append((ts, price))

        # After loading, check for momentum
        entries = self._price_history.get(condition_id, [])
        if len(entries) >= 2:
            now = int(time.time())
            cutoff = now - int(self._window_seconds)
            recent = [(ts, p) for ts, p in entries if ts >= cutoff]
            self._price_history[condition_id] = recent

            if len(recent) >= 2:
                oldest_price = recent[0][1]
                newest_price = recent[-1][1]
                if oldest_price > 0:
                    change = (newest_price - oldest_price) / oldest_price
                    if abs(change) >= self._min_change:
                        signal = MomentumSignal(
                            condition_id=condition_id,
                            question=question,
                            direction="UP" if change > 0 else "DOWN",
                            price_start=oldest_price,
                            price_now=newest_price,
                            change_pct=change,
                            minutes_elapsed=(recent[-1][0] - recent[0][0]) / 60,
                            slug=slug,
                        )
                        logger.info(
                            "MOMENTUM [%s] (historical): %s — %.1f%%",
                            signal.direction, question[:40], change * 100,
                        )

        return signal

    def cleanup_stale(self) -> int:
        """Remove markets with no recent price data."""
        now = int(time.time())
        cutoff = now - int(self._window_seconds * 2)
        stale = [
            cid
            for cid, hist in self._price_history.items()
            if not hist or hist[-1][0] < cutoff
        ]
        for cid in stale:
            del self._price_history[cid]
        return len(stale)
