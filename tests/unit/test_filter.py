"""Unit tests for src/strategy/filter.py (SPEC-05)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from src.config import Config
from src.db.models import FilterResult, MarketInfo, TraderTrade
from src.strategy.filter import TradeFilter


@pytest.fixture()
def trade_filter() -> TradeFilter:
    return TradeFilter()


@pytest.fixture()
def now_ts() -> int:
    return int(time.time())


class TestTradeFilterPassesAll:
    def test_passes_all_criteria(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        result = trade_filter.evaluate(
            sample_trade, sample_market, config, current_exposure=0.0, now_ts=now_ts
        )
        assert result.passed is True
        assert result.reason == "OK"


class TestTradeFilterRejectsNonSports:
    def test_fails_non_sports_market(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        non_sports = MarketInfo(
            condition_id=sample_market.condition_id,
            question="Will BTC reach $100k?",
            category="crypto",
            volume=50000.0,
            liquidity=10000.0,
            end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
            is_resolved=False,
            yes_price=0.52,
            no_price=0.48,
        )
        result = trade_filter.evaluate(
            sample_trade, non_sports, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "esportivo" in result.reason.lower()


class TestTradeFilterRejectsResolved:
    def test_fails_resolved_market(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        resolved = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=50000.0,
            liquidity=10000.0,
            end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
            is_resolved=True,
            yes_price=1.0,
            no_price=0.0,
        )
        result = trade_filter.evaluate(
            sample_trade, resolved, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "resolvido" in result.reason.lower()


class TestTradeFilterRejectsExpired:
    def test_fails_expired_market(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        expired = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=50000.0,
            liquidity=10000.0,
            end_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            is_resolved=False,
            yes_price=0.52,
            no_price=0.48,
        )
        result = trade_filter.evaluate(
            sample_trade, expired, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "expirado" in result.reason.lower()


class TestTradeFilterRejectsLowVolume:
    def test_fails_low_volume(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        low_vol = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=100.0,
            liquidity=50.0,
            end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
            is_resolved=False,
            yes_price=0.52,
            no_price=0.48,
        )
        result = trade_filter.evaluate(
            sample_trade, low_vol, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "volume" in result.reason.lower()


class TestTradeFilterRejectsPriceOutOfRange:
    def test_fails_price_too_low(
        self,
        trade_filter: TradeFilter,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        low_price_trade = TraderTrade(
            proxy_wallet="0x" + "b2" * 20,
            timestamp=now_ts - 60,
            condition_id="0xcond",
            transaction_hash="0xhash",
            price=0.10,
            size=100.0,
            usdc_size=10.0,
            side="BUY",
            outcome="Yes",
            title="Test",
            slug="ucl-test",
            event_slug="ucl-test",
        )
        result = trade_filter.evaluate(
            low_price_trade, sample_market, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "fora do range" in result.reason.lower()

    def test_fails_price_too_high(
        self,
        trade_filter: TradeFilter,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        high_price_trade = TraderTrade(
            proxy_wallet="0x" + "b2" * 20,
            timestamp=now_ts - 60,
            condition_id="0xcond",
            transaction_hash="0xhash",
            price=0.95,
            size=100.0,
            usdc_size=95.0,
            side="BUY",
            outcome="Yes",
            title="Test",
            slug="ucl-test",
            event_slug="ucl-test",
        )
        result = trade_filter.evaluate(
            high_price_trade, sample_market, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "fora do range" in result.reason.lower()


class TestTradeFilterRejectsOldTrade:
    def test_fails_old_trade(
        self,
        trade_filter: TradeFilter,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        old_trade = TraderTrade(
            proxy_wallet="0x" + "b2" * 20,
            timestamp=now_ts - 7200,  # 2 hours ago
            condition_id="0xcond",
            transaction_hash="0xhash",
            price=0.52,
            size=100.0,
            usdc_size=52.0,
            side="BUY",
            outcome="Yes",
            title="Test",
            slug="ucl-test",
            event_slug="ucl-test",
        )
        result = trade_filter.evaluate(
            old_trade, sample_market, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "min" in result.reason.lower()


class TestTradeFilterRejectsSell:
    def test_fails_sell_trade(
        self,
        trade_filter: TradeFilter,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        sell_trade = TraderTrade(
            proxy_wallet="0x" + "b2" * 20,
            timestamp=now_ts - 60,
            condition_id="0xcond",
            transaction_hash="0xhash",
            price=0.52,
            size=100.0,
            usdc_size=52.0,
            side="SELL",
            outcome="Yes",
            title="Test",
            slug="ucl-test",
            event_slug="ucl-test",
        )
        result = trade_filter.evaluate(
            sell_trade, sample_market, config, now_ts=now_ts
        )
        assert result.passed is False
        assert "compra" in result.reason.lower()


class TestTradeFilterRejectsMaxExposure:
    def test_fails_max_exposure_reached(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        result = trade_filter.evaluate(
            sample_trade,
            sample_market,
            config,
            current_exposure=99.0,
            now_ts=now_ts,
        )
        assert result.passed is False
        assert "exposição" in result.reason.lower()


class TestTradeFilterReasonDescriptive:
    def test_filter_reason_message_is_descriptive(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
        now_ts: int,
    ) -> None:
        low_vol = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=3200.0,
            liquidity=1000.0,
            end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
            is_resolved=False,
            yes_price=0.52,
            no_price=0.48,
        )
        result = trade_filter.evaluate(
            sample_trade, low_vol, config, now_ts=now_ts
        )
        assert "$3200" in result.reason or "3200" in result.reason
        assert "$5000" in result.reason or "5000" in result.reason
