"""Position monitor — tracks open positions and detects resolution.

Realistic simulation:
- Take-profit checks REAL liquidity before selling
- Exit slippage scales with position size vs liquidity
- 2% Polymarket fee on net profits
- Underdogs (entry < 0.20) get higher slippage penalty
- Max take-profit capped at realistic levels
"""

from __future__ import annotations

import asyncio
import logging

from src.api.clob import CLOBClient, CLOBError
from src.api.polymarket import PolymarketClient
from src.config import Config
from src.db.models import Position
from src.db.repository import Repository

logger = logging.getLogger(__name__)

# Realistic constraints
POLYMARKET_FEE = 0.02  # 2% on net profit
MIN_EXIT_SLIPPAGE = 0.01  # 1% minimum slippage on exit
MAX_REALISTIC_TP_MULTIPLIER = 3.0  # Cap take-profit at 3x (300%) max


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
        while True:
            await self.check_positions()
            await asyncio.sleep(self._config.position_check_interval_seconds)

    async def check_positions(self) -> None:
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

        # === RESOLUTION ===
        if market.is_resolved:
            won = self._determine_outcome(pos, market.resolved_outcome)
            if won:
                gross = pos.shares - pos.usdc_invested  # $1/share on win
                fee = max(0, gross) * POLYMARKET_FEE
                pnl = gross - fee
                status = "won"
            else:
                pnl = -pos.usdc_invested
                status = "lost"

            self._repo.update_position_result(pos.id, status, pnl)  # type: ignore[arg-type]
            if hasattr(self._clob, '_simulated_balance'):
                self._clob._simulated_balance += pos.usdc_invested + pnl
            logger.info(
                "Position resolved: %s — %s (PnL: $%.2f)",
                pos.market_title[:40], status.upper(), pnl,
            )

            if self._on_position_resolved:
                try:
                    await self._on_position_resolved(pos, status, pnl)  # type: ignore[misc]
                except Exception:
                    logger.exception("Error in on_position_resolved callback")
            return

        # === TAKE PROFIT ===
        if self._config.take_profit_pct <= 0:
            return

        current_price = (
            market.yes_price if pos.outcome == "Yes" else market.no_price
        )
        if pos.entry_price <= 0:
            return

        unrealized_pct = (current_price - pos.entry_price) / pos.entry_price
        if unrealized_pct < self._config.take_profit_pct:
            return

        # === REALISTIC EXIT SIMULATION ===

        # 1. Check real liquidity (can we actually sell?)
        liquidity_ok = True
        real_exit_slippage = MIN_EXIT_SLIPPAGE
        try:
            book = await self._clob.get_order_book(pos.token_id)
            # Slippage scales with position size vs available liquidity
            if book.bid_depth_usd > 0:
                size_vs_liquidity = pos.usdc_invested / book.bid_depth_usd
                # If our position is >20% of bid depth, slippage is huge
                if size_vs_liquidity > 0.50:
                    liquidity_ok = False
                    logger.debug(
                        "Skip TP: %s — position $%.2f is %.0f%% of bid depth $%.0f",
                        pos.market_title[:30], pos.usdc_invested,
                        size_vs_liquidity * 100, book.bid_depth_usd,
                    )
                elif size_vs_liquidity > 0.10:
                    real_exit_slippage = min(size_vs_liquidity, 0.10)  # Up to 10%
                # else: small position, normal slippage
            else:
                liquidity_ok = False  # No bids at all
        except CLOBError:
            # If we can't check liquidity, use conservative slippage
            real_exit_slippage = 0.03  # 3% conservative

        if not liquidity_ok:
            return  # Can't sell — no liquidity

        # 2. Cap the unrealized gain at realistic levels
        # Underdogs (entry < 0.20) rarely have liquidity to exit at top price
        if pos.entry_price < 0.20:
            # For deep underdogs, cap exit price at entry * 3x max
            max_exit = pos.entry_price * MAX_REALISTIC_TP_MULTIPLIER
            effective_exit = min(current_price, max_exit)
        else:
            effective_exit = current_price

        # 3. Calculate realistic P&L
        gross_pnl = (effective_exit - pos.entry_price) * pos.shares

        # 4. Deduct fees and slippage
        exit_slippage_cost = gross_pnl * real_exit_slippage
        fee_cost = max(0, gross_pnl - exit_slippage_cost) * POLYMARKET_FEE
        pnl = gross_pnl - exit_slippage_cost - fee_cost

        # 5. If after all costs PnL is negative, don't take profit
        if pnl <= 0:
            return

        self._repo.update_position_result(pos.id, "sold", pnl)  # type: ignore[arg-type]
        if hasattr(self._clob, '_simulated_balance'):
            self._clob._simulated_balance += pos.usdc_invested + pnl

        actual_pct = pnl / pos.usdc_invested * 100 if pos.usdc_invested > 0 else 0
        logger.info(
            "Take profit: %s — gross +%.0f%%, net +%.0f%% ($%.2f) [slip=%.1f%%, fee=%.1f%%]",
            pos.market_title[:35],
            unrealized_pct * 100,
            actual_pct,
            pnl,
            real_exit_slippage * 100,
            POLYMARKET_FEE * 100,
        )

        if self._on_take_profit:
            try:
                await self._on_take_profit(pos, pnl)  # type: ignore[misc]
            except Exception:
                logger.exception("Error in on_take_profit callback")

    @staticmethod
    def _determine_outcome(position: Position, resolved_outcome: str) -> bool:
        if position.outcome == "Yes":
            return resolved_outcome.lower() in ("yes", "1", "true")
        return resolved_outcome.lower() in ("no", "0", "false")
