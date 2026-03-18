"""Telegram notification sender and command handler."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Config
from src.db.models import ExecutionResult, MarketInfo, Position, TraderTrade
from src.db.repository import Repository

logger = logging.getLogger(__name__)


def _format_pnl(value: float) -> str:
    """Format P&L as +$X.XX or -$X.XX."""
    if value >= 0:
        return f"+${value:.2f}"
    return f"-${abs(value):.2f}"


class TelegramNotifier:
    """Formats and sends Telegram notifications."""

    def __init__(
        self,
        config: Config,
        repository: Repository,
        send_fn: Any | None = None,
    ) -> None:
        self._config = config
        self._repo = repository
        self._send_fn = send_fn
        self._bot: Any | None = None

    async def _init_bot(self) -> None:
        if self._bot is not None:
            return
        if self._send_fn is not None:
            return
        try:
            from telegram import Bot

            self._bot = Bot(token=self._config.telegram_bot_token)
        except ImportError:
            logger.warning("python-telegram-bot not installed; notifications disabled")

    async def _send(self, text: str) -> None:
        if self._send_fn is not None:
            await self._send_fn(text)
            return
        await self._init_bot()
        if self._bot is None:
            logger.warning("Telegram bot not available, message dropped: %s", text[:80])
            return
        try:
            await self._bot.send_message(
                chat_id=self._config.telegram_chat_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send Telegram message")

    # ── Message formatters ───────────────────────────────────────

    @staticmethod
    def format_trade_detected(
        trade: TraderTrade, reason: str
    ) -> str:
        return (
            "\U0001f50d Trade detectado \u2014 N\u00c3O copiado\n"
            f"Trader: {trade.trader_name or trade.proxy_wallet[:10]}\n"
            f"Mercado: {trade.title}\n"
            f"Lado: {trade.outcome} @ ${trade.price:.2f}\n"
            f"Valor: ${trade.usdc_size:,.0f}\n"
            f"Motivo: {reason}"
        )

    @staticmethod
    def format_trade_executed(
        trade: TraderTrade, result: ExecutionResult
    ) -> str:
        mode = "\U0001f9ea DRY RUN (sem dinheiro real)" if result.dry_run else "\U0001f4b0 LIVE"
        return (
            "\u2705 Trade executado\n"
            f"Trader copiado: {trade.trader_name or trade.proxy_wallet[:10]}\n"
            f"Mercado: {trade.title}\n"
            f"Lado: {trade.outcome} @ ${result.price:.2f}\n"
            f"Investido: ${result.usdc_spent:.2f}\n"
            f"Modo: {mode}"
        )

    @staticmethod
    def format_position_resolved_win(
        position: Position, pnl: float, daily_pnl: float
    ) -> str:
        received = position.usdc_invested + pnl
        pct = (pnl / position.usdc_invested * 100) if position.usdc_invested > 0 else 0
        return (
            "\U0001f3c6 Posi\u00e7\u00e3o resolvida \u2014 GANHOU!\n"
            f"Mercado: {position.market_title}\n"
            f"Resultado: {position.outcome} \u2713\n"
            f"Investido: ${position.usdc_invested:.2f}\n"
            f"Recebido: ${received:.2f}\n"
            f"Lucro: +${pnl:.2f} (+{pct:.0f}%)\n"
            f"P&L do dia: {_format_pnl(daily_pnl)}"
        )

    @staticmethod
    def format_position_resolved_loss(
        position: Position, pnl: float, daily_pnl: float
    ) -> str:
        return (
            "\u274c Posi\u00e7\u00e3o resolvida \u2014 perdeu\n"
            f"Mercado: {position.market_title}\n"
            f"Resultado: {position.outcome} \u2717\n"
            f"Investido: ${position.usdc_invested:.2f}\n"
            f"Perda: -${abs(pnl):.2f}\n"
            f"P&L do dia: {_format_pnl(daily_pnl)}"
        )

    @staticmethod
    def format_error(message: str) -> str:
        return (
            "\u26a0\ufe0f ERRO CR\u00cdTICO\n"
            "Bot pausado por seguran\u00e7a.\n"
            f"Erro: {message}\n"
            "Use /resume para retomar manualmente."
        )

    def format_status(self) -> str:
        positions = self._repo.get_open_positions()
        daily_pnl = self._repo.get_daily_pnl()
        total_pnl = self._repo.get_total_pnl()
        exposure = self._repo.get_total_open_exposure()
        paused = self._repo.get_state("paused", "false") == "true"

        mode_icon = "\U0001f534" if paused else "\U0001f7e2"
        mode_label = "PAUSADO" if paused else "ATIVO"
        dry_label = " (DRY RUN)" if self._config.dry_run else ""

        lines = [
            "\U0001f4ca Status do Bot",
            f"Mode: {mode_icon} {mode_label}{dry_label}",
            f"Posi\u00e7\u00f5es abertas: {len(positions)}",
            f"P&L hoje: ${daily_pnl:+.2f}",
            f"P&L total: ${total_pnl:+.2f}",
            f"Exposi\u00e7\u00e3o atual: ${exposure:.2f} / ${self._config.max_total_exposure_usd:.2f}",
        ]

        if positions:
            lines.append("\nPosi\u00e7\u00f5es abertas:")
            for p in positions:
                lines.append(
                    f"\u2022 {p.market_title[:40]} {p.outcome} @ ${p.entry_price:.2f}"
                )

        return "\n".join(lines)

    # ── High-level send methods ──────────────────────────────────

    async def send_trade_detected(self, trade: TraderTrade, reason: str) -> None:
        await self._send(self.format_trade_detected(trade, reason))

    async def send_trade_executed(
        self, trade: TraderTrade, result: ExecutionResult
    ) -> None:
        await self._send(self.format_trade_executed(trade, result))

    async def send_position_resolved(
        self, position: Position, status: str, pnl: float
    ) -> None:
        daily_pnl = self._repo.get_daily_pnl()
        if status == "won":
            msg = self.format_position_resolved_win(position, pnl, daily_pnl)
        else:
            msg = self.format_position_resolved_loss(position, pnl, daily_pnl)
        await self._send(msg)

    async def send_error(self, message: str) -> None:
        await self._send(self.format_error(message))

    async def send_status(self) -> None:
        await self._send(self.format_status())
