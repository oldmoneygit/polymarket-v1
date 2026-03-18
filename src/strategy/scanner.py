"""High-probability market scanner — finds near-certain markets about to resolve.

# [MERGED FROM polymarket-v1] New module — Wannac strategy scanner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.db.models import MarketInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannerSignal:
    """A high-probability opportunity detected by the scanner."""

    condition_id: str
    question: str
    side: str  # "Yes" or "No" — whichever is high-prob
    probability: float  # The high-prob side's price
    volume: float
    hours_to_resolution: float
    expected_return_pct: float  # (1 - price) / price
    slug: str


class HighProbScanner:
    """Scans active sports markets for high-probability opportunities.

    Implements the 'Wannac strategy' — buy high-probability outcomes
    (>85%) near resolution for small but consistent returns.
    """

    def __init__(
        self,
        min_probability: float = 0.85,
        max_hours_to_resolution: float = 48.0,
        min_volume: float = 5000.0,
    ) -> None:
        self._min_prob = min_probability
        self._max_hours = max_hours_to_resolution
        self._min_volume = min_volume

    def evaluate(self, market: MarketInfo) -> ScannerSignal | None:
        """Check if a market qualifies as a high-probability opportunity."""
        if market.is_resolved:
            return None

        if market.category != "sports":
            return None

        if market.volume < self._min_volume:
            return None

        now = datetime.now(timezone.utc)
        hours_left = (market.end_date - now).total_seconds() / 3600
        if hours_left <= 0 or hours_left > self._max_hours:
            return None

        # Determine which side is high probability
        if market.yes_price >= self._min_prob:
            side = "Yes"
            prob = market.yes_price
        elif market.no_price >= self._min_prob:
            side = "No"
            prob = market.no_price
        else:
            return None

        expected_return = (1.0 - prob) / prob if prob > 0 else 0.0

        return ScannerSignal(
            condition_id=market.condition_id,
            question=market.question,
            side=side,
            probability=prob,
            volume=market.volume,
            hours_to_resolution=hours_left,
            expected_return_pct=expected_return,
            slug=market.slug,
        )
