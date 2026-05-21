"""Unit tests for MinuteAggregator — 1m candle aggregation from watch_trades stream.

Tests cover:
  - State machine: finalize on minute roll, keep partial for current minute
  - Multi-symbol independence
  - Hypothesis invariants: low <= open,close <= high for every finalized bucket

TDD cycle: these tests are written BEFORE the implementation (RED phase).

Decisions honored:
  D-43: watch_ohlcv banned (ccxt#27253); MinuteAggregator builds 1m candles from trades
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.conftest import money


@pytest.fixture()
def aggregator():  # type: ignore[no-untyped-def]
    from shortfire.ingest.mexc.live_candles import MinuteAggregator

    return MinuteAggregator()


SYMBOL = "BTC/USDT:USDT"
SYMBOL2 = "ETH/USDT:USDT"

_T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
_T2 = datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)


def _dt(h: int = 12, m: int = 0, s: int = 0) -> datetime:
    return datetime(2024, 1, 1, h, m, s, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test 1: Finalization on minute roll
# ---------------------------------------------------------------------------


def test_minute_aggregator_finalizes_on_minute_roll(aggregator):  # type: ignore[no-untyped-def]
    """Three trades in minute 12:00, one trade in 12:01 → finalized 12:00 bucket returned."""
    p1 = Decimal("100")
    p2 = Decimal("110")
    p3 = Decimal("95")
    q = Decimal("1")

    # Trade 1 — 12:00:00
    result = aggregator.on_trade(SYMBOL, _dt(12, 0, 0), p1, q)
    assert result is None, "First trade in new minute should return None (starts partial)"

    # Trade 2 — 12:00:30 (same minute)
    result = aggregator.on_trade(SYMBOL, _dt(12, 0, 30), p2, q)
    assert result is None, "Second trade same minute should return None"

    # Trade 3 — 12:00:59 (same minute)
    result = aggregator.on_trade(SYMBOL, _dt(12, 0, 59), p3, q)
    assert result is None, "Third trade same minute should return None"

    # Trade 4 — 12:01:00 (new minute) → should finalize 12:00 bucket
    result = aggregator.on_trade(SYMBOL, _dt(12, 1, 0), Decimal("200"), q)
    assert result is not None, "Trade in new minute should finalize previous bucket"
    assert result["ts"] == _dt(12, 0, 0), "Finalized ts must be minute boundary of 12:00"
    assert result["open"] == p1, f"Open should be first-trade price {p1}"
    assert result["high"] == p2, f"High should be max price {p2}"
    assert result["low"] == p3, f"Low should be min price {p3}"
    assert result["close"] == p3, f"Close should be last-trade price before rollover {p3}"
    assert result["volume"] == q * 3, "Volume should be sum of 3 trades"


# ---------------------------------------------------------------------------
# Test 2: Partial kept for current minute (no premature emit)
# ---------------------------------------------------------------------------


def test_minute_aggregator_keeps_partial_for_current_minute(aggregator):  # type: ignore[no-untyped-def]
    """Trades only in minute 12:00 → no finalized bucket emitted; partial accumulates."""
    prices = [Decimal("100"), Decimal("200"), Decimal("50")]
    qty = Decimal("2")

    for s, price in enumerate(prices):
        result = aggregator.on_trade(SYMBOL, _dt(12, 0, s * 10), price, qty)
        assert result is None, "Should not finalize until next minute arrives"

    partial = aggregator._partial[SYMBOL]
    assert partial["volume"] == qty * 3, "Volume should accumulate across all trades"
    assert partial["open"] == Decimal("100"), "Open is first-trade price"
    assert partial["high"] == Decimal("200"), "High is max price"
    assert partial["low"] == Decimal("50"), "Low is min price"
    assert partial["close"] == Decimal("50"), "Close is most-recent trade price"


# ---------------------------------------------------------------------------
# Test 3: Multi-symbol independence
# ---------------------------------------------------------------------------


def test_aggregator_multi_symbol_independence(aggregator):  # type: ignore[no-untyped-def]
    """Interleaved trades for two symbols finalize independently."""
    # BTC trades in minute 12:00
    aggregator.on_trade(SYMBOL, _dt(12, 0, 0), Decimal("100"), Decimal("1"))
    aggregator.on_trade(SYMBOL, _dt(12, 0, 10), Decimal("200"), Decimal("1"))

    # ETH trades in minute 12:00
    aggregator.on_trade(SYMBOL2, _dt(12, 0, 5), Decimal("10"), Decimal("5"))
    aggregator.on_trade(SYMBOL2, _dt(12, 0, 20), Decimal("20"), Decimal("5"))

    # BTC crosses into minute 12:01 → finalizes BTC only
    btc_fin = aggregator.on_trade(SYMBOL, _dt(12, 1, 0), Decimal("300"), Decimal("1"))
    assert btc_fin is not None, "BTC 12:00 bucket should finalize"
    assert btc_fin["open"] == Decimal("100")
    assert btc_fin["high"] == Decimal("200")

    # ETH is still in partial (hasn't received a next-minute trade)
    assert SYMBOL2 in aggregator._partial, "ETH partial should still exist"
    assert aggregator._partial[SYMBOL2]["open"] == Decimal("10")

    # ETH crosses into 12:01
    eth_fin = aggregator.on_trade(SYMBOL2, _dt(12, 1, 0), Decimal("30"), Decimal("5"))
    assert eth_fin is not None, "ETH 12:00 bucket should finalize"
    assert eth_fin["open"] == Decimal("10")
    assert eth_fin["high"] == Decimal("20")
    assert eth_fin["volume"] == Decimal("10")  # 5 + 5


# ---------------------------------------------------------------------------
# Test 4 (Hypothesis): Invariants across random trade sequences
# ---------------------------------------------------------------------------


_minute_dt = st.datetimes(
    min_value=datetime(2024, 1, 1, 0, 0),
    max_value=datetime(2024, 1, 1, 23, 59),
).map(lambda d: d.replace(second=0, microsecond=0, tzinfo=UTC))


@settings(max_examples=200, deadline=None)
@given(
    trades=st.lists(
        st.tuples(_minute_dt, money, money),
        min_size=2,
        max_size=100,
    )
)
def test_aggregator_invariants_under_random_trades(trades: list) -> None:  # type: ignore[type-arg]
    """Property: every finalized bucket satisfies low <= open,close <= high."""
    from shortfire.ingest.mexc.live_candles import MinuteAggregator

    agg = MinuteAggregator()
    finalized = []
    for ts, price, qty in sorted(trades, key=lambda t: t[0]):
        result = agg.on_trade(SYMBOL, ts, price, qty)
        if result is not None:
            finalized.append(result)

    for bucket in finalized:
        assert bucket["low"] <= bucket["open"], (
            f"Invariant violated: low={bucket['low']} > open={bucket['open']}"
        )
        assert bucket["low"] <= bucket["close"], (
            f"Invariant violated: low={bucket['low']} > close={bucket['close']}"
        )
        assert bucket["open"] <= bucket["high"], (
            f"Invariant violated: open={bucket['open']} > high={bucket['high']}"
        )
        assert bucket["close"] <= bucket["high"], (
            f"Invariant violated: close={bucket['close']} > high={bucket['high']}"
        )
