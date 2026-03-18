"""Unit tests for src/errors.py."""

from src.errors import ErrorCode, PolymarketError


class TestErrorCode:
    def test_retryable_codes(self) -> None:
        assert ErrorCode.NETWORK_ERROR.retryable is True
        assert ErrorCode.RATE_LIMIT.retryable is True
        assert ErrorCode.API_ERROR.retryable is True
        assert ErrorCode.WEBSOCKET_ERROR.retryable is True

    def test_non_retryable_codes(self) -> None:
        assert ErrorCode.AUTH_ERROR.retryable is False
        assert ErrorCode.INVALID_MARKET.retryable is False
        assert ErrorCode.MARKET_CLOSED.retryable is False
        assert ErrorCode.INSUFFICIENT_FUNDS.retryable is False
        assert ErrorCode.INSUFFICIENT_LIQUIDITY.retryable is False
        assert ErrorCode.INVALID_ORDER.retryable is False
        assert ErrorCode.CONFIG_ERROR.retryable is False


class TestPolymarketError:
    def test_factory_methods(self) -> None:
        assert PolymarketError.network("x").code == ErrorCode.NETWORK_ERROR
        assert PolymarketError.rate_limit("x").code == ErrorCode.RATE_LIMIT
        assert PolymarketError.auth("x").code == ErrorCode.AUTH_ERROR
        assert PolymarketError.invalid_market("x").code == ErrorCode.INVALID_MARKET
        assert PolymarketError.market_closed("x").code == ErrorCode.MARKET_CLOSED
        assert PolymarketError.insufficient_funds("x").code == ErrorCode.INSUFFICIENT_FUNDS
        assert PolymarketError.insufficient_liquidity("x").code == ErrorCode.INSUFFICIENT_LIQUIDITY
        assert PolymarketError.invalid_order("x").code == ErrorCode.INVALID_ORDER
        assert PolymarketError.websocket("x").code == ErrorCode.WEBSOCKET_ERROR

    def test_default_code(self) -> None:
        err = PolymarketError("generic")
        assert err.code == ErrorCode.API_ERROR

    def test_message_preserved(self) -> None:
        err = PolymarketError.network("connection timeout")
        assert "connection timeout" in str(err)
