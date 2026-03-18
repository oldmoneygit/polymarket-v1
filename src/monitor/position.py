"""Position monitor — tracks open positions and detects resolution."""

from __future__ import annotations

import asyncio
import logging

from src.api.clob import CLOBClient
from src.api.polymarket import PolymarketClient
from src.config import Config
from src.db.models import Position
from src.db.repository import Repository

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitors open positions for market resolution and take-profit."""

    def __init__(
        self,
        config: Config,
        polymarket_client: PolymarketClient,
        clob_client: CLOBClient,
        repository: Repository,
        on_position_resolved: object | None = None,
        on_take_profit: object | None = None,
    ) -> None:
        self._config = config
        self._api = polymarket_client
        self._clob = clob_client
        self._repo = repository
        self._on_position_resolved = on_position_resolved
        self._on_take_profit = on_take_profit

    async def start(self) -> None:
        """Run the position monitoring loop forever."""
        while True:
            await self.check_positions()
            await asyncio.sleep(self._config.position_check_interval_seconds)

    async def check_positions(self) -> None:
        """Check all open positions once."""
        positions = self._repo.get_open_positions()
        for pos in positions:
            try:
                await self._check_single(pos)
            except Exception:
                logger.exception(
                    "Error checking position %s (%s)", pos.id, pos.market_title
                )

    async def _check_single(self, pos: Position) -> None:
        market = await self._api.get_market_info(pos.condition_id)
        if market is None:
            logger.warning("Market not found for position %s", pos.condition_id)
            return

        if market.is_resolved:
            won = self._determine_outcome(pos, market.resolved_outcome)
            if won:
                gross = pos.shares - pos.usdc_invested  # $1/share on win
                fee = max(0, gross) * 0.02  # 2% fee on NET PROFIT only
                pnl = gross - fee
                status = "won"
            else:
                pnl = -pos.usdc_invested  # Full loss, no fee on losses
                status = "lost"

            self._repo.update_position_result(pos.id, status, pnl)  # type: ignore[arg-type]
            # Return to simulated balance
            if hasattr(self._clob, '_simulated_balance'):
                self._clob._simulated_balance += pos.usdc_invested + pnl
            logger.info(
                "Position resolved: %s — %s (PnL: $%.2f)",
                pos.market_title[:40],
                status.upper(),
                pnl,
            )

            if self._on_position_resolved:
                try:
                    await self._on_position_resolved(pos, status, pnl)  # type: ignore[misc]
                except Exception:
                    logger.exception("Error in on_position_resolved callback")
            return

        # Take profit check (only for unresolved markets)
        if self._config.take_profit_pct > 0:
            current_price = (
                market.yes_price if pos.outcome == "Yes" else market.no_price
            )
            if pos.entry_price > 0:
                unrealized_pnl_pct = (
                    (current_price - pos.entry_price) / pos.entry_price
                )
                if unrealized_pnl_pct >= self._config.take_profit_pct:
                    # Realistic P&L: deduct 2% fee + 1% estimated slippage on exit
                    gross_pnl = (current_price - pos.entry_price) * pos.shares
                    exit_fee = pos.usdc_invested * 0.02  # 2% Polymarket fee
                    exit_slippage = gross_pnl * 0.01  # ~1% slippage on exit
                    pnl = gross_pnl - exit_fee - exit_slippage
                    self._repo.update_position_result(pos.id, "sold", pnl)  # type: ignore[arg-type]
                    # Return capital to simulated balance
                    if hasattr(self._clob, '_simulated_balance'):
                        self._clob._simulated_balance += pos.usdc_invested + pnl
                    logger.info(
                        "Take profit triggered: %s — +%.0f%% gross, PnL: $%.2f (after 2%% fee + slippage)",
                        pos.market_title[:40],
                        unrealized_pnl_pct * 100,
                        pnl,
                    )

                    if self._on_take_profit:
                        try:
                            await self._on_take_profit(pos, pnl)  # type: ignore[misc]
                        except Exception:
                            logger.exception("Error in on_take_profit callback")

    @staticmethod
    def _determine_outcome(position: Position, resolved_outcome: str) -> bool:
        """Determine if the position won based on the market resolution."""
        if position.outcome == "Yes":
            return resolved_outcome.lower() in ("yes", "1", "true")
        return resolved_outcome.lower() in ("no", "0", "false")
