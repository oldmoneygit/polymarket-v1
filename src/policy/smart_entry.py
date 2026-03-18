"""Smart entry calculator — multi-signal entry planning.

Analyzes 4 signals to determine optimal entry strategy:
1. Price vs VWAP (are we buying above or below average?)
2. Orderbook depth (enough liquidity?)
3. Price momentum (is price moving for or against us?)
4. Flow imbalance (more buys or sells recently?)

Generates an entry plan: MARKET (urgent), LIMIT (patient), or SKIP.
Inspired by Dylan's smart_entry.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from src.api.clob import OrderBookSummary

logger = logging.getLogger(__name__)


class EntryStrategy(Enum):
    MARKET = "MARKET"    # Execute immediately (strong signals)
    LIMIT = "LIMIT"      # Place limit order slightly below ask
    PATIENT = "PATIENT"  # Wait for better price
    SKIP = "SKIP"        # Signals too negative, don't enter


@dataclass(frozen=True)
class EntryPlan:
    """Recommended entry plan with price levels."""

    strategy: EntryStrategy
    target_price: float     # Recommended entry price
    urgency: float          # 0-1 (1 = enter now)
    signals: dict[str, float]  # Individual signal scores (-1 to +1)
    reason: str


class SmartEntryCalculator:
    """Calculates optimal entry strategy based on multiple signals."""

    def __init__(
        self,
        urgency_threshold: float = 0.60,
        skip_threshold: float = -0.30,
    ) -> None:
        self._urgency_thresh = urgency_threshold
        self._skip_thresh = skip_threshold

    def calculate(
        self,
        book: OrderBookSummary,
        trade_price: float,
        market_yes_price: float,
        recent_prices: list[float] | None = None,
    ) -> EntryPlan:
        """Calculate entry plan from orderbook and price data.

        Args:
            book: Current orderbook snapshot.
            trade_price: Price the copied trader entered at.
            market_yes_price: Current YES price.
            recent_prices: List of recent prices (newest last) for momentum.
        """
        signals: dict[str, float] = {}

        # Signal 1: Price vs trader's entry (are we getting a worse price?)
        if trade_price > 0:
            price_diff = (trade_price - market_yes_price) / trade_price
            # Positive = market cheaper than trader's entry = good for us
            signals["price_vs_trader"] = max(-1, min(1, price_diff * 10))
        else:
            signals["price_vs_trader"] = 0.0

        # Signal 2: Orderbook depth (enough liquidity?)
        if book.ask_depth_usd >= 1000:
            signals["depth"] = 1.0
        elif book.ask_depth_usd >= 200:
            signals["depth"] = 0.5
        elif book.ask_depth_usd >= 50:
            signals["depth"] = 0.0
        else:
            signals["depth"] = -1.0

        # Signal 3: Spread (tight = good, wide = bad)
        if book.spread_pct < 0.02:
            signals["spread"] = 1.0
        elif book.spread_pct < 0.05:
            signals["spread"] = 0.3
        else:
            signals["spread"] = -0.5

        # Signal 4: Price momentum (is price moving in our favor?)
        if recent_prices and len(recent_prices) >= 3:
            oldest = recent_prices[0]
            newest = recent_prices[-1]
            if oldest > 0:
                momentum = (newest - oldest) / oldest
                # Negative momentum = price dropping = good to buy
                signals["momentum"] = max(-1, min(1, -momentum * 5))
            else:
                signals["momentum"] = 0.0
        else:
            signals["momentum"] = 0.0

        # Aggregate score (weighted average)
        weights = {"price_vs_trader": 0.35, "depth": 0.25, "spread": 0.20, "momentum": 0.20}
        total_score = sum(signals[k] * weights[k] for k in signals)

        # Determine strategy
        if total_score >= self._urgency_thresh:
            strategy = EntryStrategy.MARKET
            target = book.best_ask  # Buy at ask (immediate)
            urgency = min(1.0, total_score)
            reason = "Strong signals — enter now"
        elif total_score >= 0:
            strategy = EntryStrategy.LIMIT
            # Place limit at midpoint (save on spread)
            target = book.midpoint
            urgency = max(0, total_score)
            reason = "OK signals — use limit order"
        elif total_score >= self._skip_thresh:
            strategy = EntryStrategy.PATIENT
            target = book.best_bid + book.spread * 0.25  # Near bid
            urgency = 0.0
            reason = "Weak signals — wait for better price"
        else:
            strategy = EntryStrategy.SKIP
            target = 0.0
            urgency = 0.0
            reason = "Negative signals — skip this entry"

        logger.debug(
            "Smart entry: %s @ %.4f (score=%.2f, urgency=%.2f) — %s",
            strategy.value, target, total_score, urgency, reason,
        )

        return EntryPlan(
            strategy=strategy,
            target_price=round(target, 4),
            urgency=round(urgency, 2),
            signals=signals,
            reason=reason,
        )
