"""Trader activity monitor — polls the Data API for new trades.

# [MERGED FROM polymarket-v1] Enhanced — adds per-market copy cooldown
# to prevent duplicate positions on the same market from the same trader.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from src.api.polymarket import PolymarketClient
from src.config import Config
from src.db.models import TraderTrade
from src.db.repository import Repository

logger = logging.getLogger(__name__)


class TraderMonitor:
    """Polls trader activity and fires callbacks on newly detected trades."""

    def __init__(
        self,
        config: Config,
        polymarket_client: PolymarketClient,
        repository: Repository,
        on_new_trade: Callable[[TraderTrade], Awaitable[None]],
    ) -> None:
        self._config = config
        self._api = polymarket_client
        self._repo = repository
        self._on_new_trade = on_new_trade
        self._seen_hashes: set[str] = set()
        self._consecutive_failures: dict[str, int] = {}
        # [MERGED FROM polymarket-v1] Track copied markets per trader to avoid duplicating positions
        # Key: (wallet, condition_id) -> timestamp of first copy
        self._copied_markets: dict[tuple[str, str], int] = {}
        self._copy_cooldown_seconds = 3600  # 1 hour cooldown per market per trader

    def load_seen_hashes(self) -> None:
        """Hydrate the in-memory dedup set from SQLite."""
        self._seen_hashes = self._repo.load_seen_hashes(days_back=7)
        logger.info("Loaded %d seen hashes from database", len(self._seen_hashes))

    async def start(self) -> None:
        """Run the monitoring loop forever."""
        self.load_seen_hashes()
        while True:
            for wallet in self._config.trader_wallets:
                await self._check_trader(wallet)
                await asyncio.sleep(1)  # 1s gap between traders
            await asyncio.sleep(self._config.poll_interval_seconds)  # pragma: no cover

    async def run_once(self) -> None:
        """Run a single polling cycle (useful for testing)."""
        for wallet in self._config.trader_wallets:
            await self._check_trader(wallet)

    async def _check_trader(self, wallet: str) -> None:
        try:
            trades = await self._api.get_trader_activity(wallet)
            self._consecutive_failures[wallet] = 0
        except Exception:
            count = self._consecutive_failures.get(wallet, 0) + 1
            self._consecutive_failures[wallet] = count
            logger.warning(
                "Failed to fetch activity for %s (attempt %d)", wallet, count
            )
            return

        now = int(time.time())
        max_age_seconds = self._config.max_trade_age_minutes * 60

        for trade in trades:
            tx_hash = trade.transaction_hash
            if not tx_hash:
                continue
            if tx_hash in self._seen_hashes:
                continue

            # Skip old trades
            age = now - trade.timestamp
            if age > max_age_seconds:
                # Still mark as seen so we don't recheck
                self._seen_hashes.add(tx_hash)
                self._repo.save_seen_hash(tx_hash, wallet)
                continue

            # Mark hash as seen
            self._seen_hashes.add(tx_hash)
            self._repo.save_seen_hash(tx_hash, wallet)

            # [MERGED FROM polymarket-v1] Dedup: skip if we already copied this market
            # for this trader recently
            market_key = (wallet, trade.condition_id)
            last_copy = self._copied_markets.get(market_key, 0)
            if now - last_copy < self._copy_cooldown_seconds:
                logger.debug(
                    "Skipping duplicate market copy: %s by %s (cooldown)",
                    trade.title[:40],
                    wallet[:10],
                )
                continue

            self._copied_markets[market_key] = now

            logger.info(
                "New trade detected: %s %s %s @ %.4f ($%.2f) — %s",
                trade.side,
                trade.outcome,
                trade.title[:50],
                trade.price,
                trade.usdc_size,
                wallet[:10],
            )

            try:
                await self._on_new_trade(trade)
            except Exception:
                logger.exception("Error processing trade %s", tx_hash)
