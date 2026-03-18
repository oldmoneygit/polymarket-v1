"""Unit tests for src/monitor/position.py (SPEC-07)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.api.clob import CLOBClient
from src.config import Config
from src.db.models import MarketInfo, Position
from src.db.repository import Repository
from src.monitor.position import PositionMonitor


def _make_market(
    is_resolved: bool = False,
    resolved_outcome: str = "",
    yes_price: float = 0.52,
    no_price: float = 0.48,
) -> MarketInfo:
    return MarketInfo(
        condition_id="0xcond",
        question="Test?",
        category="sports",
        volume=50000.0,
        liquidity=10000.0,
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        is_resolved=is_resolved,
        yes_price=yes_price,
        no_price=no_price,
        resolved_outcome=resolved_outcome,
    )


class TestResolvedMarketYesWin:
    @pytest.mark.asyncio
    async def test_resolved_market_yes_win_calculates_pnl(
        self, config: Config, sample_position: Position, tmp_db: Repository
    ) -> None:
        pid = tmp_db.save_position(sample_position)
        resolved_market = _make_market(is_resolved=True, resolved_outcome="Yes")

        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=resolved_market)
        callback = AsyncMock()

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
            on_position_resolved=callback,
        )

        await monitor.check_positions()

        positions = tmp_db.get_open_positions()
        assert len(positions) == 0  # No longer open

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[1] == "won"
        pnl = call_args[2]
        assert pnl > 0  # shares - usdc_invested


class TestResolvedMarketYesLoss:
    @pytest.mark.asyncio
    async def test_resolved_market_yes_loss_calculates_pnl(
        self, config: Config, tmp_db: Repository
    ) -> None:
        position = Position(
            condition_id="0xcond",
            token_id="token1",
            side="BUY",
            outcome="Yes",
            entry_price=0.52,
            shares=9.62,
            usdc_invested=5.0,
            trader_copied="0xtrader",
            market_title="Test",
            opened_at=int(time.time()) - 3600,
            status="open",
            dry_run=True,
        )
        pid = tmp_db.save_position(position)

        resolved_market = _make_market(is_resolved=True, resolved_outcome="No")
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=resolved_market)
        callback = AsyncMock()

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
            on_position_resolved=callback,
        )

        await monitor.check_positions()

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[1] == "lost"
        pnl = call_args[2]
        assert pnl == pytest.approx(-5.0)


class TestUnresolvedMarket:
    @pytest.mark.asyncio
    async def test_unresolved_market_no_action(
        self, config: Config, sample_position: Position, tmp_db: Repository
    ) -> None:
        tmp_db.save_position(sample_position)
        unresolved = _make_market(is_resolved=False)

        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=unresolved)
        callback = AsyncMock()

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
            on_position_resolved=callback,
        )

        await monitor.check_positions()

        positions = tmp_db.get_open_positions()
        assert len(positions) == 1  # Still open
        callback.assert_not_called()


class TestTakeProfit:
    @pytest.mark.asyncio
    async def test_take_profit_triggers_sell(
        self, config: Config, tmp_db: Repository
    ) -> None:
        position = Position(
            condition_id="0xcond",
            token_id="token1",
            side="BUY",
            outcome="Yes",
            entry_price=0.50,
            shares=10.0,
            usdc_invested=5.0,
            trader_copied="0xtrader",
            market_title="Test",
            opened_at=int(time.time()) - 3600,
            status="open",
            dry_run=True,
        )
        tmp_db.save_position(position)

        # Price went from 0.50 to 0.65 = +30% (above 20% take profit)
        high_price_market = _make_market(
            is_resolved=False, yes_price=0.65, no_price=0.35
        )

        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=high_price_market)
        tp_callback = AsyncMock()

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
            on_take_profit=tp_callback,
        )

        await monitor.check_positions()

        positions = tmp_db.get_open_positions()
        assert len(positions) == 0  # Sold

    @pytest.mark.asyncio
    async def test_take_profit_disabled_no_sell(
        self, tmp_db: Repository
    ) -> None:
        position = Position(
            condition_id="0xcond",
            token_id="token1",
            side="BUY",
            outcome="Yes",
            entry_price=0.50,
            shares=10.0,
            usdc_invested=5.0,
            trader_copied="0xtrader",
            market_title="Test",
            opened_at=int(time.time()) - 3600,
            status="open",
            dry_run=True,
        )
        tmp_db.save_position(position)

        high_price_market = _make_market(
            is_resolved=False, yes_price=0.65, no_price=0.35
        )
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=high_price_market)

        no_tp_config = Config(
            poly_api_key="key",
            poly_api_secret="secret",
            poly_api_passphrase="pass",
            poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="",
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC",
            telegram_chat_id="123",
            dry_run=True,
            take_profit_pct=0.0,  # Disabled
        )

        monitor = PositionMonitor(
            config=no_tp_config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(no_tp_config),
            repository=tmp_db,
        )

        await monitor.check_positions()

        positions = tmp_db.get_open_positions()
        assert len(positions) == 1  # Still open — take profit disabled


class TestDetermineOutcomeNo:
    def test_no_position_wins_on_no_resolution(self) -> None:
        pos = Position(
            condition_id="c", token_id="t", side="BUY", outcome="No",
            entry_price=0.4, shares=10, usdc_invested=4,
            trader_copied="0xt", market_title="T", opened_at=0,
        )
        assert PositionMonitor._determine_outcome(pos, "No") is True
        assert PositionMonitor._determine_outcome(pos, "0") is True
        assert PositionMonitor._determine_outcome(pos, "false") is True
        assert PositionMonitor._determine_outcome(pos, "Yes") is False


class TestTakeProfitCallback:
    @pytest.mark.asyncio
    async def test_take_profit_calls_callback(
        self, config: Config, tmp_db: Repository
    ) -> None:
        position = Position(
            condition_id="0xcond", token_id="token1", side="BUY",
            outcome="Yes", entry_price=0.50, shares=10.0,
            usdc_invested=5.0, trader_copied="0xtrader",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(position)

        high_price_market = _make_market(
            is_resolved=False, yes_price=0.65, no_price=0.35
        )
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=high_price_market)
        tp_callback = AsyncMock()

        monitor = PositionMonitor(
            config=config, polymarket_client=mock_api,
            clob_client=CLOBClient(config), repository=tmp_db,
            on_take_profit=tp_callback,
        )
        await monitor.check_positions()
        tp_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_take_profit_callback_exception(
        self, config: Config, tmp_db: Repository
    ) -> None:
        position = Position(
            condition_id="0xcond", token_id="token1", side="BUY",
            outcome="Yes", entry_price=0.50, shares=10.0,
            usdc_invested=5.0, trader_copied="0xtrader",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(position)

        high = _make_market(is_resolved=False, yes_price=0.65, no_price=0.35)
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=high)
        tp_callback = AsyncMock(side_effect=RuntimeError("boom"))

        monitor = PositionMonitor(
            config=config, polymarket_client=mock_api,
            clob_client=CLOBClient(config), repository=tmp_db,
            on_take_profit=tp_callback,
        )
        # Should not crash
        await monitor.check_positions()


class TestResolvedCallbackException:
    @pytest.mark.asyncio
    async def test_on_resolved_callback_exception(
        self, config: Config, sample_position: Position, tmp_db: Repository
    ) -> None:
        tmp_db.save_position(sample_position)
        resolved = _make_market(is_resolved=True, resolved_outcome="Yes")
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=resolved)
        callback = AsyncMock(side_effect=RuntimeError("cb error"))

        monitor = PositionMonitor(
            config=config, polymarket_client=mock_api,
            clob_client=CLOBClient(config), repository=tmp_db,
            on_position_resolved=callback,
        )
        # Should not crash
        await monitor.check_positions()
        callback.assert_called_once()


class TestCheckSingleException:
    @pytest.mark.asyncio
    async def test_exception_in_check_single(
        self, config: Config, tmp_db: Repository
    ) -> None:
        pos = Position(
            condition_id="0xcond", token_id="t", side="BUY", outcome="Yes",
            entry_price=0.5, shares=10, usdc_invested=5, trader_copied="0xt",
            market_title="Test", opened_at=int(time.time()), status="open",
        )
        tmp_db.save_position(pos)

        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(side_effect=RuntimeError("api fail"))

        monitor = PositionMonitor(
            config=config, polymarket_client=mock_api,
            clob_client=CLOBClient(config), repository=tmp_db,
        )
        # Should not crash
        await monitor.check_positions()


class TestStartLoop:
    @pytest.mark.asyncio
    async def test_start_runs_and_can_be_cancelled(
        self, config: Config, tmp_db: Repository
    ) -> None:
        """Cover lines 38-40: the start() while True loop."""
        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=None)

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
        )

        async def cancel_after_one_cycle() -> None:
            await asyncio.sleep(0.05)
            task.cancel()

        task = asyncio.create_task(monitor.start())
        cancel_task = asyncio.create_task(cancel_after_one_cycle())

        with pytest.raises(asyncio.CancelledError):
            await task
        await cancel_task


class TestMarketNotFound:
    @pytest.mark.asyncio
    async def test_market_not_found_skips(
        self, config: Config, sample_position: Position, tmp_db: Repository
    ) -> None:
        tmp_db.save_position(sample_position)

        mock_api = AsyncMock()
        mock_api.get_market_info = AsyncMock(return_value=None)

        monitor = PositionMonitor(
            config=config,
            polymarket_client=mock_api,
            clob_client=CLOBClient(config),
            repository=tmp_db,
        )

        await monitor.check_positions()

        positions = tmp_db.get_open_positions()
        assert len(positions) == 1  # Unchanged
