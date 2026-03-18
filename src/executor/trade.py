"""Trade executor — places orders on the CLOB after safety checks.

# [MERGED FROM polymarket-v1] Enhanced — adds order book pre-checks (liquidity,
# slippage estimation), position averaging support, and safety constants.
"""

from __future__ import annotations

import logging
import time

from src.api.clob import CLOBClient, CLOBError
from src.config import Config
from src.db.models import ExecutionResult, MarketInfo, Position, TraderTrade
from src.db.repository import Repository

logger = logging.getLogger(__name__)

# [MERGED FROM polymarket-v1] New safety constants
# Max acceptable slippage before skipping trade
MAX_SLIPPAGE = 0.05  # 5%
# Min order book depth required (USD)
MIN_LIQUIDITY_USD = 50.0


class TradeExecutor:
    """Executes copy trades with full safety checks."""

    def __init__(
        self,
        config: Config,
        clob_client: CLOBClient,
        repository: Repository,
    ) -> None:
        self._config = config
        self._clob = clob_client
        self._repo = repository

    async def execute(
        self,
        trade: TraderTrade,
        market: MarketInfo,
    ) -> ExecutionResult:
        """Attempt to execute a copy trade. Returns result regardless of success."""
        config = self._config

        # 1. Check balance
        try:
            balance = await self._clob.get_balance()
        except CLOBError as exc:
            return ExecutionResult(
                success=False, error=f"Erro ao consultar saldo: {exc}"
            )

        if balance < config.capital_per_trade_usd:
            return ExecutionResult(
                success=False,
                error=f"Saldo insuficiente: ${balance:.2f}",
            )

        # 2. Check daily stop
        daily_pnl = self._repo.get_daily_pnl()
        if daily_pnl <= -config.max_daily_loss_usd:
            return ExecutionResult(
                success=False, error="Stop diário atingido"
            )

        # 3. Calculate size respecting exposure limits
        current_exposure = self._repo.get_total_open_exposure()
        headroom = config.max_total_exposure_usd - current_exposure
        amount = min(config.capital_per_trade_usd, headroom)
        if amount <= 0:
            return ExecutionResult(
                success=False, error="Sem capital disponível"
            )

        # 4. Determine token_id
        token_id = trade.token_id or trade.condition_id

        # 5. Order book pre-check (liquidity + slippage)
        # [MERGED FROM polymarket-v1] New safety checks
        try:
            book = await self._clob.get_order_book(token_id)
            if not book.has_liquidity and not config.dry_run:
                return ExecutionResult(
                    success=False,
                    error=f"Sem liquidez no order book (bid_depth=${book.bid_depth_usd:.0f}, ask_depth=${book.ask_depth_usd:.0f})",
                )
            slippage = self._clob.estimate_slippage(book, amount, "BUY")
            if slippage > MAX_SLIPPAGE and not config.dry_run:
                return ExecutionResult(
                    success=False,
                    error=f"Slippage estimado {slippage:.1%} acima do máximo {MAX_SLIPPAGE:.0%}",
                )
            if book.ask_depth_usd < MIN_LIQUIDITY_USD and not config.dry_run:
                return ExecutionResult(
                    success=False,
                    error=f"Liquidez insuficiente: ${book.ask_depth_usd:.0f} < ${MIN_LIQUIDITY_USD:.0f}",
                )
            logger.info(
                "Order book: bid=%.4f ask=%.4f spread=%.4f (%.2f%%) depth=$%.0f/$%.0f slippage=%.2f%%",
                book.best_bid, book.best_ask, book.spread,
                book.spread_pct * 100, book.bid_depth_usd, book.ask_depth_usd,
                slippage * 100,
            )
        except CLOBError:
            logger.debug("Order book check failed, proceeding anyway")

        # 6. Check for existing position (averaging support)
        # [MERGED FROM polymarket-v1] New — position averaging
        existing = self._repo.find_open_position(trade.condition_id, trade.outcome)
        if existing is not None:
            logger.info(
                "Adding to existing position: %s %s (current $%.2f)",
                trade.outcome, trade.title[:30], existing.usdc_invested,
            )

        # 7. Execute order
        try:
            order = await self._clob.create_market_order(
                token_id=token_id,
                side="BUY",
                amount_usdc=amount,
            )
        except CLOBError as exc:
            return ExecutionResult(
                success=False, error=f"Erro na execução: {exc}"
            )

        # 8. Save position (or update existing)
        entry_price = order.price if order.price > 0 else trade.price
        shares = order.filled_size if order.filled_size > 0 else (amount / entry_price if entry_price > 0 else 0)
        usdc_invested = amount

        # [MERGED FROM polymarket-v1] Position averaging support
        if existing is not None:
            # Average into existing position
            total_invested = existing.usdc_invested + usdc_invested
            total_shares = existing.shares + shares
            avg_price = total_invested / total_shares if total_shares > 0 else entry_price
            self._repo.update_position_average(
                existing.id, total_shares, total_invested, avg_price  # type: ignore[arg-type]
            )
            logger.info(
                "Position averaged: %s — $%.2f total, %.2f shares @ %.4f avg",
                trade.title[:40], total_invested, total_shares, avg_price,
            )
        else:
            position = Position(
                condition_id=trade.condition_id,
                token_id=token_id,
                side=trade.side,
                outcome=trade.outcome,
                entry_price=entry_price,
                shares=shares,
                usdc_invested=usdc_invested,
                trader_copied=trade.proxy_wallet,
                market_title=trade.title,
                opened_at=int(time.time()),
                status="open",
                order_id=order.order_id,
                dry_run=config.dry_run,
            )
            self._repo.save_position(position)

        logger.info(
            "Trade executed: %s %s @ %.4f — $%.2f invested (dry_run=%s)",
            trade.outcome,
            trade.title[:40],
            entry_price,
            usdc_invested,
            config.dry_run,
        )

        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            price=entry_price,
            usdc_spent=usdc_invested,
            dry_run=config.dry_run,
        )
