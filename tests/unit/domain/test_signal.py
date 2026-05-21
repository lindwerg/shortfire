"""Property tests for Signal domain type.

Tests:
  1. Happy path — valid construction
  2. Naive datetime raises ValidationError
  3. Confidence must be in [0, 1]
  4. Round-trip preserves all fields
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from pydantic import ValidationError

from shortfire.domain.trading import Signal
from tests.conftest import utc_dt


def test_signal_happy_path() -> None:
    """Valid Signal constructs successfully."""
    s = Signal(
        symbol="BTCUSDT",
        side="short",
        kind="pump_short",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        confidence=Decimal("0.75"),
    )
    assert s.symbol == "BTCUSDT"
    assert s.side == "short"
    assert s.kind == "pump_short"
    assert s.confidence == Decimal("0.75")
    assert s.shap_top == ()


def test_signal_naive_datetime_raises() -> None:
    """Signal with naive datetime raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Signal(
            symbol="BTCUSDT",
            side="short",
            kind="pump_short",
            ts=datetime(2026, 5, 21),  # naive
            confidence=Decimal("0.75"),
        )


def test_signal_confidence_above_one_raises() -> None:
    """Signal with confidence > 1 raises ValidationError."""
    with pytest.raises(ValidationError):
        Signal(
            symbol="BTCUSDT",
            side="short",
            kind="pump_short",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            confidence=Decimal("1.01"),  # > 1
        )


def test_signal_confidence_below_zero_raises() -> None:
    """Signal with confidence < 0 raises ValidationError."""
    with pytest.raises(ValidationError):
        Signal(
            symbol="BTCUSDT",
            side="short",
            kind="pump_short",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            confidence=Decimal("-0.01"),  # < 0
        )


def test_signal_confidence_at_boundaries() -> None:
    """Signal confidence accepts 0 and 1 (inclusive boundaries)."""
    ts = datetime(2026, 5, 21, tzinfo=UTC)
    for confidence in (Decimal("0"), Decimal("1")):
        s = Signal(
            symbol="BTCUSDT",
            side="long",
            kind="pump_short",
            ts=ts,
            confidence=confidence,
        )
        assert Decimal("0") <= s.confidence <= Decimal("1")


@given(ts=utc_dt)
@settings(max_examples=50)
def test_signal_round_trip(ts: datetime) -> None:
    """Round-trip model_dump / model_validate preserves all fields."""
    s = Signal(
        symbol="ETHUSDT",
        side="short",
        kind="pump_short",
        ts=ts,
        confidence=Decimal("0.9"),
        shap_top=(("rsi_14", Decimal("0.42")), ("oi_change_1h", Decimal("0.31"))),
    )
    assert Signal.model_validate(s.model_dump()) == s
