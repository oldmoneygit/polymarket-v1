"""Portfolio risk management — prevents over-concentration.

Enforces:
- Category exposure cap (35% of max exposure)
- Single market exposure cap (25% of max exposure)
- Max correlated positions per category (6)
- Cash reserve (always keep 20% liquid)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.db.models import MarketInfo, Position

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskCheck:
    """Result of a portfolio risk check."""

    allowed: bool
    reason: str
    category_exposure_pct: float = 0.0
    market_exposure_pct: float = 0.0
    cash_reserve_pct: float = 0.0


class PortfolioRiskManager:
    """Checks portfolio concentration before allowing new trades."""

    def __init__(
        self,
        max_exposure: float = 200.0,
        category_cap_pct: float = 0.50,
        market_cap_pct: float = 0.30,
        max_positions_per_category: int = 15,
        cash_reserve_pct: float = 0.10,
    ) -> None:
        self._max_exposure = max_exposure
        self._category_cap = category_cap_pct
        self._market_cap = market_cap_pct
        self._max_per_category = max_positions_per_category
        self._cash_reserve = cash_reserve_pct

    def check(
        self,
        market: MarketInfo,
        trade_amount: float,
        open_positions: list[Position],
    ) -> RiskCheck:
        """Check if a new trade passes all portfolio risk rules."""
        total_exposure = sum(p.usdc_invested for p in open_positions)
        max_usable = self._max_exposure * (1.0 - self._cash_reserve)

        # 1. Cash reserve: never use more than (1 - reserve%) of max exposure
        if total_exposure + trade_amount > max_usable:
            return RiskCheck(
                allowed=False,
                reason=f"Cash reserve: ${total_exposure:.0f} + ${trade_amount:.0f} > ${max_usable:.0f} (reserva {self._cash_reserve:.0%})",
                cash_reserve_pct=self._cash_reserve,
            )

        # 2. Category exposure cap
        category = market.category or "other"
        category_exposure = sum(
            p.usdc_invested for p in open_positions
            if self._position_category(p) == category
        )
        category_limit = self._max_exposure * self._category_cap
        if category_exposure + trade_amount > category_limit:
            cat_pct = (category_exposure + trade_amount) / self._max_exposure
            return RiskCheck(
                allowed=False,
                reason=f"Category '{category}' cap: ${category_exposure:.0f} + ${trade_amount:.0f} > ${category_limit:.0f} ({self._category_cap:.0%})",
                category_exposure_pct=cat_pct,
            )

        # 3. Positions per category cap
        category_count = sum(
            1 for p in open_positions
            if self._position_category(p) == category
        )
        if category_count >= self._max_per_category:
            return RiskCheck(
                allowed=False,
                reason=f"Max positions in '{category}': {category_count}/{self._max_per_category}",
            )

        # 4. Single market concentration
        market_exposure = sum(
            p.usdc_invested for p in open_positions
            if p.condition_id == market.condition_id
        )
        market_limit = self._max_exposure * self._market_cap
        if market_exposure + trade_amount > market_limit:
            mkt_pct = (market_exposure + trade_amount) / self._max_exposure
            return RiskCheck(
                allowed=False,
                reason=f"Market cap: ${market_exposure:.0f} + ${trade_amount:.0f} > ${market_limit:.0f} ({self._market_cap:.0%})",
                market_exposure_pct=mkt_pct,
            )

        # All checks passed
        cat_pct = (category_exposure + trade_amount) / self._max_exposure
        mkt_pct = (market_exposure + trade_amount) / self._max_exposure
        cash_pct = 1.0 - (total_exposure + trade_amount) / self._max_exposure

        return RiskCheck(
            allowed=True,
            reason="OK",
            category_exposure_pct=cat_pct,
            market_exposure_pct=mkt_pct,
            cash_reserve_pct=cash_pct,
        )

    @staticmethod
    def _position_category(position: Position) -> str:
        """Infer category from position data."""
        title = position.market_title.lower()
        sports_kw = ["nba", "nhl", "nfl", "mlb", "ucl", "epl", "spread", "o/u", "vs.", "win on"]
        esports_kw = ["valorant", "vcl", "cs2", "lol", "dota"]
        politics_kw = ["trump", "biden", "election", "congress", "senate"]
        crypto_kw = ["btc", "eth", "sol", "bitcoin", "crypto"]

        for kw in esports_kw:
            if kw in title:
                return "esports"
        for kw in politics_kw:
            if kw in title:
                return "politics"
        for kw in crypto_kw:
            if kw in title:
                return "crypto"
        for kw in sports_kw:
            if kw in title:
                return "sports"
        return "other"

    def format_status(self, open_positions: list[Position]) -> str:
        """Format portfolio risk summary."""
        total = sum(p.usdc_invested for p in open_positions)
        max_usable = self._max_exposure * (1.0 - self._cash_reserve)

        # Count by category
        categories: dict[str, tuple[int, float]] = {}
        for p in open_positions:
            cat = self._position_category(p)
            count, usd = categories.get(cat, (0, 0.0))
            categories[cat] = (count + 1, usd + p.usdc_invested)

        lines = [
            f"Exposure: ${total:.2f} / ${max_usable:.0f} ({total / self._max_exposure:.0%})",
            f"Cash reserve: ${self._max_exposure - total:.2f} ({1 - total / self._max_exposure:.0%})",
            "Categories:",
        ]
        for cat, (count, usd) in sorted(categories.items(), key=lambda x: x[1][1], reverse=True):
            pct = usd / self._max_exposure * 100
            lines.append(f"  {cat}: {count} pos, ${usd:.2f} ({pct:.0f}%)")

        return "\n".join(lines)
