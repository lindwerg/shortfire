"""CandleRepo Protocol — data-layer boundary for candle hypertable (FOUND-08, D-06).

Phase 0: Protocol definition only.
Phase 1: asyncpg-backed TimescaleDB implementation.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from shortfire.domain.market import Candle


@runtime_checkable
class CandleRepo(Protocol):
    """Typed boundary for candle hypertable read/write operations."""

    async def insert(self, candles: tuple[Candle, ...]) -> None: ...

    async def fetch_by_symbol(self, symbol: str) -> tuple[Candle, ...]: ...

    async def fetch_by_time_range(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]: ...
