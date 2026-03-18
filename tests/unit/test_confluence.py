"""Unit tests for src/strategy/confluence.py."""

from __future__ import annotations

import time

from src.strategy.confluence import ConfluenceDetector, MarketSignal


class TestConfluenceDetector:
    def test_single_trader_no_confluence(self) -> None:
        det = ConfluenceDetector()
        signal = det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        assert signal.trader_count == 1
        assert signal.is_confluence is False

    def test_two_traders_creates_confluence(self) -> None:
        det = ConfluenceDetector()
        det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        signal = det.record_trade("cond1", "Test", "Yes", "0xbbb", 200.0)
        assert signal.trader_count == 2
        assert signal.is_confluence is True
        assert signal.total_usdc == 300.0

    def test_same_trader_no_duplicate(self) -> None:
        det = ConfluenceDetector()
        det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        signal = det.record_trade("cond1", "Test", "Yes", "0xaaa", 50.0)
        assert signal.trader_count == 1
        assert signal.total_usdc == 150.0

    def test_tier_s_weighted_higher(self) -> None:
        det = ConfluenceDetector()
        # JaJackson is Tier S (weight 3)
        signal = det.record_trade(
            "cond1", "Test", "Yes",
            "0xf195721ad850377c96cd634457c70cd9e8308057", 1000.0
        )
        assert signal.weighted_score == 3

    def test_tier_a_weight(self) -> None:
        det = ConfluenceDetector()
        signal = det.record_trade(
            "cond1", "Test", "Yes",
            "0xead152b855effa6b5b5837f53b24c0756830c76a", 50.0
        )
        assert signal.weighted_score == 1

    def test_strength_levels(self) -> None:
        det = ConfluenceDetector()
        # Two Tier S = 6 → STRONG
        det.record_trade(
            "cond1", "Test", "Yes",
            "0xf195721ad850377c96cd634457c70cd9e8308057", 100.0
        )
        signal = det.record_trade(
            "cond1", "Test", "Yes",
            "0xa8e089ade142c95538e06196e09c85681112ad50", 100.0
        )
        assert signal.strength == "STRONG"

    def test_moderate_strength(self) -> None:
        det = ConfluenceDetector()
        # One Tier S (3) + one Tier A (1) = 4 → MODERATE
        det.record_trade(
            "cond1", "Test", "Yes",
            "0xf195721ad850377c96cd634457c70cd9e8308057", 100.0
        )
        signal = det.record_trade(
            "cond1", "Test", "Yes",
            "0xead152b855effa6b5b5837f53b24c0756830c76a", 50.0
        )
        assert signal.strength == "MODERATE"

    def test_get_active_confluences(self) -> None:
        det = ConfluenceDetector()
        det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        det.record_trade("cond1", "Test", "Yes", "0xbbb", 200.0)
        det.record_trade("cond2", "Test2", "No", "0xccc", 50.0)

        confluences = det.get_active_confluences()
        assert len(confluences) == 1
        assert confluences[0].condition_id == "cond1"

    def test_cleanup_stale(self) -> None:
        det = ConfluenceDetector(window_seconds=1)
        det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        det._signals[("cond1", "Yes")].last_seen = int(time.time()) - 10
        removed = det.cleanup_stale()
        assert removed == 1
        assert len(det.get_active_confluences()) == 0

    def test_different_outcomes_separate_signals(self) -> None:
        det = ConfluenceDetector()
        det.record_trade("cond1", "Test", "Yes", "0xaaa", 100.0)
        det.record_trade("cond1", "Test", "No", "0xbbb", 100.0)
        assert len(det.get_active_confluences()) == 0  # Different outcomes
