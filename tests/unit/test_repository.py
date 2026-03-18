"""Unit tests for src/db/repository.py (SPEC-09)."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.db.models import Position
from src.db.repository import Repository


class TestSeenHashes:
    def test_save_and_check_seen_hash(self, tmp_db: Repository) -> None:
        tmp_db.save_seen_hash("0xhash1", "0xwallet1")
        assert tmp_db.is_seen("0xhash1") is True

    def test_is_seen_returns_false_for_unknown(self, tmp_db: Repository) -> None:
        assert tmp_db.is_seen("0xnonexistent") is False

    def test_load_seen_hashes_respects_days_back(self, tmp_db: Repository) -> None:
        # Insert a hash with old timestamp (manually)
        old_ts = int(time.time()) - (10 * 86400)  # 10 days ago
        tmp_db._conn.execute(
            "INSERT INTO seen_hashes (hash, trader_wallet, created_at) VALUES (?, ?, ?)",
            ("old_hash", "0xw", old_ts),
        )
        tmp_db._conn.commit()

        # Insert a recent hash
        tmp_db.save_seen_hash("recent_hash", "0xw")

        hashes = tmp_db.load_seen_hashes(days_back=7)
        assert "recent_hash" in hashes
        assert "old_hash" not in hashes

    def test_duplicate_hash_ignored(self, tmp_db: Repository) -> None:
        tmp_db.save_seen_hash("0xdup", "0xw")
        tmp_db.save_seen_hash("0xdup", "0xw")  # Should not raise
        assert tmp_db.is_seen("0xdup") is True


class TestPositions:
    def _make_position(self, **overrides: object) -> Position:
        defaults = dict(
            condition_id="cond1",
            token_id="tok1",
            side="BUY",
            outcome="Yes",
            entry_price=0.50,
            shares=10.0,
            usdc_invested=5.0,
            trader_copied="0xtrader",
            market_title="Test Market",
            opened_at=int(time.time()),
            status="open",
            dry_run=True,
        )
        defaults.update(overrides)
        return Position(**defaults)  # type: ignore[arg-type]

    def test_save_and_retrieve_position(self, tmp_db: Repository) -> None:
        pos = self._make_position()
        pid = tmp_db.save_position(pos)
        assert pid >= 1

        positions = tmp_db.get_open_positions()
        assert len(positions) == 1
        assert positions[0].condition_id == "cond1"
        assert positions[0].id == pid

    def test_update_position_result(self, tmp_db: Repository) -> None:
        pos = self._make_position()
        pid = tmp_db.save_position(pos)

        tmp_db.update_position_result(pid, "won", 4.50)
        positions = tmp_db.get_open_positions()
        assert len(positions) == 0  # No longer "open"

    def test_get_total_open_exposure(self, tmp_db: Repository) -> None:
        tmp_db.save_position(self._make_position(usdc_invested=5.0))
        tmp_db.save_position(self._make_position(usdc_invested=10.0, condition_id="c2"))
        assert tmp_db.get_total_open_exposure() == pytest.approx(15.0)

    def test_get_total_open_exposure_empty(self, tmp_db: Repository) -> None:
        assert tmp_db.get_total_open_exposure() == 0.0


class TestPnL:
    def _make_closed_position(
        self, tmp_db: Repository, pnl: float, closed_at: int | None = None
    ) -> int:
        pos = Position(
            condition_id="cond1",
            token_id="tok1",
            side="BUY",
            outcome="Yes",
            entry_price=0.50,
            shares=10.0,
            usdc_invested=5.0,
            trader_copied="0xtrader",
            market_title="Test",
            opened_at=int(time.time()) - 3600,
            status="open",
            dry_run=True,
        )
        pid = tmp_db.save_position(pos)
        close_ts = closed_at or int(time.time())
        tmp_db._conn.execute(
            "UPDATE positions SET status='won', pnl=?, closed_at=? WHERE id=?",
            (pnl, close_ts, pid),
        )
        tmp_db._conn.commit()
        return pid

    def test_get_daily_pnl_empty(self, tmp_db: Repository) -> None:
        assert tmp_db.get_daily_pnl() == 0.0

    def test_get_daily_pnl_with_trades(self, tmp_db: Repository) -> None:
        now = datetime.now(timezone.utc)
        today_ts = int(
            datetime(now.year, now.month, now.day, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        )
        self._make_closed_position(tmp_db, 4.50, closed_at=today_ts)
        self._make_closed_position(tmp_db, -2.00, closed_at=today_ts)

        pnl = tmp_db.get_daily_pnl(now.date())
        assert pnl == pytest.approx(2.50)

    def test_get_total_pnl(self, tmp_db: Repository) -> None:
        self._make_closed_position(tmp_db, 4.50)
        self._make_closed_position(tmp_db, -2.00)
        assert tmp_db.get_total_pnl() == pytest.approx(2.50)


class TestBotState:
    def test_state_get_set(self, tmp_db: Repository) -> None:
        assert tmp_db.get_state("paused", "false") == "false"
        tmp_db.set_state("paused", "true")
        assert tmp_db.get_state("paused") == "true"

    def test_state_overwrite(self, tmp_db: Repository) -> None:
        tmp_db.set_state("key1", "val1")
        tmp_db.set_state("key1", "val2")
        assert tmp_db.get_state("key1") == "val2"


class TestDatabaseInit:
    def test_database_created_on_init(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new_test.db"
        repo = Repository(db_path=db_path)
        assert db_path.exists()
        repo.close()
