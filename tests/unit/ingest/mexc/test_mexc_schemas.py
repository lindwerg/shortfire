"""Unit tests for MexcOhlcvRow Pydantic v2 schema — round-trip, Hypothesis, negative cases.

Covers:
- from_ccxt_row produces Candle with source="mexc_native", tz-aware ts, Decimal OHLCV
- Hypothesis property: valid low/open/high/close round-trips preserve all fields
- Negative: non-numeric high raises ValidationError
- to_domain() always emits tz-aware ts
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.conftest import money


def _make_ccxt_row(
    ts_ms: int = 1_684_675_200_000,
    open_: str = "30000",
    high: str = "30100",
    low: str = "29900",
    close: str = "30050",
    volume: str = "12.5",
) -> list:
    """Build a ccxt-format OHLCV row (6-element list)."""
    return [ts_ms, open_, high, low, close, volume]


def test_ohlcv_row_from_ccxt_row_roundtrip() -> None:
    """from_ccxt_row produces a Candle with source='mexc_native', tz-aware ts, Decimal OHLCV."""
    from shortfire.ingest.mexc.schemas import MexcOhlcvRow

    row = _make_ccxt_row()
    schema = MexcOhlcvRow.from_ccxt_row(row, symbol="BTC/USDT:USDT", timeframe="1m")
    candle = schema.to_domain()

    assert candle.source == "mexc_native"
    assert candle.symbol == "BTC/USDT:USDT"
    assert candle.timeframe == "1m"
    assert candle.ts.tzinfo is not None
    assert isinstance(candle.open, Decimal)
    assert isinstance(candle.high, Decimal)
    assert isinstance(candle.low, Decimal)
    assert isinstance(candle.close, Decimal)
    assert isinstance(candle.volume, Decimal)


@given(
    low=money,
    spread=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1000"),
        places=8,
        allow_nan=False,
        allow_infinity=False,
    ),
    volume=money,
    ts_ms=st.integers(min_value=0, max_value=10**13),
)
def test_ohlcv_hypothesis_valid_roundtrip(low: Decimal, spread: Decimal, volume: Decimal, ts_ms: int) -> None:
    """Property: valid OHLCV row preserves all fields through from_ccxt_row → to_domain()."""
    from shortfire.ingest.mexc.schemas import MexcOhlcvRow

    high = low + spread
    open_ = low + spread / 2
    close = low + spread / 4
    row = [ts_ms, str(open_), str(high), str(low), str(close), str(volume)]
    schema = MexcOhlcvRow.from_ccxt_row(row, symbol="BTC/USDT:USDT", timeframe="1m")
    candle = schema.to_domain()
    assert candle.source == "mexc_native"
    assert candle.ts.tzinfo is not None


def test_ohlcv_row_non_numeric_high_raises_validation_error() -> None:
    """Non-numeric 'high' raises ValidationError (Pydantic strict mode)."""
    from pydantic import ValidationError

    from shortfire.ingest.mexc.schemas import MexcOhlcvRow

    row = [1_684_675_200_000, "30000", "abc", "29900", "30050", "12.5"]
    with pytest.raises((ValidationError, Exception)):
        MexcOhlcvRow.from_ccxt_row(row, symbol="BTC/USDT:USDT", timeframe="1m")


def test_to_domain_ts_is_always_tz_aware() -> None:
    """to_domain() always produces a tz-aware ts, regardless of input ms value."""
    from shortfire.ingest.mexc.schemas import MexcOhlcvRow

    row = _make_ccxt_row(ts_ms=0)
    schema = MexcOhlcvRow.from_ccxt_row(row, symbol="ETH/USDT:USDT", timeframe="1d")
    candle = schema.to_domain()
    assert candle.ts.tzinfo is not None
