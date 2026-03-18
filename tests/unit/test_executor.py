"""Unit tests for src/executor/trade.py (SPEC-06)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.clob import CLOBClient, CLOBError
from src.config import Config
from src.db.models import ExecutionResult, MarketInfo, OrderResult, Position, TraderTrade
from src.db.repository import Repository
from src.executor.trade import TradeExecutor


class TestDryRunExecution:
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
        assert result.usdc_spent > 0
        assert result.order_id is not None


class TestInsufficientBalance:
    @pytest.mark.asyncio
    async def test_insufficient_balance_returns_error(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = AsyncMock()
        clob.get_balance = AsyncMock(return_value=1.0)

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "insuficiente" in result.error.lower()


class TestDailyStopLoss:
    @pytest.mark.asyncio
    async def test_daily_stop_prevents_execution(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        # Create losing positions to trigger daily stop
        now = datetime.now(timezone.utc)
        today_ts = int(
            datetime(now.year, now.month, now.day, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        )
        for i in range(5):
            pos = Position(
                condition_id=f"cond{i}",
                token_id=f"tok{i}",
                side="BUY",
                outcome="Yes",
                entry_price=0.5,
                shares=10.0,
                usdc_invested=5.0,
                trader_copied="0xtrader",
                market_title="Test",
                opened_at=int(time.time()) - 3600,
                status="open",
                dry_run=True,
            )
            pid = tmp_db.save_position(pos)
            tmp_db._conn.execute(
                "UPDATE positions SET status='lost', pnl=?, closed_at=? WHERE id=?",
                (-5.0, today_ts, pid),
            )
            tmp_db._conn.commit()

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "stop diário" in result.error.lower()


class TestMaxExposureLimits:
    @pytest.mark.asyncio
    async def test_max_exposure_limits_trade_size(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        # Fill up exposure to near max
        for i in range(19):
            pos = Position(
                condition_id=f"cond{i}",
                token_id=f"tok{i}",
                side="BUY",
                outcome="Yes",
                entry_price=0.5,
                shares=10.0,
                usdc_invested=5.0,
                trader_copied="0xtrader",
                market_title="Test",
                opened_at=int(time.time()),
                status="open",
                dry_run=True,
            )
            tmp_db.save_position(pos)

        # Exposure is now $95 out of $100 max
        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        assert result.usdc_spent == 5.0  # Full $5 fits within remaining $5

    @pytest.mark.asyncio
    async def test_zero_headroom_returns_error(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        for i in range(20):
            pos = Position(
                condition_id=f"cond{i}",
                token_id=f"tok{i}",
                side="BUY",
                outcome="Yes",
                entry_price=0.5,
                shares=10.0,
                usdc_invested=5.0,
                trader_copied="0xtrader",
                market_title="Test",
                opened_at=int(time.time()),
                status="open",
                dry_run=True,
            )
            tmp_db.save_position(pos)

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "capital" in result.error.lower()


class TestSuccessfulExecution:
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
        assert positions[0].condition_id == sample_trade.condition_id
        assert positions[0].trader_copied == sample_trade.proxy_wallet
        assert positions[0].dry_run is True


class TestCLOBOrderError:
    @pytest.mark.asyncio
    async def test_clob_create_order_error(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        """CLOBError during create_market_order."""
        from src.api.clob import OrderBookSummary
        clob = AsyncMock(spec=CLOBClient)
        clob.get_balance = AsyncMock(return_value=1000.0)
        clob.get_order_book = AsyncMock(return_value=OrderBookSummary(
            token_id="t", best_bid=0.5, best_ask=0.51, spread=0.01,
            midpoint=0.505, bid_depth_usd=10000, ask_depth_usd=10000,
        ))
        clob.estimate_slippage = MagicMock(return_value=0.0)
        clob.create_market_order = AsyncMock(
            side_effect=CLOBError("Order rejected")
        )

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "execução" in result.error.lower()


class TestCLOBErrorHandling:
    @pytest.mark.asyncio
    async def test_clob_error_returns_failure_gracefully(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        clob = AsyncMock()
        clob.get_balance = AsyncMock(side_effect=CLOBError("Connection refused"))

        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is False
        assert "saldo" in result.error.lower()
