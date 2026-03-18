"""Event-driven backtesting engine for Polymarket strategies.

# [MERGED FROM polymarket-v1] New module — backtest simulation engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.config import Config
from src.db.models import FilterResult, MarketInfo, TraderTrade
from src.strategy.filter import TradeFilter

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """A single simulated trade in the backtest."""

    timestamp: int
    condition_id: str
    title: str
    outcome: str
    entry_price: float
    size_usd: float
    trader_wallet: str
    resolved: bool = False
    won: bool = False
    exit_price: float = 0.0
    pnl: float = 0.0


@dataclass
class BacktestResult:
    """Aggregate results of a backtest run."""

    total_trades: int = 0
    resolved_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        if self.resolved_trades == 0:
            return 0.0
        return self.wins / self.resolved_trades

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def avg_pnl(self) -> float:
        if not self.trades:
            return 0.0
        return self.total_pnl / len(self.trades)

    @property
    def sharpe_estimate(self) -> float:
        """Rough Sharpe ratio estimate (daily returns not available, use per-trade)."""
        if len(self.trades) < 2:
            return 0.0
        pnls = [t.pnl for t in self.trades if t.resolved]
        if not pnls:
            return 0.0
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
        std = variance ** 0.5
        if std == 0:
            return 0.0
        return mean / std


class BacktestEngine:
    """Runs a strategy backtest against historical trade + market data."""

    def __init__(
        self,
        capital_per_trade: float = 5.0,
        max_exposure: float = 100.0,
        max_daily_loss: float = 20.0,
        min_volume: float = 5000.0,
        min_prob: float = 0.10,
        max_prob: float = 0.90,
        max_age_minutes: int = 60,
        take_profit_pct: float = 0.20,
        slippage: float = 0.005,
    ) -> None:
        self._capital_per_trade = capital_per_trade
        self._max_exposure = max_exposure
        self._max_daily_loss = max_daily_loss
        self._slippage = slippage
        self._take_profit = take_profit_pct

        self._config_params = {
            "capital_per_trade": capital_per_trade,
            "max_exposure": max_exposure,
            "max_daily_loss": max_daily_loss,
            "min_volume": min_volume,
            "min_prob": min_prob,
            "max_prob": max_prob,
            "max_age_minutes": max_age_minutes,
            "take_profit_pct": take_profit_pct,
            "slippage": slippage,
        }

        self._filter = TradeFilter()
        self._filter_config = Config(
            poly_api_key="backtest",
            poly_api_secret="backtest",
            poly_api_passphrase="backtest",
            poly_wallet_address="0x" + "00" * 20,
            poly_private_key="",
            trader_wallets=["0x" + "00" * 20],
            telegram_bot_token="backtest",
            telegram_chat_id="0",
            capital_per_trade_usd=capital_per_trade,
            max_total_exposure_usd=max_exposure,
            max_daily_loss_usd=max_daily_loss,
            min_market_volume_usd=min_volume,
            min_probability=min_prob,
            max_probability=max_prob,
            max_trade_age_minutes=max_age_minutes,
            take_profit_pct=take_profit_pct,
            dry_run=True,
        )

    def run(
        self,
        trades: list[TraderTrade],
        markets: dict[str, MarketInfo],
    ) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            trades: Chronologically sorted trades from monitored traders.
            markets: Map of condition_id -> MarketInfo (with resolution data).
        """
        result = BacktestResult(params=self._config_params)
        open_positions: list[BacktestTrade] = []
        seen_markets: set[str] = set()
        equity = 0.0

        for trade in trades:
            market = markets.get(trade.condition_id)
            if market is None:
                continue

            # Dedup: one entry per market
            market_key = f"{trade.proxy_wallet}:{trade.condition_id}"
            if market_key in seen_markets:
                continue

            # Calculate current exposure
            current_exposure = sum(t.size_usd for t in open_positions)

            # For filtering, pretend market is not yet resolved (as it would be at trade time)
            filter_market = MarketInfo(
                condition_id=market.condition_id,
                question=market.question,
                category=market.category,
                volume=market.volume,
                liquidity=market.liquidity,
                end_date=market.end_date,
                is_resolved=False,  # At trade time, market was still open
                yes_price=market.yes_price,
                no_price=market.no_price,
                slug=market.slug,
            )

            filter_result = self._filter.evaluate(
                trade, filter_market, self._filter_config, current_exposure, trade.timestamp
            )
            if not filter_result.passed:
                continue

            seen_markets.add(market_key)

            # Simulate entry with slippage
            entry_price = trade.price * (1 + self._slippage)
            size = min(self._capital_per_trade, self._max_exposure - current_exposure)
            if size <= 0:
                continue

            bt_trade = BacktestTrade(
                timestamp=trade.timestamp,
                condition_id=trade.condition_id,
                title=trade.title,
                outcome=trade.outcome,
                entry_price=entry_price,
                size_usd=size,
                trader_wallet=trade.proxy_wallet,
            )

            # Check resolution
            if market.is_resolved:
                bt_trade.resolved = True
                won = self._check_win(trade.outcome, market.resolved_outcome)
                bt_trade.won = won
                if won:
                    shares = size / entry_price if entry_price > 0 else 0
                    bt_trade.pnl = shares - size  # $1/share - cost
                    bt_trade.exit_price = 1.0
                    result.wins += 1
                else:
                    bt_trade.pnl = -size
                    bt_trade.exit_price = 0.0
                    result.losses += 1
                result.resolved_trades += 1
            else:
                # Check take-profit if market has current price
                if self._take_profit > 0:
                    current = market.yes_price if trade.outcome == "Yes" else market.no_price
                    if entry_price > 0 and current > entry_price:
                        unrealized = (current - entry_price) / entry_price
                        if unrealized >= self._take_profit:
                            bt_trade.resolved = True
                            bt_trade.won = True
                            shares = size / entry_price
                            bt_trade.pnl = (current - entry_price) * shares
                            bt_trade.exit_price = current
                            result.wins += 1
                            result.resolved_trades += 1

            if not bt_trade.resolved:
                open_positions.append(bt_trade)

            result.trades.append(bt_trade)
            result.total_trades += 1
            result.total_pnl += bt_trade.pnl

            # Track drawdown
            equity += bt_trade.pnl
            if equity > result.peak_equity:
                result.peak_equity = equity
            drawdown = result.peak_equity - equity
            if drawdown > result.max_drawdown:
                result.max_drawdown = drawdown

        return result

    @staticmethod
    def _check_win(outcome: str, resolved_outcome: str) -> bool:
        if outcome == "Yes":
            return resolved_outcome.lower() in ("yes", "1", "true")
        return resolved_outcome.lower() in ("no", "0", "false")
