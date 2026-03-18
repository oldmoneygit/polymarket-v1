"""Whale conviction scoring — advanced multi-signal trader scoring.

Evolves basic confluence into a weighted conviction system:
- whale_count * 25 (how many whales agree)
- log10(total_usd) * 8 (how much money is behind it)
- profit_factor (historical profitability of these whales)
- Position delta detection (new entry, increase, decrease, exit)

Inspired by Dylan's wallet_scanner.py.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PositionDelta(Enum):
    """Type of position change detected."""

    NEW_ENTRY = "NEW_ENTRY"
    SIZE_INCREASE = "SIZE_INCREASE"
    SIZE_DECREASE = "SIZE_DECREASE"
    EXIT = "EXIT"
    NO_CHANGE = "NO_CHANGE"


class SignalStrength(Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


@dataclass
class ConvictionSignal:
    """Aggregated conviction signal for a market."""

    condition_id: str
    title: str
    outcome: str
    whale_count: int = 0
    total_usd: float = 0.0
    wallets: list[str] = field(default_factory=list)
    deltas: list[PositionDelta] = field(default_factory=list)
    conviction_score: float = 0.0
    first_seen: int = 0
    last_seen: int = 0

    @property
    def strength(self) -> SignalStrength:
        if self.conviction_score >= 70:
            return SignalStrength.STRONG
        if self.conviction_score >= 45:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    @property
    def edge_boost(self) -> float:
        """Edge adjustment based on conviction."""
        if self.strength == SignalStrength.STRONG:
            return 0.08  # +8% edge
        if self.strength == SignalStrength.MODERATE:
            return 0.04  # +4% edge
        return 0.0

    @property
    def sizing_multiplier(self) -> float:
        """Position sizing multiplier based on conviction."""
        if self.strength == SignalStrength.STRONG:
            return 2.0
        if self.strength == SignalStrength.MODERATE:
            return 1.5
        return 1.0


def compute_conviction_score(
    whale_count: int,
    total_usd: float,
    avg_whale_profit_rate: float = 0.05,
) -> float:
    """Compute conviction score (0-100).

    Formula:
      count_factor = whale_count * 25
      usd_factor = log10(max(total_usd, 1)) * 8
      profit_factor = min(avg_whale_profit_rate * 200, 15)
      score = min(count_factor + usd_factor + profit_factor, 100)
    """
    count_factor = whale_count * 25
    usd_factor = math.log10(max(total_usd, 1.0)) * 8
    profit_factor = min(avg_whale_profit_rate * 200, 15.0)

    return min(count_factor + usd_factor + profit_factor, 100.0)


class WhaleConvictionTracker:
    """Tracks whale activity per market and computes conviction signals."""

    def __init__(self, window_seconds: int = 7200) -> None:
        self._window = window_seconds
        # Key: (condition_id, outcome) -> ConvictionSignal
        self._signals: dict[tuple[str, str], ConvictionSignal] = {}
        # Track previous sizes for delta detection
        # Key: (wallet, condition_id) -> last_known_usd
        self._prev_sizes: dict[tuple[str, str], float] = {}

    def record_trade(
        self,
        condition_id: str,
        title: str,
        outcome: str,
        wallet: str,
        usd_size: float,
        side: str = "BUY",
    ) -> ConvictionSignal:
        """Record a trade and return updated conviction signal."""
        now = int(time.time())
        key = (condition_id, outcome)

        signal = self._signals.get(key)
        if signal is None or (now - signal.last_seen) > self._window:
            signal = ConvictionSignal(
                condition_id=condition_id,
                title=title,
                outcome=outcome,
                first_seen=now,
            )
            self._signals[key] = signal

        wallet_lower = wallet.lower()

        # Detect position delta
        size_key = (wallet_lower, condition_id)
        prev_size = self._prev_sizes.get(size_key, 0.0)

        if side == "SELL":
            delta = PositionDelta.EXIT if usd_size >= prev_size * 0.9 else PositionDelta.SIZE_DECREASE
            self._prev_sizes[size_key] = max(0, prev_size - usd_size)
        elif prev_size == 0:
            delta = PositionDelta.NEW_ENTRY
            self._prev_sizes[size_key] = usd_size
        elif usd_size > prev_size * 0.10:
            delta = PositionDelta.SIZE_INCREASE
            self._prev_sizes[size_key] = prev_size + usd_size
        else:
            delta = PositionDelta.NO_CHANGE

        # Update signal
        if wallet_lower not in signal.wallets:
            signal.wallets.append(wallet_lower)
            signal.whale_count = len(signal.wallets)

        signal.total_usd += usd_size
        signal.deltas.append(delta)
        signal.last_seen = now

        # Recompute conviction
        signal.conviction_score = compute_conviction_score(
            signal.whale_count, signal.total_usd,
        )

        if signal.conviction_score >= 45:
            logger.info(
                "CONVICTION [%s] %.0f: %s %s — %d whales, $%.0f, %s",
                signal.strength.value,
                signal.conviction_score,
                outcome, title[:40],
                signal.whale_count, signal.total_usd,
                delta.value,
            )

        return signal

    def get_signal(self, condition_id: str, outcome: str) -> ConvictionSignal | None:
        """Get current conviction signal for a market."""
        return self._signals.get((condition_id, outcome))

    def get_active_signals(self, min_score: float = 45.0) -> list[ConvictionSignal]:
        """Return all active conviction signals above threshold."""
        now = int(time.time())
        return [
            s for s in self._signals.values()
            if s.conviction_score >= min_score and (now - s.last_seen) <= self._window
        ]

    def cleanup_stale(self) -> int:
        """Remove stale signals outside the window."""
        now = int(time.time())
        stale = [k for k, s in self._signals.items() if (now - s.last_seen) > self._window]
        for k in stale:
            del self._signals[k]
        return len(stale)
