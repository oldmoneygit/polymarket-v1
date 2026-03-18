"""Probability calibrator — corrects systematic bias in predictions.

Uses Platt Scaling (logistic compression) + historical feedback.
Requires minimum 30 resolved predictions to activate.

Pipeline:
  raw_prob → extremity_shrinkage → low_evidence_penalty
           → contradiction_penalty → ensemble_spread_penalty
           → historical_calibration (if enough data)
           → final_calibrated_prob

Inspired by Dylan's calibrator.py.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationResult:
    """Result of calibrating a probability estimate."""

    raw_prob: float
    calibrated_prob: float
    adjustments: dict[str, float]
    brier_score: float  # Historical accuracy (lower = better)
    sample_count: int  # How many resolved predictions we have


def _logit(p: float) -> float:
    """Log-odds transform."""
    p = max(0.001, min(0.999, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Inverse logit."""
    return 1.0 / (1.0 + math.exp(-x))


class Calibrator:
    """Calibrates probability estimates using Platt scaling + heuristics."""

    def __init__(
        self,
        shrinkage: float = 0.90,
        min_samples: int = 30,
    ) -> None:
        self._shrinkage = shrinkage
        self._min_samples = min_samples
        # Historical calibration data (populated from DB)
        self._historical_bias: float = 0.0  # Positive = overconfident
        self._brier_score: float = 0.0
        self._sample_count: int = 0

    def load_from_stats(self, stats: dict) -> None:
        """Load calibration data from prediction stats."""
        self._sample_count = stats.get("count", 0)
        self._brier_score = stats.get("brier_score", 0.0)
        # Estimate bias from Brier score (rough heuristic)
        # Perfect calibration = Brier ~0.25 for binary outcomes
        if self._sample_count >= self._min_samples:
            self._historical_bias = max(0, self._brier_score - 0.25) * 0.5

    def calibrate(
        self,
        raw_prob: float,
        evidence_quality: float = 0.7,
        contradiction_count: int = 0,
        ensemble_spread: float = 0.0,
    ) -> CalibrationResult:
        """Apply calibration pipeline to a raw probability estimate.

        Args:
            raw_prob: Raw probability estimate (0-1).
            evidence_quality: Quality of evidence (0-1, 1=high quality).
            contradiction_count: Number of contradicting signals.
            ensemble_spread: Spread between multiple model estimates.
        """
        adjustments: dict[str, float] = {}
        p = raw_prob

        # 1. Extremity shrinkage — pull extreme probabilities toward 0.5
        logit_raw = _logit(p)
        p = _sigmoid(logit_raw * self._shrinkage)
        adjustments["extremity_shrinkage"] = p - raw_prob

        # 2. Low evidence penalty — if evidence is weak, pull toward 0.50
        if evidence_quality < 0.4:
            penalty = (0.50 - p) * (0.4 - evidence_quality) * 2
            p += penalty
            adjustments["low_evidence"] = penalty
        else:
            adjustments["low_evidence"] = 0.0

        # 3. Contradiction penalty — each contradiction pulls toward 0.50
        if contradiction_count > 0:
            per_contradiction = 0.10
            total_penalty = min(contradiction_count * per_contradiction, 0.30)
            p = p + (0.50 - p) * total_penalty
            adjustments["contradictions"] = (0.50 - raw_prob) * total_penalty
        else:
            adjustments["contradictions"] = 0.0

        # 4. Ensemble spread penalty — high disagreement = low confidence
        if ensemble_spread > 0.10:
            spread_penalty = min((ensemble_spread - 0.10) * 2, 0.30)
            p = p + (0.50 - p) * spread_penalty
            adjustments["ensemble_spread"] = (0.50 - raw_prob) * spread_penalty
        else:
            adjustments["ensemble_spread"] = 0.0

        # 5. Historical calibration — if we have enough data
        if self._sample_count >= self._min_samples and self._historical_bias > 0:
            bias_correction = -self._historical_bias * (p - 0.50)
            p += bias_correction
            adjustments["historical_bias"] = bias_correction
        else:
            adjustments["historical_bias"] = 0.0

        # Clamp to valid range
        p = max(0.02, min(0.98, p))

        return CalibrationResult(
            raw_prob=raw_prob,
            calibrated_prob=round(p, 4),
            adjustments=adjustments,
            brier_score=self._brier_score,
            sample_count=self._sample_count,
        )

    def format_status(self) -> str:
        return (
            f"Calibrator: {self._sample_count} samples\n"
            f"Brier score: {self._brier_score:.4f}\n"
            f"Historical bias: {self._historical_bias:.4f}\n"
            f"Active: {'Yes' if self._sample_count >= self._min_samples else 'No (need more data)'}"
        )
