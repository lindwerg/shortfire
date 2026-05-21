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

# Task 1 types — imported here; Task 2 will add the remaining 3
from shortfire.domain.market import Candle, Funding, Liquidation, OrderBook, OrderBookLevel


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


_TASK1_CASES = [
    (Candle, _naive_candle()),
    (OrderBook, _naive_orderbook()),
    (Funding, _naive_funding()),
    (Liquidation, _naive_liquidation()),
]

_TASK1_IDS = ["Candle", "OrderBook", "Funding", "Liquidation"]


@pytest.mark.parametrize("model_cls,kwargs", _TASK1_CASES, ids=_TASK1_IDS)
def test_naive_datetime_raises(model_cls: type, kwargs: dict[str, Any]) -> None:
    """Every domain type with a ts field rejects a naive datetime."""
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        model_cls(**kwargs)
