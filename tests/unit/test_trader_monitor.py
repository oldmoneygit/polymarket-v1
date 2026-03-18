"""Unit tests for src/monitor/trader.py (SPEC-04)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Config
from src.db.models import TraderTrade
from src.db.repository import Repository
from src.monitor.trader import TraderMonitor


def _make_trade(
    tx_hash: str = "0xhash1",
    timestamp: int | None = None,
    wallet: str = "",
) -> TraderTrade:
    return TraderTrade(
        proxy_wallet=wallet or ("0x" + "b2" * 20),
        timestamp=timestamp or (int(time.time()) - 60),
        condition_id="cond1",
        transaction_hash=tx_hash,
        price=0.52,
        size=100.0,
        usdc_size=52.0,
        side="BUY",
        outcome="Yes",
        title="Test Market",
        slug="ucl-test-match",
        event_slug="ucl-test",
    )


class TestTraderMonitor:
    @pytest.mark.asyncio
    async def test_new_trade_triggers_callback(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        api = AsyncMock()
        api.get_trader_activity.return_value = [_make_trade()]

        monitor = TraderMonitor(config, api, tmp_db, callback)
        monitor.load_seen_hashes()
        await monitor.run_once()

        callback.assert_called_once()
        called_trade = callback.call_args[0][0]
        assert called_trade.transaction_hash == "0xhash1"

    @pytest.mark.asyncio
    async def test_already_seen_trade_skipped(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        api = AsyncMock()
        api.get_trader_activity.return_value = [_make_trade()]

        # Pre-save the hash
        tmp_db.save_seen_hash("0xhash1", config.trader_wallets[0])

        monitor = TraderMonitor(config, api, tmp_db, callback)
        monitor.load_seen_hashes()
        await monitor.run_once()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_old_trade_skipped(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        api = AsyncMock()
        old_ts = int(time.time()) - 7200  # 2 hours ago
        api.get_trader_activity.return_value = [_make_trade(timestamp=old_ts)]

        monitor = TraderMonitor(config, api, tmp_db, callback)
        monitor.load_seen_hashes()
        await monitor.run_once()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_failure_continues_other_traders(
        self,
        env_vars: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_db: Repository,
    ) -> None:
        w1 = "0x" + "aa" * 20
        w2 = "0x" + "bb" * 20
        monkeypatch.setenv("TRADER_WALLETS", f"{w1},{w2}")
        cfg = Config.load()

        callback = AsyncMock()
        api = AsyncMock()

        # First wallet fails, second succeeds
        trade_w2 = _make_trade(tx_hash="0xhashW2", wallet=w2)

        async def side_effect(wallet: str, limit: int = 50) -> list[TraderTrade]:
            if wallet == w1.lower():
                raise Exception("API down")
            return [trade_w2]

        api.get_trader_activity.side_effect = side_effect

        monitor = TraderMonitor(cfg, api, tmp_db, callback)
        monitor.load_seen_hashes()
        await monitor.run_once()

        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplication_persists_across_restarts(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        api = AsyncMock()
        api.get_trader_activity.return_value = [_make_trade()]

        # First run
        m1 = TraderMonitor(config, api, tmp_db, callback)
        m1.load_seen_hashes()
        await m1.run_once()
        assert callback.call_count == 1

        # Second run — new monitor instance (simulates restart)
        callback.reset_mock()
        m2 = TraderMonitor(config, api, tmp_db, callback)
        m2.load_seen_hashes()
        await m2.run_once()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_traders_all_checked(
        self,
        env_vars: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_db: Repository,
    ) -> None:
        w1 = "0x" + "aa" * 20
        w2 = "0x" + "bb" * 20
        monkeypatch.setenv("TRADER_WALLETS", f"{w1},{w2}")
        cfg = Config.load()

        callback = AsyncMock()
        api = AsyncMock()
        api.get_trader_activity.return_value = [
            _make_trade(tx_hash="0xunique_per_call")
        ]

        # Different hash per call
        call_count = 0

        async def varying_trades(wallet: str, limit: int = 50) -> list[TraderTrade]:
            nonlocal call_count
            call_count += 1
            return [_make_trade(tx_hash=f"0xhash_{call_count}")]

        api.get_trader_activity.side_effect = varying_trades

        monitor = TraderMonitor(cfg, api, tmp_db, callback)
        monitor.load_seen_hashes()
        await monitor.run_once()

        assert callback.call_count == 2
