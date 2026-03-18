"""Unit tests for src/monitor/trader.py (SPEC-04)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Config
from src.db.models import TraderTrade
from src.db.repository import Repository
from src.monitor.trader import TraderMonitor


def _make_trade(
    tx_hash: str = "0xhash1",
    timestamp: int | None = None,
    wallet: str = "0x" + "b2" * 20,
    **overrides: object,
) -> TraderTrade:
    defaults = dict(
        proxy_wallet=wallet,
        timestamp=timestamp or int(time.time()) - 60,
        condition_id="0xcond",
        transaction_hash=tx_hash,
        price=0.52,
        size=100.0,
        usdc_size=52.0,
        side="BUY",
        outcome="Yes",
        title="Test Market",
        slug="ucl-test",
        event_slug="ucl-test",
        trader_name="TestTrader",
        token_id="token1",
    )
    defaults.update(overrides)
    return TraderTrade(**defaults)  # type: ignore[arg-type]


class TestNewTradeDetection:
    @pytest.mark.asyncio
    async def test_new_trade_triggers_callback(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        mock_api = AsyncMock()
        trade = _make_trade()
        mock_api.get_trader_activity = AsyncMock(return_value=[trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        await monitor.run_once()

        callback.assert_called_once()
        called_trade = callback.call_args[0][0]
        assert called_trade.transaction_hash == "0xhash1"


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_already_seen_trade_skipped(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        mock_api = AsyncMock()
        trade = _make_trade()
        mock_api.get_trader_activity = AsyncMock(return_value=[trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        await monitor.run_once()
        assert callback.call_count == 1

        # Second cycle with same trade
        callback.reset_mock()
        await monitor.run_once()
        assert callback.call_count == 0

    @pytest.mark.asyncio
    async def test_deduplication_persists_across_restarts(
        self, config: Config, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "dedup.db"
        repo1 = Repository(db_path=db_path)
        callback = AsyncMock()
        mock_api = AsyncMock()
        trade = _make_trade()
        mock_api.get_trader_activity = AsyncMock(return_value=[trade])

        monitor1 = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=repo1,
            on_new_trade=callback,
        )
        await monitor1.run_once()
        assert callback.call_count == 1
        repo1.close()

        # "Restart" with new monitor and repo but same DB
        repo2 = Repository(db_path=db_path)
        callback2 = AsyncMock()
        monitor2 = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=repo2,
            on_new_trade=callback2,
        )
        monitor2.load_seen_hashes()
        await monitor2.run_once()
        assert callback2.call_count == 0
        repo2.close()


class TestOldTradesSkipped:
    @pytest.mark.asyncio
    async def test_old_trade_skipped(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        mock_api = AsyncMock()
        old_trade = _make_trade(
            tx_hash="0xold",
            timestamp=int(time.time()) - 7200,  # 2 hours old
        )
        mock_api.get_trader_activity = AsyncMock(return_value=[old_trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        await monitor.run_once()
        callback.assert_not_called()


class TestAPIFailureHandling:
    @pytest.mark.asyncio
    async def test_api_failure_continues_other_traders(
        self, tmp_db: Repository, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wallet1 = "0x" + "b2" * 20
        wallet2 = "0x" + "cc" * 20
        monkeypatch.setenv("TRADER_WALLETS", f"{wallet1},{wallet2}")
        two_wallet_config = Config.load()

        callback = AsyncMock()
        mock_api = AsyncMock()

        trade2 = _make_trade(tx_hash="0xfromwallet2", wallet=wallet2)

        async def side_effect(wallet: str, limit: int = 50) -> list[TraderTrade]:
            if wallet == wallet1:
                raise ConnectionError("API down for wallet1")
            return [trade2]

        mock_api.get_trader_activity = AsyncMock(side_effect=side_effect)

        monitor = TraderMonitor(
            config=two_wallet_config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        await monitor.run_once()
        # Should still process wallet2 despite wallet1 failure
        callback.assert_called_once()


class TestEmptyTransactionHash:
    @pytest.mark.asyncio
    async def test_empty_tx_hash_skipped(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        mock_api = AsyncMock()
        no_hash_trade = _make_trade(tx_hash="")
        mock_api.get_trader_activity = AsyncMock(return_value=[no_hash_trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )
        await monitor.run_once()
        callback.assert_not_called()


class TestCallbackException:
    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock(side_effect=RuntimeError("callback boom"))
        mock_api = AsyncMock()
        trade = _make_trade()
        mock_api.get_trader_activity = AsyncMock(return_value=[trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )
        # Should not raise despite callback error
        await monitor.run_once()
        callback.assert_called_once()


class TestStartLoop:
    @pytest.mark.asyncio
    async def test_start_runs_and_can_be_cancelled(
        self, config: Config, tmp_db: Repository
    ) -> None:
        """Cover lines 42-47: the start() while True loop."""
        callback = AsyncMock()
        mock_api = AsyncMock()
        mock_api.get_trader_activity = AsyncMock(return_value=[])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        async def cancel_after_one_cycle() -> None:
            await asyncio.sleep(0.05)
            task.cancel()

        task = asyncio.create_task(monitor.start())
        cancel_task = asyncio.create_task(cancel_after_one_cycle())

        with pytest.raises(asyncio.CancelledError):
            await task
        await cancel_task


class TestMultipleTraders:
    @pytest.mark.asyncio
    async def test_multiple_traders_all_checked(
        self, config: Config, tmp_db: Repository
    ) -> None:
        callback = AsyncMock()
        mock_api = AsyncMock()

        wallet = config.trader_wallets[0]
        trade = _make_trade(wallet=wallet)
        mock_api.get_trader_activity = AsyncMock(return_value=[trade])

        monitor = TraderMonitor(
            config=config,
            polymarket_client=mock_api,
            repository=tmp_db,
            on_new_trade=callback,
        )

        await monitor.run_once()
        assert mock_api.get_trader_activity.call_count == len(
            config.trader_wallets
        )
