"""Trade executor — places orders on the CLOB after safety checks.

Supports BUY (open position) and SELL (close position) copy trading.
Supports 3 sizing modes: fixed, proportional, portfolio-weighted.
Integrates confluence signals for dynamic position sizing.
"""

from __future__ import annotations

import logging
import time

from src.api.clob import CLOBClient, CLOBError
from src.config import Config
from src.db.models import ExecutionResult, MarketInfo, Position, TraderTrade
from src.db.repository import Repository
from src.strategy.confluence import ConfluenceDetector, MarketSignal
from src.strategy.kelly import fractional_kelly, estimate_win_prob_from_trader

logger = logging.getLogger(__name__)

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
        confluence: ConfluenceDetector | None = None,
    ) -> None:
        self._config = config
        self._clob = clob_client
        self._repo = repository
        self._confluence = confluence

    def _calculate_size(
        self,
        trade: TraderTrade,
        headroom: float,
        confluence_signal: MarketSignal | None = None,
    ) -> float:
        """Calculate trade size based on configured sizing mode."""
        config = self._config

        if config.copy_size_mode == "kelly":
            # Kelly Criterion sizing — estimates edge from trader win rate + market price
            # Use market price as baseline, blend with assumed 60% trader win rate
            win_prob = estimate_win_prob_from_trader(
                trader_win_rate=0.60,  # Conservative default
                market_price=trade.price,
                confidence_weight=0.6,
            )
            bankroll = config.max_total_exposure_usd - self._repo.get_total_open_exposure()
            base = fractional_kelly(
                win_prob=win_prob,
                price=trade.price,
                bankroll=max(0, bankroll),
                fraction=config.kelly_fraction,
                min_bet=1.0,
                max_bet=config.max_copy_trade_usd,
            )
        elif config.copy_size_mode == "proportional":
            # Size proportional to trader's trade size
            base = trade.usdc_size * config.copy_size_multiplier
        elif config.copy_size_mode == "portfolio":
            # Size as percentage of current available capital
            balance_approx = config.max_total_exposure_usd - self._repo.get_total_open_exposure()
            base = max(0, balance_approx) * config.copy_size_multiplier
        else:
            # Fixed mode (default)
            base = config.capital_per_trade_usd

        # Apply confluence boost
        if confluence_signal is not None and config.confluence_enabled:
            if confluence_signal.strength == "STRONG":
                base *= config.confluence_boost_strong
                logger.info(
                    "Confluence STRONG boost: %.1fx → $%.2f",
                    config.confluence_boost_strong, base,
                )
            elif confluence_signal.strength == "MODERATE":
                base *= config.confluence_boost_moderate
                logger.info(
                    "Confluence MODERATE boost: %.1fx → $%.2f",
                    config.confluence_boost_moderate, base,
                )

        # Apply caps
        base = min(base, config.max_copy_trade_usd)
        base = min(base, headroom)
        base = min(base, config.capital_per_trade_usd * 5)  # Safety: never more than 5x base

        return max(0, base)

    async def execute(
        self,
        trade: TraderTrade,
        market: MarketInfo,
    ) -> ExecutionResult:
        """Attempt to execute a copy trade. Returns result regardless of success."""
        if trade.side == "SELL":
            return await self._execute_sell(trade, market)
        return await self._execute_buy(trade, market)

    async def _execute_sell(
        self,
        trade: TraderTrade,
        market: MarketInfo,
    ) -> ExecutionResult:
        """Close an existing position when the copied trader sells."""
        config = self._config

        existing = self._repo.find_open_position(trade.condition_id, trade.outcome)
        if existing is None:
            return ExecutionResult(
                success=False,
                error="SELL: sem posição aberta para fechar",
            )

        token_id = existing.token_id or trade.token_id or trade.condition_id

        # Order book pre-check for SELL
        try:
            book = await self._clob.get_order_book(token_id)
            slippage = self._clob.estimate_slippage(book, existing.usdc_invested, "SELL")
            if slippage > MAX_SLIPPAGE and not config.dry_run:
                return ExecutionResult(
                    success=False,
                    error=f"SELL slippage {slippage:.1%} acima do máximo {MAX_SLIPPAGE:.0%}",
                )
        except CLOBError:
            logger.debug("SELL order book check failed, proceeding anyway")

        # Execute sell
        try:
            order = await self._clob.create_market_order(
                token_id=token_id,
                side="SELL",
                amount_usdc=existing.shares,
            )
        except CLOBError as exc:
            return ExecutionResult(
                success=False, error=f"Erro na venda: {exc}"
            )

        # Calculate P&L and close position
        sell_price = order.price if order.price > 0 else trade.price
        proceeds = existing.shares * sell_price
        pnl = proceeds - existing.usdc_invested

        self._repo.update_position_result(
            existing.id, "sold", pnl  # type: ignore[arg-type]
        )

        logger.info(
            "SELL executed: %s %s — sold %.2f shares @ %.4f, PnL: $%.2f (dry_run=%s)",
            trade.outcome, trade.title[:40],
            existing.shares, sell_price, pnl, config.dry_run,
        )

        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            price=sell_price,
            usdc_spent=0.0,
            dry_run=config.dry_run,
        )

    async def _execute_buy(
        self,
        trade: TraderTrade,
        market: MarketInfo,
    ) -> ExecutionResult:
        """Open or add to a position when the copied trader buys."""
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

        # Get confluence signal if available
        confluence_signal = None
        if self._confluence is not None and config.confluence_enabled:
            key = (trade.condition_id, trade.outcome)
            signals = self._confluence._signals
            confluence_signal = signals.get(key)

        amount = self._calculate_size(trade, headroom, confluence_signal)
        if amount <= 0:
            return ExecutionResult(
                success=False, error="Sem capital disponível"
            )

        # 4. Determine token_id
        token_id = trade.token_id or trade.condition_id

        # 5. Order book pre-check (liquidity + slippage)
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

        if existing is not None:
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
            "Trade executed: %s %s @ %.4f — $%.2f invested (dry_run=%s, mode=%s)",
            trade.outcome,
            trade.title[:40],
            entry_price,
            usdc_invested,
            config.dry_run,
            config.copy_size_mode,
        )

        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            price=entry_price,
            usdc_spent=usdc_invested,
            dry_run=config.dry_run,
        )
