"""Polymarket Data API and Gamma API client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.api.rate_limiter import PolymarketRateLimiter
from src.db.models import MarketInfo, TraderTrade

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_RETRIES = 3
RETRY_BACKOFFS = [1, 2, 4]  # seconds

# Slug prefixes from Gamma API — these are definitive sport identifiers
SPORTS_SLUG_PREFIXES: list[str] = [
    "nba-", "nhl-", "nfl-", "mlb-", "mls-",
    "cbb-",  # College basketball (NCAA)
    "ucl-", "epl-", "fl1-", "bun-",  # European football
    "bra-", "bra2-", "col1-", "mex-",  # Latin American football
    "den-", "j2-", "kor-",  # Other football leagues
    "atp-", "wta-",  # Tennis
    "cs2-", "lol-", "dota2-", "val-",  # Esports
]

SPORTS_KEYWORDS: list[str] = [
    # Football / Soccer
    "soccer", "football", "mls", "ucl", "epl", "laliga",
    "bundesliga", "seriea", "ligue1", "premier", "champions",
    "copa", "world-cup", "fifa", "europa-league",
    # Basketball
    "nba", "ncaa", "ncaab", "march-madness",
    # Hockey
    "nhl",
    # American Football / Baseball
    "nfl", "mlb",
    # Other sports
    "tennis", "atp", "wta", "formula1", "f1", "golf", "ufc",
    # Generic patterns
    "win-on", "beat", "spread", "o/u", "moneyline", "vs.",
]


class APIError(Exception):
    """Raised on non-recoverable API errors."""


def _detect_category(slug: str, event_slug: str, extra: str = "") -> str:
    """Classify a market based on slug prefixes and keywords."""
    slug_lower = slug.lower()
    for prefix in SPORTS_SLUG_PREFIXES:
        if slug_lower.startswith(prefix):
            return "sports"

    combined = f"{slug} {event_slug} {extra}".lower()
    for kw in SPORTS_KEYWORDS:
        if kw in combined:
            return "sports"
    return "other"


class PolymarketClient:
    """Async client for Polymarket Data API and Gamma API."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._external_session = session is not None
        self._session = session
        self._rate_limiter = PolymarketRateLimiter()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._external_session:
            await self._session.close()

    async def _get_with_retry(self, url: str, params: dict[str, Any] | None = None) -> Any:
        await self._rate_limiter.acquire_get()
        session = await self._get_session()
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status >= 500:
                        last_error = APIError(f"HTTP {resp.status} from {url}")
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFFS[attempt])
                            continue
                        raise last_error
                    if resp.status >= 400:
                        text = await resp.text()
                        raise APIError(f"HTTP {resp.status} from {url}: {text}")
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = APIError(f"Network error on {url}: {exc}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFFS[attempt])
                    continue
                raise last_error from exc
        raise last_error or APIError("Unexpected retry exhaustion")  # pragma: no cover

    # ── Public API ───────────────────────────────────────────────

    async def get_trader_activity(
        self, wallet: str, limit: int = 50
    ) -> list[TraderTrade]:
        """Fetch recent trade activity for a wallet from the Data API."""
        data = await self._get_with_retry(
            f"{DATA_API_BASE}/activity",
            params={"user": wallet, "type": "TRADE", "limit": str(limit)},
        )
        if not isinstance(data, list):
            data = data.get("data", data.get("history", []))
        return [self._parse_trade(item, wallet) for item in data if isinstance(item, dict)]

    async def get_market_info(self, condition_id: str) -> MarketInfo | None:
        """Fetch market details from the Gamma API."""
        data = await self._get_with_retry(
            f"{GAMMA_API_BASE}/markets",
            params={"condition_ids": condition_id},
        )
        markets = data if isinstance(data, list) else []
        if not markets:
            return None
        return self._parse_market(markets[0])

    # ── Parsing ──────────────────────────────────────────────────

    @staticmethod
    def _parse_trade(raw: dict[str, Any], wallet: str) -> TraderTrade:
        slug = raw.get("slug", raw.get("market_slug", ""))
        event_slug = raw.get("event_slug", raw.get("eventSlug", ""))
        return TraderTrade(
            proxy_wallet=wallet,
            timestamp=int(raw.get("timestamp", 0)),
            condition_id=raw.get("conditionId", raw.get("condition_id", "")),
            transaction_hash=raw.get("transactionHash", raw.get("transaction_hash", "")),
            price=float(raw.get("price", 0)),
            size=float(raw.get("size", 0)),
            usdc_size=float(raw.get("usdcSize", raw.get("usdc_size", 0))),
            side=raw.get("side", "BUY").upper(),
            outcome=raw.get("outcome", raw.get("outcomeIndex", "Yes")),
            title=raw.get("title", raw.get("question", "")),
            slug=slug,
            event_slug=event_slug,
            trader_name=raw.get("name", raw.get("username", "")),
            token_id=raw.get("asset", raw.get("tokenId", raw.get("token_id", ""))),
        )

    @staticmethod
    def _parse_market(raw: dict[str, Any]) -> MarketInfo:
        slug = raw.get("slug", raw.get("market_slug", ""))
        event_slug = raw.get("event_slug", raw.get("eventSlug", ""))
        category = raw.get("category", "")
        group_title = raw.get("groupItemTitle", raw.get("group_item_title", ""))
        question = raw.get("question", raw.get("title", ""))
        sports_market_type = raw.get("sportsMarketType", "")
        if sports_market_type:
            category = "sports"
        elif not category or category == "unknown":
            category = _detect_category(slug, event_slug, f"{group_title} {question}")

        end_date_raw = raw.get("endDate", raw.get("end_date_iso", ""))
        if end_date_raw:
            try:
                end_date = datetime.fromisoformat(end_date_raw.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                end_date = datetime(2099, 1, 1, tzinfo=timezone.utc)
        else:
            end_date = datetime(2099, 1, 1, tzinfo=timezone.utc)

        # Parse outcomePrices
        outcome_prices = raw.get("outcomePrices", None)
        if isinstance(outcome_prices, str):
            import json
            try:
                prices = json.loads(outcome_prices)
                yes_price = float(prices[0]) if prices else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 1.0 - yes_price
            except (json.JSONDecodeError, IndexError):
                yes_price = float(raw.get("yes_price", 0.5))
                no_price = float(raw.get("no_price", 0.5))
        elif isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        else:
            yes_price = float(raw.get("yes_price", raw.get("bestAsk", 0.5)))
            no_price = float(raw.get("no_price", 1.0 - yes_price))

        resolved_outcome = ""
        if raw.get("resolved", raw.get("is_resolved", False)):
            resolved_outcome = raw.get("resolution", raw.get("resolved_outcome", ""))

        return MarketInfo(
            condition_id=raw.get("conditionId", raw.get("condition_id", "")),
            question=raw.get("question", raw.get("title", "")),
            category=category,
            volume=float(raw.get("volume", raw.get("volumeNum", 0))),
            liquidity=float(raw.get("liquidity", raw.get("liquidityNum", 0))),
            end_date=end_date,
            is_resolved=bool(raw.get("resolved", raw.get("is_resolved", False))),
            yes_price=yes_price,
            no_price=no_price,
            slug=slug,
            resolved_outcome=resolved_outcome,
        )
