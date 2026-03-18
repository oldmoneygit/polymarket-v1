"""Unit tests for src/backtest/engine.py."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from src.backtest.engine import BacktestEngine, BacktestResult, BacktestTrade
from src.db.models import MarketInfo, TraderTrade


def _trade(
    price: float = 0.52,
    outcome: str = "Yes",
    condition_id: str = "cond1",
    age_seconds: int = 300,
) -> TraderTrade:
    return TraderTrade(
        proxy_wallet="0x" + "bb" * 20,
        timestamp=int(time.time()) - age_seconds,
        condition_id=condition_id,
        transaction_hash=f"0xhash{condition_id}{price}",
        price=price,
        size=100.0,
        usdc_size=price * 100,
        side="BUY",
        outcome=outcome,
        title="Test Market",
        slug="nba-test",
        event_slug="nba-test",
    )


def _market(
    condition_id: str = "cond1",
    resolved: bool = True,
    resolved_outcome: str = "Yes",
    volume: float = 50000.0,
    yes_price: float = 0.52,
) -> MarketInfo:
    return MarketInfo(
        condition_id=condition_id,
        question="Test?",
        category="sports",
        volume=volume,
        liquidity=10000.0,
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        is_resolved=resolved,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        resolved_outcome=resolved_outcome,
    )


class TestBacktestEngine:
    def test_winning_trade(self) -> None:
        trades = [_trade(price=0.52, outcome="Yes")]
        markets = {"cond1": _market(resolved=True, resolved_outcome="Yes")}
        result = BacktestEngine().run(trades, markets)
        assert result.total_trades == 1
        assert result.wins == 1
        assert result.total_pnl > 0

    def test_losing_trade(self) -> None:
        trades = [_trade(price=0.52, outcome="Yes")]
        markets = {"cond1": _market(resolved=True, resolved_outcome="No")}
        result = BacktestEngine().run(trades, markets)
        assert result.losses == 1
        assert result.total_pnl < 0

    def test_unresolved_market(self) -> None:
        trades = [_trade()]
        markets = {"cond1": _market(resolved=False)}
        result = BacktestEngine().run(trades, markets)
        assert result.total_trades == 1
        assert result.resolved_trades == 0

    def test_missing_market_skipped(self) -> None:
        trades = [_trade(condition_id="nonexistent")]
        result = BacktestEngine().run(trades, {})
        assert result.total_trades == 0

    def test_deduplication(self) -> None:
        trades = [
            _trade(price=0.52, condition_id="cond1"),
            _trade(price=0.55, condition_id="cond1"),
        ]
        markets = {"cond1": _market()}
        result = BacktestEngine().run(trades, markets)
        assert result.total_trades == 1

    def test_multiple_markets(self) -> None:
        trades = [
            _trade(price=0.52, condition_id="c1"),
            _trade(price=0.40, condition_id="c2"),
        ]
        markets = {
            "c1": _market("c1", resolved=True, resolved_outcome="Yes"),
            "c2": _market("c2", resolved=True, resolved_outcome="No"),
        }
        result = BacktestEngine().run(trades, markets)
        assert result.total_trades == 2
        assert result.wins == 1
        assert result.losses == 1


class TestBacktestResult:
    def test_win_rate(self) -> None:
        r = BacktestResult(resolved_trades=10, wins=7, losses=3)
        assert r.win_rate == 0.7

    def test_win_rate_empty(self) -> None:
        assert BacktestResult().win_rate == 0.0

    def test_profit_factor(self) -> None:
        r = BacktestResult(trades=[
            BacktestTrade(0, "c1", "T", "Yes", 0.5, 5, "0x", True, True, 1.0, 4.0),
            BacktestTrade(0, "c2", "T", "Yes", 0.5, 5, "0x", True, False, 0.0, -5.0),
        ])
        assert r.profit_factor == 4.0 / 5.0

    def test_sharpe_estimate(self) -> None:
        r = BacktestResult(
            resolved_trades=3,
            trades=[
                BacktestTrade(0, "c1", "T", "Yes", 0.5, 5, "0x", True, True, 1.0, 4.0),
                BacktestTrade(0, "c2", "T", "Yes", 0.5, 5, "0x", True, True, 1.0, 3.0),
                BacktestTrade(0, "c3", "T", "Yes", 0.5, 5, "0x", True, False, 0.0, -2.0),
            ],
        )
        assert r.sharpe_estimate != 0.0
