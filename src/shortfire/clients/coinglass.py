"""CoinglassClient Protocol — external boundary for Coinglass derivatives data (FOUND-08, D-06).

Phase 0: Protocol definition only.
Phase 1: httpx-backed concrete implementation.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from shortfire.domain.market import Funding, Liquidation


@runtime_checkable
class CoinglassClient(Protocol):
    """Typed boundary for Coinglass REST API interactions."""

    async def fetch_funding_aggregate(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]: ...

    async def fetch_open_interest(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[tuple[datetime, str], ...]: ...  # (ts, oi_value_str) — narrowed in Phase 1

    async def fetch_liquidations(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Liquidation, ...]: ...
