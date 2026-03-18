"""Data models used across the bot (pure dataclasses, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraderTrade:
    """A single trade detected from a monitored trader."""

    proxy_wallet: str
    timestamp: int  # Unix timestamp
    condition_id: str
    transaction_hash: str
    price: float  # 0.0–1.0 implied probability
    size: float  # Number of shares
    usdc_size: float  # Value in USDC
    side: str  # "BUY" or "SELL"
    outcome: str  # "Yes" or "No"
    title: str  # Market question
    slug: str  # Market slug
    event_slug: str  # Event slug
    trader_name: str = ""
    token_id: str = ""  # Asset / token ID


@dataclass
class MarketInfo:
    """Information about a Polymarket market."""

    condition_id: str
    question: str
    category: str  # "sports", "crypto", "politics", etc.
    volume: float  # Total volume in USDC
    liquidity: float
    end_date: datetime
    is_resolved: bool
    yes_price: float  # Current YES token price
    no_price: float  # Current NO token price
    slug: str = ""
    resolved_outcome: str = ""  # "Yes" or "No" if resolved


@dataclass
class Position:
    """A tracked position in the local database."""

    condition_id: str
    token_id: str
    side: str  # "BUY"
    outcome: str  # "Yes" or "No"
    entry_price: float
    shares: float
    usdc_invested: float
    trader_copied: str
    market_title: str
    opened_at: int  # Unix timestamp
    status: str = "open"  # "open", "won", "lost", "sold"
    id: int | None = None
    closed_at: int | None = None
    pnl: float | None = None
    order_id: str | None = None
    dry_run: bool = False


@dataclass
class FilterResult:
    """Result of evaluating a trade against quality filters."""

    passed: bool
    reason: str  # "OK" or rejection reason


@dataclass
class OrderResult:
    """Result from placing an order on the CLOB."""

    order_id: str
    status: str  # "live", "filled", "canceled", "simulated"
    price: float = 0.0
    size: float = 0.0
    filled_size: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionResult:
    """Result of attempting to execute a copy trade."""

    success: bool
    order_id: str | None = None
    price: float = 0.0
    usdc_spent: float = 0.0
    error: str | None = None
    dry_run: bool = False
