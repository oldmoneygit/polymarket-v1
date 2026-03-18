"""Unit tests for Sprint 3 — Regime Detector, Smart Entry."""

from __future__ import annotations

import pytest

from src.api.clob import OrderBookSummary
from src.policy.regime import RegimeDetector, Regime
from src.policy.smart_entry import SmartEntryCalculator, EntryStrategy


# ── Regime Detector ───────────────────────────────────────────


class TestRegimeDetector:
    def test_low_activity_with_no_data(self) -> None:
        rd = RegimeDetector()
        state = rd.detect()
        assert state.regime == Regime.LOW_ACTIVITY

    def test_normal_after_consistent_wins(self) -> None:
        rd = RegimeDetector()
        # Mostly positive, low variance = NORMAL or TRENDING
        for pnl in [0.3, 0.2, 0.4, 0.1, 0.3, 0.2, 0.3, 0.1, 0.2, 0.3]:
            rd.record_pnl(pnl)
        state = rd.detect()
        assert state.regime in (Regime.NORMAL, Regime.TRENDING)

    def test_trending_on_win_streak(self) -> None:
        rd = RegimeDetector(win_streak_threshold=4)
        for _ in range(6):
            rd.record_pnl(1.0)
        state = rd.detect()
        assert state.regime == Regime.TRENDING
        assert state.kelly_mult > 1.0  # Boost

    def test_mean_reverting_on_loss_streak(self) -> None:
        rd = RegimeDetector(loss_streak_threshold=3)
        # Some wins then losses
        for _ in range(5):
            rd.record_pnl(0.5)
        for _ in range(4):
            rd.record_pnl(-1.0)
        state = rd.detect()
        assert state.regime == Regime.MEAN_REVERTING
        assert state.kelly_mult < 1.0  # Reduce

    def test_high_volatility(self) -> None:
        rd = RegimeDetector()
        # Wild swings
        for i in range(10):
            rd.record_pnl(5.0 if i % 2 == 0 else -4.5)
        state = rd.detect()
        assert state.regime in (Regime.HIGH_VOLATILITY, Regime.NORMAL)

    def test_format_status(self) -> None:
        rd = RegimeDetector()
        for _ in range(5):
            rd.record_pnl(1.0)
        text = rd.format_status()
        assert "Regime:" in text
        assert "Kelly" in text


# ── Smart Entry Calculator ────────────────────────────────────


_GOOD_BOOK = OrderBookSummary(
    token_id="t1", best_bid=0.49, best_ask=0.51,
    spread=0.02, midpoint=0.50,
    bid_depth_usd=5000.0, ask_depth_usd=5000.0,
)

_THIN_BOOK = OrderBookSummary(
    token_id="t1", best_bid=0.45, best_ask=0.55,
    spread=0.10, midpoint=0.50,
    bid_depth_usd=20.0, ask_depth_usd=20.0,
)


class TestSmartEntry:
    def test_market_entry_on_strong_signals(self) -> None:
        calc = SmartEntryCalculator()
        plan = calc.calculate(
            book=_GOOD_BOOK,
            trade_price=0.55,  # Trader entered higher, market cheaper for us
            market_yes_price=0.50,
            recent_prices=[0.52, 0.51, 0.50],  # Price dropping = good to buy
        )
        assert plan.strategy == EntryStrategy.MARKET
        assert plan.urgency > 0.5
        assert plan.target_price > 0

    def test_skip_on_bad_signals(self) -> None:
        calc = SmartEntryCalculator()
        plan = calc.calculate(
            book=_THIN_BOOK,  # Thin orderbook
            trade_price=0.45,  # Trader got cheaper, market more expensive now
            market_yes_price=0.55,
            recent_prices=[0.48, 0.50, 0.55],  # Price rising against us
        )
        assert plan.strategy in (EntryStrategy.PATIENT, EntryStrategy.SKIP)

    def test_limit_on_moderate_signals(self) -> None:
        calc = SmartEntryCalculator()
        plan = calc.calculate(
            book=_GOOD_BOOK,
            trade_price=0.50,  # Same as market
            market_yes_price=0.50,
        )
        assert plan.strategy in (EntryStrategy.LIMIT, EntryStrategy.MARKET)

    def test_all_signals_present(self) -> None:
        calc = SmartEntryCalculator()
        plan = calc.calculate(
            book=_GOOD_BOOK,
            trade_price=0.50,
            market_yes_price=0.50,
            recent_prices=[0.50, 0.50, 0.50],
        )
        assert "price_vs_trader" in plan.signals
        assert "depth" in plan.signals
        assert "spread" in plan.signals
        assert "momentum" in plan.signals

    def test_no_recent_prices_still_works(self) -> None:
        calc = SmartEntryCalculator()
        plan = calc.calculate(
            book=_GOOD_BOOK,
            trade_price=0.50,
            market_yes_price=0.50,
        )
        assert plan.signals["momentum"] == 0.0
        assert plan.strategy != EntryStrategy.SKIP
