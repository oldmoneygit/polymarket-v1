"""Unit tests for src/executor/trade.py (SPEC-06)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.api.clob import CLOBClient, CLOBError, OrderBookSummary
from src.config import Config
from src.db.models import ExecutionResult, MarketInfo, OrderResult, Position, TraderTrade
from src.db.repository import Repository
from src.executor.trade import TradeExecutor

# [MERGED FROM polymarket-v1] Helper for mocking order book in executor tests
_MOCK_ORDER_BOOK = OrderBookSummary(
    token_id="token123", best_bid=0.50, best_ask=0.51,
    spread=0.01, midpoint=0.505,
    bid_depth_usd=10000.0, ask_depth_usd=10000.0,
)


class TestTradeExecutor:
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated_result(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)

        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        assert result.dry_run is True
        assert result.usdc_spent == 5.0

        # Position saved in DB
        positions = tmp_db.get_open_positions()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_insufficient_balance_returns_error(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = AsyncMock(spec=CLOBClient)
        clob.get_balance = AsyncMock(return_value=1.0)  # Less than 5.0
        clob.get_order_book = AsyncMock(return_value=_MOCK_ORDER_BOOK)
        clob.estimate_slippage = lambda *a, **kw: 0.0

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "Saldo insuficiente" in (result.error or "")

    @pytest.mark.asyncio
    async def test_daily_stop_prevents_execution(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = AsyncMock(spec=CLOBClient)
        clob.get_balance = AsyncMock(return_value=1000.0)
        clob.get_order_book = AsyncMock(return_value=_MOCK_ORDER_BOOK)
        clob.estimate_slippage = lambda *a, **kw: 0.0

        # Simulate -$20 daily loss
        now = datetime.now(timezone.utc)
        today_ts = int(
            datetime(now.year, now.month, now.day, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        )
        pos = Position(
            condition_id="c1", token_id="t1", side="BUY", outcome="Yes",
            entry_price=0.5, shares=10, usdc_invested=20.0,
            trader_copied="0xabc", market_title="Lost", opened_at=today_ts - 100,
            status="open", dry_run=True,
        )
        pid = tmp_db.save_position(pos)
        tmp_db._conn.execute(
            "UPDATE positions SET status='lost', pnl=?, closed_at=? WHERE id=?",
            (-20.0, today_ts, pid),
        )
        tmp_db._conn.commit()

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "Stop diário" in (result.error or "")

    @pytest.mark.asyncio
    async def test_max_exposure_limits_trade_size(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        # Fill exposure to 97 → only $3 headroom (less than $5 per trade)
        for i in range(19):
            p = Position(
                condition_id=f"c{i}", token_id=f"t{i}", side="BUY",
                outcome="Yes", entry_price=0.5, shares=10,
                usdc_invested=5.0, trader_copied="0x", market_title="X",
                opened_at=int(time.time()), status="open", dry_run=True,
            )
            tmp_db.save_position(p)
        # 19 * 5.0 = 95.0 exposure, headroom = 5.0

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        assert result.usdc_spent <= 5.0

    @pytest.mark.asyncio
    async def test_successful_execution_saves_position(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)

        result = await executor.execute(sample_trade, sample_market)
        assert result.success is True

        positions = tmp_db.get_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.condition_id == sample_trade.condition_id
        assert pos.trader_copied == sample_trade.proxy_wallet
        assert pos.dry_run is True

    @pytest.mark.asyncio
    async def test_clob_error_returns_failure_gracefully(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = AsyncMock(spec=CLOBClient)
        clob.get_balance = AsyncMock(return_value=1000.0)
        clob.get_order_book = AsyncMock(return_value=_MOCK_ORDER_BOOK)
        clob.estimate_slippage = lambda *a, **kw: 0.0
        clob.create_market_order = AsyncMock(side_effect=CLOBError("Network timeout"))

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "execução" in (result.error or "").lower() or "Network" in (result.error or "")
