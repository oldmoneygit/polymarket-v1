"""Unit tests for src/discovery/leaderboard.py."""

from __future__ import annotations

import pytest

from src.discovery.leaderboard import LeaderboardScanner, TraderProfile


class TestTraderProfile:
    def test_is_copyable_when_meets_criteria(self) -> None:
        p = TraderProfile(
            address="0xabc",
            username="TopTrader",
            profit_loss=5000.0,
            volume=100000.0,
            positions_count=200,
            markets_traded=50,
            profit_rate=0.05,
            gain=10000.0,
            loss=3000.0,
            gain_loss_ratio=3.33,
            score=80.0,
        )
        assert p.is_copyable is True

    def test_not_copyable_low_profit_rate(self) -> None:
        p = TraderProfile(
            address="0xabc",
            username="LowProfit",
            profit_loss=100.0,
            volume=100000.0,
            positions_count=200,
            markets_traded=50,
            profit_rate=0.001,  # Below 2%
            gain=1000.0,
            loss=900.0,
            gain_loss_ratio=1.11,
            score=10.0,
        )
        assert p.is_copyable is False

    def test_not_copyable_low_gain_loss(self) -> None:
        p = TraderProfile(
            address="0xabc",
            username="EvenTrader",
            profit_loss=1000.0,
            volume=100000.0,
            positions_count=200,
            markets_traded=50,
            profit_rate=0.03,
            gain=5000.0,
            loss=4000.0,
            gain_loss_ratio=1.25,  # Below 2.0
            score=30.0,
        )
        assert p.is_copyable is False

    def test_not_copyable_too_few_trades(self) -> None:
        p = TraderProfile(
            address="0xabc",
            username="Newbie",
            profit_loss=5000.0,
            volume=10000.0,
            positions_count=20,  # Below 100
            markets_traded=5,
            profit_rate=0.50,
            gain=8000.0,
            loss=3000.0,
            gain_loss_ratio=2.67,
            score=50.0,
        )
        assert p.is_copyable is False


class TestLeaderboardScanner:
    def test_parse_profile_valid_data(self) -> None:
        scanner = LeaderboardScanner()
        raw = {
            "proxyWallet": "0x" + "ab" * 20,
            "username": "TestTrader",
            "pnl": 5000.0,
            "volume": 100000.0,
            "positionsCount": 300,
            "marketsTraded": 80,
            "gain": 15000.0,
            "loss": -5000.0,
        }
        profile = scanner._parse_profile(raw)
        assert profile is not None
        assert profile.profit_rate == pytest.approx(0.05)
        assert profile.gain_loss_ratio == pytest.approx(3.0)
        assert profile.is_copyable is True

    def test_parse_profile_missing_address_returns_none(self) -> None:
        scanner = LeaderboardScanner()
        raw = {"username": "NoAddress", "pnl": 100}
        assert scanner._parse_profile(raw) is None

    def test_format_discovery_message_empty(self) -> None:
        msg = LeaderboardScanner.format_discovery_message([])
        assert "Nenhum" in msg

    def test_format_discovery_message_with_profiles(self) -> None:
        profiles = [
            TraderProfile(
                address="0x" + "ab" * 20,
                username="Alpha",
                profit_loss=10000.0,
                volume=200000.0,
                positions_count=500,
                markets_traded=100,
                profit_rate=0.05,
                gain=20000.0,
                loss=10000.0,
                gain_loss_ratio=2.0,
                score=75.0,
            )
        ]
        msg = LeaderboardScanner.format_discovery_message(profiles)
        assert "Alpha" in msg
        assert "/copy" in msg
