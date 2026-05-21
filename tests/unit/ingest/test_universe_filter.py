"""Unit tests for universe snapshot filter logic (UNIV-01).

Tests the qualifying-volume filter as a pure function extracted from snapshot.py.
Uses synthetic ticker dicts — no DB, no network.
"""

from decimal import Decimal

from shortfire.ingest.universe.snapshot import filter_qualifying_tickers

# ---------------------------------------------------------------------------
# Test 1: volume threshold is strict > 500K
# ---------------------------------------------------------------------------


def test_universe_filter_qualifies_above_500k() -> None:
    """Only symbols with quote volume STRICTLY above $500K are marked qualifying (UNIV-01).

    filter_qualifying_tickers returns ALL :USDT-perp symbols seen (UNIV-02 completeness)
    but marks is_qualifying=True only for strict > $500K.
    """
    tickers = {
        "LOW/USDT:USDT": {"quoteVolume": "100000", "last": "1.0"},
        "MID_LOW/USDT:USDT": {"quoteVolume": "400000", "last": "2.0"},
        "EXACT/USDT:USDT": {"quoteVolume": "500000", "last": "3.0"},  # exactly 500K → NOT qualifying
        "HIGH/USDT:USDT": {"quoteVolume": "750000", "last": "4.0"},
        "VERY_HIGH/USDT:USDT": {"quoteVolume": "1000000", "last": "5.0"},
    }
    result = filter_qualifying_tickers(tickers)
    # All 5 :USDT-perp symbols are present (UNIV-02)
    assert len(result) == 5
    # Only HIGH and VERY_HIGH are qualifying
    assert result["HIGH/USDT:USDT"]["is_qualifying"] is True
    assert result["VERY_HIGH/USDT:USDT"]["is_qualifying"] is True
    # 500K is NOT qualifying (strict >)
    assert result["EXACT/USDT:USDT"]["is_qualifying"] is False
    assert result["LOW/USDT:USDT"]["is_qualifying"] is False
    assert result["MID_LOW/USDT:USDT"]["is_qualifying"] is False


def test_universe_filter_qualifies_returns_volume_and_price() -> None:
    """Qualifying tickers have volume_24h_usd and price_usd fields in result dict."""
    tickers = {
        "BTC/USDT:USDT": {"quoteVolume": "900000", "last": "65000.0"},
    }
    result = filter_qualifying_tickers(tickers)
    assert "BTC/USDT:USDT" in result
    entry = result["BTC/USDT:USDT"]
    assert entry["volume_24h_usd"] == Decimal("900000")
    assert entry["price_usd"] == Decimal("65000.0")
    assert entry["is_qualifying"] is True


# ---------------------------------------------------------------------------
# Test 2: non-:USDT-perp symbols are skipped
# ---------------------------------------------------------------------------


def test_universe_filter_rejects_non_usdt_perp() -> None:
    """Non-perpetual-USDT symbols are ignored regardless of volume."""
    tickers = {
        "BTC/USD": {"quoteVolume": "9999999", "last": "65000.0"},  # spot, no :USDT
        "BTC/USDT": {"quoteVolume": "9999999", "last": "65000.0"},  # spot with USDT quote, no :USDT suffix
        "BTC/USDT:USDT": {"quoteVolume": "600000", "last": "65000.0"},  # perp — should qualify
    }
    result = filter_qualifying_tickers(tickers)
    assert "BTC/USD" not in result
    assert "BTC/USDT" not in result
    assert "BTC/USDT:USDT" in result


def test_universe_filter_handles_missing_quoteVolume() -> None:
    """Symbols with missing or None quoteVolume are gracefully skipped (not qualifying)."""
    tickers = {
        "BROKEN/USDT:USDT": {"last": "1.0"},  # no quoteVolume key
        "NULL_VOL/USDT:USDT": {"quoteVolume": None, "last": "1.0"},
        "ZERO_VOL/USDT:USDT": {"quoteVolume": "0", "last": "1.0"},
    }
    result = filter_qualifying_tickers(tickers)
    qualifying = [sym for sym, v in result.items() if v["is_qualifying"]]
    assert len(qualifying) == 0
