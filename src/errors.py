"""Structured error hierarchy for the Polymarket bot.

# [MERGED FROM polymarket-v1] New module — typed errors with retry classification.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(Enum):
    """Categorized error codes for smart retry and notification logic."""

    NETWORK_ERROR = "NETWORK_ERROR"  # Retry with backoff
    RATE_LIMIT = "RATE_LIMIT"  # Retry after delay
    API_ERROR = "API_ERROR"  # Generic API failure
    AUTH_ERROR = "AUTH_ERROR"  # Bad credentials — do not retry
    INVALID_MARKET = "INVALID_MARKET"  # Market gone — do not retry
    MARKET_CLOSED = "MARKET_CLOSED"  # Market resolved — do not retry
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"  # No money — do not retry
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"  # Order book too thin
    INVALID_ORDER = "INVALID_ORDER"  # Bad order params
    WEBSOCKET_ERROR = "WEBSOCKET_ERROR"  # WS connection issue
    CONFIG_ERROR = "CONFIG_ERROR"  # Bad configuration

    @property
    def retryable(self) -> bool:
        return self in (
            ErrorCode.NETWORK_ERROR,
            ErrorCode.RATE_LIMIT,
            ErrorCode.API_ERROR,
            ErrorCode.WEBSOCKET_ERROR,
        )


class PolymarketError(Exception):
    """Base error with typed error code for smart handling."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.API_ERROR) -> None:
        super().__init__(message)
        self.code = code

    @classmethod
    def network(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.NETWORK_ERROR)

    @classmethod
    def rate_limit(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.RATE_LIMIT)

    @classmethod
    def auth(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.AUTH_ERROR)

    @classmethod
    def invalid_market(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.INVALID_MARKET)

    @classmethod
    def market_closed(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.MARKET_CLOSED)

    @classmethod
    def insufficient_funds(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.INSUFFICIENT_FUNDS)

    @classmethod
    def insufficient_liquidity(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.INSUFFICIENT_LIQUIDITY)

    @classmethod
    def invalid_order(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.INVALID_ORDER)

    @classmethod
    def websocket(cls, msg: str) -> PolymarketError:
        return cls(msg, ErrorCode.WEBSOCKET_ERROR)
