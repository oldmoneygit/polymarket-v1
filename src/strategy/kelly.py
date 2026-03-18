"""Kelly Criterion position sizing — dynamic allocation based on estimated edge.

# [MERGED FROM polymarket-v1] New module — Kelly Criterion for position sizing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def kelly_fraction(win_prob: float, odds: float) -> float:
    """Calculate optimal Kelly fraction for a binary bet.

    Args:
        win_prob: Estimated probability of winning (0-1).
        odds: Payout odds (profit/risk ratio). For Polymarket:
              odds = (1 - price) / price  (e.g., price=0.60 -> odds=0.667)

    Returns:
        Optimal fraction of bankroll to bet (can be negative = don't bet).
    """
    if odds <= 0 or win_prob <= 0 or win_prob >= 1:
        return 0.0
    return (win_prob * (odds + 1) - 1) / odds


def fractional_kelly(
    win_prob: float,
    price: float,
    bankroll: float,
    fraction: float = 0.25,
    min_bet: float = 1.0,
    max_bet: float = 50.0,
) -> float:
    """Calculate position size using fractional Kelly.

    Uses 1/4 Kelly by default (conservative — reduces variance).

    Args:
        win_prob: Estimated probability of winning.
        price: Current market price (also the cost per share).
        bankroll: Total available capital.
        fraction: Kelly fraction (0.25 = quarter Kelly).
        min_bet: Minimum bet size in USD.
        max_bet: Maximum bet size in USD.

    Returns:
        Recommended position size in USD.
    """
    if price <= 0 or price >= 1:
        return 0.0

    odds = (1.0 - price) / price
    full_kelly = kelly_fraction(win_prob, odds)

    if full_kelly <= 0:
        return 0.0  # Negative edge — don't bet

    sized = bankroll * full_kelly * fraction
    return max(min_bet, min(sized, max_bet))


def estimate_win_prob_from_trader(
    trader_win_rate: float,
    market_price: float,
    confidence_weight: float = 0.6,
) -> float:
    """Estimate win probability by blending trader's historical win rate with market price.

    Args:
        trader_win_rate: Historical win rate of the trader being copied (0-1).
        market_price: Current market-implied probability.
        confidence_weight: How much to trust the trader vs the market (0-1).
            0.6 = 60% trader, 40% market.

    Returns:
        Blended win probability estimate.
    """
    return (trader_win_rate * confidence_weight) + (
        market_price * (1.0 - confidence_weight)
    )
