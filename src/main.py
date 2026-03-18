"""Entry point — starts all bot services concurrently."""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.api.clob import CLOBClient
from src.api.polymarket import PolymarketClient
from src.config import Config
from src.db.models import MarketInfo, TraderTrade
from src.db.repository import Repository
from src.executor.trade import TradeExecutor
from src.monitor.position import PositionMonitor
from src.monitor.trader import TraderMonitor
from src.notifier.telegram import TelegramNotifier
from src.strategy.confluence import ConfluenceDetector
from src.strategy.filter import TradeFilter
from src.strategy.momentum import MomentumDetector
from src.strategy.scanner import HighProbScanner

logger = logging.getLogger("polymarket_bot")


def setup_logging(level: str) -> None:
    """Configure rotating file + console logging."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console_handler)


class Bot:
    """Orchestrates all bot components."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._repo = Repository()
        self._polymarket = PolymarketClient()
        self._clob = CLOBClient(config)
        self._filter = TradeFilter()
        self._confluence = ConfluenceDetector()
        self._momentum = MomentumDetector()
        self._scanner = HighProbScanner()
        self._executor = TradeExecutor(config, self._clob, self._repo)
        self._notifier = TelegramNotifier(config, self._repo)
        self._trader_monitor = TraderMonitor(
            config=config,
            polymarket_client=self._polymarket,
            repository=self._repo,
            on_new_trade=self._handle_new_trade,
        )
        self._position_monitor = PositionMonitor(
            config=config,
            polymarket_client=self._polymarket,
            clob_client=self._clob,
            repository=self._repo,
            on_position_resolved=self._handle_position_resolved,
        )

    async def _handle_new_trade(self, trade: TraderTrade) -> None:
        """Pipeline: detect → filter → execute → notify."""
        # Check if paused
        if self._repo.get_state("paused", "false") == "true":
            logger.info("Bot is paused, skipping trade %s", trade.transaction_hash)
            return

        # Record confluence signal (before any filtering)
        self._confluence.record_trade(
            condition_id=trade.condition_id,
            title=trade.title,
            outcome=trade.outcome,
            trader_wallet=trade.proxy_wallet,
            usdc_size=trade.usdc_size,
        )

        # Fetch market info
        market = await self._polymarket.get_market_info(trade.condition_id)
        if market is None:
            logger.warning("Market not found: %s", trade.condition_id)
            return

        # Track momentum
        self._momentum.record_price(
            condition_id=trade.condition_id,
            yes_price=market.yes_price,
            question=market.question,
            slug=market.slug,
        )

        # Check scanner (high-prob opportunities)
        scan_signal = self._scanner.evaluate(market)
        if scan_signal is not None:
            logger.info(
                "SCANNER: %s %s @ %.0f%% — +%.1f%% return, %.0fh to resolve",
                scan_signal.side,
                scan_signal.question[:50],
                scan_signal.probability * 100,
                scan_signal.expected_return_pct * 100,
                scan_signal.hours_to_resolution,
            )

        # Run filter
        current_exposure = self._repo.get_total_open_exposure()
        result = self._filter.evaluate(
            trade, market, self._config, current_exposure
        )

        if not result.passed:
            logger.info("Trade filtered out: %s — %s", trade.title[:40], result.reason)
            return

        # Execute
        exec_result = await self._executor.execute(trade, market)

        if exec_result.success:
            await self._notifier.send_trade_executed(trade, exec_result)
        else:
            logger.warning("Execution failed: %s", exec_result.error)
            if exec_result.error and "Stop diário" in exec_result.error:
                self._repo.set_state("paused", "true")
                await self._notifier.send_error(exec_result.error)
            elif exec_result.error:
                await self._notifier.send_trade_detected(trade, exec_result.error)

    async def _handle_position_resolved(
        self, position: object, status: str, pnl: float
    ) -> None:
        from src.db.models import Position

        if isinstance(position, Position):
            await self._notifier.send_position_resolved(position, status, pnl)

    async def run(self) -> None:
        """Start all services concurrently."""
        logger.info("Starting Polymarket Copy Trading Bot...")
        logger.info("Monitoring %d traders", len(self._config.trader_wallets))
        logger.info("Dry run: %s", self._config.dry_run)

        try:
            await asyncio.gather(
                self._trader_monitor.start(),
                self._position_monitor.start(),
            )
        except asyncio.CancelledError:
            logger.info("Bot shutting down...")
        finally:
            await self._polymarket.close()
            self._repo.close()


def main() -> None:
    config = Config.load()
    setup_logging(config.log_level)
    bot = Bot(config)

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")


if __name__ == "__main__":  # pragma: no cover
    main()
