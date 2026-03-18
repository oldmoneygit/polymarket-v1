"""Unit tests for Sprint 4 — Calibrator, Prediction Tracker."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db.repository import Repository
from src.policy.calibrator import Calibrator


# ── Calibrator ────────────────────────────────────────────────


class TestCalibrator:
    def test_extremity_shrinkage(self) -> None:
        cal = Calibrator()
        result = cal.calibrate(raw_prob=0.95)
        # Should be pulled toward 0.5
        assert result.calibrated_prob < 0.95
        assert result.calibrated_prob > 0.80

    def test_low_evidence_pulls_to_center(self) -> None:
        cal = Calibrator()
        result = cal.calibrate(raw_prob=0.80, evidence_quality=0.2)
        assert result.calibrated_prob < 0.80
        assert result.adjustments["low_evidence"] != 0.0

    def test_high_evidence_no_penalty(self) -> None:
        cal = Calibrator()
        result = cal.calibrate(raw_prob=0.70, evidence_quality=0.9)
        assert result.adjustments["low_evidence"] == 0.0

    def test_contradictions_reduce_confidence(self) -> None:
        cal = Calibrator()
        r_clean = cal.calibrate(raw_prob=0.75, contradiction_count=0)
        r_contradicted = cal.calibrate(raw_prob=0.75, contradiction_count=3)
        # With contradictions, prob should be closer to 0.50
        assert abs(r_contradicted.calibrated_prob - 0.50) < abs(r_clean.calibrated_prob - 0.50)

    def test_ensemble_spread_reduces_confidence(self) -> None:
        cal = Calibrator()
        r_tight = cal.calibrate(raw_prob=0.70, ensemble_spread=0.05)
        r_wide = cal.calibrate(raw_prob=0.70, ensemble_spread=0.25)
        assert abs(r_wide.calibrated_prob - 0.50) < abs(r_tight.calibrated_prob - 0.50)

    def test_historical_bias_correction(self) -> None:
        cal = Calibrator(min_samples=5)
        cal.load_from_stats({"count": 50, "brier_score": 0.35})
        result = cal.calibrate(raw_prob=0.70)
        assert result.adjustments["historical_bias"] != 0.0
        assert result.sample_count == 50

    def test_no_historical_correction_without_data(self) -> None:
        cal = Calibrator(min_samples=30)
        result = cal.calibrate(raw_prob=0.70)
        assert result.adjustments["historical_bias"] == 0.0
        assert result.sample_count == 0

    def test_clamped_to_valid_range(self) -> None:
        cal = Calibrator()
        r_high = cal.calibrate(raw_prob=0.999)
        r_low = cal.calibrate(raw_prob=0.001)
        assert 0.02 <= r_high.calibrated_prob <= 0.98
        assert 0.02 <= r_low.calibrated_prob <= 0.98

    def test_format_status(self) -> None:
        cal = Calibrator()
        text = cal.format_status()
        assert "Calibrator" in text
        assert "Brier" in text


# ── Prediction Tracker (Repository) ──────────────────────────


class TestPredictionTracker:
    def test_save_and_resolve_prediction(self, tmp_db: Repository) -> None:
        pid = tmp_db.save_prediction(
            condition_id="c1",
            market_title="Test Market",
            predicted_prob=0.65,
            market_price=0.50,
            edge=0.15,
        )
        assert pid > 0

        # Resolve it
        tmp_db.resolve_prediction("c1", "Yes")

        resolved = tmp_db.get_resolved_predictions(10)
        assert len(resolved) == 1
        assert resolved[0]["outcome_actual"] == "Yes"
        assert resolved[0]["predicted_prob"] == 0.65

    def test_prediction_stats(self, tmp_db: Repository) -> None:
        # Save 3 predictions
        for i, (prob, outcome) in enumerate([
            (0.70, "Yes"),
            (0.60, "No"),
            (0.80, "Yes"),
        ]):
            tmp_db.save_prediction(f"c{i}", f"Market {i}", prob, 0.50, prob - 0.50)
            tmp_db.resolve_prediction(f"c{i}", outcome)

        stats = tmp_db.get_prediction_stats()
        assert stats["count"] == 3
        assert stats["brier_score"] > 0
        assert "avg_edge" in stats

    def test_unresolved_predictions_not_in_stats(self, tmp_db: Repository) -> None:
        tmp_db.save_prediction("c1", "Open Market", 0.60, 0.50, 0.10)
        # Don't resolve it
        stats = tmp_db.get_prediction_stats()
        assert stats["count"] == 0
