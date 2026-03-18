"""SQLite repository for persistence — no ORM, raw sqlite3."""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from src.db.models import Position

_DEFAULT_DB_PATH = Path("data/polymarket_bot.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seen_hashes (
    hash TEXT PRIMARY KEY,
    trader_wallet TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    usdc_invested REAL NOT NULL,
    trader_copied TEXT NOT NULL,
    market_title TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    closed_at INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    pnl REAL,
    order_id TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class Repository:
    """Lightweight SQLite repository for the bot's persistent data."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._run_migrations()

    def _run_migrations(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── seen_hashes ──────────────────────────────────────────────

    def save_seen_hash(self, hash_: str, trader_wallet: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_hashes (hash, trader_wallet, created_at) "
            "VALUES (?, ?, ?)",
            (hash_, trader_wallet, int(time.time())),
        )
        self._conn.commit()

    def is_seen(self, hash_: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_hashes WHERE hash = ?", (hash_,)
        ).fetchone()
        return row is not None

    def load_seen_hashes(self, days_back: int = 7) -> set[str]:
        cutoff = int(time.time()) - (days_back * 86400)
        rows = self._conn.execute(
            "SELECT hash FROM seen_hashes WHERE created_at >= ?", (cutoff,)
        ).fetchall()
        return {row["hash"] for row in rows}

    # ── positions ────────────────────────────────────────────────

    def save_position(self, position: Position) -> int:
        cursor = self._conn.execute(
            "INSERT INTO positions "
            "(condition_id, token_id, side, outcome, entry_price, shares, "
            "usdc_invested, trader_copied, market_title, opened_at, "
            "closed_at, status, pnl, order_id, dry_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                position.condition_id,
                position.token_id,
                position.side,
                position.outcome,
                position.entry_price,
                position.shares,
                position.usdc_invested,
                position.trader_copied,
                position.market_title,
                position.opened_at,
                position.closed_at,
                position.status,
                position.pnl,
                position.order_id,
                1 if position.dry_run else 0,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_open_positions(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE status = 'open'"
        ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def update_position_result(
        self, position_id: int, status: str, pnl: float
    ) -> None:
        self._conn.execute(
            "UPDATE positions SET status = ?, pnl = ?, closed_at = ? WHERE id = ?",
            (status, pnl, int(time.time()), position_id),
        )
        self._conn.commit()

    def find_open_position(
        self, condition_id: str, outcome: str
    ) -> Position | None:
        """Find an existing open position for a condition+outcome."""
        row = self._conn.execute(
            "SELECT * FROM positions WHERE condition_id = ? AND outcome = ? AND status = 'open' LIMIT 1",
            (condition_id, outcome),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_position(row)

    def update_position_average(
        self, position_id: int, shares: float, usdc_invested: float, avg_price: float
    ) -> None:
        """Update a position with averaged-in values."""
        self._conn.execute(
            "UPDATE positions SET shares = ?, usdc_invested = ?, entry_price = ? WHERE id = ?",
            (shares, usdc_invested, avg_price, position_id),
        )
        self._conn.commit()

    def get_total_open_exposure(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(usdc_invested), 0.0) AS total "
            "FROM positions WHERE status = 'open'"
        ).fetchone()
        return float(row["total"])

    # ── P&L ──────────────────────────────────────────────────────

    def get_daily_pnl(self, target_date: date | None = None) -> float:
        if target_date is None:
            target_date = datetime.now(timezone.utc).date()
        start_ts = int(
            datetime(
                target_date.year, target_date.month, target_date.day,
                tzinfo=timezone.utc,
            ).timestamp()
        )
        end_ts = start_ts + 86400
        row = self._conn.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) AS total "
            "FROM positions WHERE closed_at >= ? AND closed_at < ? AND pnl IS NOT NULL",
            (start_ts, end_ts),
        ).fetchone()
        return float(row["total"])

    def get_total_pnl(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) AS total "
            "FROM positions WHERE pnl IS NOT NULL"
        ).fetchone()
        return float(row["total"])

    def get_pnl_history(self, days: int = 30) -> list[tuple[date, float]]:
        cutoff = int(time.time()) - (days * 86400)
        rows = self._conn.execute(
            "SELECT closed_at, pnl FROM positions "
            "WHERE closed_at >= ? AND pnl IS NOT NULL "
            "ORDER BY closed_at",
            (cutoff,),
        ).fetchall()
        daily: dict[date, float] = {}
        for row in rows:
            d = datetime.fromtimestamp(row["closed_at"], tz=timezone.utc).date()
            daily[d] = daily.get(d, 0.0) + row["pnl"]
        return sorted(daily.items())

    # ── bot_state ────────────────────────────────────────────────

    def get_state(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (key, value, int(time.time())),
        )
        self._conn.commit()

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            id=row["id"],
            condition_id=row["condition_id"],
            token_id=row["token_id"],
            side=row["side"],
            outcome=row["outcome"],
            entry_price=row["entry_price"],
            shares=row["shares"],
            usdc_invested=row["usdc_invested"],
            trader_copied=row["trader_copied"],
            market_title=row["market_title"],
            opened_at=row["opened_at"],
            closed_at=row["closed_at"],
            status=row["status"],
            pnl=row["pnl"],
            order_id=row["order_id"],
            dry_run=bool(row["dry_run"]),
        )
