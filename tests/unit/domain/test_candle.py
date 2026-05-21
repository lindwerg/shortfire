"""Property tests for Candle domain type.

Tests:
  1. Round-trip: model_dump/model_validate preserves all fields
  2. Invariant: low > high raises ValidationError
  3. Naive datetime raises ValidationError
  4. (Phase 1) Source widening: mexc_native / coinglass_aggregate / coinglass_mexc_only accepted
  5. (Phase 1) Old source labels "mexc" / "coinglass" rejected
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from pydantic import ValidationError

from shortfire.domain.market import Candle
from tests.conftest import money, utc_dt

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
# D-59: widened Source Literal values
SOURCES = ["mexc_native", "coinglass_aggregate", "coinglass_mexc_only", "coingecko"]


@given(
    low=money,
    delta1=money,
    delta2=money,
    volume=money,
    ts=utc_dt,
)
@settings(max_examples=100)
def test_candle_round_trip(
    low: Decimal, delta1: Decimal, delta2: Decimal, volume: Decimal, ts: datetime
) -> None:
    """Round-trip model_dump / model_validate preserves all fields for valid candles."""
    # Build a valid OHLC from low + deltas
    open_ = low + delta1
    high = max(open_, low + delta2)
    close = low + (delta1 + delta2) / Decimal("2")
    # Ensure the constructed candle satisfies low <= open, close <= high
    assume(low <= open_ <= high)
    assume(low <= close <= high)

    c = Candle(
        symbol="BTCUSDT",
        source="mexc_native",
        timeframe="1m",
        ts=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    assert Candle.model_validate(c.model_dump()) == c


def test_candle_invariant_low_gt_high_raises() -> None:
    """Candle with low > high raises ValidationError."""
    with pytest.raises(ValidationError, match=r"low.*<=.*high|Candle invariant"):
        Candle(
            symbol="BTCUSDT",
            source="mexc_native",
            timeframe="1m",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("99"),  # high < low — violates invariant
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )


def test_candle_invariant_open_gt_high_raises() -> None:
    """Candle with open > high raises ValidationError."""
    with pytest.raises(ValidationError, match=r"low.*<=.*high|Candle invariant"):
        Candle(
            symbol="BTCUSDT",
            source="mexc_native",
            timeframe="1m",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            open=Decimal("105"),  # open > high — violates invariant
            high=Decimal("104"),
            low=Decimal("100"),
            close=Decimal("101"),
            volume=Decimal("10"),
        )


def test_candle_naive_datetime_raises() -> None:
    """Candle with naive datetime raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Candle(
            symbol="BTCUSDT",
            source="mexc_native",
            timeframe="1m",
            ts=datetime(2026, 5, 21),  # naive — no tz
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
        )


def test_candle_happy_path() -> None:
    """Candle with valid data constructs successfully using mexc_native source."""
    c = Candle(
        symbol="BTCUSDT",
        source="mexc_native",
        timeframe="1m",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    assert c.symbol == "BTCUSDT"
    assert c.source == "mexc_native"
    assert c.timeframe == "1m"
    assert c.low <= c.open <= c.high
    assert c.low <= c.close <= c.high


def test_candle_source_coinglass_aggregate() -> None:
    """Candle with source='coinglass_aggregate' constructs successfully (D-59)."""
    c = Candle(
        symbol="BTCUSDT",
        source="coinglass_aggregate",
        timeframe="1h",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    assert c.source == "coinglass_aggregate"


def test_candle_source_coinglass_mexc_only() -> None:
    """Candle with source='coinglass_mexc_only' constructs successfully (D-59)."""
    c = Candle(
        symbol="BTCUSDT",
        source="coinglass_mexc_only",
        timeframe="1h",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    assert c.source == "coinglass_mexc_only"


def test_candle_source_coingecko() -> None:
    """Candle with source='coingecko' constructs successfully (unchanged label in widened Literal)."""
    c = Candle(
        symbol="BTCUSDT",
        source="coingecko",
        timeframe="1d",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    assert c.source == "coingecko"


def test_candle_rejects_old_mexc_source_label() -> None:
    """Candle with old label source='mexc' raises ValidationError (D-59, Phase 1 widening).

    The old short label 'mexc' is no longer in the Source Literal — only
    'mexc_native', 'coinglass_aggregate', 'coinglass_mexc_only', 'coingecko' are valid.
    """
    with pytest.raises(
        ValidationError,
        match=r"mexc_native|coinglass_aggregate|coinglass_mexc_only|coingecko",
    ):
        Candle(
            symbol="BTCUSDT",
            source="mexc",  # type: ignore[arg-type]  # intentionally invalid — testing rejection
            timeframe="1m",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
        )


def test_candle_rejects_old_coinglass_source_label() -> None:
    """Candle with old label source='coinglass' raises ValidationError (D-59)."""
    with pytest.raises(
        ValidationError,
        match=r"mexc_native|coinglass_aggregate|coinglass_mexc_only|coingecko",
    ):
        Candle(
            symbol="BTCUSDT",
            source="coinglass",  # type: ignore[arg-type]  # intentionally invalid
            timeframe="1m",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
        )
