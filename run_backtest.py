"""Run backtest against real historical data from monitored traders.

Usage:
    python run_backtest.py                    # Basic backtest
    python run_backtest.py --optimize         # Grid search for best params
    python run_backtest.py --alpha-decay      # Measure edge vs delay
    python run_backtest.py --days 14          # Last 14 days (default: 7)
    python run_backtest.py --capital 1.0      # $1 per trade
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from src.api.polymarket import PolymarketClient
from src.backtest.alpha_decay import analyze_alpha_decay, format_decay_report
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.optimizer import GridSearchOptimizer
from src.config import Config
from src.db.models import MarketInfo, TraderTrade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def fetch_historical_data(
    config: Config, days: int = 7, limit_per_trader: int = 200
) -> tuple[list[TraderTrade], dict[str, MarketInfo]]:
    """Fetch trades and market data from all monitored traders."""
    client = PolymarketClient()
    all_trades: list[TraderTrade] = []
    markets: dict[str, MarketInfo] = {}

    try:
        for i, wallet in enumerate(config.trader_wallets, 1):
            logger.info(
                "Fetching trader %d/%d: %s...",
                i, len(config.trader_wallets), wallet[:10],
            )
            try:
                trades = await client.get_trader_activity(wallet, limit=limit_per_trader)
                all_trades.extend(trades)
                logger.info("  Got %d trades", len(trades))
            except Exception as e:
                logger.warning("  Failed: %s", e)

        # Deduplicate by tx hash
        seen_hashes: set[str] = set()
        unique_trades: list[TraderTrade] = []
        for t in all_trades:
            if t.transaction_hash and t.transaction_hash not in seen_hashes:
                seen_hashes.add(t.transaction_hash)
                unique_trades.append(t)

        # Fetch market info for all condition IDs
        condition_ids = {t.condition_id for t in unique_trades}
        logger.info("Fetching market info for %d unique markets...", len(condition_ids))

        for cid in condition_ids:
            try:
                market = await client.get_market_info(cid)
                if market is not None:
                    markets[cid] = market
            except Exception:
                pass
            await asyncio.sleep(0.1)  # Rate limit courtesy

        logger.info(
            "Data loaded: %d trades, %d markets (%d resolved)",
            len(unique_trades),
            len(markets),
            sum(1 for m in markets.values() if m.is_resolved),
        )

        # Sort chronologically
        unique_trades.sort(key=lambda t: t.timestamp)

        return unique_trades, markets
    finally:
        await client.close()


def print_result(result: BacktestResult, label: str = "Backtest") -> None:
    """Print backtest results in a formatted table."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Total trades:      {result.total_trades}")
    print(f"  Resolved:          {result.resolved_trades}")
    print(f"  Wins:              {result.wins}")
    print(f"  Losses:            {result.losses}")
    print(f"  Win rate:          {result.win_rate:.1%}")
    print(f"  Total P&L:         ${result.total_pnl:+.2f}")
    print(f"  Avg P&L/trade:     ${result.avg_pnl:+.4f}")
    print(f"  Profit factor:     {result.profit_factor:.2f}")
    print(f"  Max drawdown:      ${result.max_drawdown:.2f}")
    print(f"  Sharpe estimate:   {result.sharpe_estimate:.2f}")
    print(f"{'=' * 60}")

    if result.trades:
        print(f"\n  Top 10 trades:")
        sorted_trades = sorted(result.trades, key=lambda t: t.pnl, reverse=True)
        for t in sorted_trades[:10]:
            status = "WON" if t.won else ("LOST" if t.resolved else "OPEN")
            print(
                f"    {status:5} ${t.pnl:+.2f} | {t.outcome} {t.title[:40]} @ {t.entry_price:.2f}"
            )

    if result.params:
        print(f"\n  Parameters:")
        for k, v in result.params.items():
            print(f"    {k}: {v}")
    print()


async def run_basic_backtest(config: Config, days: int, capital: float) -> None:
    """Run a basic backtest with current config."""
    trades, markets = await fetch_historical_data(config, days)

    if not trades:
        print("No trade data available. Traders may not have recent activity.")
        return

    engine = BacktestEngine(
        capital_per_trade=capital,
        max_exposure=config.max_total_exposure_usd,
        max_daily_loss=config.max_daily_loss_usd,
        min_volume=config.min_market_volume_usd,
        min_prob=config.min_probability,
        max_prob=config.max_probability,
        max_age_minutes=config.max_trade_age_minutes,
        take_profit_pct=config.take_profit_pct,
    )

    result = engine.run(trades, markets)
    print_result(result, f"Backtest ({days} days, ${capital}/trade)")


async def run_optimizer(config: Config, days: int) -> None:
    """Run grid search optimization."""
    trades, markets = await fetch_historical_data(config, days)

    if not trades:
        print("No trade data available.")
        return

    optimizer = GridSearchOptimizer()
    opt_result = optimizer.optimize(trades, markets)

    print(f"\n{'=' * 60}")
    print(f"  Grid Search Optimization ({opt_result.total_combinations} combos)")
    print(f"{'=' * 60}")
    print(f"  Best score: {opt_result.best_score:.2f}")
    print_result(opt_result.best_result, "Best Configuration")

    print("  Top 5 configurations:")
    for i, (params, score, res) in enumerate(opt_result.all_results[:5], 1):
        print(
            f"  {i}. score={score:.1f} | pnl=${res.total_pnl:+.2f} | "
            f"wr={res.win_rate:.0%} | trades={res.resolved_trades} | "
            f"params={params}"
        )
    print()


async def run_alpha_decay(config: Config, days: int) -> None:
    """Analyze alpha decay across different delays."""
    trades, markets = await fetch_historical_data(config, days)

    if not trades:
        print("No trade data available.")
        return

    points = analyze_alpha_decay(trades, markets)
    print(f"\n{format_decay_report(points)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket Copy Trading Backtest")
    parser.add_argument("--optimize", action="store_true", help="Run grid search optimization")
    parser.add_argument("--alpha-decay", action="store_true", help="Analyze alpha decay")
    parser.add_argument("--days", type=int, default=7, help="Days of history (default: 7)")
    parser.add_argument("--capital", type=float, default=1.0, help="USD per trade (default: 1.0)")
    args = parser.parse_args()

    config = Config.load()

    if args.optimize:
        asyncio.run(run_optimizer(config, args.days))
    elif args.alpha_decay:
        asyncio.run(run_alpha_decay(config, args.days))
    else:
        asyncio.run(run_basic_backtest(config, args.days, args.capital))


if __name__ == "__main__":
    main()
