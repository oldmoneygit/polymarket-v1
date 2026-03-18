"""Unit tests for src/api/websocket.py."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.websocket import PolymarketWebSocket


class TestWebSocketSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_stores_markets(self) -> None:
        ws = PolymarketWebSocket()
        await ws.subscribe(["token1", "token2"])
        assert "token1" in ws._subscribed_markets
        assert "token2" in ws._subscribed_markets

    @pytest.mark.asyncio
    async def test_subscribe_with_active_connection(self) -> None:
        ws = PolymarketWebSocket()
        mock_ws = AsyncMock()
        mock_ws.closed = False
        ws._ws = mock_ws
        await ws.subscribe(["token1"])
        assert mock_ws.send_json.call_count == 2  # trade + price channels


class TestWebSocketMessageHandling:
    @pytest.mark.asyncio
    async def test_handle_trade_message(self) -> None:
        received = []

        async def on_trade(data: dict) -> None:
            received.append(data)

        ws = PolymarketWebSocket(on_trade=on_trade)
        await ws._handle_message(json.dumps({
            "channel": "trade",
            "data": [{"price": "0.52", "size": "100"}],
        }))
        assert len(received) == 1
        assert received[0]["price"] == "0.52"

    @pytest.mark.asyncio
    async def test_handle_trade_single_dict(self) -> None:
        received = []

        async def on_trade(data: dict) -> None:
            received.append(data)

        ws = PolymarketWebSocket(on_trade=on_trade)
        await ws._handle_message(json.dumps({
            "channel": "trade",
            "data": {"price": "0.50"},
        }))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_handle_price_message(self) -> None:
        received = []

        async def on_price(data: dict) -> None:
            received.append(data)

        ws = PolymarketWebSocket(on_price=on_price)
        await ws._handle_message(json.dumps({
            "channel": "price",
            "yes": 0.52,
        }))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self) -> None:
        ws = PolymarketWebSocket()
        await ws._handle_message("not json")  # Should not crash

    @pytest.mark.asyncio
    async def test_handle_trade_callback_error(self) -> None:
        async def bad_callback(data: dict) -> None:
            raise RuntimeError("boom")

        ws = PolymarketWebSocket(on_trade=bad_callback)
        # Should not crash
        await ws._handle_message(json.dumps({
            "channel": "trade",
            "data": [{"price": "0.50"}],
        }))

    @pytest.mark.asyncio
    async def test_no_callback_no_crash(self) -> None:
        ws = PolymarketWebSocket()
        await ws._handle_message(json.dumps({
            "channel": "trade",
            "data": [{"price": "0.50"}],
        }))


class TestWebSocketStop:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self) -> None:
        ws = PolymarketWebSocket()
        ws._running = True
        await ws.stop()
        assert ws._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_connections(self) -> None:
        ws = PolymarketWebSocket()
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_session = AsyncMock()
        mock_session.closed = False
        ws._ws = mock_ws
        ws._session = mock_session
        await ws.stop()
        mock_ws.close.assert_called_once()
        mock_session.close.assert_called_once()
