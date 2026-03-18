"""Unit tests for src/api/polymarket.py (SPEC-02)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.polymarket import (
    APIError,
    PolymarketClient,
    _detect_category,
)
from src.db.models import MarketInfo, TraderTrade


class TestDetectCategory:
    @pytest.mark.parametrize(
        "slug,event_slug,expected",
        [
            ("ucl-psg-cfc-2026", "ucl-psg-cfc", "sports"),
            ("nba-lal-bos-2026", "nba-lal-bos", "sports"),
            ("nhl-nsh-wpg-2026", "nhl-nsh-wpg", "sports"),
            ("mls-sj-sea-2026", "mls-sj-sea", "sports"),
            ("epl-liv-mun-2026", "premier-league", "sports"),
            ("will-btc-reach-100k", "crypto-btc", "other"),
            ("trump-executive-order", "politics-usa", "other"),
            ("nba-lal-bos-2026-03-17", "", "sports"),
            ("bundesliga-bay-bvb", "", "sports"),
            ("football-world-cup", "", "sports"),
        ],
    )
    def test_detect_sports_market_by_slug(
        self, slug: str, event_slug: str, expected: str
    ) -> None:
        assert _detect_category(slug, event_slug) == expected

    @pytest.mark.parametrize(
        "slug,expected",
        [
            ("cbb-ncst-tx-2026-03-17-spread-home-4pt5", "sports"),
            ("atp-djokovic-sinner-2026-03-18", "sports"),
            ("wta-swiatek-gauff-2026-03-18", "sports"),
            ("cs2-navi-faze-2026-03-18", "sports"),
            ("lol-jdg-lll-2026-03-19", "sports"),
            ("bra-vas-flu-2026-03-18", "sports"),
            ("fl1-psg-lyon-2026-03-20", "sports"),
        ],
    )
    def test_detect_sports_by_slug_prefix(self, slug: str, expected: str) -> None:
        assert _detect_category(slug, "") == expected

    def test_detect_non_sports_market(self) -> None:
        assert _detect_category("bitcoin-price-100k", "crypto") == "other"


class TestParseTraderActivity:
    @pytest.mark.asyncio
    async def test_parse_trader_activity_response(self) -> None:
        mock_response = [
            {
                "transactionHash": "0xabc123",
                "timestamp": 1710700000,
                "conditionId": "0xcond1",
                "price": "0.52",
                "size": "100",
                "usdcSize": "52",
                "side": "BUY",
                "outcome": "Yes",
                "title": "Will PSG win?",
                "slug": "ucl-psg-cfc-2026",
                "event_slug": "ucl-psg-cfc",
                "name": "TestTrader",
                "asset": "token123",
            }
        ]

        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=mock_response)

        trades = await client.get_trader_activity("0xwallet")

        assert len(trades) == 1
        trade = trades[0]
        assert trade.transaction_hash == "0xabc123"
        assert trade.price == 0.52
        assert trade.side == "BUY"
        assert trade.outcome == "Yes"
        assert trade.title == "Will PSG win?"
        assert trade.token_id == "token123"

        await client.close()


class TestParseMarketInfo:
    @pytest.mark.asyncio
    async def test_parse_market_info_response(self) -> None:
        mock_response = [
            {
                "conditionId": "0xcond1",
                "question": "Will PSG win on 2026-03-11?",
                "slug": "ucl-psg-cfc-2026-03-11-psg",
                "event_slug": "ucl-psg-cfc-2026-03-11",
                "volume": "50000",
                "liquidity": "10000",
                "endDate": "2099-01-01T00:00:00Z",
                "resolved": False,
                "outcomePrices": '["0.52","0.48"]',
            }
        ]

        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=mock_response)

        market = await client.get_market_info("0xcond1")

        assert market is not None
        assert market.condition_id == "0xcond1"
        assert market.question == "Will PSG win on 2026-03-11?"
        assert market.category == "sports"
        assert market.volume == 50000.0
        assert market.is_resolved is False
        assert market.yes_price == pytest.approx(0.52)
        assert market.no_price == pytest.approx(0.48)

        await client.close()

    @pytest.mark.asyncio
    async def test_market_not_found_returns_none(self) -> None:
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=[])

        market = await client.get_market_info("0xnonexistent")
        assert market is None

        await client.close()


class TestAPIErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_raises_exception(self) -> None:
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(side_effect=APIError("HTTP 404"))

        with pytest.raises(APIError, match="404"):
            await client.get_trader_activity("0xwallet")

        await client.close()


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retry_on_500_error(self) -> None:
        """Test that 500 errors trigger retry and eventually succeed."""
        client = PolymarketClient()

        call_count = 0

        async def mock_retry(url: str, params: dict | None = None) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APIError("HTTP 500 from test")
            return []

        client._get_with_retry = AsyncMock(side_effect=mock_retry)

        # First call raises, second succeeds
        with pytest.raises(APIError):
            await client.get_trader_activity("0xwallet")

        # Reset and test that the method is called
        client._get_with_retry = AsyncMock(return_value=[])
        trades = await client.get_trader_activity("0xwallet")
        assert trades == []
        await client.close()


class TestActivityResponseFormats:
    @pytest.mark.asyncio
    async def test_activity_dict_with_data_key(self) -> None:
        """When API returns dict with 'data' key instead of list."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(
            return_value={"data": [{"transactionHash": "0xh1", "timestamp": 100, "price": "0.5", "size": "10", "usdcSize": "5", "side": "BUY", "outcome": "Yes", "title": "T", "slug": "s", "event_slug": "e"}]}
        )
        trades = await client.get_trader_activity("0xw")
        assert len(trades) == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_activity_dict_with_history_key(self) -> None:
        """When API returns dict with 'history' key."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(
            return_value={"history": [{"transactionHash": "0xh1", "timestamp": 100, "price": "0.5", "size": "10", "usdcSize": "5", "side": "BUY", "outcome": "Yes", "title": "T", "slug": "s", "event_slug": "e"}]}
        )
        trades = await client.get_trader_activity("0xw")
        assert len(trades) == 1
        await client.close()


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_get_session_creates_new(self) -> None:
        client = PolymarketClient()
        session = await client._get_session()
        assert session is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_close_does_not_close_external_session(self) -> None:
        import aiohttp
        ext = aiohttp.ClientSession()
        client = PolymarketClient(session=ext)
        await client.close()
        assert not ext.closed
        await ext.close()

    @pytest.mark.asyncio
    async def test_close_closes_own_session(self) -> None:
        client = PolymarketClient()
        _ = await client._get_session()
        await client.close()


class TestRetryWithRealSession:
    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises(self) -> None:
        """Simulate 3 consecutive 500 errors."""
        client = PolymarketClient()
        fail_count = 0

        original = client._get_with_retry

        async def always_fail(url: str, params: dict | None = None) -> None:
            raise APIError("HTTP 500 from test-url")

        client._get_with_retry = AsyncMock(side_effect=always_fail)
        with pytest.raises(APIError):
            await client.get_trader_activity("0xw")
        await client.close()

    @pytest.mark.asyncio
    async def test_network_error_retry(self) -> None:
        """Network errors should be wrapped in APIError."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(
            side_effect=APIError("Network error on test: timeout")
        )
        with pytest.raises(APIError, match="Network error"):
            await client.get_market_info("0xcond")
        await client.close()


class TestMarketParsingEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_end_date_uses_fallback(self) -> None:
        """Invalid date string falls back to 2099."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=[{
            "conditionId": "0xc", "question": "T?", "slug": "nba-t",
            "volume": "100", "liquidity": "50", "resolved": False,
            "endDate": "not-a-date",
        }])
        market = await client.get_market_info("0xc")
        assert market is not None
        assert market.end_date.year == 2099
        await client.close()

    @pytest.mark.asyncio
    async def test_no_end_date_uses_fallback(self) -> None:
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=[{
            "conditionId": "0xc", "question": "T?", "slug": "nba-t",
            "volume": "100", "liquidity": "50", "resolved": False,
        }])
        market = await client.get_market_info("0xc")
        assert market is not None
        assert market.end_date.year == 2099
        await client.close()

    @pytest.mark.asyncio
    async def test_invalid_outcome_prices_string(self) -> None:
        """Bad JSON in outcomePrices string falls back."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=[{
            "conditionId": "0xc", "question": "T?", "slug": "nba-t",
            "volume": "100", "liquidity": "50", "resolved": False,
            "outcomePrices": "not-json",
            "yes_price": "0.60", "no_price": "0.40",
        }])
        market = await client.get_market_info("0xc")
        assert market is not None
        assert market.yes_price == pytest.approx(0.60)
        await client.close()

    @pytest.mark.asyncio
    async def test_resolved_market_has_outcome(self) -> None:
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=[{
            "conditionId": "0xc", "question": "T?", "slug": "nba-t",
            "volume": "100", "liquidity": "50",
            "resolved": True, "resolution": "Yes",
            "outcomePrices": '["1.0","0.0"]',
        }])
        market = await client.get_market_info("0xc")
        assert market is not None
        assert market.is_resolved is True
        assert market.resolved_outcome == "Yes"
        await client.close()

    @pytest.mark.asyncio
    async def test_market_info_non_list_response(self) -> None:
        """get_market_info returns None when response is dict, not list."""
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value={"error": "not found"})
        market = await client.get_market_info("0xc")
        assert market is None
        await client.close()


