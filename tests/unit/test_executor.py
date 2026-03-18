"""Unit tests for src/executor/trade.py — updated for Tier 1."""

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
from src.strategy.confluence import ConfluenceDetector

_MOCK_ORDER_BOOK = OrderBookSummary(
    token_id="token123", best_bid=0.50, best_ask=0.51,
    spread=0.01, midpoint=0.505,
    bid_depth_usd=10000.0, ask_depth_usd=10000.0,
)


class TestTradeExecutorBuy:
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
        clob.get_balance = AsyncMock(return_value=1.0)
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
        for i in range(19):
            p = Position(
                condition_id=f"c{i}", token_id=f"t{i}", side="BUY",
                outcome="Yes", entry_price=0.5, shares=10,
                usdc_invested=5.0, trader_copied="0x", market_title="X",
                opened_at=int(time.time()), status="open", dry_run=True,
            )
            tmp_db.save_position(p)

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


class TestTradeExecutorSell:
    @pytest.mark.asyncio
    async def test_sell_closes_existing_position(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        # First create an open position
        pos = Position(
            condition_id=sample_trade.condition_id,
            token_id="token123",
            side="BUY",
            outcome="Yes",
            entry_price=0.52,
            shares=9.62,
            usdc_invested=5.0,
            trader_copied=sample_trade.proxy_wallet,
            market_title=sample_trade.title,
            opened_at=int(time.time()) - 3600,
            status="open",
            dry_run=True,
        )
        tmp_db.save_position(pos)

        sell_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash="0xtxsell001",
            price=0.60,
            size=9.62,
            usdc_size=5.77,
            side="SELL",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
            token_id="token123",
        )

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sell_trade, sample_market)

        assert result.success is True
        assert result.dry_run is True

        # Position should be closed
        open_positions = tmp_db.get_open_positions()
        assert len(open_positions) == 0

    @pytest.mark.asyncio
    async def test_sell_fails_without_position(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        sell_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash="0xtxsell002",
            price=0.60,
            size=9.62,
            usdc_size=5.77,
            side="SELL",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
            token_id="token123",
        )

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db)
        result = await executor.execute(sell_trade, sample_market)

        assert result.success is False
        assert "sem posição" in (result.error or "")


class TestCopySizing:
    @pytest.mark.asyncio
    async def test_proportional_sizing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_vars: dict[str, str],
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        monkeypatch.setenv("COPY_SIZE_MODE", "proportional")
        monkeypatch.setenv("COPY_SIZE_MULTIPLIER", "0.10")  # 10% of trader
        cfg = Config.load()

        clob = CLOBClient(cfg)
        executor = TradeExecutor(cfg, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        # Trader's trade is $52, 10% = $5.20
        assert result.usdc_spent == pytest.approx(5.2, abs=0.1)

    @pytest.mark.asyncio
    async def test_max_copy_trade_caps_size(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_vars: dict[str, str],
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        monkeypatch.setenv("COPY_SIZE_MODE", "proportional")
        monkeypatch.setenv("COPY_SIZE_MULTIPLIER", "1.0")  # 100% of trader = $52
        monkeypatch.setenv("MAX_COPY_TRADE_USD", "10.0")
        cfg = Config.load()

        clob = CLOBClient(cfg)
        executor = TradeExecutor(cfg, clob, tmp_db)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        assert result.usdc_spent <= 10.0


class TestConfluenceIntegration:
    @pytest.mark.asyncio
    async def test_confluence_boosts_position_size(
        self,
        config: Config,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        tmp_db: Repository,
    ) -> None:
        confluence = ConfluenceDetector()
        # Record 2 trades from different S-tier traders → STRONG signal
        confluence.record_trade(
            sample_trade.condition_id, sample_trade.title, "Yes",
            "0xf195721ad850377c96cd634457c70cd9e8308057", 100.0,  # JaJackson (S)
        )
        confluence.record_trade(
            sample_trade.condition_id, sample_trade.title, "Yes",
            "0xa8e089ade142c95538e06196e09c85681112ad50", 200.0,  # Wannac (S)
        )

        clob = CLOBClient(config)
        executor = TradeExecutor(config, clob, tmp_db, confluence)
        result = await executor.execute(sample_trade, sample_market)

        assert result.success is True
        # With STRONG confluence (2.0x), $5 base → $10
        assert result.usdc_spent == pytest.approx(10.0, abs=0.5)
