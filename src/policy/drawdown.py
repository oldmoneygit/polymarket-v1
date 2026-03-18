"""Drawdown Heat System — 4-level circuit breaker for capital protection.

Inspired by Dylan's Fully-Autonomous-Polymarket-AI-Trading-Bot.
Tracks equity curve and applies progressive position sizing reduction.

Levels:
  GREEN  (0-10% DD): Full trading, kelly_multiplier = 1.0
  YELLOW (10-15% DD): Reduced sizing, kelly_multiplier = 0.50
  ORANGE (15-20% DD): Minimal sizing, kelly_multiplier = 0.25
  RED    (20%+ DD): All trading halted, kelly_multiplier = 0.0
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class HeatLevel(Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


HEAT_MULTIPLIERS = {
    HeatLevel.GREEN: 1.0,
    HeatLevel.YELLOW: 0.50,
    HeatLevel.ORANGE: 0.25,
    HeatLevel.RED: 0.0,
}

HEAT_EMOJI = {
    HeatLevel.GREEN: "🟢",
    HeatLevel.YELLOW: "🟡",
    HeatLevel.ORANGE: "🟠",
    HeatLevel.RED: "🔴",
}


@dataclass
class DrawdownState:
    """Current drawdown state snapshot."""

    peak_equity: float
    current_equity: float
    drawdown_pct: float
    heat_level: HeatLevel
    kelly_multiplier: float
    is_killed: bool
    last_updated: int

    @property
    def emoji(self) -> str:
        return HEAT_EMOJI[self.heat_level]


class DrawdownManager:
    """Tracks equity and manages drawdown-based position sizing."""

    def __init__(
        self,
        initial_equity: float = 0.0,
        warning_pct: float = 0.10,
        critical_pct: float = 0.15,
        kill_pct: float = 0.20,
    ) -> None:
        self._warning = warning_pct
        self._critical = critical_pct
        self._kill = kill_pct
        self._peak_equity = initial_equity
        self._current_equity = initial_equity
        self._is_killed = False
        self._equity_history: list[tuple[int, float]] = []
        self._max_history = 1000

    def update_equity(self, pnl: float) -> DrawdownState:
        """Update equity with realized P&L and return current state."""
        self._current_equity += pnl
        now = int(time.time())
        self._equity_history.append((now, self._current_equity))

        # Trim history
        if len(self._equity_history) > self._max_history:
            self._equity_history = self._equity_history[-500:]

        # Update peak
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity

        return self.get_state()

    def set_equity(self, total_pnl: float) -> DrawdownState:
        """Set absolute equity level (e.g., from DB on startup)."""
        self._current_equity = total_pnl
        if total_pnl > self._peak_equity:
            self._peak_equity = total_pnl
        return self.get_state()

    def get_state(self) -> DrawdownState:
        """Get current drawdown state."""
        if self._peak_equity <= 0:
            dd_pct = 0.0
        else:
            dd_pct = (self._peak_equity - self._current_equity) / self._peak_equity

        dd_pct = max(0.0, dd_pct)

        # Determine heat level
        if self._is_killed or dd_pct >= self._kill:
            level = HeatLevel.RED
            self._is_killed = True
        elif dd_pct >= self._critical:
            level = HeatLevel.ORANGE
        elif dd_pct >= self._warning:
            level = HeatLevel.YELLOW
        else:
            level = HeatLevel.GREEN

        multiplier = HEAT_MULTIPLIERS[level]

        return DrawdownState(
            peak_equity=self._peak_equity,
            current_equity=self._current_equity,
            drawdown_pct=dd_pct,
            heat_level=level,
            kelly_multiplier=multiplier,
            is_killed=self._is_killed,
            last_updated=int(time.time()),
        )

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed. Returns (allowed, reason)."""
        state = self.get_state()
        if state.is_killed:
            return False, f"KILL SWITCH: drawdown {state.drawdown_pct:.0%} (peak ${state.peak_equity:.2f})"
        if state.heat_level == HeatLevel.RED:
            return False, f"RED ZONE: drawdown {state.drawdown_pct:.0%}"
        return True, f"{state.emoji} {state.heat_level.value}: sizing {state.kelly_multiplier:.0%}"

    def reset_kill_switch(self) -> None:
        """Manual reset after review. Use with caution."""
        self._is_killed = False
        self._peak_equity = self._current_equity
        logger.warning("Kill switch reset. New peak: $%.2f", self._peak_equity)

    def format_status(self) -> str:
        """Format current state for display."""
        s = self.get_state()
        return (
            f"{s.emoji} Heat: {s.heat_level.value}\n"
            f"Peak: ${s.peak_equity:.2f}\n"
            f"Current: ${s.current_equity:.2f}\n"
            f"Drawdown: {s.drawdown_pct:.1%}\n"
            f"Sizing: {s.kelly_multiplier:.0%}"
        )