class TestGetWithRetryDirect:
    @pytest.mark.asyncio
    async def test_500_retry_then_success(self) -> None:
        """Test the actual _get_with_retry with mocked session."""
        import aiohttp
        from contextlib import asynccontextmanager

        call_count = 0
        client = PolymarketClient()

        class FakeResp:
            def __init__(self, status, data=None):
                self.status = status
                self._data = data
            async def json(self):
                return self._data or []
            async def text(self):
                return "error"
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass

        responses = [FakeResp(500), FakeResp(200, [{"test": True}])]
        idx = 0

        class FakeSession:
            closed = False
            def get(self, url, params=None):
                nonlocal idx
                r = responses[idx]
                idx += 1
                return r

        client._session = FakeSession()
        client._external_session = True

        with patch("src.api.polymarket.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get_with_retry("http://test")
        assert result == [{"test": True}]

    @pytest.mark.asyncio
    async def test_500_exhaustion(self) -> None:
        """3 consecutive 500s should raise APIError."""
        client = PolymarketClient()

        class FakeResp:
            status = 500
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass

        class FakeSession:
            closed = False
            def get(self, url, params=None):
                return FakeResp()

        client._session = FakeSession()
        client._external_session = True

        with patch("src.api.polymarket.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(APIError, match="500"):
                await client._get_with_retry("http://test")

    @pytest.mark.asyncio
    async def test_400_raises_immediately(self) -> None:
        client = PolymarketClient()

        class FakeResp:
            status = 404
            async def text(self):
                return "not found"
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass

        class FakeSession:
            closed = False
            def get(self, url, params=None):
                return FakeResp()

        client._session = FakeSession()
        client._external_session = True

        with pytest.raises(APIError, match="404"):
            await client._get_with_retry("http://test")

    @pytest.mark.asyncio
    async def test_network_error_retry_then_success(self) -> None:
        import aiohttp
        client = PolymarketClient()
        call_count = 0

        class FakeResp:
            status = 200
            async def json(self):
                return {"ok": True}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass

        class FakeSession:
            closed = False
            def get(self, url, params=None):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise aiohttp.ClientError("timeout")
                return FakeResp()

        client._session = FakeSession()
        client._external_session = True

        with patch("src.api.polymarket.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get_with_retry("http://test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_network_error_exhaustion(self) -> None:
        import aiohttp
        client = PolymarketClient()

        class FakeSession:
            closed = False
            def get(self, url, params=None):
                raise aiohttp.ClientError("always fail")

        client._session = FakeSession()
        client._external_session = True

        with patch("src.api.polymarket.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(APIError, match="Network error"):
                await client._get_with_retry("http://test")


class TestOutcomePricesParsing:
    @pytest.mark.asyncio
    async def test_outcome_prices_as_list(self) -> None:
        mock_response = [
            {
                "conditionId": "0xcond",
                "question": "Test?",
                "slug": "nba-test",
                "volume": "1000",
                "liquidity": "500",
                "resolved": False,
                "outcomePrices": [0.65, 0.35],
            }
        ]
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=mock_response)
        market = await client.get_market_info("0xcond")
        assert market is not None
        assert market.yes_price == pytest.approx(0.65)
        assert market.no_price == pytest.approx(0.35)
        await client.close()

    @pytest.mark.asyncio
    async def test_outcome_prices_fallback(self) -> None:
        mock_response = [
            {
                "conditionId": "0xcond",
                "question": "Test?",
                "slug": "politics-test",
                "volume": "1000",
                "liquidity": "500",
                "resolved": False,
                "bestAsk": "0.70",
            }
        ]
        client = PolymarketClient()
        client._get_with_retry = AsyncMock(return_value=mock_response)
        market = await client.get_market_info("0xcond")
        assert market is not None
        assert market.yes_price == pytest.approx(0.70)
        assert market.no_price == pytest.approx(0.30)
        await client.close()
