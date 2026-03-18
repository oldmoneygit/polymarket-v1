"""WebSocket client for real-time Polymarket CLOB data."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from src.errors import PolymarketError

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Reconnection settings
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_BASE_DELAY = 5  # seconds
PING_INTERVAL = 30  # seconds


class PolymarketWebSocket:
    """WebSocket client for real-time market data from Polymarket CLOB.

    Supports channels: price, book, trade, ticker.
    Auto-reconnects with exponential backoff.
    """

    def __init__(
        self,
        on_trade: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_price: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._on_trade = on_trade
        self._on_price = on_price
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._subscribed_markets: set[str] = set()
        self._running = False
        self._reconnect_count = 0

    async def subscribe(self, asset_ids: list[str]) -> None:
        """Subscribe to trade and price updates for given asset/token IDs."""
        self._subscribed_markets.update(asset_ids)
        if self._ws is not None and not self._ws.closed:
            for asset_id in asset_ids:
                await self._send_subscribe(asset_id)

    async def _send_subscribe(self, asset_id: str) -> None:
        """Send subscription message for a market."""
        if self._ws is None or self._ws.closed:
            return
        for channel in ("trade", "price"):
            msg = {
                "type": "subscribe",
                "channel": channel,
                "assets_id": asset_id,
            }
            await self._ws.send_json(msg)
            logger.debug("Subscribed to %s for %s", channel, asset_id[:12])

    async def start(self) -> None:
        """Connect and listen for messages. Auto-reconnects on failure."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                self._running = False
                break
            except Exception:
                self._reconnect_count += 1
                if self._reconnect_count > MAX_RECONNECT_ATTEMPTS:
                    logger.error(
                        "WebSocket max reconnect attempts (%d) reached",
                        MAX_RECONNECT_ATTEMPTS,
                    )
                    self._running = False
                    break
                delay = min(
                    RECONNECT_BASE_DELAY * (2 ** (self._reconnect_count - 1)),
                    60,
                )
                logger.warning(
                    "WebSocket disconnected, reconnecting in %ds (attempt %d/%d)",
                    delay, self._reconnect_count, MAX_RECONNECT_ATTEMPTS,
                )
                await asyncio.sleep(delay)

    async def _connect_and_listen(self) -> None:
        """Single connection lifecycle."""
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                WS_URL, heartbeat=PING_INTERVAL
            )
            logger.info("WebSocket connected to %s", WS_URL)
            self._reconnect_count = 0

            # Re-subscribe after reconnect
            for asset_id in self._subscribed_markets:
                await self._send_subscribe(asset_id)

            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        finally:
            if self._ws and not self._ws.closed:
                await self._ws.close()
            if self._session and not self._session.closed:
                await self._session.close()

    async def _handle_message(self, raw: str) -> None:
        """Parse and dispatch a WebSocket message."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        channel = data.get("channel", data.get("type", ""))

        if channel == "trade" and self._on_trade:
            trades = data.get("data", data.get("trades", []))
            if isinstance(trades, list):
                for trade in trades:
                    try:
                        await self._on_trade(trade)
                    except Exception:
                        logger.exception("Error in on_trade callback")
            elif isinstance(trades, dict):
                try:
                    await self._on_trade(trades)
                except Exception:
                    logger.exception("Error in on_trade callback")

        elif channel == "price" and self._on_price:
            try:
                await self._on_price(data)
            except Exception:
                logger.exception("Error in on_price callback")

    async def stop(self) -> None:
        """Gracefully close the WebSocket."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
