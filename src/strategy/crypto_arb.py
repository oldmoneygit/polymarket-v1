"""Crypto latency arbitrage detector — spots mispricings in short-term crypto markets.

Monitors BTC/ETH/SOL 5min and 15min up/down markets on Polymarket.
Detects when the Polymarket price lags behind actual spot price movement.

This is a detection module only — it generates signals, not trades.
Integration with live exchange feeds (Binance, Coinbase) is required for production use.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Polymarket crypto market slugs to watch
CRYPTO_MARKET_PATTERNS = [
    "btc-above", "btc-below", "btc-up", "btc-down",
    "eth-above", "eth-below", "eth-up", "eth-down",
    "sol-above", "sol-below", "sol-up", "sol-down",
    "xrp-above", "xrp-below",
    "5min", "15min", "1hour",
]


@dataclass(frozen=True)
class ArbSignal:
    """A detected latency arbitrage opportunity."""

    condition_id: str
    question: str
    asset: str  # "BTC", "ETH", "SOL"
    direction: str  # "UP" or "DOWN"
    polymarket_price: float
    estimated_fair_price: float
    edge_pct: float  # How much the market is mispriced
    time_window_minutes: int  # 5, 15, or 60
    slug: str


def is_crypto_short_term(slug: str, question: str) -> bool:
    """Check if a market is a short-term crypto up/down bet."""
    combined = f"{slug} {question}".lower()
    has_crypto = any(
        asset in combined
        for asset in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp"]
    )
    has_timeframe = any(
        tf in combined
        for tf in ["5 min", "5min", "15 min", "15min", "1 hour", "1hour", "next hour"]
    )
    has_direction = any(
        d in combined
        for d in ["up or down", "above", "below", "higher", "lower", "increase", "decrease"]
    )
    return has_crypto and (has_timeframe or has_direction)


def extract_asset(slug: str, question: str) -> str:
    """Extract the crypto asset from market text."""
    combined = f"{slug} {question}".lower()
    if "btc" in combined or "bitcoin" in combined:
        return "BTC"
    if "eth" in combined or "ethereum" in combined:
        return "ETH"
    if "sol" in combined or "solana" in combined:
        return "SOL"
    if "xrp" in combined:
        return "XRP"
    return "UNKNOWN"


class CryptoArbDetector:
    """Detects latency arbitrage opportunities in crypto short-term markets.

    In production, this should be connected to live exchange price feeds
    (Binance WebSocket, Coinbase, etc.) to compare Polymarket prices
    against real-time spot prices.

    For now, it uses momentum detection as a proxy: if the Polymarket
    price hasn't caught up to a rapid price movement, that's an opportunity.
    """

    def __init__(self, min_edge_pct: float = 0.03) -> None:
        self._min_edge = min_edge_pct
        # Track recent spot prices (simulated — in prod, use exchange feed)
        self._spot_cache: dict[str, list[tuple[int, float]]] = {}
        self._window_seconds = 300  # 5 min lookback

    def record_spot_price(self, asset: str, price: float) -> None:
        """Record a spot price observation from an exchange feed."""
        now = int(time.time())
        history = self._spot_cache.setdefault(asset, [])
        history.append((now, price))
        # Trim old
        cutoff = now - self._window_seconds
        self._spot_cache[asset] = [(t, p) for t, p in history if t >= cutoff]

    def evaluate(
        self,
        condition_id: str,
        question: str,
        slug: str,
        polymarket_yes_price: float,
        polymarket_no_price: float,
    ) -> ArbSignal | None:
        """Check if a crypto market has a latency arbitrage opportunity.

        This is a simplified version. Production implementation would:
        1. Get real-time spot price from Binance/Coinbase WebSocket
        2. Calculate fair value of the Polymarket contract
        3. Compare with current Polymarket price
        4. Signal if edge > min_edge_pct
        """
        if not is_crypto_short_term(slug, question):
            return None

        asset = extract_asset(slug, question)
        if asset == "UNKNOWN":
            return None

        # Determine if this is an "up" or "down" market
        combined = f"{slug} {question}".lower()
        is_up_market = any(w in combined for w in ["above", "up", "higher", "increase"])

        # Determine time window
        if "5min" in combined or "5 min" in combined:
            window = 5
        elif "15min" in combined or "15 min" in combined:
            window = 15
        else:
            window = 60

        # Check spot price movement
        spot_history = self._spot_cache.get(asset, [])
        if len(spot_history) < 2:
            return None

        oldest_price = spot_history[0][1]
        current_price = spot_history[-1][1]
        if oldest_price <= 0:
            return None

        spot_change_pct = (current_price - oldest_price) / oldest_price

        # Estimate fair price based on spot movement
        if is_up_market:
            # If spot is going up, YES should be worth more
            if spot_change_pct > 0.001:  # Meaningful upward movement
                estimated_fair = min(0.95, polymarket_yes_price + spot_change_pct)
            else:
                return None
        else:
            # If spot is going down, YES (of "will go down") should be worth more
            if spot_change_pct < -0.001:
                estimated_fair = min(0.95, polymarket_yes_price + abs(spot_change_pct))
            else:
                return None

        edge = estimated_fair - polymarket_yes_price
        if edge < self._min_edge:
            return None

        signal = ArbSignal(
            condition_id=condition_id,
            question=question,
            asset=asset,
            direction="UP" if is_up_market else "DOWN",
            polymarket_price=polymarket_yes_price,
            estimated_fair_price=estimated_fair,
            edge_pct=edge,
            time_window_minutes=window,
            slug=slug,
        )

        logger.info(
            "CRYPTO ARB [%s %s %dmin]: market=%.2f fair=%.2f edge=%.1f%%",
            asset, signal.direction, window,
            polymarket_yes_price, estimated_fair, edge * 100,
        )

        return signal
