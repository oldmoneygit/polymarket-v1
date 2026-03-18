"""CLOB API client for order execution on Polymarket.

# [MERGED FROM polymarket-v1] Enhanced — adds OrderBookSummary, get_order_book(),
# estimate_slippage(), get_price_history(), create_fak_order(), create_gtd_order(),
# close(), and uses structured PolymarketError.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.config import Config
from src.db.models import OrderResult
from src.errors import ErrorCode, PolymarketError

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"


# Keep backward compat alias
CLOBError = PolymarketError


@dataclass(frozen=True)
class OrderBookSummary:
    """Snapshot of order book state for a token."""

    token_id: str
    best_bid: float
    best_ask: float
    spread: float
    midpoint: float
    bid_depth_usd: float  # Total USD available on bid side
    ask_depth_usd: float  # Total USD available on ask side

    @property
    def spread_pct(self) -> float:
        return self.spread / self.midpoint if self.midpoint > 0 else 0.0

    @property
    def has_liquidity(self) -> bool:
        return self.bid_depth_usd > 0 and self.ask_depth_usd > 0


class CLOBClient:
    """Interface with the Polymarket CLOB for order placement and balance queries."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: object | None = None
        self._http_session: aiohttp.ClientSession | None = None
        # Realistic dry-run balance tracking
        self._simulated_balance: float = config.max_total_exposure_usd
        self._simulated_pnl: float = 0.0
        if not config.dry_run:
            self._init_real_client(config)

    def _init_real_client(self, config: Config) -> None:
        try:
            from py_clob_client.client import ClobClient as RealClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=config.poly_api_key,
                api_secret=config.poly_api_secret,
                api_passphrase=config.poly_api_passphrase,
            )
            self._client = RealClobClient(
                host="https://clob.polymarket.com",
                key=config.poly_private_key,
                chain_id=137,
                creds=creds,
            )
        except ImportError:
            logger.warning(
                "py-clob-client not installed; only dry-run mode is available"
            )

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._http_session

    # -- Order Book -------------------------------------------------------
    # [MERGED FROM polymarket-v1] New method

    async def get_order_book(self, token_id: str) -> OrderBookSummary:
        """Fetch order book and return summary with liquidity info.

        In dry-run, fetches REAL orderbook data from the API for realistic simulation.
        Falls back to synthetic data only if the API call fails.
        """
        session = await self._get_http_session()
        try:
            async with session.get(
                f"{CLOB_BASE}/book", params={"token_id": token_id}
            ) as resp:
                if resp.status != 200:
                    raise PolymarketError.network(
                        f"Order book HTTP {resp.status}"
                    )
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if self._config.dry_run:
                # Fallback for dry-run if API fails
                logger.debug("Order book fetch failed in dry-run, using fallback: %s", exc)
                return OrderBookSummary(
                    token_id=token_id, best_bid=0.49, best_ask=0.51,
                    spread=0.02, midpoint=0.50,
                    bid_depth_usd=500.0, ask_depth_usd=500.0,
                )
            raise PolymarketError.network(f"Order book fetch failed: {exc}") from exc

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0

        bid_depth = sum(float(b["price"]) * float(b["size"]) for b in bids)
        ask_depth = sum(float(a["price"]) * float(a["size"]) for a in asks)

        spread = best_ask - best_bid
        midpoint = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0.0

        return OrderBookSummary(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            midpoint=midpoint,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
        )

    # [MERGED FROM polymarket-v1] New method
    def estimate_slippage(
        self, book: OrderBookSummary, amount_usd: float, side: str = "BUY"
    ) -> float:
        """Estimate price slippage for a given order size.

        Returns slippage as a fraction (0.02 = 2%).
        """
        if side.upper() == "BUY":
            available = book.ask_depth_usd
            ref_price = book.best_ask
        else:
            available = book.bid_depth_usd
            ref_price = book.best_bid

        if available <= 0 or ref_price <= 0:
            return 1.0  # 100% slippage = no liquidity

        # Simple model: slippage proportional to order size vs depth
        if amount_usd <= available * 0.05:
            return 0.0  # Small order, negligible slippage
        return min(amount_usd / available, 1.0)

    # -- Price History ----------------------------------------------------
    # [MERGED FROM polymarket-v1] New method

    async def get_price_history(
        self, token_id: str, interval: str = "1h", fidelity: int = 60
    ) -> list[dict[str, Any]]:
        """Fetch OHLC price history for a token.

        Intervals: 1m, 5m, 1h, 6h, 1d, 1w, max
        """
        if self._config.dry_run:
            return []

        session = await self._get_http_session()
        try:
            async with session.get(
                f"{CLOB_BASE}/prices-history",
                params={
                    "market": token_id,
                    "interval": interval,
                    "fidelity": str(fidelity),
                },
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("history", data) if isinstance(data, dict) else data
        except Exception:
            logger.debug("Price history fetch failed for %s", token_id)
            return []

    # -- Balance & Positions ----------------------------------------------

    def update_simulated_balance(self, delta: float) -> None:
        """Update simulated balance (for dry-run tracking)."""
        self._simulated_balance += delta

    async def get_balance(self) -> float:
        """Return available USDC balance."""
        if self._config.dry_run:
            bal = max(0, self._simulated_balance)
            logger.info("[DRY RUN] get_balance -> $%.2f", bal)
            return bal

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            balance = self._client.get_balance()  # type: ignore[union-attr]
            return float(balance)
        except Exception as exc:
            raise PolymarketError.network(f"Failed to get balance: {exc}") from exc

    async def get_open_positions(self) -> list[dict[str, object]]:
        """Return open positions from the CLOB."""
        if self._config.dry_run:
            logger.info("[DRY RUN] get_open_positions -> returning empty list")
            return []

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            positions = self._client.get_positions()  # type: ignore[union-attr]
            return positions if isinstance(positions, list) else []
        except Exception as exc:
            raise PolymarketError.network(f"Failed to get positions: {exc}") from exc

    # -- Order Placement --------------------------------------------------

    async def create_market_order(
        self, token_id: str, side: str, amount_usdc: float,
        reference_price: float = 0.0,
    ) -> OrderResult:
        """Place a FOK market order on the CLOB.

        Args:
            reference_price: In dry-run, the price the copied trader got.
                Used as base for realistic slippage simulation.
        """
        if self._config.dry_run:
            # Realistic dry-run: use trader's price + slippage penalty
            # We'd get a WORSE price than the trader (we're copying with delay)
            if reference_price > 0:
                if side.upper() == "BUY":
                    # Slippage penalty scales with how cheap the asset is
                    # Cheap underdogs (< 0.20) have wider spreads = more slippage
                    if reference_price < 0.15:
                        slip_pct = random.uniform(0.03, 0.08)  # 3-8% for deep underdogs
                    elif reference_price < 0.30:
                        slip_pct = random.uniform(0.02, 0.05)  # 2-5% for underdogs
                    else:
                        slip_pct = random.uniform(0.01, 0.03)  # 1-3% normal
                    slippage = reference_price * slip_pct
                    exec_price = min(reference_price + slippage, 0.99)
                else:
                    slip_pct = random.uniform(0.01, 0.03)
                    slippage = reference_price * slip_pct
                    exec_price = max(reference_price - slippage, 0.01)
            else:
                # No reference price, try orderbook
                try:
                    book = await self.get_order_book(token_id)
                    exec_price = book.best_ask if side.upper() == "BUY" else book.best_bid
                except Exception:
                    exec_price = 0.50

            shares = amount_usdc / exec_price if exec_price > 0 else 0
            self._simulated_balance -= amount_usdc

            logger.info(
                "[DRY RUN] Market order: %s $%.2f @ %.4f (ref=%.4f, %.2f shares, bal=$%.2f)",
                side, amount_usdc, exec_price, reference_price, shares, self._simulated_balance,
            )
            return OrderResult(
                order_id=f"dry-{int(datetime.now(timezone.utc).timestamp())}",
                status="simulated",
                price=exec_price,
                size=shares,
                filled_size=shares,
                timestamp=datetime.now(timezone.utc),
            )

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL
            order = self._client.create_and_post_order(  # type: ignore[union-attr]
                {
                    "tokenID": token_id,
                    "side": order_side,
                    "size": amount_usdc,
                    "type": "FOK",
                }
            )
            return OrderResult(
                order_id=order.get("orderID", order.get("id", "")),
                status=order.get("status", "live"),
                price=float(order.get("price", 0)),
                size=float(order.get("size", amount_usdc)),
                filled_size=float(order.get("filledSize", amount_usdc)),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise PolymarketError(
                f"Order execution failed: {exc}", ErrorCode.API_ERROR
            ) from exc

    # [MERGED FROM polymarket-v1] New method — FAK orders
    async def create_fak_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> OrderResult:
        """Place a FAK (Fill-And-Kill) order — fills what's available, cancels rest.

        Better than FOK for copy trading: partial fills are OK.
        """
        if self._config.dry_run:
            logger.info(
                "[DRY RUN] Would create FAK order: "
                f"token={token_id} side={side} price={price:.4f} size={size:.2f}"
            )
            return OrderResult(
                order_id="dry-run-fake-id",
                status="simulated",
                price=price,
                size=size,
                filled_size=size,
                timestamp=datetime.now(timezone.utc),
            )

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL
            order = self._client.create_and_post_order(  # type: ignore[union-attr]
                {
                    "tokenID": token_id,
                    "side": order_side,
                    "price": price,
                    "size": size,
                    "type": "FAK",
                }
            )
            return OrderResult(
                order_id=order.get("orderID", order.get("id", "")),
                status=order.get("status", "live"),
                price=float(order.get("price", price)),
                size=float(order.get("size", size)),
                filled_size=float(order.get("filledSize", 0)),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise PolymarketError(
                f"FAK order failed: {exc}", ErrorCode.API_ERROR
            ) from exc

    # [MERGED FROM polymarket-v1] New method — GTD orders
    async def create_gtd_order(
        self, token_id: str, side: str, price: float, size: float, expiration_ts: int
    ) -> OrderResult:
        """Place a GTD (Good-Til-Date) order — expires at a specific timestamp.

        Perfect for sports: set expiration to game start time so the order
        auto-cancels if not filled before the match begins.
        Polymarket requires: expiration >= now + 90 seconds.
        """
        if self._config.dry_run:
            logger.info(
                "[DRY RUN] Would create GTD order: "
                f"token={token_id} side={side} price={price:.4f} "
                f"size={size:.2f} expires={expiration_ts}"
            )
            return OrderResult(
                order_id="dry-run-fake-id",
                status="simulated",
                price=price,
                size=size,
                filled_size=size,
                timestamp=datetime.now(timezone.utc),
            )

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL
            order = self._client.create_and_post_order(  # type: ignore[union-attr]
                {
                    "tokenID": token_id,
                    "side": order_side,
                    "price": price,
                    "size": size,
                    "type": "GTD",
                    "expiration": str(expiration_ts),
                }
            )
            return OrderResult(
                order_id=order.get("orderID", order.get("id", "")),
                status=order.get("status", "live"),
                price=float(order.get("price", price)),
                size=float(order.get("size", size)),
                filled_size=float(order.get("filledSize", 0)),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise PolymarketError(
                f"GTD order failed: {exc}", ErrorCode.API_ERROR
            ) from exc

    async def create_limit_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> OrderResult:
        """Place a GTC limit order on the CLOB."""
        if self._config.dry_run:
            logger.info(
                "[DRY RUN] Would create limit order: "
                f"token={token_id} side={side} price={price:.4f} size={size:.2f}"
            )
            return OrderResult(
                order_id="dry-run-fake-id",
                status="simulated",
                price=price,
                size=size,
                filled_size=0.0,
                timestamp=datetime.now(timezone.utc),
            )

        if self._client is None:
            raise PolymarketError("CLOB client not initialized", ErrorCode.CONFIG_ERROR)

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL
            order = self._client.create_and_post_order(  # type: ignore[union-attr]
                {
                    "tokenID": token_id,
                    "side": order_side,
                    "price": price,
                    "size": size,
                    "type": "GTC",
                }
            )
            return OrderResult(
                order_id=order.get("orderID", order.get("id", "")),
                status=order.get("status", "live"),
                price=float(order.get("price", price)),
                size=float(order.get("size", size)),
                filled_size=float(order.get("filledSize", 0)),
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise PolymarketError(
                f"Limit order failed: {exc}", ErrorCode.API_ERROR
            ) from exc

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
