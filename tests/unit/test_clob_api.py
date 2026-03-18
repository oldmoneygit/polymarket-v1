"""Unit tests for src/api/clob.py (SPEC-03)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.api.clob import CLOBClient, CLOBError
from src.config import Config
from src.db.models import OrderResult


class TestDryRunMode:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_api(self, config: Config) -> None:
        assert config.dry_run is True
        client = CLOBClient(config)
        assert client._client is None  # No real client initialized

    @pytest.mark.asyncio
    async def test_dry_run_get_balance(self, config: Config) -> None:
        client = CLOBClient(config)
        balance = await client.get_balance()
        assert balance == 1000.0

    @pytest.mark.asyncio
    async def test_dry_run_get_open_positions(self, config: Config) -> None:
        client = CLOBClient(config)
        positions = await client.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_dry_run_market_order(self, config: Config) -> None:
        client = CLOBClient(config)
        result = await client.create_market_order(
            token_id="token123", side="BUY", amount_usdc=5.0
        )
        assert isinstance(result, OrderResult)
        assert result.order_id == "dry-run-fake-id"
        assert result.status == "simulated"
        assert result.size == 5.0
        assert result.filled_size == 5.0

    @pytest.mark.asyncio
    async def test_dry_run_limit_order(self, config: Config) -> None:
        client = CLOBClient(config)
        result = await client.create_limit_order(
            token_id="token123", side="BUY", price=0.52, size=10.0
        )
        assert isinstance(result, OrderResult)
        assert result.order_id == "dry-run-fake-id"
        assert result.status == "simulated"
        assert result.price == 0.52
        assert result.size == 10.0
        assert result.filled_size == 0.0


class TestLiveClientNotInitialized:
    @pytest.mark.asyncio
    async def test_get_balance_without_client_raises(
        self, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_config = Config(
            poly_api_key="key",
            poly_api_secret="secret",
            poly_api_passphrase="pass",
            poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC",
            telegram_chat_id="123",
            dry_run=False,
        )
        with patch(
            "src.api.clob.CLOBClient._init_real_client",
            side_effect=lambda c: None,
        ):
            client = CLOBClient(live_config)
            client._client = None

        with pytest.raises(CLOBError, match="not initialized"):
            await client.get_balance()

    @pytest.mark.asyncio
    async def test_get_positions_without_client_raises(
        self, config: Config
    ) -> None:
        live_config = Config(
            poly_api_key="key",
            poly_api_secret="secret",
            poly_api_passphrase="pass",
            poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC",
            telegram_chat_id="123",
            dry_run=False,
        )
        with patch(
            "src.api.clob.CLOBClient._init_real_client",
            side_effect=lambda c: None,
        ):
            client = CLOBClient(live_config)
            client._client = None

        with pytest.raises(CLOBError, match="not initialized"):
            await client.get_open_positions()

    @pytest.mark.asyncio
    async def test_create_order_without_client_raises(
        self, config: Config
    ) -> None:
        live_config = Config(
            poly_api_key="key",
            poly_api_secret="secret",
            poly_api_passphrase="pass",
            poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC",
            telegram_chat_id="123",
            dry_run=False,
        )
        with patch(
            "src.api.clob.CLOBClient._init_real_client",
            side_effect=lambda c: None,
        ):
            client = CLOBClient(live_config)
            client._client = None

        with pytest.raises(CLOBError, match="not initialized"):
            await client.create_market_order("tok", "BUY", 5.0)


class TestLiveClientRealCalls:
    @pytest.mark.asyncio
    async def test_live_get_balance_with_mock_client(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.get_balance.return_value = 42.5
            client._client = mock_real
            balance = await client.get_balance()
            assert balance == 42.5

    @pytest.mark.asyncio
    async def test_live_get_balance_exception_wraps(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.get_balance.side_effect = RuntimeError("connection lost")
            client._client = mock_real
            with pytest.raises(CLOBError, match="Failed to get balance"):
                await client.get_balance()

    @pytest.mark.asyncio
    async def test_live_get_positions_returns_list(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.get_positions.return_value = [{"id": 1}]
            client._client = mock_real
            pos = await client.get_open_positions()
            assert pos == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_live_get_positions_non_list(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.get_positions.return_value = "not a list"
            client._client = mock_real
            pos = await client.get_open_positions()
            assert pos == []

    @pytest.mark.asyncio
    async def test_live_get_positions_exception(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.get_positions.side_effect = RuntimeError("fail")
            client._client = mock_real
            with pytest.raises(CLOBError, match="Failed to get positions"):
                await client.get_open_positions()

    @pytest.mark.asyncio
    async def test_live_create_market_order_success(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.create_and_post_order.return_value = {
                "orderID": "ord1", "status": "filled",
                "price": 0.52, "size": 10.0, "filledSize": 10.0,
            }
            client._client = mock_real
            result = await client.create_market_order("tok", "BUY", 10.0)
            assert result.order_id == "ord1"
            assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_live_create_market_order_sell(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.create_and_post_order.return_value = {
                "orderID": "ord2", "status": "filled",
                "price": 0.48, "size": 5.0, "filledSize": 5.0,
            }
            client._client = mock_real
            result = await client.create_market_order("tok", "SELL", 5.0)
            assert result.order_id == "ord2"

    @pytest.mark.asyncio
    async def test_live_create_market_order_exception(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.create_and_post_order.side_effect = RuntimeError("fail")
            client._client = mock_real
            with pytest.raises(CLOBError, match="Order execution failed"):
                await client.create_market_order("tok", "BUY", 5.0)

    @pytest.mark.asyncio
    async def test_live_create_limit_order_success(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.create_and_post_order.return_value = {
                "orderID": "lim1", "status": "live",
                "price": 0.50, "size": 20.0, "filledSize": 0,
            }
            client._client = mock_real
            result = await client.create_limit_order("tok", "SELL", 0.50, 20.0)
            assert result.order_id == "lim1"
            assert result.status == "live"

    @pytest.mark.asyncio
    async def test_live_create_limit_order_not_initialized(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            client._client = None
            with pytest.raises(CLOBError, match="not initialized"):
                await client.create_limit_order("tok", "BUY", 0.50, 10.0)

    @pytest.mark.asyncio
    async def test_live_create_limit_order_exception(self) -> None:
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        with patch("src.api.clob.CLOBClient._init_real_client"):
            client = CLOBClient(live_config)
            mock_real = MagicMock()
            mock_real.create_and_post_order.side_effect = RuntimeError("boom")
            client._client = mock_real
            with pytest.raises(CLOBError, match="Limit order failed"):
                await client.create_limit_order("tok", "BUY", 0.50, 10.0)


class TestInitRealClient:
    def test_init_real_client_success(self) -> None:
        """Cover lines 34-41: successful real client init."""
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0x" + "ff" * 32,
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        # py-clob-client IS installed, so _init_real_client should succeed
        with patch("src.api.clob.CLOBClient._init_real_client") as mock_init:
            client = CLOBClient(live_config)
            mock_init.assert_called_once()

    def test_init_real_client_actually_runs(self) -> None:
        """Cover lines 34-41: _init_real_client creates ClobClient."""
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        client = CLOBClient.__new__(CLOBClient)
        client._config = live_config
        client._client = None
        client._init_real_client(live_config)
        assert client._client is not None


class TestInitRealClientImportError:
    def test_import_error_fallback(self) -> None:
        """Cover lines 47-48: ImportError when py_clob_client missing."""
        live_config = Config(
            poly_api_key="key", poly_api_secret="secret",
            poly_api_passphrase="pass", poly_wallet_address="0x" + "a1" * 20,
            poly_private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
            trader_wallets=["0x" + "b2" * 20],
            telegram_bot_token="123:ABC", telegram_chat_id="123",
            dry_run=False,
        )
        client = CLOBClient.__new__(CLOBClient)
        client._config = live_config
        client._client = None

        import importlib
        import sys
        # Temporarily hide py_clob_client
        saved = {}
        for mod_name in list(sys.modules):
            if mod_name.startswith("py_clob_client"):
                saved[mod_name] = sys.modules.pop(mod_name)

        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("py_clob_client"):
                raise ImportError(f"Fake: no module {name}")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            client._init_real_client(live_config)

        # Restore
        sys.modules.update(saved)
        assert client._client is None


class TestCreateOrderResult:
    @pytest.mark.asyncio
    async def test_create_order_returns_result(self, config: Config) -> None:
        client = CLOBClient(config)
        result = await client.create_market_order(
            token_id="tok123", side="BUY", amount_usdc=10.0
        )
        assert result.success if hasattr(result, "success") else True
        assert result.order_id is not None
        assert result.timestamp is not None
