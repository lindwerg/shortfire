"""MexcClient Protocol — external boundary for MEXC futures exchange (FOUND-08, D-06).

Phase 0: Protocol definition only.
Phase 1: ccxt-backed concrete implementation.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from shortfire.domain.market import Candle, Funding, OrderBook
from shortfire.domain.trading import Order


@runtime_checkable
class MexcClient(Protocol):
    """Typed boundary for all MEXC REST/WS interactions."""

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]: ...

    async def fetch_funding_rate_history(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]: ...

    async def fetch_order_book(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBook: ...

    async def place_order(self, order: Order) -> str: ...  # returns exchange order id

    async def cancel_order(self, client_order_id: str) -> None: ...
