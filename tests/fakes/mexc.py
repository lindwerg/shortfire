"""FakeMexcClient — deterministic stub conforming to MexcClient Protocol (FOUND-08, TEST-05).

Phase 0: only fetch_ohlcv + place_order + cancel_order have meaningful bodies.
fetch_funding_rate_history and fetch_order_book raise NotImplementedError — Phase 1 fills these in.
"""

from datetime import datetime

from shortfire.domain.market import Candle, Funding, OrderBook
from shortfire.domain.trading import Order


class FakeMexcClient:
    """Deterministic fake for Phase 0+ unit tests. Phase 1 fills in real implementations."""

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles
        self._placed_orders: list[Order] = []

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        """Return canned candles filtered by symbol and time window [since, until]."""
        return tuple(c for c in self._candles if c.symbol == symbol and since <= c.ts <= until)

    async def fetch_funding_rate_history(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]:
        raise NotImplementedError("Phase 1 fills this in")

    async def fetch_order_book(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBook:
        raise NotImplementedError("Phase 1 fills this in")

    @property
    def placed_orders(self) -> list[Order]:
        """Read-only access to recorded orders for test assertions."""
        return self._placed_orders

    async def place_order(self, order: Order) -> str:
        """Record the order and return a deterministic fake exchange order id."""
        self._placed_orders.append(order)
        return f"fake-order-id-{len(self._placed_orders)}"

    async def cancel_order(self, client_order_id: str) -> None:
        return None
