"""Unit tests for src/strategy/crypto_arb.py."""

from __future__ import annotations

from src.strategy.crypto_arb import (
    CryptoArbDetector,
    extract_asset,
    is_crypto_short_term,
)


class TestIsCryptoShortTerm:
    def test_btc_5min_market(self) -> None:
        assert is_crypto_short_term(
            "btc-above-100k-5min", "Will BTC be above $100k in 5 minutes?"
        )

    def test_eth_15min_market(self) -> None:
        assert is_crypto_short_term(
            "eth-up-15min", "Will ETH go up in the next 15 minutes?"
        )

    def test_non_crypto_market(self) -> None:
        assert not is_crypto_short_term(
            "ucl-psg-cfc", "Will PSG win against Chelsea?"
        )

    def test_crypto_without_timeframe(self) -> None:
        # Has crypto but no short-term timeframe AND no direction
        assert not is_crypto_short_term(
            "btc-market", "Will BTC exist?"
        )

    def test_crypto_with_direction_no_timeframe(self) -> None:
        assert is_crypto_short_term(
            "btc-above-100k", "Will BTC be above $100k?"
        )


class TestExtractAsset:
    def test_btc(self) -> None:
        assert extract_asset("btc-5min", "Bitcoin 5 min") == "BTC"

    def test_eth(self) -> None:
        assert extract_asset("eth-up", "Ethereum up") == "ETH"

    def test_sol(self) -> None:
        assert extract_asset("sol-15min", "Solana 15 min") == "SOL"

    def test_unknown(self) -> None:
        assert extract_asset("doge-moon", "Dogecoin to the moon") == "UNKNOWN"


class TestCryptoArbDetector:
    def test_detects_arb_when_spot_moves(self) -> None:
        detector = CryptoArbDetector(min_edge_pct=0.02)
        # Simulate spot price going up
        detector.record_spot_price("BTC", 99000.0)
        detector.record_spot_price("BTC", 101000.0)  # ~2% up

        signal = detector.evaluate(
            condition_id="c1",
            question="Will BTC be above $100k in 5 minutes?",
            slug="btc-above-100k-5min",
            polymarket_yes_price=0.50,
            polymarket_no_price=0.50,
        )
        assert signal is not None
        assert signal.asset == "BTC"
        assert signal.direction == "UP"
        assert signal.edge_pct > 0

    def test_no_signal_when_no_spot_data(self) -> None:
        detector = CryptoArbDetector()
        signal = detector.evaluate(
            condition_id="c1",
            question="Will BTC be above $100k in 5 minutes?",
            slug="btc-above-100k-5min",
            polymarket_yes_price=0.50,
            polymarket_no_price=0.50,
        )
        assert signal is None

    def test_no_signal_for_non_crypto(self) -> None:
        detector = CryptoArbDetector()
        detector.record_spot_price("BTC", 99000.0)
        detector.record_spot_price("BTC", 101000.0)
        signal = detector.evaluate(
            condition_id="c1",
            question="Will PSG win?",
            slug="ucl-psg",
            polymarket_yes_price=0.50,
            polymarket_no_price=0.50,
        )
        assert signal is None

    def test_no_signal_when_edge_below_threshold(self) -> None:
        detector = CryptoArbDetector(min_edge_pct=0.10)
        # Tiny spot movement
        detector.record_spot_price("BTC", 100000.0)
        detector.record_spot_price("BTC", 100100.0)  # 0.1% up
        signal = detector.evaluate(
            condition_id="c1",
            question="Will BTC be above $100k in 5 minutes?",
            slug="btc-above-100k-5min",
            polymarket_yes_price=0.50,
            polymarket_no_price=0.50,
        )
        assert signal is None
