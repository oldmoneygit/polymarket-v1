"""Unit tests for src/strategy/kelly.py."""

from __future__ import annotations

import pytest

from src.strategy.kelly import (
    estimate_win_prob_from_trader,
    fractional_kelly,
    kelly_fraction,
)


class TestKellyFraction:
    def test_positive_edge(self) -> None:
        f = kelly_fraction(0.60, 1.0)
        assert f == pytest.approx(0.20)

    def test_no_edge(self) -> None:
        f = kelly_fraction(0.50, 1.0)
        assert f == pytest.approx(0.0)

    def test_negative_edge(self) -> None:
        f = kelly_fraction(0.40, 1.0)
        assert f < 0

    def test_high_odds(self) -> None:
        odds = 0.40 / 0.60
        f = kelly_fraction(0.94, odds)
        assert f > 0.5

    def test_edge_cases(self) -> None:
        assert kelly_fraction(0.0, 1.0) == 0.0
        assert kelly_fraction(1.0, 1.0) == 0.0
        assert kelly_fraction(0.5, 0.0) == 0.0


class TestFractionalKelly:
    def test_quarter_kelly(self) -> None:
        size = fractional_kelly(
            win_prob=0.70, price=0.52, bankroll=500, fraction=0.25
        )
        assert size > 0
        assert size <= 50.0

    def test_negative_edge_returns_zero(self) -> None:
        size = fractional_kelly(win_prob=0.30, price=0.52, bankroll=500)
        assert size == 0.0

    def test_respects_min_bet(self) -> None:
        size = fractional_kelly(
            win_prob=0.51, price=0.50, bankroll=10,
            fraction=0.25, min_bet=2.0,
        )
        assert size >= 2.0

    def test_respects_max_bet(self) -> None:
        size = fractional_kelly(
            win_prob=0.90, price=0.50, bankroll=10000,
            fraction=0.25, max_bet=25.0,
        )
        assert size <= 25.0

    def test_invalid_price(self) -> None:
        assert fractional_kelly(0.5, 0.0, 500) == 0.0
        assert fractional_kelly(0.5, 1.0, 500) == 0.0


class TestEstimateWinProb:
    def test_blends_trader_and_market(self) -> None:
        prob = estimate_win_prob_from_trader(
            trader_win_rate=0.70, market_price=0.50, confidence_weight=0.6
        )
        expected = 0.70 * 0.6 + 0.50 * 0.4
        assert prob == pytest.approx(expected)

    def test_full_trader_confidence(self) -> None:
        prob = estimate_win_prob_from_trader(0.80, 0.50, 1.0)
        assert prob == pytest.approx(0.80)

    def test_full_market_confidence(self) -> None:
        prob = estimate_win_prob_from_trader(0.80, 0.50, 0.0)
        assert prob == pytest.approx(0.50)
