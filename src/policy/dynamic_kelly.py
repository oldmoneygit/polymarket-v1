"""Dynamic Kelly Criterion — 7-multiplier adaptive position sizing.

Inspired by Dylan's position_sizer.py. Calculates optimal position size
using fractional Kelly with 7 adjustment multipliers:

1. Confidence multiplier (how certain is the edge estimate)
2. Drawdown multiplier (from heat system)
3. Timeline multiplier (fast markets get more)
4. Volatility multiplier (high vol = reduce)
5. Regime multiplier (trending vs mean-reverting)
6. Category multiplier (sports vs politics vs crypto)
7. Liquidity multiplier (thin books = reduce)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.db.models import MarketInfo
from src.policy.drawdown import DrawdownManager
from src.policy.edge_calc import EdgeResult
from src.strategy.whale_conviction import ConvictionSignal, SignalStrength

logger = logging.getLogger(__name__)


# Category risk multipliers
CATEGORY_MULTIPLIERS = {
    "sports": 1.0,      # Most predictable
    "esports": 0.90,    # Good but smaller markets
    "crypto": 0.70,     # Volatile
    "politics": 0.60,   # Hard to predict, slow resolution
    "other": 0.50,      # Unknown category = conservative
}


@dataclass(frozen=True)
class SizingResult:
    """Result of dynamic Kelly sizing calculation."""

    base_kelly: float  # Raw Kelly fraction
    adjusted_kelly: float  # After all multipliers
    position_usd: float  # Final dollar amount
    multipliers: dict[str, float]  # Each multiplier value
    reason: str  # Human-readable explanation


class DynamicKellySizer:
    """Calculates position size using Kelly with 7 adaptive multipliers."""

    def __init__(
        self,
        bankroll: float = 200.0,
        kelly_fraction: float = 0.25,
        min_bet: float = 0.50,
        max_bet: float = 25.0,
        max_bankroll_pct: float = 0.10,
    ) -> None:
        self._bankroll = bankroll
        self._kelly_fraction = kelly_fraction
        self._min_bet = min_bet
        self._max_bet = max_bet
        self._max_bankroll_pct = max_bankroll_pct

    def calculate(
        self,
        edge: EdgeResult,
        market: MarketInfo,
        drawdown: DrawdownManager,
        conviction: ConvictionSignal | None = None,
        available_capital: float | None = None,
    ) -> SizingResult:
        """Calculate dynamic position size with all 7 multipliers."""
        bankroll = available_capital if available_capital is not None else self._bankroll

        if not edge.has_edge or edge.net_edge <= 0:
            return SizingResult(
                base_kelly=0.0, adjusted_kelly=0.0, position_usd=0.0,
                multipliers={}, reason="No edge",
            )

        # Base Kelly: f* = (p * b - q) / b
        price = edge.market_prob
        if price <= 0 or price >= 1:
            return SizingResult(
                base_kelly=0.0, adjusted_kelly=0.0, position_usd=0.0,
                multipliers={}, reason="Invalid price",
            )

        odds = (1.0 - price) / price
        win_prob = edge.model_prob
        full_kelly = (win_prob * (odds + 1) - 1) / odds
        if full_kelly <= 0:
            return SizingResult(
                base_kelly=full_kelly, adjusted_kelly=0.0, position_usd=0.0,
                multipliers={}, reason=f"Negative Kelly: {full_kelly:.4f}",
            )

        base = full_kelly * self._kelly_fraction

        # === 7 MULTIPLIERS ===

        multipliers: dict[str, float] = {}

        # 1. Confidence multiplier
        if conviction is not None and conviction.strength == SignalStrength.STRONG:
            conf_mult = 1.0
        elif conviction is not None and conviction.strength == SignalStrength.MODERATE:
            conf_mult = 0.75
        else:
            conf_mult = 0.50  # Low confidence when no conviction data
        multipliers["confidence"] = conf_mult

        # 2. Drawdown multiplier (from heat system)
        dd_state = drawdown.get_state()
        multipliers["drawdown"] = dd_state.kelly_multiplier

        # 3. Timeline multiplier (fast = more, slow = less)
        from datetime import datetime, timezone
        hours = max(0, (market.end_date - datetime.now(timezone.utc)).total_seconds() / 3600)
        if hours <= 6:
            time_mult = 1.3  # Fast market bonus
        elif hours <= 24:
            time_mult = 1.0
        elif hours <= 48:
            time_mult = 0.7
        else:
            time_mult = 0.4
        multipliers["timeline"] = time_mult

        # 4. Volatility multiplier (high spread = high vol = reduce)
        spread = abs(1.0 - market.yes_price - market.no_price)
        if spread < 0.03:
            vol_mult = 1.0
        elif spread < 0.06:
            vol_mult = 0.80
        else:
            vol_mult = 0.60
        multipliers["volatility"] = vol_mult

        # 5. Regime multiplier (simplified — based on recent PnL trend)
        # In production, use RegimeDetector. For now, use drawdown as proxy.
        if dd_state.drawdown_pct < 0.05:
            regime_mult = 1.1  # Things going well
        elif dd_state.drawdown_pct < 0.10:
            regime_mult = 1.0
        else:
            regime_mult = 0.80  # Losing streak
        multipliers["regime"] = regime_mult

        # 6. Category multiplier
        cat = market.category or "other"
        cat_mult = CATEGORY_MULTIPLIERS.get(cat, 0.50)
        multipliers["category"] = cat_mult

        # 7. Liquidity multiplier
        if market.liquidity >= 10000:
            liq_mult = 1.0
        elif market.liquidity >= 5000:
            liq_mult = 0.80
        elif market.liquidity >= 1000:
            liq_mult = 0.60
        else:
            liq_mult = 0.30
        multipliers["liquidity"] = liq_mult

        # Apply all multipliers
        adjusted = base
        for name, mult in multipliers.items():
            adjusted *= mult

        # Convert to dollars
        position_usd = bankroll * adjusted

        # Apply caps
        position_usd = min(position_usd, self._max_bet)
        position_usd = min(position_usd, bankroll * self._max_bankroll_pct)

        # Minimum viable bet
        if position_usd < self._min_bet:
            return SizingResult(
                base_kelly=full_kelly,
                adjusted_kelly=adjusted,
                position_usd=0.0,
                multipliers=multipliers,
                reason=f"Below min bet: ${position_usd:.2f} < ${self._min_bet:.2f}",
            )

        logger.info(
            "Kelly sizing: base=%.4f adjusted=%.4f → $%.2f "
            "(conf=%.1f dd=%.1f time=%.1f vol=%.1f regime=%.1f cat=%.1f liq=%.1f)",
            full_kelly, adjusted, position_usd,
            conf_mult, dd_state.kelly_multiplier, time_mult,
            vol_mult, regime_mult, cat_mult, liq_mult,
        )

        return SizingResult(
            base_kelly=full_kelly,
            adjusted_kelly=adjusted,
            position_usd=round(position_usd, 2),
            multipliers=multipliers,
            reason="OK",
        )
