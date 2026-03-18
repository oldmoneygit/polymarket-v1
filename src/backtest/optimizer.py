"""Grid search optimizer for backtest filter parameters."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any

from src.backtest.engine import BacktestEngine, BacktestResult
from src.db.models import MarketInfo, TraderTrade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimizationResult:
    """Best parameters found by the optimizer."""

    best_params: dict[str, Any]
    best_score: float
    best_result: BacktestResult
    all_results: list[tuple[dict[str, Any], float, BacktestResult]]
    total_combinations: int


class GridSearchOptimizer:
    """Exhaustive grid search over backtest parameters.

    Tests all combinations and finds the Pareto-optimal config
    based on a scoring function (default: PnL * win_rate).
    """

    def __init__(
        self,
        param_grid: dict[str, list[Any]] | None = None,
    ) -> None:
        self._grid = param_grid or self._default_grid()

    @staticmethod
    def _default_grid() -> dict[str, list[Any]]:
        return {
            "min_volume": [2000.0, 5000.0, 10000.0, 25000.0],
            "min_prob": [0.10, 0.20, 0.30],
            "max_prob": [0.75, 0.85, 0.90],
            "max_age_minutes": [15, 30, 60, 120],
            "capital_per_trade": [2.0, 5.0, 10.0],
            "take_profit_pct": [0.0, 0.15, 0.25, 0.40],
        }

    @staticmethod
    def _score(result: BacktestResult) -> float:
        """Score a backtest result. Higher is better.

        Combines PnL, win rate, and penalizes drawdown.
        """
        if result.resolved_trades == 0:
            return -999.0

        pnl_score = result.total_pnl
        wr_bonus = result.win_rate * 10  # Reward high win rate
        dd_penalty = result.max_drawdown * 2  # Penalize drawdown
        trade_bonus = min(result.resolved_trades / 10, 5)  # Reward more data

        return pnl_score + wr_bonus - dd_penalty + trade_bonus

    def optimize(
        self,
        trades: list[TraderTrade],
        markets: dict[str, MarketInfo],
    ) -> OptimizationResult:
        """Run grid search across all parameter combinations."""
        keys = list(self._grid.keys())
        values = list(self._grid.values())
        combinations = list(itertools.product(*values))
        total = len(combinations)

        logger.info("Grid search: %d combinations to test", total)

        all_results: list[tuple[dict[str, Any], float, BacktestResult]] = []
        best_score = float("-inf")
        best_params: dict[str, Any] = {}
        best_result = BacktestResult()

        for i, combo in enumerate(combinations):
            params = dict(zip(keys, combo))

            # Skip invalid combos
            if params.get("min_prob", 0) >= params.get("max_prob", 1):
                continue

            engine = BacktestEngine(**params)
            result = engine.run(trades, markets)
            score = self._score(result)

            all_results.append((params, score, result))

            if score > best_score:
                best_score = score
                best_params = params
                best_result = result

            if (i + 1) % 100 == 0:
                logger.info(
                    "Grid search progress: %d/%d (best score: %.2f)",
                    i + 1, total, best_score,
                )

        logger.info(
            "Grid search complete. Best: score=%.2f pnl=$%.2f wr=%.1f%% trades=%d",
            best_score,
            best_result.total_pnl,
            best_result.win_rate * 100,
            best_result.resolved_trades,
        )

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            best_result=best_result,
            all_results=sorted(all_results, key=lambda x: x[1], reverse=True),
            total_combinations=total,
        )
