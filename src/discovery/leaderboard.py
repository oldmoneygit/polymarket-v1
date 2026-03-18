"""Leaderboard scanner — discovers profitable wallets to copy trade.

Scrapes the Polymarket leaderboard and evaluates traders based on:
- Win rate (> 60%)
- Profit rate (> 2%)
- Gain/Loss ratio (> 2)
- Trade count (> 100)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"


def _format_pnl(value: float) -> str:
    if value >= 0:
        return f"+${value:.2f}"
    return f"-${abs(value):.2f}"


@dataclass(frozen=True)
class TraderProfile:
    """Profile of a potential trader to copy."""

    address: str
    username: str
    profit_loss: float  # Total P&L in USDC
    volume: float  # Total volume traded
    positions_count: int
    markets_traded: int
    profit_rate: float  # profit / volume
    gain: float
    loss: float
    gain_loss_ratio: float
    score: float  # Computed quality score

    @property
    def is_copyable(self) -> bool:
        """Meets minimum criteria for copy trading."""
        return (
            self.profit_rate >= 0.02
            and self.gain_loss_ratio >= 2.0
            and self.positions_count >= 100
            and self.profit_loss > 0
        )


class LeaderboardScanner:
    """Scans the Polymarket leaderboard for profitable traders."""

    def __init__(
        self,
        min_profit_rate: float = 0.02,
        min_gain_loss_ratio: float = 2.0,
        min_positions: int = 100,
    ) -> None:
        self._min_profit_rate = min_profit_rate
        self._min_gl_ratio = min_gain_loss_ratio
        self._min_positions = min_positions

    async def scan(
        self,
        period: str = "all",
        limit: int = 50,
    ) -> list[TraderProfile]:
        """Fetch leaderboard and return ranked, filtered traders.

        Args:
            period: "daily", "weekly", "monthly", "all"
            limit: Number of leaderboard entries to fetch
        """
        raw_traders = await self._fetch_leaderboard(period, limit)
        profiles = [self._parse_profile(t) for t in raw_traders]
        profiles = [p for p in profiles if p is not None]

        # Filter by criteria
        copyable = [p for p in profiles if p.is_copyable]

        # Sort by score descending
        copyable.sort(key=lambda p: p.score, reverse=True)

        logger.info(
            "Leaderboard scan: %d fetched, %d profiles, %d copyable",
            len(raw_traders), len(profiles), len(copyable),
        )

        return copyable

    async def get_trader_stats(self, address: str) -> TraderProfile | None:
        """Fetch detailed stats for a single trader address."""
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(
                    f"{DATA_API_BASE}/profile",
                    params={"user": address},
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return self._parse_profile(data)
            except Exception:
                logger.debug("Failed to fetch stats for %s", address[:10])
                return None

    async def _fetch_leaderboard(
        self, period: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch the leaderboard from Polymarket Data API."""
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Try the leaderboard endpoint
                async with session.get(
                    f"{DATA_API_BASE}/leaderboard",
                    params={
                        "period": period,
                        "limit": str(limit),
                        "sortBy": "pnl",
                        "sortDirection": "DESC",
                    },
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Leaderboard API returned %d", resp.status)
                        return []
                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    return data.get("data", data.get("leaderboard", []))
            except Exception:
                logger.exception("Failed to fetch leaderboard")
                return []

    def _parse_profile(self, raw: dict[str, Any]) -> TraderProfile | None:
        """Parse raw API data into a TraderProfile."""
        try:
            address = raw.get("proxyWallet", raw.get("address", raw.get("user", "")))
            if not address:
                return None

            username = raw.get("username", raw.get("name", ""))
            profit_loss = float(raw.get("pnl", raw.get("profit_loss", 0)))
            volume = float(raw.get("volume", raw.get("totalVolume", 0)))
            positions_count = int(raw.get("positionsCount", raw.get("positions_count", raw.get("numTrades", 0))))
            markets_traded = int(raw.get("marketsTraded", raw.get("markets_traded", 0)))
            gain = float(raw.get("gain", raw.get("totalGain", 0)))
            loss = abs(float(raw.get("loss", raw.get("totalLoss", 0))))

            profit_rate = profit_loss / volume if volume > 0 else 0.0
            gain_loss_ratio = gain / loss if loss > 0 else (10.0 if gain > 0 else 0.0)

            # Quality score: weighted combination
            score = (
                profit_rate * 30
                + min(gain_loss_ratio, 10) * 20
                + min(positions_count / 500, 1.0) * 20
                + min(profit_loss / 10000, 1.0) * 30
            )

            return TraderProfile(
                address=address.lower(),
                username=username,
                profit_loss=profit_loss,
                volume=volume,
                positions_count=positions_count,
                markets_traded=markets_traded,
                profit_rate=profit_rate,
                gain=gain,
                loss=loss,
                gain_loss_ratio=gain_loss_ratio,
                score=score,
            )
        except (ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def format_discovery_message(profiles: list[TraderProfile], top_n: int = 5) -> str:
        """Format discovered traders for Telegram notification."""
        if not profiles:
            return "Nenhum trader encontrado com os criterios minimos."

        lines = ["\U0001f50e Traders descobertos:\n"]
        for i, p in enumerate(profiles[:top_n], 1):
            lines.append(
                f"{i}. {p.username or p.address[:10]}\n"
                f"   PnL: {_format_pnl(p.profit_loss)} | "
                f"G/L: {p.gain_loss_ratio:.1f} | "
                f"Trades: {p.positions_count}\n"
                f"   <code>{p.address}</code>"
            )
        lines.append(f"\nUse /copy 0x... para adicionar.")
        return "\n".join(lines)
