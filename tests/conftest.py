"""Shared fixtures for all tests."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.config import Config
from src.db.models import (
    ExecutionResult,
    FilterResult,
    MarketInfo,
    OrderResult,
    Position,
    TraderTrade,
)
from src.db.repository import Repository


@pytest.fixture(autouse=True)
def _block_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent Config.load from reading the real .env file."""
    monkeypatch.setattr("src.config.load_dotenv", lambda *a, **kw: None)


@pytest.fixture()
def env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set minimal valid environment variables and return them."""
    vals = {
        "POLY_API_KEY": "test-api-key",
        "POLY_API_SECRET": "test-api-secret",
        "POLY_API_PASSPHRASE": "test-passphrase",
        "POLY_WALLET_ADDRESS": "0x" + "a1" * 20,
        "POLY_PRIVATE_KEY": "",
        "TRADER_WALLETS": "0x" + "b2" * 20,
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
        "TELEGRAM_CHAT_ID": "8512554637",
        "CAPITAL_PER_TRADE_USD": "5.0",
        "MAX_TOTAL_EXPOSURE_USD": "100.0",
        "MAX_DAILY_LOSS_USD": "20.0",
        "MIN_MARKET_VOLUME_USD": "5000.0",
        "MIN_PROBABILITY": "0.30",
        "MAX_PROBABILITY": "0.75",
        "MAX_TRADE_AGE_MINUTES": "60",
        "TAKE_PROFIT_PCT": "0.20",
        "SLIPPAGE_TOLERANCE": "0.02",
        "DRY_RUN": "true",
        "POLL_INTERVAL_SECONDS": "30",
        "POSITION_CHECK_INTERVAL_SECONDS": "60",
        "LOG_LEVEL": "DEBUG",
    }
    for k, v in vals.items():
        monkeypatch.setenv(k, v)
    return vals


@pytest.fixture()
def config(env_vars: dict[str, str]) -> Config:
    """Return a valid Config loaded from env_vars fixture."""
    return Config.load()


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Repository:
    """Return a Repository backed by a temp SQLite file."""
    repo = Repository(db_path=tmp_path / "test.db")
    yield repo
    repo.close()


@pytest.fixture()
def sample_trade() -> TraderTrade:
    return TraderTrade(
        proxy_wallet="0x" + "b2" * 20,
        timestamp=int(time.time()) - 300,  # 5 min ago
        condition_id="0xcond123",
        transaction_hash="0xtxhash001",
        price=0.52,
        size=100.0,
        usdc_size=52.0,
        side="BUY",
        outcome="Yes",
        title="Will PSG win on 2026-03-11?",
        slug="ucl-psg1-cfc1-2026-03-11-psg1",
        event_slug="ucl-psg1-cfc1-2026-03-11",
        trader_name="HorizonSplendidView",
        token_id="token123",
    )


@pytest.fixture()
def sample_market() -> MarketInfo:
    return MarketInfo(
        condition_id="0xcond123",
        question="Will PSG win on 2026-03-11?",
        category="sports",
        volume=50000.0,
        liquidity=10000.0,
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        is_resolved=False,
        yes_price=0.52,
        no_price=0.48,
        slug="ucl-psg1-cfc1-2026-03-11-psg1",
    )


@pytest.fixture()
def sample_position() -> Position:
    return Position(
        id=1,
        condition_id="0xcond123",
        token_id="token123",
        side="BUY",
        outcome="Yes",
        entry_price=0.52,
        shares=9.62,
        usdc_invested=5.0,
        trader_copied="0x" + "b2" * 20,
        market_title="Will PSG win on 2026-03-11?",
        opened_at=int(time.time()) - 3600,
        status="open",
        dry_run=True,
    )
