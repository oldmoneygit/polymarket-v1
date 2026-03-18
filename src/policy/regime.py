"""Regime detector — identifies current market regime and adjusts behavior.

5 regimes:
  NORMAL: Standard conditions, no adjustment
  TRENDING: Winning streak, slight boost
  MEAN_REVERTING: After big swing, reduce and wait
  HIGH_VOLATILITY: Wild swings, reduce sizing heavily
  LOW_ACTIVITY: Few trades/resolutions, be patient

Inspired by Dylan's regime_detector.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Regime(Enum):
    NORMAL = "NORMAL"
    TRENDING = "TRENDING"
    MEAN_REVERTING = "MEAN_REVERTING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_ACTIVITY = "LOW_ACTIVITY"


@dataclass(frozen=True)
class RegimeState:
    """Current regime with adjustment multipliers."""

    regime: Regime
    confidence: float  # 0-1
    kelly_mult: float
    edge_threshold_mult: float  # Multiply min_edge by this
    size_mult: float
    description: str


# Multipliers per regime
_REGIME_CONFIG: dict[Regime, dict[str, float]] = {
    Regime.NORMAL: {"kelly": 1.0, "edge_threshold": 1.0, "size": 1.0},
    Regime.TRENDING: {"kelly": 1.15, "edge_threshold": 0.90, "size": 1.10},
    Regime.MEAN_REVERTING: {"kelly": 0.80, "edge_threshold": 1.20, "size": 0.80},
    Regime.HIGH_VOLATILITY: {"kelly": 0.60, "edge_threshold": 1.50, "size": 0.70},
    Regime.LOW_ACTIVITY: {"kelly": 0.80, "edge_threshold": 1.30, "size": 0.80},
}


class RegimeDetector:
    """Detects market regime from recent trading performance."""

    def __init__(
        self,
        window_size: int = 20,
        win_streak_threshold: int = 5,
        loss_streak_threshold: int = 3,
        vol_threshold: float = 0.50,
    ) -> None:
        self._window = window_size
        self._win_streak_thresh = win_streak_threshold
        self._loss_streak_thresh = loss_streak_threshold
        self._vol_threshold = vol_threshold
        self._pnl_history: list[float] = []

    def record_pnl(self, pnl: float) -> RegimeState:
        """Record a P&L result and return updated regime."""
        self._pnl_history.append(pnl)
        if len(self._pnl_history) > self._window * 2:
            self._pnl_history = self._pnl_history[-self._window:]
        return self.detect()

    def detect(self) -> RegimeState:
        """Analyze recent history and determine current regime."""
        recent = self._pnl_history[-self._window:]

        if len(recent) < 3:
            return self._make_state(Regime.LOW_ACTIVITY, 0.3, "Insufficient data")

        wins = sum(1 for p in recent if p > 0)
        losses = sum(1 for p in recent if p < 0)
        total = len(recent)

        # Win/loss streaks
        current_streak = 0
        streak_positive = True
        for p in reversed(recent):
            if current_streak == 0:
                streak_positive = p >= 0
                current_streak = 1
            elif (p >= 0) == streak_positive:
                current_streak += 1
            else:
                break

        # Volatility (std dev of PnL)
        mean_pnl = sum(recent) / total
        variance = sum((p - mean_pnl) ** 2 for p in recent) / total
        std_pnl = variance ** 0.5
        avg_abs = sum(abs(p) for p in recent) / total
        vol_ratio = std_pnl / avg_abs if avg_abs > 0 else 0

        # Detect regime
        if total < 5:
            regime = Regime.LOW_ACTIVITY
            conf = 0.4
            desc = f"Only {total} trades in window"

        elif streak_positive and current_streak >= self._win_streak_thresh:
            regime = Regime.TRENDING
            conf = min(0.5 + current_streak * 0.1, 0.9)
            desc = f"Win streak of {current_streak}"

        elif not streak_positive and current_streak >= self._loss_streak_thresh:
            regime = Regime.MEAN_REVERTING
            conf = min(0.5 + current_streak * 0.1, 0.9)
            desc = f"Loss streak of {current_streak}, expect reversion"

        elif vol_ratio > self._vol_threshold:
            regime = Regime.HIGH_VOLATILITY
            conf = min(0.5 + vol_ratio, 0.9)
            desc = f"High PnL volatility (ratio: {vol_ratio:.2f})"

        elif wins / total < 0.30:
            regime = Regime.HIGH_VOLATILITY
            conf = 0.6
            desc = f"Low win rate: {wins}/{total} ({wins/total:.0%})"

        else:
            regime = Regime.NORMAL
            conf = 0.7
            desc = f"W:{wins} L:{losses} streak:{current_streak} vol:{vol_ratio:.2f}"

        return self._make_state(regime, conf, desc)

    @staticmethod
    def _make_state(regime: Regime, confidence: float, description: str) -> RegimeState:
        config = _REGIME_CONFIG[regime]
        return RegimeState(
            regime=regime,
            confidence=confidence,
            kelly_mult=config["kelly"],
            edge_threshold_mult=config["edge_threshold"],
            size_mult=config["size"],
            description=description,
        )

    def format_status(self) -> str:
        state = self.detect()
        return (
            f"Regime: {state.regime.value}\n"
            f"Confidence: {state.confidence:.0%}\n"
            f"Kelly mult: {state.kelly_mult:.2f}\n"
            f"Size mult: {state.size_mult:.2f}\n"
            f"{state.description}"
        )
