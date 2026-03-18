"""Unit tests for src/notifier/telegram.py (SPEC-08)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.config import Config
from src.db.models import ExecutionResult, Position, TraderTrade
from src.db.repository import Repository
from src.notifier.telegram import TelegramNotifier


class TestFormatTradeExecuted:
    def test_format_trade_executed_message(
        self, sample_trade: TraderTrade
    ) -> None:
        result = ExecutionResult(
            success=True,
            order_id="ord1",
            price=0.52,
            usdc_spent=5.0,
            dry_run=True,
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, result)

        assert "Trade executado" in msg
        assert "HorizonSplendidView" in msg
        assert "PSG" in msg
        assert "$0.52" in msg
        assert "$5.00" in msg
        assert "DRY RUN" in msg

    def test_format_trade_executed_live(
        self, sample_trade: TraderTrade
    ) -> None:
        result = ExecutionResult(
            success=True,
            order_id="ord1",
            price=0.52,
            usdc_spent=5.0,
            dry_run=False,
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, result)
        assert "LIVE" in msg
        assert "DRY RUN" not in msg


class TestFormatPositionResolved:
    def test_format_position_resolved_win(
        self, sample_position: Position
    ) -> None:
        pnl = 4.62
        daily_pnl = 12.30
        msg = TelegramNotifier.format_position_resolved_win(
            sample_position, pnl, daily_pnl
        )

        assert "GANHOU" in msg
        assert "PSG" in msg
        assert "$5.00" in msg
        assert "+$4.62" in msg
        assert "12.30" in msg

    def test_format_position_resolved_loss(
        self, sample_position: Position
    ) -> None:
        pnl = -5.0
        daily_pnl = -2.70
        msg = TelegramNotifier.format_position_resolved_loss(
            sample_position, pnl, daily_pnl
        )

        assert "perdeu" in msg
        assert "PSG" in msg
        assert "$5.00" in msg
        assert "2.70" in msg


class TestFormatStatus:
    def test_format_status_message(
        self, config: Config, tmp_db: Repository, sample_position: Position
    ) -> None:
        tmp_db.save_position(sample_position)
        notifier = TelegramNotifier(config, tmp_db)
        msg = notifier.format_status()

        assert "Status do Bot" in msg
        assert "ATIVO" in msg
        assert "DRY RUN" in msg
        assert "1" in msg  # 1 position

    def test_format_status_empty(
        self, config: Config, tmp_db: Repository
    ) -> None:
        notifier = TelegramNotifier(config, tmp_db)
        msg = notifier.format_status()

        assert "Status do Bot" in msg
        assert "0" in msg  # 0 positions


class TestFormatTradeDetected:
    def test_format_trade_detected(self, sample_trade: TraderTrade) -> None:
        msg = TelegramNotifier.format_trade_detected(
            sample_trade, "Volume $3,200 abaixo do mínimo $5,000"
        )

        assert "NÃO copiado" in msg
        assert "HorizonSplendidView" in msg
        assert "Volume" in msg


class TestFormatError:
    def test_format_error_message(self) -> None:
        msg = TelegramNotifier.format_error("Stop diário atingido (-$20.00)")

        assert "ERRO" in msg
        assert "pausado" in msg
        assert "Stop diário" in msg
        assert "/resume" in msg


class TestDryRunFlagInMessages:
    def test_dry_run_flag_shown_in_messages(
        self, sample_trade: TraderTrade
    ) -> None:
        dry_result = ExecutionResult(
            success=True, order_id="ord1", price=0.5, usdc_spent=5.0, dry_run=True
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, dry_result)
        assert "DRY RUN" in msg

        live_result = ExecutionResult(
            success=True, order_id="ord1", price=0.5, usdc_spent=5.0, dry_run=False
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, live_result)
        assert "DRY RUN" not in msg


class TestBotInit:
    @pytest.mark.asyncio
    async def test_init_bot_with_import(
        self, config: Config, tmp_db: Repository
    ) -> None:
        notifier = TelegramNotifier(config, tmp_db)
        # _init_bot should set _bot when telegram is installed
        await notifier._init_bot()
        assert notifier._bot is not None

    @pytest.mark.asyncio
    async def test_init_bot_skipped_when_send_fn(
        self, config: Config, tmp_db: Repository
    ) -> None:
        async def noop(text: str) -> None:
            pass
        notifier = TelegramNotifier(config, tmp_db, send_fn=noop)
        await notifier._init_bot()
        assert notifier._bot is None  # Not initialized because send_fn exists

    @pytest.mark.asyncio
    async def test_init_bot_skipped_when_already_set(
        self, config: Config, tmp_db: Repository
    ) -> None:
        notifier = TelegramNotifier(config, tmp_db)
        notifier._bot = "fake-bot"
        await notifier._init_bot()
        assert notifier._bot == "fake-bot"  # Not replaced

    @pytest.mark.asyncio
    async def test_init_bot_import_error(
        self, config: Config, tmp_db: Repository
    ) -> None:
        from unittest.mock import patch
        notifier = TelegramNotifier(config, tmp_db)
        with patch.dict("sys.modules", {"telegram": None}):
            with patch("builtins.__import__", side_effect=ImportError("no telegram")):
                await notifier._init_bot()
        assert notifier._bot is None


class TestSendWithBot:
    @pytest.mark.asyncio
    async def test_send_with_real_bot_success(
        self, config: Config, tmp_db: Repository
    ) -> None:
        notifier = TelegramNotifier(config, tmp_db)
        mock_bot = AsyncMock()
        notifier._bot = mock_bot
        await notifier._send("Test message")
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_bot_exception(
        self, config: Config, tmp_db: Repository
    ) -> None:
        notifier = TelegramNotifier(config, tmp_db)
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = RuntimeError("send failed")
        notifier._bot = mock_bot
        # Should not crash
        await notifier._send("Test message")

    @pytest.mark.asyncio
    async def test_send_no_bot_no_fn(
        self, config: Config, tmp_db: Repository
    ) -> None:
        from unittest.mock import patch
        notifier = TelegramNotifier(config, tmp_db)
        # Force _bot to None by simulating import error
        with patch.object(notifier, "_init_bot", new_callable=AsyncMock):
            notifier._bot = None
            # Should not crash, just log warning
            await notifier._send("Test")


class TestSendTradeExecutedMethod:
    @pytest.mark.asyncio
    async def test_send_trade_executed(
        self, config: Config, tmp_db: Repository,
        sample_trade: TraderTrade,
    ) -> None:
        captured: list[str] = []
        async def cap(text: str) -> None:
            captured.append(text)
        notifier = TelegramNotifier(config, tmp_db, send_fn=cap)
        result = ExecutionResult(
            success=True, order_id="ord1", price=0.52,
            usdc_spent=5.0, dry_run=True,
        )
        await notifier.send_trade_executed(sample_trade, result)
        assert len(captured) == 1
        assert "Trade executado" in captured[0]


class TestSendStatusMethod:
    @pytest.mark.asyncio
    async def test_send_status(
        self, config: Config, tmp_db: Repository,
    ) -> None:
        captured: list[str] = []
        async def cap(text: str) -> None:
            captured.append(text)
        notifier = TelegramNotifier(config, tmp_db, send_fn=cap)
        await notifier.send_status()
        assert len(captured) == 1
        assert "Status" in captured[0]


class TestSendIntegration:
    @pytest.mark.asyncio
    async def test_send_uses_custom_send_fn(
        self,
        config: Config,
        tmp_db: Repository,
        sample_trade: TraderTrade,
    ) -> None:
        captured: list[str] = []

        async def capture_fn(text: str) -> None:
            captured.append(text)

        notifier = TelegramNotifier(config, tmp_db, send_fn=capture_fn)
        await notifier.send_trade_detected(sample_trade, "Test reason")

        assert len(captured) == 1
        assert "Test reason" in captured[0]

    @pytest.mark.asyncio
    async def test_send_position_resolved_win(
        self,
        config: Config,
        tmp_db: Repository,
        sample_position: Position,
    ) -> None:
        captured: list[str] = []

        async def capture_fn(text: str) -> None:
            captured.append(text)

        notifier = TelegramNotifier(config, tmp_db, send_fn=capture_fn)
        await notifier.send_position_resolved(sample_position, "won", 4.62)

        assert len(captured) == 1
        assert "GANHOU" in captured[0]

    @pytest.mark.asyncio
    async def test_send_position_resolved_loss(
        self,
        config: Config,
        tmp_db: Repository,
        sample_position: Position,
    ) -> None:
        captured: list[str] = []

        async def capture_fn(text: str) -> None:
            captured.append(text)

        notifier = TelegramNotifier(config, tmp_db, send_fn=capture_fn)
        await notifier.send_position_resolved(sample_position, "lost", -5.0)

        assert len(captured) == 1
        assert "perdeu" in captured[0]

    @pytest.mark.asyncio
    async def test_send_error(
        self, config: Config, tmp_db: Repository
    ) -> None:
        captured: list[str] = []

        async def capture_fn(text: str) -> None:
            captured.append(text)

        notifier = TelegramNotifier(config, tmp_db, send_fn=capture_fn)
        await notifier.send_error("Test error")

        assert len(captured) == 1
        assert "ERRO" in captured[0]
