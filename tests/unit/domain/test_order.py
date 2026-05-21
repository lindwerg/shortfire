"""Property tests for Order domain type — including EXEC-02 structural invariant.

Tests:
  1. Order(intent='close', reduce_only=False) raises ValidationError (EXEC-02)
  2. Order(intent='close', reduce_only=True) succeeds and round-trips
  3. Hypothesis: close+reduce_only=False ALWAYS raises (D-15)
  4. Hypothesis: open+reduce_only=False succeeds (open orders don't require reduce_only)
  5. Naive datetime raises
  6. Negative/zero quantity raises
"""

from datetime import UTC, datetime
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from pydantic import ValidationError

from shortfire.domain.trading import Order
from tests.conftest import money, utc_dt


def test_close_order_reduce_only_false_raises() -> None:
    """Order(intent='close', reduce_only=False) raises ValidationError (EXEC-02)."""
    with pytest.raises(ValidationError, match=r"reduce_only=True|EXEC-02"):
        Order(
            client_order_id="x",
            symbol="BTCUSDT",
            intent="close",
            side="short",
            order_type="market",
            quantity=Decimal("1.5"),
            reduce_only=False,  # must be True for close orders
            ts=datetime(2026, 5, 21, tzinfo=UTC),
        )


def test_close_order_reduce_only_true_succeeds() -> None:
    """Order(intent='close', reduce_only=True) constructs and round-trips."""
    o = Order(
        client_order_id="x",
        symbol="BTCUSDT",
        intent="close",
        side="short",
        order_type="market",
        quantity=Decimal("1.5"),
        reduce_only=True,
        ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert o.reduce_only is True
    assert Order.model_validate(o.model_dump()) == o


def test_open_order_reduce_only_false_succeeds() -> None:
    """Order(intent='open', reduce_only=False) is valid — no EXEC-02 constraint."""
    o = Order(
        client_order_id="y",
        symbol="BTCUSDT",
        intent="open",
        side="short",
        order_type="market",
        quantity=Decimal("1.0"),
        reduce_only=False,
        ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert o.intent == "open"
    assert o.reduce_only is False


def test_order_naive_datetime_raises() -> None:
    """Order with naive datetime raises ValidationError."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Order(
            client_order_id="z",
            symbol="BTCUSDT",
            intent="open",
            side="long",
            order_type="market",
            quantity=Decimal("1.0"),
            reduce_only=False,
            ts=datetime(2026, 5, 21),  # naive
        )


def test_order_zero_quantity_raises() -> None:
    """Order with quantity=0 raises ValidationError."""
    with pytest.raises(ValidationError):
        Order(
            client_order_id="z",
            symbol="BTCUSDT",
            intent="open",
            side="long",
            order_type="market",
            quantity=Decimal("0"),  # must be > 0
            reduce_only=False,
            ts=datetime(2026, 5, 21, tzinfo=UTC),
        )


def test_order_limit_with_price() -> None:
    """Limit order with price field constructs and round-trips."""
    o = Order(
        client_order_id="limit-1",
        symbol="BTCUSDT",
        intent="open",
        side="long",
        order_type="limit",
        quantity=Decimal("0.5"),
        price=Decimal("95000"),
        reduce_only=False,
        ts=datetime(2026, 5, 21, tzinfo=UTC),
    )
    assert o.price == Decimal("95000")
    assert Order.model_validate(o.model_dump()) == o


@given(
    side=st.sampled_from(["short", "long"]),
    qty=money,
    ts=utc_dt,
)
@settings(max_examples=100)
def test_close_order_requires_reduce_only_hypothesis(side: str, qty: Decimal, ts: datetime) -> None:
    """Hypothesis: Order(intent='close', reduce_only=False) ALWAYS raises."""
    with pytest.raises(ValidationError, match=r"reduce_only=True|EXEC-02"):
        Order(
            client_order_id="x",
            symbol="BTCUSDT",
            intent="close",
            side=side,  # type: ignore[arg-type]
            order_type="market",
            quantity=qty,
            reduce_only=False,
            ts=ts,
        )


@given(
    side=st.sampled_from(["short", "long"]),
    qty=money,
    ts=utc_dt,
)
@settings(max_examples=100)
def test_open_order_does_not_require_reduce_only_hypothesis(side: str, qty: Decimal, ts: datetime) -> None:
    """Hypothesis: Order(intent='open', reduce_only=False) always succeeds."""
    o = Order(
        client_order_id="x",
        symbol="BTCUSDT",
        intent="open",
        side=side,  # type: ignore[arg-type]
        order_type="market",
        quantity=qty,
        reduce_only=False,
        ts=ts,
    )
    assert o.intent == "open"
    assert Order.model_validate(o.model_dump()) == o
