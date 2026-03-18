"""Alpha decay analysis — measures how copy-trade edge degrades with delay."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.backtest.engine import BacktestEngine, BacktestResult
from src.db.models import MarketInfo, TraderTrade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecayPoint:
    """Win rate and PnL at a specific copy delay."""

    delay_minutes: int
    win_rate: float
    total_pnl: float
    resolved_trades: int
    avg_entry_price: float


def analyze_alpha_decay(
    trades: list[TraderTrade],
    markets: dict[str, MarketInfo],
    delays: list[int] | None = None,
) -> list[DecayPoint]:
    """Run backtests at different max_age_minutes to measure alpha decay.

    Shows how the edge erodes as you copy trades later and later.
    Default delays: [1, 5, 10, 15, 30, 45, 60, 90, 120] minutes.
    """
    if delays is None:
        delays = [1, 5, 10, 15, 30, 45, 60, 90, 120]

    results: list[DecayPoint] = []

    for delay in delays:
        engine = BacktestEngine(
            max_age_minutes=delay,
            capital_per_trade=5.0,
            min_volume=5000.0,
            min_prob=0.10,
            max_prob=0.90,
        )
        bt = engine.run(trades, markets)

        avg_price = 0.0
        if bt.trades:
            avg_price = sum(t.entry_price for t in bt.trades) / len(bt.trades)

        point = DecayPoint(
            delay_minutes=delay,
            win_rate=bt.win_rate,
            total_pnl=bt.total_pnl,
            resolved_trades=bt.resolved_trades,
            avg_entry_price=avg_price,
        )
        results.append(point)

        logger.info(
            "Alpha decay @ %dmin: wr=%.1f%% pnl=$%.2f trades=%d avg_price=%.3f",
            delay, bt.win_rate * 100, bt.total_pnl, bt.resolved_trades, avg_price,
        )

    return results


def format_decay_report(points: list[DecayPoint]) -> str:
    """Format alpha decay results as a readable table."""
    lines = [
        "Alpha Decay Analysis",
        "=" * 60,
        f"{'Delay':>8} | {'Win Rate':>9} | {'PnL':>10} | {'Trades':>7} | {'Avg Price':>10}",
        "-" * 60,
    ]
    for p in points:
        lines.append(
            f"{p.delay_minutes:>6}min | {p.win_rate:>8.1%} | ${p.total_pnl:>9.2f} | {p.resolved_trades:>7} | {p.avg_entry_price:>10.4f}"
        )
    return "\n".join(lines)
