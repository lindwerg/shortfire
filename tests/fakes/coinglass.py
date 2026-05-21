"""FakeCoinglassClient — deterministic stub conforming to CoinglassClient Protocol (FOUND-08, TEST-05).

Phase 0: all methods raise NotImplementedError — Phase 1 fills these in.
"""

from datetime import datetime

from shortfire.domain.market import Funding, Liquidation


class FakeCoinglassClient:
    """Deterministic fake for Phase 0+ unit tests. Phase 1 fills in real implementations."""

    async def fetch_funding_aggregate(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]:
        raise NotImplementedError("Phase 1 fills this in")

    async def fetch_open_interest(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[tuple[datetime, str], ...]:
        raise NotImplementedError("Phase 1 fills this in")

    async def fetch_liquidations(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Liquidation, ...]:
        raise NotImplementedError("Phase 1 fills this in")
