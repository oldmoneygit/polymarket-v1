"""Unit tests for src/strategy/filter.py — updated for Tier 1."""

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


class TestTradeFilter:
    def test_passes_all_criteria(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        result = trade_filter.evaluate(sample_trade, sample_market, config)
        assert result.passed is True
        assert result.reason == "OK"

    def test_passes_non_sports_when_categories_all(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        """With MARKET_CATEGORIES=all, non-sports markets should pass."""
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question="Will BTC hit 100k?",
            category="crypto",
            volume=sample_market.volume,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            is_resolved=False,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug="btc-100k",
        )
        result = trade_filter.evaluate(sample_trade, market, config)
        assert result.passed is True

    def test_fails_category_when_filtered(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        monkeypatch: pytest.MonkeyPatch,
        env_vars: dict[str, str],
    ) -> None:
        """When MARKET_CATEGORIES=sports, non-sports markets should fail."""
        monkeypatch.setenv("MARKET_CATEGORIES", "sports")
        cfg = Config.load()
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question="Will BTC hit 100k?",
            category="crypto",
            volume=sample_market.volume,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            is_resolved=False,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug="btc-100k",
        )
        result = trade_filter.evaluate(sample_trade, market, cfg)
        assert result.passed is False
        assert "Categoria" in result.reason

    def test_fails_resolved_market(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=sample_market.volume,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            is_resolved=True,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug=sample_market.slug,
        )
        result = trade_filter.evaluate(sample_trade, market, config)
        assert result.passed is False
        assert "resolvido" in result.reason

    def test_fails_expired_market(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=sample_market.volume,
            liquidity=sample_market.liquidity,
            end_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            is_resolved=False,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug=sample_market.slug,
        )
        result = trade_filter.evaluate(sample_trade, market, config)
        assert result.passed is False
        assert "expirado" in result.reason

    def test_fails_low_volume(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=100.0,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            is_resolved=False,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug=sample_market.slug,
        )
        result = trade_filter.evaluate(sample_trade, market, config)
        assert result.passed is False
        assert "Volume" in result.reason

    def test_fails_price_too_low(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash=sample_trade.transaction_hash,
            price=0.05,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="BUY",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(trade, sample_market, config)
        assert result.passed is False
        assert "fora do range" in result.reason

    def test_fails_price_too_high(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash=sample_trade.transaction_hash,
            price=0.95,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="BUY",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(trade, sample_market, config)
        assert result.passed is False
        assert "fora do range" in result.reason

    def test_fails_old_trade(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        old_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=int(time.time()) - 7200,
            condition_id=sample_trade.condition_id,
            transaction_hash=sample_trade.transaction_hash,
            price=0.52,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="BUY",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(old_trade, sample_market, config)
        assert result.passed is False
        assert "min" in result.reason

    # -- SELL tests --

    def test_sell_passes_when_has_open_position(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        sell_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash="0xtxsell001",
            price=0.52,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="SELL",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(
            sell_trade, sample_market, config, has_open_position=True
        )
        assert result.passed is True
        assert "SELL" in result.reason

    def test_sell_fails_when_no_open_position(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        sell_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash="0xtxsell002",
            price=0.52,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="SELL",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(
            sell_trade, sample_market, config, has_open_position=False
        )
        assert result.passed is False
        assert "sem posição" in result.reason

    def test_sell_fails_when_copy_sell_disabled(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        monkeypatch: pytest.MonkeyPatch,
        env_vars: dict[str, str],
    ) -> None:
        monkeypatch.setenv("COPY_SELL", "false")
        cfg = Config.load()
        sell_trade = TraderTrade(
            proxy_wallet=sample_trade.proxy_wallet,
            timestamp=sample_trade.timestamp,
            condition_id=sample_trade.condition_id,
            transaction_hash="0xtxsell003",
            price=0.52,
            size=sample_trade.size,
            usdc_size=sample_trade.usdc_size,
            side="SELL",
            outcome="Yes",
            title=sample_trade.title,
            slug=sample_trade.slug,
            event_slug=sample_trade.event_slug,
        )
        result = trade_filter.evaluate(
            sell_trade, sample_market, cfg, has_open_position=True
        )
        assert result.passed is False
        assert "desabilitado" in result.reason

    def test_fails_max_exposure_reached(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        result = trade_filter.evaluate(
            sample_trade, sample_market, config, current_exposure=98.0
        )
        assert result.passed is False
        assert "Exposição" in result.reason

    def test_filter_reason_message_is_descriptive(
        self,
        trade_filter: TradeFilter,
        sample_trade: TraderTrade,
        sample_market: MarketInfo,
        config: Config,
    ) -> None:
        market = MarketInfo(
            condition_id=sample_market.condition_id,
            question=sample_market.question,
            category="sports",
            volume=1000.0,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            is_resolved=False,
            yes_price=sample_market.yes_price,
            no_price=sample_market.no_price,
            slug=sample_market.slug,
        )
        result = trade_filter.evaluate(sample_trade, market, config)
        assert result.passed is False
        assert "$" in result.reason
        assert "1000" in result.reason or "5000" in result.reason
