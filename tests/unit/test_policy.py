"""Unit tests for src/policy/ modules."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from src.db.models import MarketInfo, Position, TraderTrade
from src.config import Config
from src.policy.drawdown import DrawdownManager, HeatLevel
from src.policy.portfolio_risk import PortfolioRiskManager
from src.policy.risk_checklist import RiskChecklist


# ── Drawdown Heat System ──────────────────────────────────────


class TestDrawdownManager:
    def test_starts_green(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        state = dm.get_state()
        assert state.heat_level == HeatLevel.GREEN
        assert state.kelly_multiplier == 1.0
        assert state.drawdown_pct == 0.0

    def test_yellow_at_10_pct(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-10.0)  # 10% loss
        state = dm.get_state()
        assert state.heat_level == HeatLevel.YELLOW
        assert state.kelly_multiplier == 0.50

    def test_orange_at_15_pct(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-15.0)
        state = dm.get_state()
        assert state.heat_level == HeatLevel.ORANGE
        assert state.kelly_multiplier == 0.25

    def test_red_kills_trading(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-20.0)
        state = dm.get_state()
        assert state.heat_level == HeatLevel.RED
        assert state.kelly_multiplier == 0.0
        assert state.is_killed is True

        can, reason = dm.can_trade()
        assert can is False
        assert "KILL" in reason

    def test_recovery_updates_peak(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(50.0)  # Peak now 150
        state = dm.get_state()
        assert state.peak_equity == 150.0
        assert state.heat_level == HeatLevel.GREEN

    def test_kill_switch_persists_after_recovery(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-25.0)  # Trigger kill
        dm.update_equity(10.0)   # Partial recovery
        state = dm.get_state()
        assert state.is_killed is True  # Kill persists

    def test_reset_kill_switch(self) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-25.0)
        dm.reset_kill_switch()
        can, _ = dm.can_trade()
        assert can is True

    def test_set_equity_from_db(self) -> None:
        dm = DrawdownManager()
        dm.set_equity(50.0)
        state = dm.get_state()
        assert state.peak_equity == 50.0
        assert state.current_equity == 50.0


# ── Portfolio Risk Manager ────────────────────────────────────


class TestPortfolioRiskManager:
    def _make_position(self, title: str, invested: float, condition_id: str = "c1") -> Position:
        return Position(
            condition_id=condition_id, token_id="t1", side="BUY",
            outcome="Yes", entry_price=0.5, shares=invested * 2,
            usdc_invested=invested, trader_copied="0x", market_title=title,
            opened_at=int(time.time()), status="open", dry_run=True,
        )

    def _make_market(self, category: str = "sports", condition_id: str = "new") -> MarketInfo:
        return MarketInfo(
            condition_id=condition_id, question="Test?", category=category,
            volume=50000, liquidity=10000,
            end_date=datetime.now(timezone.utc) + timedelta(hours=3),
            is_resolved=False, yes_price=0.5, no_price=0.5,
        )

    def test_allows_when_no_positions(self) -> None:
        prm = PortfolioRiskManager(max_exposure=200.0)
        result = prm.check(self._make_market(), 2.0, [])
        assert result.allowed is True

    def test_blocks_cash_reserve(self) -> None:
        prm = PortfolioRiskManager(max_exposure=100.0, cash_reserve_pct=0.20)
        # Max usable = $80. Fill to $79.
        positions = [self._make_position("NBA game", 79.0, f"c{i}") for i in range(1)]
        result = prm.check(self._make_market(), 2.0, positions)
        assert result.allowed is False
        assert "reserve" in result.reason.lower()

    def test_blocks_category_cap(self) -> None:
        prm = PortfolioRiskManager(max_exposure=200.0, category_cap_pct=0.35)
        # Category cap = $70. Fill sports to $69.
        positions = [self._make_position("NBA vs X", 69.0, f"c{i}") for i in range(1)]
        result = prm.check(self._make_market("sports"), 2.0, positions)
        assert result.allowed is False
        assert "Category" in result.reason or "cap" in result.reason.lower()

    def test_blocks_max_positions_per_category(self) -> None:
        prm = PortfolioRiskManager(max_exposure=200.0, max_positions_per_category=3)
        positions = [self._make_position(f"NBA game {i}", 2.0, f"c{i}") for i in range(3)]
        result = prm.check(self._make_market("sports"), 2.0, positions)
        assert result.allowed is False
        assert "positions" in result.reason.lower()

    def test_blocks_single_market_concentration(self) -> None:
        prm = PortfolioRiskManager(max_exposure=200.0, market_cap_pct=0.25)
        # Market cap = $50. Already have $49 in same market.
        positions = [self._make_position("NBA game", 49.0, "same_market")]
        market = self._make_market(condition_id="same_market")
        result = prm.check(market, 2.0, positions)
        assert result.allowed is False
        assert "Market" in result.reason


# ── Risk Checklist ────────────────────────────────────────────


class TestRiskChecklist:
    def test_all_pass_on_clean_state(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo,
    ) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        prm = PortfolioRiskManager(max_exposure=config.max_total_exposure_usd)
        rc = RiskChecklist(config, dm, prm)

        result = rc.run(
            sample_trade, sample_market,
            trade_amount=2.0, balance=1000.0,
            daily_pnl=0.0, open_positions=[],
        )
        assert result.all_passed is True
        assert len(result.checks) == 15

    def test_fails_when_kill_switch(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo,
    ) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        dm.update_equity(-25.0)  # Trigger kill
        prm = PortfolioRiskManager(max_exposure=config.max_total_exposure_usd)
        rc = RiskChecklist(config, dm, prm)

        result = rc.run(
            sample_trade, sample_market,
            trade_amount=2.0, balance=1000.0,
            daily_pnl=0.0, open_positions=[],
        )
        assert result.all_passed is False
        failed_names = [c.name for c in result.failed_checks]
        assert "kill_switch" in failed_names

    def test_summary_format(
        self, config: Config, sample_trade: TraderTrade, sample_market: MarketInfo,
    ) -> None:
        dm = DrawdownManager(initial_equity=100.0)
        prm = PortfolioRiskManager(max_exposure=config.max_total_exposure_usd)
        rc = RiskChecklist(config, dm, prm)

        result = rc.run(
            sample_trade, sample_market,
            trade_amount=2.0, balance=1000.0,
            daily_pnl=0.0, open_positions=[],
        )
        assert "PASS" in result.summary
        assert "15/15" in result.summary
