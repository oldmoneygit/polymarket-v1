"""Unit tests for src/db/models.py."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from src.db.models import (
    ExecutionResult,
    FilterResult,
    MarketInfo,
    OrderResult,
    Position,
    TraderTrade,
)


class TestTraderTrade:
    def test_defaults(self) -> None:
        t = TraderTrade(
            proxy_wallet="0xabc",
            timestamp=1000,
            condition_id="cond1",
            transaction_hash="0xhash",
            price=0.5,
            size=10.0,
            usdc_size=5.0,
            side="BUY",
            outcome="Yes",
            title="Test",
            slug="test-slug",
            event_slug="test-event",
        )
        assert t.trader_name == ""
        assert t.token_id == ""

    def test_all_fields(self, sample_trade: TraderTrade) -> None:
        assert sample_trade.side == "BUY"
        assert sample_trade.outcome == "Yes"
        assert sample_trade.price == 0.52


class TestMarketInfo:
    def test_fields(self, sample_market: MarketInfo) -> None:
        assert sample_market.category == "sports"
        assert sample_market.is_resolved is False
        assert sample_market.yes_price + sample_market.no_price == pytest.approx(1.0)


class TestPosition:
    def test_defaults(self) -> None:
        p = Position(
            condition_id="c1",
            token_id="t1",
            side="BUY",
            outcome="Yes",
            entry_price=0.5,
            shares=10.0,
            usdc_invested=5.0,
            trader_copied="0xabc",
            market_title="Test",
            opened_at=int(time.time()),
        )
        assert p.status == "open"
        assert p.id is None
        assert p.pnl is None
        assert p.dry_run is False


class TestFilterResult:
    def test_passed(self) -> None:
        r = FilterResult(passed=True, reason="OK")
        assert r.passed is True

    def test_rejected(self) -> None:
        r = FilterResult(passed=False, reason="Volume too low")
        assert r.passed is False
        assert "Volume" in r.reason


class TestExecutionResult:
    def test_success(self) -> None:
        r = ExecutionResult(success=True, order_id="ord1", price=0.5, usdc_spent=5.0)
        assert r.success is True
        assert r.error is None

    def test_failure(self) -> None:
        r = ExecutionResult(success=False, error="Insufficient balance")
        assert r.success is False
        assert r.order_id is None


# Need pytest import for approx
import pytest
