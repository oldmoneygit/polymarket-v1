"""Unit tests for src/strategy/scanner.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.db.models import MarketInfo
from src.strategy.scanner import HighProbScanner


def _make_market(
    yes_price: float = 0.90,
    no_price: float = 0.10,
    volume: float = 10000.0,
    hours_until_end: float = 12.0,
    is_resolved: bool = False,
    category: str = "sports",
) -> MarketInfo:
    end = datetime.now(timezone.utc) + timedelta(hours=hours_until_end)
    return MarketInfo(
        condition_id="0xcond",
        question="Will Team A win?",
        category=category,
        volume=volume,
        liquidity=5000.0,
        end_date=end,
        is_resolved=is_resolved,
        yes_price=yes_price,
        no_price=no_price,
        slug="nba-test",
    )


class TestHighProbScanner:
    def test_detects_high_prob_yes(self) -> None:
        scanner = HighProbScanner(min_probability=0.85)
        signal = scanner.evaluate(_make_market(yes_price=0.92, no_price=0.08))
        assert signal is not None
        assert signal.side == "Yes"
        assert signal.probability == 0.92
        assert signal.expected_return_pct == pytest.approx((1 - 0.92) / 0.92, rel=0.01)

    def test_detects_high_prob_no(self) -> None:
        scanner = HighProbScanner(min_probability=0.85)
        signal = scanner.evaluate(_make_market(yes_price=0.08, no_price=0.92))
        assert signal is not None
        assert signal.side == "No"

    def test_rejects_low_probability(self) -> None:
        scanner = HighProbScanner(min_probability=0.85)
        assert scanner.evaluate(_make_market(yes_price=0.60, no_price=0.40)) is None

    def test_rejects_resolved(self) -> None:
        scanner = HighProbScanner()
        assert scanner.evaluate(_make_market(is_resolved=True)) is None

    def test_rejects_non_sports(self) -> None:
        scanner = HighProbScanner()
        assert scanner.evaluate(_make_market(category="crypto")) is None

    def test_rejects_low_volume(self) -> None:
        scanner = HighProbScanner(min_volume=5000)
        assert scanner.evaluate(_make_market(volume=100)) is None

    def test_rejects_too_far_from_resolution(self) -> None:
        scanner = HighProbScanner(max_hours_to_resolution=24)
        assert scanner.evaluate(_make_market(hours_until_end=100)) is None

    def test_rejects_expired(self) -> None:
        scanner = HighProbScanner()
        assert scanner.evaluate(_make_market(hours_until_end=-1)) is None
