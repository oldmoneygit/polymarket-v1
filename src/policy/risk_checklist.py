"""15-Point Risk Checklist — comprehensive pre-trade validation.

Every trade must pass ALL checks before execution.
Inspired by Dylan's Fully-Autonomous-Polymarket-AI-Trading-Bot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import Config
from src.db.models import MarketInfo, Position, TraderTrade
from src.policy.drawdown import DrawdownManager
from src.policy.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    """Result of a single risk check."""

    name: str
    passed: bool
    reason: str


@dataclass
class ChecklistResult:
    """Result of the full 15-point checklist."""

    checks: list[CheckResult]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        if self.all_passed:
            return f"PASS ({passed}/{total})"
        failed_names = ", ".join(c.name for c in self.failed_checks)
        return f"FAIL ({passed}/{total}) — {failed_names}"


class RiskChecklist:
    """Runs a comprehensive pre-trade risk checklist."""

    def __init__(
        self,
        config: Config,
        drawdown: DrawdownManager,
        portfolio: PortfolioRiskManager,
    ) -> None:
        self._config = config
        self._drawdown = drawdown
        self._portfolio = portfolio

    def run(
        self,
        trade: TraderTrade,
        market: MarketInfo,
        trade_amount: float,
        balance: float,
        daily_pnl: float,
        open_positions: list[Position],
    ) -> ChecklistResult:
        """Run all 15 risk checks. Returns comprehensive result."""
        checks: list[CheckResult] = []

        # 1. Kill switch (drawdown)
        can_trade, reason = self._drawdown.can_trade()
        checks.append(CheckResult("kill_switch", can_trade, reason))

        # 2. Drawdown heat level
        state = self._drawdown.get_state()
        checks.append(CheckResult(
            "heat_level",
            state.kelly_multiplier > 0,
            f"{state.emoji} {state.heat_level.value} ({state.drawdown_pct:.1%} DD)",
        ))

        # 3. Balance minimum
        min_balance = self._config.capital_per_trade_usd
        checks.append(CheckResult(
            "min_balance",
            balance >= min_balance,
            f"${balance:.2f} >= ${min_balance:.2f}" if balance >= min_balance
            else f"${balance:.2f} < ${min_balance:.2f}",
        ))

        # 4. Daily loss limit
        checks.append(CheckResult(
            "daily_loss",
            daily_pnl > -self._config.max_daily_loss_usd,
            f"${daily_pnl:+.2f} > -${self._config.max_daily_loss_usd:.2f}",
        ))

        # 5. Trade amount > 0
        checks.append(CheckResult(
            "trade_amount",
            trade_amount > 0,
            f"${trade_amount:.2f}" if trade_amount > 0 else "Amount is $0",
        ))

        # 6. Max stake per trade
        max_stake = self._config.max_copy_trade_usd
        checks.append(CheckResult(
            "max_stake",
            trade_amount <= max_stake,
            f"${trade_amount:.2f} <= ${max_stake:.2f}",
        ))

        # 7. Market not resolved
        checks.append(CheckResult(
            "market_open",
            not market.is_resolved,
            "Open" if not market.is_resolved else "RESOLVED",
        ))

        # 8. Min volume
        checks.append(CheckResult(
            "min_volume",
            market.volume >= self._config.min_market_volume_usd,
            f"${market.volume:,.0f} >= ${self._config.min_market_volume_usd:,.0f}",
        ))

        # 9. Min liquidity
        checks.append(CheckResult(
            "min_liquidity",
            market.liquidity >= 100,
            f"${market.liquidity:,.0f}",
        ))

        # 10. Max spread (implied from yes+no prices)
        spread = abs(1.0 - market.yes_price - market.no_price)
        checks.append(CheckResult(
            "max_spread",
            spread < 0.10,
            f"{spread:.2%}" if spread < 0.10 else f"Spread {spread:.2%} too wide",
        ))

        # 11. Probability floor (avoid extremes)
        price = trade.price
        checks.append(CheckResult(
            "prob_range",
            self._config.min_probability <= price <= self._config.max_probability,
            f"{price:.0%} in [{self._config.min_probability:.0%}, {self._config.max_probability:.0%}]",
        ))

        # 12. Portfolio risk (category + market + cash reserve)
        risk_check = self._portfolio.check(market, trade_amount, open_positions)
        checks.append(CheckResult(
            "portfolio_risk",
            risk_check.allowed,
            risk_check.reason,
        ))

        # 13. Max open positions (prevent over-diversification)
        max_positions = 80
        checks.append(CheckResult(
            "max_positions",
            len(open_positions) < max_positions,
            f"{len(open_positions)}/{max_positions}",
        ))

        # 14. Trade recency
        import time
        age_minutes = (int(time.time()) - trade.timestamp) / 60
        checks.append(CheckResult(
            "trade_age",
            age_minutes <= self._config.max_trade_age_minutes,
            f"{age_minutes:.0f}min <= {self._config.max_trade_age_minutes}min",
        ))

        # 15. Not a duplicate (same market already at max)
        existing_count = sum(
            1 for p in open_positions if p.condition_id == trade.condition_id
        )
        checks.append(CheckResult(
            "no_duplicate",
            existing_count < 3,
            f"{existing_count}/3 entries in this market",
        ))

        result = ChecklistResult(checks=checks)

        if not result.all_passed:
            logger.info(
                "Risk checklist FAILED: %s — %s",
                trade.title[:40],
                result.summary,
            )

        return result
