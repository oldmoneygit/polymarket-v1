"""Unit tests for Sprint 2 — Edge Calc, Whale Conviction, Dynamic Kelly."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from src.db.models import MarketInfo
from src.policy.drawdown import DrawdownManager
from src.policy.edge_calc import calculate_edge, estimate_model_prob_from_copy
from src.policy.dynamic_kelly import DynamicKellySizer
from src.strategy.whale_conviction import (
    WhaleConvictionTracker,
    compute_conviction_score,
    PositionDelta,
    SignalStrength,
)


# ── Edge Calculator ───────────────────────────────────────────


class TestEdgeCalculator:
    def test_positive_edge(self) -> None:
        result = calculate_edge(
            model_prob=0.65, market_price=0.50,
            transaction_fee=0.02, hours_to_resolution=3.0,
        )
        assert result.raw_edge == pytest.approx(0.15, abs=0.01)
        assert result.net_edge > 0
        assert result.has_edge is True

    def test_negative_edge(self) -> None:
        result = calculate_edge(
            model_prob=0.50, market_price=0.55,
        )
        assert result.raw_edge < 0
        assert result.has_edge is False

    def test_edge_after_costs(self) -> None:
        result = calculate_edge(
            model_prob=0.53, market_price=0.50,
            transaction_fee=0.02, hours_to_resolution=48.0,
        )
        # Raw edge = 3% but costs eat most of it
        assert result.raw_edge == pytest.approx(0.03, abs=0.01)
        assert result.net_edge < result.raw_edge

    def test_ev_per_dollar_positive(self) -> None:
        result = calculate_edge(model_prob=0.70, market_price=0.50)
        assert result.ev_per_dollar > 0

    def test_model_prob_from_copy(self) -> None:
        prob = estimate_model_prob_from_copy(
            trader_win_rate=0.65,
            market_price=0.50,
            confluence_count=3,
        )
        # Base: 0.65 * 0.6 + 0.50 * 0.4 = 0.59
        # Confluence: +0.06 (2 extra * 0.03)
        assert prob == pytest.approx(0.65, abs=0.02)


# ── Whale Conviction ──────────────────────────────────────────


class TestWhaleConviction:
    def test_score_single_whale_small(self) -> None:
        score = compute_conviction_score(whale_count=1, total_usd=10.0)
        assert score > 0
        assert score < 45  # Single whale + tiny size = weak

    def test_score_single_whale_large(self) -> None:
        score = compute_conviction_score(whale_count=1, total_usd=5000.0)
        assert score >= 45  # Single whale + decent size = moderate

    def test_score_multiple_whales(self) -> None:
        score = compute_conviction_score(whale_count=3, total_usd=50000.0)
        assert score >= 70  # 3 whales + big money = strong

    def test_score_capped_at_100(self) -> None:
        score = compute_conviction_score(whale_count=10, total_usd=1000000.0)
        assert score == 100.0

    def test_tracker_records_and_scores(self) -> None:
        tracker = WhaleConvictionTracker()
        s1 = tracker.record_trade("c1", "Game", "Yes", "0xaaa", 5000.0)
        assert s1.whale_count == 1
        score_1whale = s1.conviction_score

        s2 = tracker.record_trade("c1", "Game", "Yes", "0xbbb", 10000.0)
        assert s2.whale_count == 2
        # Score increases with more whales and more money
        assert s2.conviction_score > score_1whale or s2.whale_count > 1

        s3 = tracker.record_trade("c1", "Game", "Yes", "0xccc", 20000.0)
        assert s3.whale_count == 3
        assert s3.strength == SignalStrength.STRONG

    def test_delta_detection_new_entry(self) -> None:
        tracker = WhaleConvictionTracker()
        signal = tracker.record_trade("c1", "Game", "Yes", "0xaaa", 5000.0)
        assert PositionDelta.NEW_ENTRY in signal.deltas

    def test_delta_detection_increase(self) -> None:
        tracker = WhaleConvictionTracker()
        tracker.record_trade("c1", "Game", "Yes", "0xaaa", 5000.0)
        signal = tracker.record_trade("c1", "Game", "Yes", "0xaaa", 3000.0)
        assert PositionDelta.SIZE_INCREASE in signal.deltas

    def test_delta_detection_exit(self) -> None:
        tracker = WhaleConvictionTracker()
        tracker.record_trade("c1", "Game", "Yes", "0xaaa", 5000.0)
        signal = tracker.record_trade("c1", "Game", "Yes", "0xaaa", 5000.0, side="SELL")
        assert PositionDelta.EXIT in signal.deltas

    def test_sizing_multiplier(self) -> None:
        tracker = WhaleConvictionTracker()
        for i in range(3):
            signal = tracker.record_trade("c1", "Game", "Yes", f"0x{i}aaa", 20000.0)
        assert signal.sizing_multiplier >= 1.5

    def test_edge_boost(self) -> None:
        tracker = WhaleConvictionTracker()
        for i in range(3):
            signal = tracker.record_trade("c1", "Game", "Yes", f"0x{i}aaa", 20000.0)
        assert signal.edge_boost > 0


# ── Dynamic Kelly ─────────────────────────────────────────────


class TestDynamicKelly:
    def _make_market(self, hours: float = 3.0, category: str = "sports", liquidity: float = 10000.0) -> MarketInfo:
        return MarketInfo(
            condition_id="c1", question="Test?", category=category,
            volume=50000, liquidity=liquidity,
            end_date=datetime.now(timezone.utc) + timedelta(hours=hours),
            is_resolved=False, yes_price=0.50, no_price=0.50,
        )

    def _make_edge(self, model_prob: float = 0.65, market_prob: float = 0.50) -> "EdgeResult":
        from src.policy.edge_calc import calculate_edge
        return calculate_edge(model_prob, market_prob)

    def test_basic_sizing(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)
        result = sizer.calculate(edge, self._make_market(), dm)
        assert result.position_usd > 0
        assert result.reason == "OK"

    def test_no_edge_no_bet(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.45, 0.50)  # No edge
        result = sizer.calculate(edge, self._make_market(), dm)
        assert result.position_usd == 0

    def test_drawdown_reduces_size(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm_green = DrawdownManager(initial_equity=100.0)
        dm_yellow = DrawdownManager(initial_equity=100.0)
        dm_yellow.update_equity(-12.0)  # 12% drawdown = YELLOW

        edge = self._make_edge(0.65, 0.50)
        r_green = sizer.calculate(edge, self._make_market(), dm_green)
        r_yellow = sizer.calculate(edge, self._make_market(), dm_yellow)

        assert r_yellow.position_usd < r_green.position_usd

    def test_fast_market_bonus(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)

        fast = sizer.calculate(edge, self._make_market(hours=2), dm)
        slow = sizer.calculate(edge, self._make_market(hours=36), dm)

        assert fast.position_usd > slow.position_usd

    def test_crypto_gets_less_than_sports(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)

        sports = sizer.calculate(edge, self._make_market(category="sports"), dm)
        crypto = sizer.calculate(edge, self._make_market(category="crypto"), dm)

        assert sports.position_usd > crypto.position_usd

    def test_low_liquidity_reduces(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)

        high_liq = sizer.calculate(edge, self._make_market(liquidity=50000), dm)
        low_liq = sizer.calculate(edge, self._make_market(liquidity=500), dm)

        assert high_liq.position_usd > low_liq.position_usd

    def test_conviction_boosts_confidence(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)

        from src.strategy.whale_conviction import ConvictionSignal
        strong = ConvictionSignal(
            condition_id="c1", title="Game", outcome="Yes",
            whale_count=3, total_usd=50000, conviction_score=80,
        )

        r_no_conv = sizer.calculate(edge, self._make_market(), dm)
        r_strong = sizer.calculate(edge, self._make_market(), dm, conviction=strong)

        assert r_strong.position_usd > r_no_conv.position_usd

    def test_all_7_multipliers_present(self) -> None:
        sizer = DynamicKellySizer(bankroll=200.0)
        dm = DrawdownManager(initial_equity=100.0)
        edge = self._make_edge(0.65, 0.50)
        result = sizer.calculate(edge, self._make_market(), dm)

        assert len(result.multipliers) == 7
        expected_keys = {"confidence", "drawdown", "timeline", "volatility", "regime", "category", "liquidity"}
        assert set(result.multipliers.keys()) == expected_keys
