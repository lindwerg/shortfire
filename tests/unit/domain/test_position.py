"""Property tests for Position domain type.

Tests:
  1. Position has frozen=False — mutation succeeds (D-08)
  2. Naive datetime raises ValidationError
  3. Round-trip preserves all fields
  4. negative qty raises (must be >= 0)
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from pydantic import ValidationError

from shortfire.domain.trading import Position
from tests.conftest import money, utc_dt


def test_position_is_mutable() -> None:
    """Position has frozen=False — mutating realized_pnl succeeds."""
    p = Position(
        symbol="BTCUSDT",
        side="short",
        qty=Decimal("1.5"),
        avg_entry_price=Decimal("50000"),
        opened_ts=datetime(2026, 5, 21, tzinfo=UTC),
        last_update_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    # frozen=False allows direct attribute mutation
    p.realized_pnl = Decimal("100")
    assert p.realized_pnl == Decimal("100")


def test_position_naive_opened_ts_raises() -> None:
    """Position with naive opened_ts raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Position(
            symbol="BTCUSDT",
            side="short",
            qty=Decimal("1.5"),
            avg_entry_price=Decimal("50000"),
            opened_ts=datetime(2026, 5, 21),  # naive
            last_update_ts=datetime(2026, 5, 21, tzinfo=UTC),
        )


def test_position_naive_last_update_ts_raises() -> None:
    """Position with naive last_update_ts raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Position(
            symbol="BTCUSDT",
            side="short",
            qty=Decimal("1.5"),
            avg_entry_price=Decimal("50000"),
            opened_ts=datetime(2026, 5, 21, tzinfo=UTC),
            last_update_ts=datetime(2026, 5, 21),  # naive
        )


def test_position_negative_qty_raises() -> None:
    """Position with negative qty raises ValidationError."""
    with pytest.raises(ValidationError):
        Position(
            symbol="BTCUSDT",
            side="short",
            qty=Decimal("-0.5"),  # must be >= 0
            avg_entry_price=Decimal("50000"),
            opened_ts=datetime(2026, 5, 21, tzinfo=UTC),
            last_update_ts=datetime(2026, 5, 21, tzinfo=UTC),
        )


def test_position_defaults() -> None:
    """Position has sensible defaults for realized_pnl and unrealized_pnl."""
    p = Position(
        symbol="BTCUSDT",
        side="long",
        qty=Decimal("0.5"),
        avg_entry_price=Decimal("95000"),
        opened_ts=datetime(2026, 5, 21, tzinfo=UTC),
        last_update_ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert p.realized_pnl == Decimal("0")
    assert p.unrealized_pnl == Decimal("0")


@given(qty=money, price=money, ts=utc_dt)
@settings(max_examples=50)
def test_position_round_trip(qty: Decimal, price: Decimal, ts: datetime) -> None:
    """Round-trip model_dump / model_validate preserves all fields."""
    p = Position(
        symbol="BTCUSDT",
        side="short",
        qty=qty,
        avg_entry_price=price,
        opened_ts=ts,
        last_update_ts=ts,
    )
    assert Position.model_validate(p.model_dump()) == p
