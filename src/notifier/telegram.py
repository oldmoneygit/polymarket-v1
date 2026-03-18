"""Telegram notification sender and interactive command handler.

Supports commands: /status, /pause, /resume, /copy, /remove,
/traders, /positions, /balance, /settings
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from src.config import Config
from src.db.models import ExecutionResult, Position, TraderTrade
from src.db.repository import Repository

logger = logging.getLogger(__name__)

_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _format_pnl(value: float) -> str:
    if value >= 0:
        return f"+${value:.2f}"
    return f"-${abs(value):.2f}"


class TelegramNotifier:
    """Formats/sends Telegram notifications and handles interactive commands."""

    def __init__(
        self,
        config: Config,
        repository: Repository,
        send_fn: Any | None = None,
        on_add_trader: Any | None = None,
        on_remove_trader: Any | None = None,
    ) -> None:
        self._config = config
        self._repo = repository
        self._send_fn = send_fn
        self._on_add_trader = on_add_trader
        self._on_remove_trader = on_remove_trader
        self._bot: Any | None = None
        self._app: Any | None = None

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

    # ── Command handler setup ─────────────────────────────────────

    async def start_command_handler(self) -> None:
        """Start listening for Telegram commands in background."""
        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CommandHandler,
                ContextTypes,
            )
        except ImportError:
            logger.warning("python-telegram-bot not installed; commands disabled")
            return

        app = Application.builder().token(self._config.telegram_bot_token).build()
        chat_id = self._config.telegram_chat_id

        async def _check_auth(update: Update) -> bool:
            if update.effective_chat and str(update.effective_chat.id) == chat_id:
                return True
            return False

        async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            await update.message.reply_text(self.format_status(), parse_mode="HTML")  # type: ignore[union-attr]

        async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            self._repo.set_state("paused", "true")
            await update.message.reply_text("Bot PAUSADO. Use /resume para retomar.")  # type: ignore[union-attr]

        async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            self._repo.set_state("paused", "false")
            await update.message.reply_text("Bot ATIVO. Monitorando traders...")  # type: ignore[union-attr]

        async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            positions = self._repo.get_open_positions()
            if not positions:
                await update.message.reply_text("Nenhuma posicao aberta.")  # type: ignore[union-attr]
                return
            lines = ["<b>Posicoes abertas:</b>"]
            for p in positions:
                lines.append(
                    f"  {p.outcome} {p.market_title[:35]}\n"
                    f"  @ ${p.entry_price:.2f} | ${p.usdc_invested:.2f} investido"
                )
            await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

        async def cmd_traders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            wallets = self._config.trader_wallets
            # Also load dynamic traders
            dynamic = self._repo.get_state("dynamic_traders", "")
            dynamic_list = [w.strip() for w in dynamic.split(",") if w.strip()]
            lines = ["<b>Traders monitorados:</b>"]
            for i, w in enumerate(wallets, 1):
                paused = self._repo.get_state(f"trader_paused:{w}", "false") == "true"
                status = "PAUSADO" if paused else "ativo"
                lines.append(f"{i}. <code>{w[:10]}...{w[-6:]}</code> [{status}]")
            if dynamic_list:
                lines.append("\n<b>Dinamicos (via /copy):</b>")
                for i, w in enumerate(dynamic_list, 1):
                    paused = self._repo.get_state(f"trader_paused:{w}", "false") == "true"
                    status = "PAUSADO" if paused else "ativo"
                    lines.append(f"{i}. <code>{w[:10]}...{w[-6:]}</code> [{status}]")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

        async def cmd_copy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            if not context.args:
                await update.message.reply_text(  # type: ignore[union-attr]
                    "Uso: /copy 0x... (endereco do trader)"
                )
                return
            wallet = context.args[0].strip().lower()
            if not _ETH_ADDRESS_RE.match(wallet):
                await update.message.reply_text("Endereco invalido. Use formato 0x...")  # type: ignore[union-attr]
                return
            # Add to dynamic traders in DB
            current = self._repo.get_state("dynamic_traders", "")
            existing = [w.strip() for w in current.split(",") if w.strip()]
            if wallet in existing or wallet in self._config.trader_wallets:
                await update.message.reply_text("Trader ja esta sendo monitorado.")  # type: ignore[union-attr]
                return
            existing.append(wallet)
            self._repo.set_state("dynamic_traders", ",".join(existing))
            if self._on_add_trader:
                await self._on_add_trader(wallet)
            await update.message.reply_text(  # type: ignore[union-attr]
                f"Trader adicionado: <code>{wallet}</code>", parse_mode="HTML"
            )

        async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            if not context.args:
                await update.message.reply_text("Uso: /remove 0x... (endereco do trader)")  # type: ignore[union-attr]
                return
            wallet = context.args[0].strip().lower()
            current = self._repo.get_state("dynamic_traders", "")
            existing = [w.strip() for w in current.split(",") if w.strip()]
            if wallet not in existing:
                await update.message.reply_text("Trader nao encontrado na lista dinamica.")  # type: ignore[union-attr]
                return
            existing.remove(wallet)
            self._repo.set_state("dynamic_traders", ",".join(existing))
            if self._on_remove_trader:
                await self._on_remove_trader(wallet)
            await update.message.reply_text(  # type: ignore[union-attr]
                f"Trader removido: <code>{wallet}</code>", parse_mode="HTML"
            )

        async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            c = self._config
            text = (
                "<b>Configuracoes:</b>\n"
                f"Modo: {'DRY RUN' if c.dry_run else 'LIVE'}\n"
                f"Copy sizing: {c.copy_size_mode}\n"
                f"Capital/trade: ${c.capital_per_trade_usd:.2f}\n"
                f"Max copy trade: ${c.max_copy_trade_usd:.2f}\n"
                f"Max exposicao: ${c.max_total_exposure_usd:.2f}\n"
                f"Stop diario: ${c.max_daily_loss_usd:.2f}\n"
                f"Categorias: {', '.join(c.market_categories)}\n"
                f"Copy SELL: {'Sim' if c.copy_sell else 'Nao'}\n"
                f"Confluencia: {'ON' if c.confluence_enabled else 'OFF'}\n"
                f"Polling: {c.poll_interval_seconds}s\n"
                f"Prob range: {c.min_probability:.0%}-{c.max_probability:.0%}"
            )
            await update.message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]

        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("pause", cmd_pause))
        app.add_handler(CommandHandler("resume", cmd_resume))
        app.add_handler(CommandHandler("positions", cmd_positions))
        app.add_handler(CommandHandler("traders", cmd_traders))
        app.add_handler(CommandHandler("copy", cmd_copy))
        app.add_handler(CommandHandler("remove", cmd_remove))
        async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            await update.message.reply_text("Gerando report... (pode levar 1-2 min)")  # type: ignore[union-attr]
            try:
                import subprocess
                result = subprocess.run(
                    ["python", "daily_report.py", "--days", "1"],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(Path(__file__).parent.parent.parent),
                )
                output = result.stdout[-3000:] if result.stdout else "Sem output"
                await update.message.reply_text(  # type: ignore[union-attr]
                    f"<pre>{output}</pre>", parse_mode="HTML"
                )
            except Exception as e:
                await update.message.reply_text(f"Erro: {e}")  # type: ignore[union-attr]

        async def cmd_discover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            await update.message.reply_text("Escaneando leaderboard...")  # type: ignore[union-attr]
            try:
                from src.discovery.leaderboard import LeaderboardScanner
                scanner = LeaderboardScanner()
                profiles = await scanner.scan(period="all", limit=30)
                msg = scanner.format_discovery_message(profiles, top_n=5)
                await update.message.reply_text(msg, parse_mode="HTML")  # type: ignore[union-attr]
            except Exception as e:
                await update.message.reply_text(f"Erro: {e}")  # type: ignore[union-attr]

        async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            lines = ["<b>Risk Status:</b>"]
            # This will be populated by the bot instance
            lines.append("Use /status for full overview")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

        app.add_handler(CommandHandler("settings", cmd_settings))
        app.add_handler(CommandHandler("analyze", cmd_analyze))
        app.add_handler(CommandHandler("discover", cmd_discover))
        app.add_handler(CommandHandler("risk", cmd_risk))

        self._app = app
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        logger.info("Telegram command handler started")

    async def stop_command_handler(self) -> None:
        if self._app is not None:
            await self._app.updater.stop()  # type: ignore[union-attr]
            await self._app.stop()
            await self._app.shutdown()

    # ── Message formatters ───────────────────────────────────────

    @staticmethod
    def format_trade_detected(trade: TraderTrade, reason: str) -> str:
        return (
            "\U0001f50d Trade detectado \u2014 NAO copiado\n"
            f"Trader: {trade.trader_name or trade.proxy_wallet[:10]}\n"
            f"Mercado: {trade.title}\n"
            f"Lado: {trade.side} {trade.outcome} @ ${trade.price:.2f}\n"
            f"Valor: ${trade.usdc_size:,.0f}\n"
            f"Motivo: {reason}"
        )

    @staticmethod
    def format_trade_executed(trade: TraderTrade, result: ExecutionResult) -> str:
        mode = "\U0001f9ea DRY RUN" if result.dry_run else "\U0001f4b0 LIVE"
        side_label = "COMPRA" if trade.side == "BUY" else "VENDA"
        return (
            f"\u2705 {side_label} executada\n"
            f"Trader: {trade.trader_name or trade.proxy_wallet[:10]}\n"
            f"Mercado: {trade.title}\n"
            f"Lado: {trade.outcome} @ ${result.price:.2f}\n"
            f"Investido: ${result.usdc_spent:.2f}\n"
            f"Modo: {mode}"
        )

    @staticmethod
    def format_position_resolved_win(position: Position, pnl: float, daily_pnl: float) -> str:
        received = position.usdc_invested + pnl
        pct = (pnl / position.usdc_invested * 100) if position.usdc_invested > 0 else 0
        return (
            "\U0001f3c6 Posicao resolvida \u2014 GANHOU!\n"
            f"Mercado: {position.market_title}\n"
            f"Resultado: {position.outcome} \u2713\n"
            f"Investido: ${position.usdc_invested:.2f}\n"
            f"Recebido: ${received:.2f}\n"
            f"Lucro: +${pnl:.2f} (+{pct:.0f}%)\n"
            f"P&L do dia: {_format_pnl(daily_pnl)}"
        )

    @staticmethod
    def format_position_resolved_loss(position: Position, pnl: float, daily_pnl: float) -> str:
        return (
            "\u274c Posicao resolvida \u2014 perdeu\n"
            f"Mercado: {position.market_title}\n"
            f"Resultado: {position.outcome} \u2717\n"
            f"Investido: ${position.usdc_invested:.2f}\n"
            f"Perda: -${abs(pnl):.2f}\n"
            f"P&L do dia: {_format_pnl(daily_pnl)}"
        )

    @staticmethod
    def format_error(message: str) -> str:
        return (
            "\u26a0\ufe0f ERRO CRITICO\n"
            "Bot pausado por seguranca.\n"
            f"Erro: {message}\n"
            "Use /resume para retomar."
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
            f"Posicoes abertas: {len(positions)}",
            f"P&L hoje: ${daily_pnl:+.2f}",
            f"P&L total: ${total_pnl:+.2f}",
            f"Exposicao: ${exposure:.2f} / ${self._config.max_total_exposure_usd:.2f}",
            f"Sizing: {self._config.copy_size_mode}",
        ]

        if positions:
            lines.append("\nPosicoes:")
            for p in positions:
                lines.append(
                    f"  {p.outcome} {p.market_title[:35]} @ ${p.entry_price:.2f}"
                )

        return "\n".join(lines)

    # ── High-level send methods ──────────────────────────────────

    async def send_trade_detected(self, trade: TraderTrade, reason: str) -> None:
        await self._send(self.format_trade_detected(trade, reason))

    async def send_trade_executed(self, trade: TraderTrade, result: ExecutionResult) -> None:
        await self._send(self.format_trade_executed(trade, result))

    async def send_position_resolved(self, position: Position, status: str, pnl: float) -> None:
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
