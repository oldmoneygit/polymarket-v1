"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _env_float(key: str, default: float | None = None) -> float:
    raw = os.getenv(key)
    if raw is None:
        if default is not None:
            return default
        raise ConfigError(f"Missing required environment variable: {key}")
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"Invalid float for {key}: {raw!r}")


def _env_int(key: str, default: int | None = None) -> int:
    raw = os.getenv(key)
    if raw is None:
        if default is not None:
            return default
        raise ConfigError(f"Missing required environment variable: {key}")
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"Invalid integer for {key}: {raw!r}")


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes")


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _validate_eth_address(address: str, label: str) -> str:
    if not _ETH_ADDRESS_RE.match(address):
        raise ConfigError(f"Invalid Ethereum address for {label}: {address!r}")
    return address.lower()


@dataclass(frozen=True)
class Config:
    # Polymarket API
    poly_api_key: str
    poly_api_secret: str
    poly_api_passphrase: str
    poly_wallet_address: str
    poly_private_key: str

    # Traders
    trader_wallets: list[str] = field(default_factory=list)

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Strategy
    capital_per_trade_usd: float = 5.0
    max_total_exposure_usd: float = 100.0
    max_daily_loss_usd: float = 20.0
    min_market_volume_usd: float = 5000.0
    min_probability: float = 0.30
    max_probability: float = 0.75
    max_trade_age_minutes: int = 60
    take_profit_pct: float = 0.20
    slippage_tolerance: float = 0.02

    # Copy sizing: "fixed" | "proportional" | "portfolio" | "kelly"
    copy_size_mode: str = "fixed"
    copy_size_multiplier: float = 0.01  # For proportional: 1% of trader's size
    max_copy_trade_usd: float = 25.0  # Max per individual copied trade
    kelly_fraction: float = 0.25  # Quarter-Kelly (conservative)

    # Market filter
    market_categories: list[str] = field(default_factory=lambda: ["all"])
    copy_sell: bool = True  # Also copy SELL trades

    # Confluence
    confluence_enabled: bool = True
    confluence_boost_moderate: float = 1.5  # Size multiplier for MODERATE confluence
    confluence_boost_strong: float = 2.0  # Size multiplier for STRONG confluence

    # Operation
    dry_run: bool = True
    poll_interval_seconds: int = 5
    position_check_interval_seconds: int = 60
    log_level: str = "INFO"

    @classmethod
    def load(cls, env_path: str | Path | None = None) -> Config:
        """Load configuration from .env file and environment variables."""
        if env_path:
            load_dotenv(env_path, override=True)
        else:
            load_dotenv(override=True)

        dry_run = _env_bool("DRY_RUN", default=True)

        # Private key is optional in dry-run mode
        poly_private_key = os.getenv("POLY_PRIVATE_KEY", "")
        if not dry_run and not poly_private_key:
            raise ConfigError(
                "POLY_PRIVATE_KEY is required when DRY_RUN is disabled"
            )

        poly_api_key = _env("POLY_API_KEY")
        poly_api_secret = _env("POLY_API_SECRET")
        poly_api_passphrase = _env("POLY_API_PASSPHRASE")

        if not poly_api_key:
            raise ConfigError("POLY_API_KEY must not be empty")
        if not poly_api_secret:
            raise ConfigError("POLY_API_SECRET must not be empty")
        if not poly_api_passphrase:
            raise ConfigError("POLY_API_PASSPHRASE must not be empty")

        poly_wallet_address = _validate_eth_address(
            _env("POLY_WALLET_ADDRESS"), "POLY_WALLET_ADDRESS"
        )

        # Trader wallets
        raw_wallets = _env("TRADER_WALLETS", "")
        wallets = [
            _validate_eth_address(w.strip(), "TRADER_WALLETS")
            for w in raw_wallets.split(",")
            if w.strip()
        ]
        if not wallets:
            raise ConfigError("TRADER_WALLETS must contain at least 1 valid address")

        telegram_bot_token = _env("TELEGRAM_BOT_TOKEN")
        if not telegram_bot_token:
            raise ConfigError("TELEGRAM_BOT_TOKEN must not be empty")

        telegram_chat_id = _env("TELEGRAM_CHAT_ID")
        if not telegram_chat_id.lstrip("-").isdigit():
            raise ConfigError(
                f"TELEGRAM_CHAT_ID must be numeric, got: {telegram_chat_id!r}"
            )

        # Strategy
        capital_per_trade_usd = _env_float("CAPITAL_PER_TRADE_USD", 5.0)
        max_total_exposure_usd = _env_float("MAX_TOTAL_EXPOSURE_USD", 100.0)
        max_daily_loss_usd = _env_float("MAX_DAILY_LOSS_USD", 20.0)
        min_market_volume_usd = _env_float("MIN_MARKET_VOLUME_USD", 5000.0)
        min_probability = _env_float("MIN_PROBABILITY", 0.30)
        max_probability = _env_float("MAX_PROBABILITY", 0.75)
        max_trade_age_minutes = _env_int("MAX_TRADE_AGE_MINUTES", 60)
        take_profit_pct = _env_float("TAKE_PROFIT_PCT", 0.20)
        slippage_tolerance = _env_float("SLIPPAGE_TOLERANCE", 0.02)

        if capital_per_trade_usd <= 0:
            raise ConfigError("CAPITAL_PER_TRADE_USD must be > 0")
        if capital_per_trade_usd > max_total_exposure_usd:
            raise ConfigError(
                "CAPITAL_PER_TRADE_USD must be <= MAX_TOTAL_EXPOSURE_USD"
            )
        if not (0.0 <= min_probability < max_probability <= 1.0):
            raise ConfigError(
                f"Invalid probability range: {min_probability} to {max_probability} "
                f"(must be 0 <= min < max <= 1)"
            )

        # Copy sizing
        copy_size_mode = _env("COPY_SIZE_MODE", "fixed").lower()
        if copy_size_mode not in ("fixed", "proportional", "portfolio", "kelly"):
            raise ConfigError(
                f"COPY_SIZE_MODE must be fixed|proportional|portfolio, got: {copy_size_mode!r}"
            )
        copy_size_multiplier = _env_float("COPY_SIZE_MULTIPLIER", 0.01)
        max_copy_trade_usd = _env_float("MAX_COPY_TRADE_USD", 25.0)
        kelly_fraction = _env_float("KELLY_FRACTION", 0.25)

        # Market categories
        raw_categories = _env("MARKET_CATEGORIES", "all")
        market_categories = [c.strip().lower() for c in raw_categories.split(",") if c.strip()]

        copy_sell = _env_bool("COPY_SELL", default=True)

        # Confluence
        confluence_enabled = _env_bool("CONFLUENCE_ENABLED", default=True)
        confluence_boost_moderate = _env_float("CONFLUENCE_BOOST_MODERATE", 1.5)
        confluence_boost_strong = _env_float("CONFLUENCE_BOOST_STRONG", 2.0)

        poll_interval_seconds = _env_int("POLL_INTERVAL_SECONDS", 5)
        position_check_interval_seconds = _env_int(
            "POSITION_CHECK_INTERVAL_SECONDS", 60
        )
        log_level = _env("LOG_LEVEL", "INFO").upper()

        config = cls(
            poly_api_key=poly_api_key,
            poly_api_secret=poly_api_secret,
            poly_api_passphrase=poly_api_passphrase,
            poly_wallet_address=poly_wallet_address,
            poly_private_key=poly_private_key,
            trader_wallets=wallets,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            capital_per_trade_usd=capital_per_trade_usd,
            max_total_exposure_usd=max_total_exposure_usd,
            max_daily_loss_usd=max_daily_loss_usd,
            min_market_volume_usd=min_market_volume_usd,
            min_probability=min_probability,
            max_probability=max_probability,
            max_trade_age_minutes=max_trade_age_minutes,
            take_profit_pct=take_profit_pct,
            slippage_tolerance=slippage_tolerance,
            copy_size_mode=copy_size_mode,
            copy_size_multiplier=copy_size_multiplier,
            max_copy_trade_usd=max_copy_trade_usd,
            kelly_fraction=kelly_fraction,
            market_categories=market_categories,
            copy_sell=copy_sell,
            confluence_enabled=confluence_enabled,
            confluence_boost_moderate=confluence_boost_moderate,
            confluence_boost_strong=confluence_boost_strong,
            dry_run=dry_run,
            poll_interval_seconds=poll_interval_seconds,
            position_check_interval_seconds=position_check_interval_seconds,
            log_level=log_level,
        )

        if dry_run:
            logger.warning(
                "\U0001f9ea DRY RUN MODE \u2014 nenhum trade real ser\u00e1 executado"
            )

        return config
