"""Unit tests for src/notifier/telegram.py (SPEC-08)."""

from __future__ import annotations

import time

import pytest

from src.config import Config
from src.db.models import ExecutionResult, Position, TraderTrade
from src.db.repository import Repository
from src.notifier.telegram import TelegramNotifier


class TestFormatMessages:
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
            success=True, order_id="ord1", price=0.52, usdc_spent=5.0, dry_run=False
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, result)
        assert "LIVE" in msg
        assert "DRY RUN" not in msg

    def test_format_position_resolved_win(
        self, sample_position: Position
    ) -> None:
        pnl = 4.62
        daily_pnl = 12.30
        msg = TelegramNotifier.format_position_resolved_win(
            sample_position, pnl, daily_pnl
        )
        assert "GANHOU" in msg
        assert "$5.00" in msg
        assert "+$4.62" in msg
        assert "$12.30" in msg

    def test_format_position_resolved_loss(
        self, sample_position: Position
    ) -> None:
        pnl = -5.0
        daily_pnl = -2.70
        msg = TelegramNotifier.format_position_resolved_loss(
            sample_position, pnl, daily_pnl
        )
        assert "perdeu" in msg
        assert "$5.00" in msg
        assert "-$2.70" in msg

    def test_format_status_message(
        self, config: Config, tmp_db: Repository
    ) -> None:
        # Add a position
        pos = Position(
            condition_id="c1", token_id="t1", side="BUY",
            outcome="Yes", entry_price=0.52, shares=9.62,
            usdc_invested=5.0, trader_copied="0xabc",
            market_title="PSG vs Chelsea", opened_at=int(time.time()),
            status="open", dry_run=True,
        )
        tmp_db.save_position(pos)

        notifier = TelegramNotifier(config, tmp_db)
        msg = notifier.format_status()

        assert "Status do Bot" in msg
        assert "ATIVO" in msg
        assert "DRY RUN" in msg
        assert "1" in msg  # 1 position
        assert "PSG vs Chelsea" in msg

    def test_dry_run_flag_shown_in_messages(
        self, sample_trade: TraderTrade
    ) -> None:
        result = ExecutionResult(
            success=True, order_id="x", price=0.5, usdc_spent=5.0, dry_run=True
        )
        msg = TelegramNotifier.format_trade_executed(sample_trade, result)
        assert "DRY RUN" in msg

    def test_format_error_message(self) -> None:
        msg = TelegramNotifier.format_error("Stop diário atingido (-$20.00)")
        assert "ERRO" in msg
        assert "Stop diário" in msg
        assert "/resume" in msg

    def test_format_trade_detected(self, sample_trade: TraderTrade) -> None:
        msg = TelegramNotifier.format_trade_detected(
            sample_trade, "Volume $3,200 abaixo do mínimo $5,000"
        )
        assert "NÃO copiado" in msg
        assert "Volume" in msg
        assert "HorizonSplendidView" in msg
