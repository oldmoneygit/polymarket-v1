"""Unit tests for src/api/polymarket.py (SPEC-02)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.polymarket import (
    APIError,
    PolymarketClient,
    _detect_category,
)


class TestDetectCategory:
    def test_detect_sports_market_by_slug(self) -> None:
        assert _detect_category("ucl-psg-chelsea-2026", "") == "sports"
        assert _detect_category("", "mls-inter-miami-2026") == "sports"
        assert _detect_category("nba-finals-2026", "") == "sports"
        assert _detect_category("premier-league-match", "") == "sports"
        assert _detect_category("will-team-beat-opponent", "") == "sports"

    def test_detect_non_sports_market(self) -> None:
        assert _detect_category("will-btc-reach-100k", "") == "other"
        assert _detect_category("us-election-2028", "") == "other"
        assert _detect_category("ai-regulation-bill", "") == "other"


class TestParseTraderActivity:
    @pytest.mark.asyncio
    async def test_parse_trader_activity_response(self) -> None:
        mock_data = [
            {
                "transactionHash": "0xhash1",
                "timestamp": 1710000000,
                "conditionId": "cond1",
                "price": 0.52,
                "size": 100,
                "usdcSize": 52,
                "side": "BUY",
                "outcome": "Yes",
                "title": "Will PSG win?",
                "slug": "ucl-psg-match",
                "event_slug": "ucl-psg",
                "asset": "token1",
            }
        ]

        client = PolymarketClient()
        with patch.object(client, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            trades = await client.get_trader_activity("0xwallet")

        assert len(trades) == 1
        assert trades[0].transaction_hash == "0xhash1"
        assert trades[0].price == 0.52
        assert trades[0].side == "BUY"
        assert trades[0].token_id == "token1"


class TestParseMarketInfo:
    @pytest.mark.asyncio
    async def test_parse_market_info_response(self) -> None:
        mock_data = [
            {
                "conditionId": "cond1",
                "question": "Will PSG win?",
                "slug": "ucl-psg-match",
                "event_slug": "ucl-event",
                "volume": 50000,
                "liquidity": 10000,
                "endDate": "2099-01-01T00:00:00Z",
                "resolved": False,
                "outcomePrices": "[0.52, 0.48]",
            }
        ]

        client = PolymarketClient()
        with patch.object(client, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            market = await client.get_market_info("cond1")

        assert market is not None
        assert market.condition_id == "cond1"
        assert market.category == "sports"
        assert market.volume == 50000
        assert market.yes_price == pytest.approx(0.52)
        assert market.no_price == pytest.approx(0.48)
        assert market.is_resolved is False

    @pytest.mark.asyncio
    async def test_market_not_found_returns_none(self) -> None:
        client = PolymarketClient()
        with patch.object(client, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            market = await client.get_market_info("nonexistent")

        assert market is None


class TestAPIErrors:
    @pytest.mark.asyncio
    async def test_api_error_raises_exception(self) -> None:
        client = PolymarketClient()
        with patch.object(
            client, "_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = APIError("HTTP 400")
            with pytest.raises(APIError, match="400"):
                await client.get_trader_activity("0xwallet")

    @pytest.mark.asyncio
    async def test_retry_on_500_error(self) -> None:
        """Verify that _get_with_retry retries on 500 and succeeds on second try."""
        client = PolymarketClient()

        call_count = 0

        class MockResp:
            def __init__(self, status: int, data: object) -> None:
                self.status = status
                self._data = data

            async def json(self) -> object:
                return self._data

            async def text(self) -> str:
                return str(self._data)

            async def __aenter__(self) -> MockResp:
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

        def mock_get(url: str, params: object = None) -> MockResp:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockResp(500, {"error": "server error"})
            return MockResp(200, [{"transactionHash": "0x1", "timestamp": 1}])

        session = MagicMock()
        session.get = mock_get
        session.closed = False
        client._session = session

        # Patch sleep to avoid waiting
        with patch("src.api.polymarket.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get_with_retry("http://example.com/test")

        assert call_count == 2
        assert isinstance(result, list)
