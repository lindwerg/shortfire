"""Property tests for OrderBook and OrderBookLevel domain types.

Tests:
  1. Bids must be descending — ascending bids raise ValidationError
  2. Asks must be ascending — descending asks raise ValidationError
  3. OrderBook must not be crossed — bids[0].price >= asks[0].price raises
  4. Round-trip preserves all fields
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shortfire.domain.market import OrderBook, OrderBookLevel


def _level(price: str, qty: str = "1") -> OrderBookLevel:
    return OrderBookLevel(price=Decimal(price), qty=Decimal(qty))


def test_orderbook_bids_must_be_descending() -> None:
    """Ascending bids raise ValidationError matching bids.*desc."""
    with pytest.raises(ValidationError, match=r"bid|descend"):
        OrderBook(
            symbol="BTCUSDT",
            source="mexc_native",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            bids=(_level("100"), _level("101")),  # ascending — wrong
            asks=(_level("102"), _level("103")),
        )


def test_orderbook_asks_must_be_ascending() -> None:
    """Descending asks raise ValidationError."""
    with pytest.raises(ValidationError, match=r"ask|ascend"):
        OrderBook(
            symbol="BTCUSDT",
            source="mexc_native",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            bids=(_level("100"), _level("99")),
            asks=(_level("103"), _level("102")),  # descending — wrong
        )


def test_orderbook_not_crossed() -> None:
    """Crossed book (bid >= ask) raises ValidationError."""
    with pytest.raises(ValidationError, match=r"cross"):
        OrderBook(
            symbol="BTCUSDT",
            source="mexc_native",
            ts=datetime(2026, 5, 21, tzinfo=UTC),
            bids=(_level("105"), _level("104")),  # best bid 105 >= best ask 105
            asks=(_level("105"), _level("106")),
        )


def test_orderbook_naive_datetime_raises() -> None:
    """OrderBook with naive datetime raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        OrderBook(
            symbol="BTCUSDT",
            source="mexc_native",
            ts=datetime(2026, 5, 21),  # naive
            bids=(_level("100"), _level("99")),
            asks=(_level("101"), _level("102")),
        )


def test_orderbook_happy_path() -> None:
    """Valid OrderBook constructs and round-trips."""
    ob = OrderBook(
        symbol="BTCUSDT",
        source="mexc_native",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        bids=(_level("100"), _level("99"), _level("98")),
        asks=(_level("101"), _level("102"), _level("103")),
    )
    assert ob.bids[0].price > ob.bids[1].price  # descending
    assert ob.asks[0].price < ob.asks[1].price  # ascending
    assert ob.bids[0].price < ob.asks[0].price  # not crossed
    assert OrderBook.model_validate(ob.model_dump()) == ob


def test_orderbook_empty_sides_allowed() -> None:
    """OrderBook with empty bids or asks is valid (before first fill)."""
    ob = OrderBook(
        symbol="BTCUSDT",
        source="mexc_native",
        ts=datetime(2026, 5, 21, tzinfo=UTC),
        bids=(),
        asks=(),
    )
    assert ob.bids == ()
    assert ob.asks == ()


def test_orderbooklevel_positive_price_and_qty() -> None:
    """OrderBookLevel requires positive price and qty."""
    with pytest.raises(ValidationError):
        OrderBookLevel(price=Decimal("0"), qty=Decimal("1"))

    with pytest.raises(ValidationError):
        OrderBookLevel(price=Decimal("100"), qty=Decimal("0"))
