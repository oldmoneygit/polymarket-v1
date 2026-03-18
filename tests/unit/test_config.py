"""Unit tests for src/config.py (SPEC-01)."""

from __future__ import annotations

import pytest

from src.config import Config, ConfigError


class TestConfigLoadsValidEnv:
    def test_config_loads_valid_env(self, env_vars: dict[str, str]) -> None:
        cfg = Config.load()
        assert cfg.poly_api_key == "test-api-key"
        assert cfg.poly_api_secret == "test-api-secret"
        assert cfg.poly_api_passphrase == "test-passphrase"
        assert cfg.poly_wallet_address == ("0x" + "a1" * 20).lower()
        assert cfg.dry_run is True
        assert cfg.capital_per_trade_usd == 5.0
        assert cfg.max_total_exposure_usd == 100.0
        assert cfg.min_probability == 0.30
        assert cfg.max_probability == 0.75

    def test_config_raises_on_missing_api_key(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("POLY_API_KEY")
        with pytest.raises(ConfigError, match="POLY_API_KEY"):
            Config.load()

    def test_config_raises_on_invalid_wallet_address(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POLY_WALLET_ADDRESS", "not-an-address")
        with pytest.raises(ConfigError, match="Invalid Ethereum address"):
            Config.load()

    def test_config_raises_on_invalid_probability_range(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MIN_PROBABILITY", "0.80")
        monkeypatch.setenv("MAX_PROBABILITY", "0.30")
        with pytest.raises(ConfigError, match="Invalid probability range"):
            Config.load()

    def test_config_dry_run_does_not_require_private_key(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.delenv("POLY_PRIVATE_KEY", raising=False)
        cfg = Config.load()
        assert cfg.dry_run is True
        assert cfg.poly_private_key == ""

    def test_config_live_requires_private_key(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("POLY_PRIVATE_KEY", "")
        with pytest.raises(ConfigError, match="POLY_PRIVATE_KEY"):
            Config.load()

    def test_config_parses_trader_wallets_list(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w1 = "0x" + "aa" * 20
        w2 = "0x" + "bb" * 20
        monkeypatch.setenv("TRADER_WALLETS", f"{w1},{w2}")
        cfg = Config.load()
        assert len(cfg.trader_wallets) == 2
        assert cfg.trader_wallets[0] == w1.lower()
        assert cfg.trader_wallets[1] == w2.lower()

    def test_config_defaults_applied_when_optional_missing(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Remove optional vars to test defaults
        monkeypatch.delenv("CAPITAL_PER_TRADE_USD", raising=False)
        monkeypatch.delenv("POLL_INTERVAL_SECONDS", raising=False)
        cfg = Config.load()
        assert cfg.capital_per_trade_usd == 5.0
        assert cfg.poll_interval_seconds == 5

    def test_config_raises_on_empty_trader_wallets(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRADER_WALLETS", "")
        with pytest.raises(ConfigError, match="at least 1"):
            Config.load()

    def test_config_raises_on_non_numeric_chat_id(
        self, env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-number")
        with pytest.raises(ConfigError, match="numeric"):
            Config.load()
