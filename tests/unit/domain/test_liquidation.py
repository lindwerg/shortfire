"""Property tests for Liquidation domain type.

Tests:
  1. Smoke test — happy path construction
  2. Naive datetime raises
  3. Non-positive qty raises
  4. Non-positive price raises
  5. Round-trip preserves all fields
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from pydantic import ValidationError

from shortfire.domain.market import Liquidation
from tests.conftest import money, utc_dt


def test_liquidation_happy_path() -> None:
    """Liquidation with valid data constructs successfully."""
    liq = Liquidation(
        symbol="BTCUSDT",
        source="mexc",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        side="short",
        qty=Decimal("0.5"),
        price=Decimal("50000"),
    )
    assert liq.symbol == "BTCUSDT"
    assert liq.side == "short"
    assert liq.qty > Decimal("0")
    assert liq.price > Decimal("0")


def test_liquidation_naive_datetime_raises() -> None:
    """Liquidation with naive datetime raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Liquidation(
            symbol="BTCUSDT",
            source="mexc",
            ts=datetime(2026, 5, 21),  # naive
            side="long",
            qty=Decimal("0.5"),
            price=Decimal("50000"),
        )


def test_liquidation_zero_qty_raises() -> None:
    """Liquidation with qty=0 raises ValidationError (must be > 0)."""
    with pytest.raises(ValidationError):
        Liquidation(
            symbol="BTCUSDT",
            source="mexc",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            side="short",
            qty=Decimal("0"),  # not positive
            price=Decimal("50000"),
        )


def test_liquidation_zero_price_raises() -> None:
    """Liquidation with price=0 raises ValidationError (must be > 0)."""
    with pytest.raises(ValidationError):
        Liquidation(
            symbol="BTCUSDT",
            source="mexc",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            side="short",
            qty=Decimal("0.5"),
            price=Decimal("0"),  # not positive
        )


def test_liquidation_both_sides() -> None:
    """Liquidation accepts both short and long sides."""
    ts = datetime(2026, 5, 21, tzinfo=UTC)
    for side in ("short", "long"):
        liq = Liquidation(
            symbol="ETHUSDT",
            source="coinglass",
            ts=ts,
            side=side,  # type: ignore[arg-type]
            qty=Decimal("1"),
            price=Decimal("3000"),
        )
        assert liq.side == side


@given(qty=money, price=money, ts=utc_dt)
@settings(max_examples=100)
def test_liquidation_round_trip(qty: Decimal, price: Decimal, ts: datetime) -> None:
    """Round-trip model_dump / model_validate preserves all fields."""
    liq = Liquidation(
        symbol="BTCUSDT",
        source="mexc",
        ts=ts,
        side="short",
        qty=qty,
        price=price,
    )
    assert Liquidation.model_validate(liq.model_dump()) == liq
