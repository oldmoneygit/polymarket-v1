"""Confluence detector — amplifies signals when multiple traders agree."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Tier weights — Tier S signals count more
TRADER_TIERS: dict[str, str] = {
    "0xf195721ad850377c96cd634457c70cd9e8308057": "S",  # JaJackson
    "0xa8e089ade142c95538e06196e09c85681112ad50": "S",  # Wannac
    "0x492442eab586f242b53bda933fd5de859c8a3782": "S",  # 0x4924
    "0xead152b855effa6b5b5837f53b24c0756830c76a": "A",  # elkmonkey
    "0x02227b8f5a9636e895607edd3185ed6ee5598ff7": "A",  # HorizonSplendidView
    "0xc2e7800b5af46e6093872b177b7a5e7f0563be51": "A",  # beachboy4
    "0x37c1874a60d348903594a96703e0507c518fc53a": "A",  # CemeterySun
    "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c": "A",  # Herdonia
}

TIER_WEIGHT = {"S": 3, "A": 1}


@dataclass
class MarketSignal:
    """Accumulated signal for a single market from multiple traders."""

    condition_id: str
    title: str
    outcome: str  # "Yes" or "No"
    traders: list[str] = field(default_factory=list)
    total_usdc: float = 0.0
    weighted_score: int = 0
    first_seen: int = 0
    last_seen: int = 0

    @property
    def trader_count(self) -> int:
        return len(self.traders)

    @property
    def is_confluence(self) -> bool:
        """True when 2+ independent traders agree on the same market."""
        return self.trader_count >= 2

    @property
    def strength(self) -> str:
        if self.weighted_score >= 6:
            return "STRONG"
        if self.weighted_score >= 3:
            return "MODERATE"
        return "WEAK"


class ConfluenceDetector:
    """Tracks trader activity per market and detects confluence signals."""

    def __init__(self, window_seconds: int = 7200) -> None:
        self._window = window_seconds
        # Key: (condition_id, outcome) → MarketSignal
        self._signals: dict[tuple[str, str], MarketSignal] = {}

    def record_trade(
        self,
        condition_id: str,
        title: str,
        outcome: str,
        trader_wallet: str,
        usdc_size: float,
    ) -> MarketSignal:
        """Record a trade and return the updated signal for this market."""
        now = int(time.time())
        key = (condition_id, outcome)

        signal = self._signals.get(key)
        if signal is None or (now - signal.last_seen) > self._window:
            signal = MarketSignal(
                condition_id=condition_id,
                title=title,
                outcome=outcome,
                first_seen=now,
            )
            self._signals[key] = signal

        wallet_lower = trader_wallet.lower()
        if wallet_lower not in signal.traders:
            signal.traders.append(wallet_lower)
            tier = TRADER_TIERS.get(wallet_lower, "A")
            signal.weighted_score += TIER_WEIGHT.get(tier, 1)

        signal.total_usdc += usdc_size
        signal.last_seen = now

        if signal.is_confluence:
            logger.info(
                "CONFLUENCE [%s]: %s %s — %d traders (%s), $%.0f total",
                signal.strength,
                signal.outcome,
                signal.title[:50],
                signal.trader_count,
                ", ".join(w[:10] for w in signal.traders),
                signal.total_usdc,
            )

        return signal

    def get_active_confluences(self) -> list[MarketSignal]:
        """Return all current confluence signals (2+ traders)."""
        now = int(time.time())
        return [
            s
            for s in self._signals.values()
            if s.is_confluence and (now - s.last_seen) <= self._window
        ]

    def cleanup_stale(self) -> int:
        """Remove signals older than the window. Returns count removed."""
        now = int(time.time())
        stale_keys = [
            k
            for k, s in self._signals.items()
            if (now - s.last_seen) > self._window
        ]
        for k in stale_keys:
            del self._signals[k]
        return len(stale_keys)
