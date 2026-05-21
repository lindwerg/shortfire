"""Parametrized test: every domain type with a ts field rejects naive datetime.

Tests:
  - Task 1: Candle, OrderBook, Funding, Liquidation reject naive ts
  - Task 2 update: Signal, Order, Position also added to the list (7 total)
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

# Task 1 types — market data
from shortfire.domain.market import Candle, Funding, Liquidation, OrderBook, OrderBookLevel

# Task 2 types — trading
from shortfire.domain.trading import Order, Position, Signal


def _naive_candle() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "source": "mexc",
        "timeframe": "1m",
        "ts": datetime(2026, 5, 21),  # naive
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100.5"),
        "volume": Decimal("10"),
    }


def _naive_orderbook() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "source": "mexc",
        "ts": datetime(2026, 5, 21),  # naive
        "bids": (OrderBookLevel(price=Decimal("100"), qty=Decimal("1")),),
        "asks": (OrderBookLevel(price=Decimal("101"), qty=Decimal("1")),),
    }


def _naive_funding() -> dict[str, Any]:
    now_naive = datetime(2026, 5, 21, 12, 0, 0)  # naive published_ts
    return {
        "symbol": "BTCUSDT",
        "source": "mexc",
        "published_ts": now_naive,
        "settlement_ts": datetime(2026, 5, 21, 20, 0, 0, tzinfo=UTC),
        "rate": Decimal("0.0001"),
    }


def _naive_liquidation() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "source": "mexc",
        "ts": datetime(2026, 5, 21),  # naive
        "side": "short",
        "qty": Decimal("0.5"),
        "price": Decimal("50000"),
    }


def _naive_signal() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": "short",
        "kind": "pump_short",
        "ts": datetime(2026, 5, 21),  # naive
        "confidence": Decimal("0.75"),
    }


def _naive_order() -> dict[str, Any]:
    return {
        "client_order_id": "x",
        "symbol": "BTCUSDT",
        "intent": "open",
        "side": "short",
        "order_type": "market",
        "quantity": Decimal("1.0"),
        "reduce_only": False,
        "ts": datetime(2026, 5, 21),  # naive
    }


def _naive_position() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": "short",
        "qty": Decimal("1.0"),
        "avg_entry_price": Decimal("50000"),
        "opened_ts": datetime(2026, 5, 21),  # naive
        "last_update_ts": datetime(2026, 5, 21, tzinfo=UTC),
    }


_ALL_CASES = [
    (Candle, _naive_candle()),
    (OrderBook, _naive_orderbook()),
    (Funding, _naive_funding()),
    (Liquidation, _naive_liquidation()),
    (Signal, _naive_signal()),
    (Order, _naive_order()),
    (Position, _naive_position()),
]

_ALL_IDS = ["Candle", "OrderBook", "Funding", "Liquidation", "Signal", "Order", "Position"]


@pytest.mark.parametrize("model_cls,kwargs", _ALL_CASES, ids=_ALL_IDS)
def test_naive_datetime_raises(model_cls: type, kwargs: dict[str, Any]) -> None:
    """Every domain type with a ts field rejects a naive datetime."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        model_cls(**kwargs)
