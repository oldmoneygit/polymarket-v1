"""Edge calculator — determines if a trade has positive expected value.

edge = model_probability - implied_probability - costs - time_discount

Only enter trades with net_edge > min_edge_pct (default 2%).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeResult:
    """Result of edge calculation for a potential trade."""

    model_prob: float  # Our estimated probability
    market_prob: float  # Market-implied probability (price)
    raw_edge: float  # model - market
    transaction_cost: float  # Fees as fraction
    time_discount: float  # Capital lockup cost
    net_edge: float  # Raw edge - costs
    has_edge: bool  # net_edge > threshold
    ev_per_dollar: float  # Expected value per $1 wagered


def calculate_edge(
    model_prob: float,
    market_price: float,
    transaction_fee: float = 0.02,
    hours_to_resolution: float = 6.0,
    annual_rate: float = 0.05,
    min_edge: float = 0.02,
) -> EdgeResult:
    """Calculate the net edge for a potential trade.

    Args:
        model_prob: Our estimated probability of the outcome (0-1).
        market_price: Current market price / implied probability (0-1).
        transaction_fee: Total transaction cost as fraction (0.02 = 2%).
        hours_to_resolution: Hours until market resolves.
        annual_rate: Opportunity cost of capital (5% annual default).
        min_edge: Minimum edge required to trade.
    """
    if market_price <= 0 or market_price >= 1:
        return EdgeResult(
            model_prob=model_prob, market_prob=market_price,
            raw_edge=0.0, transaction_cost=transaction_fee,
            time_discount=0.0, net_edge=0.0,
            has_edge=False, ev_per_dollar=0.0,
        )

    raw_edge = model_prob - market_price

    # Time value of money discount (capital locked up)
    hours_fraction = hours_to_resolution / 8760  # Hours in a year
    time_discount = market_price * annual_rate * hours_fraction

    net_edge = raw_edge - transaction_fee - time_discount

    # EV per dollar wagered
    odds = (1.0 - market_price) / market_price
    ev_per_dollar = model_prob * odds - (1 - model_prob) - transaction_fee

    has_edge = net_edge >= min_edge

    return EdgeResult(
        model_prob=model_prob,
        market_prob=market_price,
        raw_edge=raw_edge,
        transaction_cost=transaction_fee,
        time_discount=time_discount,
        net_edge=net_edge,
        has_edge=has_edge,
        ev_per_dollar=ev_per_dollar,
    )


def estimate_model_prob_from_copy(
    trader_win_rate: float,
    market_price: float,
    confluence_count: int = 1,
    trader_confidence: float = 0.6,
) -> float:
    """Estimate model probability for a copy trade.

    Blends trader's historical win rate with market price,
    boosted by confluence signals.

    Args:
        trader_win_rate: Historical win rate of copied trader (0-1).
        market_price: Current market-implied probability.
        confluence_count: Number of independent traders agreeing.
        trader_confidence: How much to trust trader vs market (0-1).
    """
    # Base blend
    base = (trader_win_rate * trader_confidence) + (
        market_price * (1.0 - trader_confidence)
    )

    # Confluence boost: each additional trader adds 3% confidence
    confluence_boost = min((confluence_count - 1) * 0.03, 0.10)
    boosted = min(base + confluence_boost, 0.95)

    return max(0.05, boosted)
