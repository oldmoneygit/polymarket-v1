"""Trade quality filter — pure logic, no I/O."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from src.config import Config
from src.db.models import FilterResult, MarketInfo, TraderTrade


class TradeFilter:
    """Evaluates whether a detected trade should be copied."""

    def evaluate(
        self,
        trade: TraderTrade,
        market: MarketInfo,
        config: Config,
        current_exposure: float = 0.0,
        now_ts: int | None = None,
    ) -> FilterResult:
        """Run all quality checks in order. Returns on first failure."""
        now = now_ts if now_ts is not None else int(time.time())

        # 1. Sports market
        if market.category != "sports":
            return FilterResult(passed=False, reason="Mercado não é esportivo")

        # 2. Market still open
        if market.is_resolved:
            return FilterResult(passed=False, reason="Mercado já resolvido")

        end_ts = int(market.end_date.timestamp())
        if end_ts < now:
            return FilterResult(passed=False, reason="Mercado expirado")

        # 3. Minimum volume
        if market.volume < config.min_market_volume_usd:
            return FilterResult(
                passed=False,
                reason=(
                    f"Volume ${market.volume:.0f} abaixo do mínimo "
                    f"${config.min_market_volume_usd:.0f}"
                ),
            )

        # 4. Price / probability in range
        price = trade.price
        if price < config.min_probability or price > config.max_probability:
            return FilterResult(
                passed=False,
                reason=(
                    f"Preço {price:.0%} fora do range "
                    f"{config.min_probability:.0%}-{config.max_probability:.0%}"
                ),
            )

        # 5. Trade recency
        age_minutes = (now - trade.timestamp) / 60
        if age_minutes > config.max_trade_age_minutes:
            return FilterResult(
                passed=False,
                reason=(
                    f"Trade com {age_minutes:.0f}min, "
                    f"limite é {config.max_trade_age_minutes}min"
                ),
            )

        # 6. Only BUY (v1)
        if trade.side != "BUY":
            return FilterResult(
                passed=False,
                reason="Apenas trades de compra são copiados",
            )

        # 7. Exposure headroom
        if current_exposure + config.capital_per_trade_usd > config.max_total_exposure_usd:
            return FilterResult(
                passed=False, reason="Exposição máxima atingida"
            )

        return FilterResult(passed=True, reason="OK")
