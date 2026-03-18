"""Unit tests for src/main.py — Bot orchestrator."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Config
from src.db.models import (
    ExecutionResult,
    FilterResult,
    MarketInfo,
    Position,
    TraderTrade,
)
from src.db.repository import Repository
from src.main import Bot, setup_logging


class TestSetupLogging:
    def test_setup_logging_creates_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        with patch("src.main.Path", return_value=log_dir):
            # Just verify it doesn't crash
            setup_logging("DEBUG")

    def test_setup_logging_with_info_level(self) -> None:
        setup_logging("INFO")

    def test_setup_logging_with_invalid_level(self) -> None:
        # Invalid level falls back to INFO
        setup_logging("NONEXISTENT")


class TestBotInit:
    def test_bot_initializes(self, config: Config, tmp_path: Path) -> None:
        with patch("src.main.Repository") as mock_repo, \
             patch("src.main.PolymarketClient"), \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier"):
            bot = Bot(config)
            assert bot._config is config


class TestHandleNewTrade:
    @pytest.mark.asyncio
    async def test_handle_new_trade_paused(
        self, config: Config, sample_trade: TraderTrade
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient"), \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier"):
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "true"
            bot = Bot(config)
            bot._repo = mock_repo

            await bot._handle_new_trade(sample_trade)
            # Should return early because paused

    @pytest.mark.asyncio
    async def test_handle_new_trade_market_not_found(
        self, config: Config, sample_trade: TraderTrade
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier"):
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "false"
            mock_poly = MockPoly.return_value
            mock_poly.get_market_info = AsyncMock(return_value=None)

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly

            await bot._handle_new_trade(sample_trade)

    @pytest.mark.asyncio
    async def test_handle_new_trade_filtered_out(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "false"
            mock_repo.get_total_open_exposure.return_value = 0.0
            mock_poly = MockPoly.return_value
            mock_poly.get_market_info = AsyncMock(return_value=sample_market)
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_trade_detected = AsyncMock()

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly
            bot._notifier = mock_notifier

            # Make filter reject
            from src.strategy.filter import TradeFilter
            mock_filter = MagicMock(spec=TradeFilter)
            mock_filter.evaluate.return_value = FilterResult(
                passed=False, reason="Volume too low"
            )
            bot._filter = mock_filter

            await bot._handle_new_trade(sample_trade)
            # Filtered trades no longer send Telegram — only logged
            mock_notifier.send_trade_detected.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_new_trade_execution_success(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "false"
            mock_repo.get_total_open_exposure.return_value = 0.0
            mock_poly = MockPoly.return_value
            mock_poly.get_market_info = AsyncMock(return_value=sample_market)
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_trade_executed = AsyncMock()

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly
            bot._notifier = mock_notifier

            mock_filter = MagicMock()
            mock_filter.evaluate.return_value = FilterResult(passed=True, reason="OK")
            bot._filter = mock_filter

            mock_executor = AsyncMock()
            mock_executor.execute = AsyncMock(return_value=ExecutionResult(
                success=True, order_id="ord1", price=0.52,
                usdc_spent=5.0, dry_run=True,
            ))
            bot._executor = mock_executor

            await bot._handle_new_trade(sample_trade)
            mock_notifier.send_trade_executed.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_new_trade_execution_daily_stop(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "false"
            mock_repo.get_total_open_exposure.return_value = 0.0
            mock_repo.set_state = MagicMock()
            mock_poly = MockPoly.return_value
            mock_poly.get_market_info = AsyncMock(return_value=sample_market)
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_error = AsyncMock()

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly
            bot._notifier = mock_notifier

            mock_filter = MagicMock()
            mock_filter.evaluate.return_value = FilterResult(passed=True, reason="OK")
            bot._filter = mock_filter

            mock_executor = AsyncMock()
            mock_executor.execute = AsyncMock(return_value=ExecutionResult(
                success=False, error="Stop diário atingido",
            ))
            bot._executor = mock_executor

            await bot._handle_new_trade(sample_trade)
            mock_repo.set_state.assert_called_with("paused", "true")
            mock_notifier.send_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_new_trade_execution_other_error(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_repo = MockRepo.return_value
            mock_repo.get_state.return_value = "false"
            mock_repo.get_total_open_exposure.return_value = 0.0
            mock_poly = MockPoly.return_value
            mock_poly.get_market_info = AsyncMock(return_value=sample_market)
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_trade_detected = AsyncMock()

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly
            bot._notifier = mock_notifier

            mock_filter = MagicMock()
            mock_filter.evaluate.return_value = FilterResult(passed=True, reason="OK")
            bot._filter = mock_filter

            mock_executor = AsyncMock()
            mock_executor.execute = AsyncMock(return_value=ExecutionResult(
                success=False, error="Saldo insuficiente",
            ))
            bot._executor = mock_executor

            await bot._handle_new_trade(sample_trade)
            mock_notifier.send_trade_detected.assert_called_once()


class TestHandlePositionResolved:
    @pytest.mark.asyncio
    async def test_handle_position_resolved_with_position(
        self, config: Config, sample_position: Position
    ) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient"), \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_position_resolved = AsyncMock()
            bot = Bot(config)
            bot._notifier = mock_notifier

            await bot._handle_position_resolved(sample_position, "won", 4.62)
            mock_notifier.send_position_resolved.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_position_resolved_non_position(
        self, config: Config
    ) -> None:
        with patch("src.main.Repository"), \
             patch("src.main.PolymarketClient"), \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_position_resolved = AsyncMock()
            bot = Bot(config)
            bot._notifier = mock_notifier

            await bot._handle_position_resolved("not a position", "won", 0)
            mock_notifier.send_position_resolved.assert_not_called()


class TestBotRun:
    @pytest.mark.asyncio
    async def test_bot_run_cancelled(self, config: Config) -> None:
        with patch("src.main.Repository") as MockRepo, \
             patch("src.main.PolymarketClient") as MockPoly, \
             patch("src.main.CLOBClient"), \
             patch("src.main.TelegramNotifier"):
            mock_repo = MockRepo.return_value
            mock_repo.close = MagicMock()
            mock_poly = MockPoly.return_value
            mock_poly.close = AsyncMock()

            bot = Bot(config)
            bot._repo = mock_repo
            bot._polymarket = mock_poly
            bot._trader_monitor = AsyncMock()
            bot._trader_monitor.start = AsyncMock(
                side_effect=asyncio.CancelledError
            )
            bot._position_monitor = AsyncMock()
            bot._position_monitor.start = AsyncMock(return_value=None)

            await bot.run()
            mock_poly.close.assert_called_once()
            mock_repo.close.assert_called_once()


class TestMainFunction:
    def test_main_keyboard_interrupt(
        self, env_vars: dict[str, str]
    ) -> None:
        with patch("src.main.Config.load") as mock_load, \
             patch("src.main.setup_logging"), \
             patch("src.main.Bot") as MockBot, \
             patch("src.main.asyncio.run", side_effect=KeyboardInterrupt):
            mock_load.return_value = Config(
                poly_api_key="k", poly_api_secret="s",
                poly_api_passphrase="p", poly_wallet_address="0x" + "a1" * 20,
                poly_private_key="", trader_wallets=["0x" + "b2" * 20],
                telegram_bot_token="123:ABC", telegram_chat_id="123",
                dry_run=True,
            )
            from src.main import main
            main()  # Should not raise
