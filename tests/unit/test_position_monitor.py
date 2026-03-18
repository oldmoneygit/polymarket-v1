"""Unit tests for src/monitor/position.py (SPEC-07)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.config import Config
from src.db.models import MarketInfo, Position
from src.db.repository import Repository
from src.monitor.position import PositionMonitor


def _make_market(
    is_resolved: bool = False,
    resolved_outcome: str = "",
    yes_price: float = 0.70,
    no_price: float = 0.30,
) -> MarketInfo:
    return MarketInfo(
        condition_id="cond1",
        question="Test Market",
        category="sports",
        volume=50000.0,
        liquidity=10000.0,
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        is_resolved=is_resolved,
        yes_price=yes_price,
        no_price=no_price,
        slug="test-slug",
        resolved_outcome=resolved_outcome,
    )


class TestPositionMonitor:
    @pytest.mark.asyncio
    async def test_resolved_market_yes_win_calculates_pnl(
        self, config: Config, tmp_db: Repository
    ) -> None:
        pos = Position(
            condition_id="cond1", token_id="tok1", side="BUY",
            outcome="Yes", entry_price=0.52, shares=9.62,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        pid = tmp_db.save_position(pos)

        api = AsyncMock()
        api.get_market_info.return_value = _make_market(
            is_resolved=True, resolved_outcome="Yes"
        )
        clob = AsyncMock()
        callback = AsyncMock()

        monitor = PositionMonitor(
            config, api, clob, tmp_db, on_position_resolved=callback
        )
        await monitor.check_positions()

        # Position should be updated
        open_positions = tmp_db.get_open_positions()
        assert len(open_positions) == 0

        # Callback called with "won"
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[1] == "won"
        gross = 9.62 - 5.0  # shares - invested
        fee = gross * 0.02  # 2% fee on profit
        assert args[2] == pytest.approx(gross - fee)  # After fee

    @pytest.mark.asyncio
    async def test_resolved_market_yes_loss_calculates_pnl(
        self, config: Config, tmp_db: Repository
    ) -> None:
        pos = Position(
            condition_id="cond1", token_id="tok1", side="BUY",
            outcome="Yes", entry_price=0.52, shares=9.62,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(pos)

        api = AsyncMock()
        api.get_market_info.return_value = _make_market(
            is_resolved=True, resolved_outcome="No"
        )
        clob = AsyncMock()
        callback = AsyncMock()

        monitor = PositionMonitor(
            config, api, clob, tmp_db, on_position_resolved=callback
        )
        await monitor.check_positions()

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[1] == "lost"
        assert args[2] == pytest.approx(-5.0)

    @pytest.mark.asyncio
    async def test_unresolved_market_no_action(
        self, config: Config, tmp_db: Repository
    ) -> None:
        pos = Position(
            condition_id="cond1", token_id="tok1", side="BUY",
            outcome="Yes", entry_price=0.52, shares=9.62,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(pos)

        api = AsyncMock()
        api.get_market_info.return_value = _make_market(
            is_resolved=False, yes_price=0.55  # small gain, below take_profit
        )
        clob = AsyncMock()
        callback = AsyncMock()

        monitor = PositionMonitor(
            config, api, clob, tmp_db, on_position_resolved=callback
        )
        await monitor.check_positions()

        # Still open
        open_positions = tmp_db.get_open_positions()
        assert len(open_positions) == 1
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_take_profit_triggers_sell(
        self, config: Config, tmp_db: Repository
    ) -> None:
        pos = Position(
            condition_id="cond1", token_id="tok1", side="BUY",
            outcome="Yes", entry_price=0.50, shares=10.0,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(pos)

        # Price went from 0.50 → 0.70 = +40%, above take_profit of 20%
        api = AsyncMock()
        api.get_market_info.return_value = _make_market(
            is_resolved=False, yes_price=0.70
        )
        clob = AsyncMock()
        tp_callback = AsyncMock()

        monitor = PositionMonitor(
            config, api, clob, tmp_db, on_take_profit=tp_callback
        )
        await monitor.check_positions()

        # Position should be marked "sold"
        open_positions = tmp_db.get_open_positions()
        assert len(open_positions) == 0

        tp_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_take_profit_disabled_no_sell(
        self,
        env_vars: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_db: Repository,
    ) -> None:
        monkeypatch.setenv("TAKE_PROFIT_PCT", "0.0")
        cfg = Config.load()

        pos = Position(
            condition_id="cond1", token_id="tok1", side="BUY",
            outcome="Yes", entry_price=0.50, shares=10.0,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="Test", opened_at=int(time.time()) - 3600,
            status="open", dry_run=True,
        )
        tmp_db.save_position(pos)

        api = AsyncMock()
        api.get_market_info.return_value = _make_market(
            is_resolved=False, yes_price=0.90  # +80% but take_profit disabled
        )
        clob = AsyncMock()
        tp_callback = AsyncMock()

        monitor = PositionMonitor(
            cfg, api, clob, tmp_db, on_take_profit=tp_callback
        )
        await monitor.check_positions()

        # Still open
        open_positions = tmp_db.get_open_positions()
        assert len(open_positions) == 1
        tp_callback.assert_not_called()
