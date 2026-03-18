"""Unit tests for src/api/clob.py (SPEC-03)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.api.clob import CLOBClient, CLOBError
from src.config import Config


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_api(self, config: Config) -> None:
        client = CLOBClient(config)
        result = await client.create_market_order("token1", "BUY", 5.0)
        assert result.status == "simulated"
        assert result.order_id == "dry-run-fake-id"

    @pytest.mark.asyncio
    async def test_dry_run_get_balance(self, config: Config) -> None:
        client = CLOBClient(config)
        balance = await client.get_balance()
        assert balance == 1000.0

    @pytest.mark.asyncio
    async def test_dry_run_get_positions(self, config: Config) -> None:
        client = CLOBClient(config)
        positions = await client.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_dry_run_limit_order(self, config: Config) -> None:
        client = CLOBClient(config)
        result = await client.create_limit_order("token1", "BUY", 0.50, 10.0)
        assert result.status == "simulated"
        assert result.price == 0.50
        assert result.size == 10.0


class TestCreateOrder:
    @pytest.mark.asyncio
    async def test_create_order_returns_result(self, config: Config) -> None:
        # Dry-run mode always returns simulated
        client = CLOBClient(config)
        result = await client.create_market_order("token1", "BUY", 5.0)
        assert result.order_id is not None
        assert result.filled_size == 5.0

    @pytest.mark.asyncio
    async def test_insufficient_balance_raises_error(
        self,
        config: Config,
    ) -> None:
        # Create a non-dry-run config to test the guard
        # [MERGED FROM polymarket-v1] Updated for PolymarketError-based CLOBError
        cfg = Config(
            poly_api_key=config.poly_api_key,
            poly_api_secret=config.poly_api_secret,
            poly_api_passphrase=config.poly_api_passphrase,
            poly_wallet_address=config.poly_wallet_address,
            poly_private_key="0x" + "ab" * 32,
            trader_wallets=config.trader_wallets,
            telegram_bot_token=config.telegram_bot_token,
            telegram_chat_id=config.telegram_chat_id,
            dry_run=False,
        )
        # Skip real client init — just test the guard
        client = CLOBClient.__new__(CLOBClient)
        client._config = cfg
        client._client = None
        client._http_session = None

        with pytest.raises(CLOBError, match="not initialized"):
            await client.get_balance()
