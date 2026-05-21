"""InMemoryCandleRepo — deterministic in-memory stub conforming to CandleRepo Protocol (FOUND-08, TEST-05).

Phase 0: fully functional in-memory implementation for unit tests.
Phase 1: asyncpg-backed TimescaleDB concrete implementation.
"""

from datetime import datetime

from shortfire.domain.market import Candle


class InMemoryCandleRepo:
    """Deterministic in-memory CandleRepo for Phase 0+ unit tests."""

    def __init__(self) -> None:
        self._candles: list[Candle] = []

    async def insert(self, candles: tuple[Candle, ...]) -> None:
        self._candles.extend(candles)

    async def fetch_by_symbol(self, symbol: str) -> tuple[Candle, ...]:
        return tuple(c for c in self._candles if c.symbol == symbol)

    async def fetch_by_time_range(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        return tuple(c for c in self._candles if c.symbol == symbol and since <= c.ts <= until)
