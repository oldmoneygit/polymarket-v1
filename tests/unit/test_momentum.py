"""Unit tests for src/strategy/momentum.py."""

from __future__ import annotations

import time
from unittest.mock import patch

from src.strategy.momentum import MomentumDetector


class TestMomentumDetector:
    def test_no_signal_on_first_record(self) -> None:
        det = MomentumDetector()
        signal = det.record_price("cond1", 0.50, "Test?")
        assert signal is None

    def test_no_signal_on_small_change(self) -> None:
        det = MomentumDetector(min_change_pct=0.10)
        det.record_price("cond1", 0.50, "Test?")
        signal = det.record_price("cond1", 0.52, "Test?")
        assert signal is None

    def test_detects_upward_momentum(self) -> None:
        det = MomentumDetector(min_change_pct=0.10)
        now = int(time.time())
        det._price_history["cond1"] = [(now - 600, 0.50)]
        signal = det.record_price("cond1", 0.60, "Team A wins?", "nba-test")
        assert signal is not None
        assert signal.direction == "UP"
        assert signal.change_pct > 0.10

    def test_detects_downward_momentum(self) -> None:
        det = MomentumDetector(min_change_pct=0.10)
        now = int(time.time())
        det._price_history["cond1"] = [(now - 600, 0.60)]
        signal = det.record_price("cond1", 0.45, "Team A wins?", "nba-test")
        assert signal is not None
        assert signal.direction == "DOWN"

    def test_trims_old_entries(self) -> None:
        det = MomentumDetector(window_minutes=5)
        now = int(time.time())
        det._price_history["cond1"] = [
            (now - 600, 0.50),
            (now - 120, 0.52),
        ]
        det.record_price("cond1", 0.53, "Test?")
        assert len(det._price_history["cond1"]) == 2

    def test_cleanup_stale(self) -> None:
        det = MomentumDetector(window_minutes=5)
        now = int(time.time())
        det._price_history["old"] = [(now - 3600, 0.50)]
        det._price_history["recent"] = [(now, 0.60)]
        removed = det.cleanup_stale()
        assert removed == 1
        assert "recent" in det._price_history
        assert "old" not in det._price_history

    def test_zero_price_no_crash(self) -> None:
        det = MomentumDetector()
        now = int(time.time())
        det._price_history["cond1"] = [(now - 60, 0.0)]
        signal = det.record_price("cond1", 0.50, "Test?")
        assert signal is None
