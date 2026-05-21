"""FakeCoinglassClient — deterministic stub conforming to CoinglassClient Protocol (FOUND-08, TEST-05).

Phase 0: all methods raise NotImplementedError — Phase 1 fills these in.
Phase 1: extended with canned response payloads matching the four schemas
         (PATTERNS.md Group 5). FakeCoinglassClient mirrors CoinglassClient interface
         exactly so production code uses Protocol-based dependency injection.
"""

from __future__ import annotations

from datetime import datetime

from shortfire.domain.market import Funding, Liquidation
from shortfire.ingest.coinglass.schemas import (
    FundingRateListResponse,
    LiquidationCoinHistoryResponse,
    LongShortAccountRatioResponse,
    OpenInterestHistoryResponse,
)


class FakeCoinglassClient:
    """Deterministic fake for Phase 1+ unit tests.

    Construct with canned response objects; fetch methods return them without any
    network call. Pass None for an endpoint to simulate a permanent 4xx (returns None).

    Example:
        canned_funding = FundingRateListResponse.model_validate({
            "code": 0, "msg": "ok",
            "data": [{"symbol": "BTC", "funding_rate": "0.0001"}],
        })
        fake = FakeCoinglassClient(funding=canned_funding)
        result = await fake.fetch_funding_rate_list()
        assert result.data[0].symbol == "BTC"
    """

    def __init__(
        self,
        *,
        funding: FundingRateListResponse | None = None,
        oi: OpenInterestHistoryResponse | None = None,
        liq: LiquidationCoinHistoryResponse | None = None,
        lsr: LongShortAccountRatioResponse | None = None,
    ) -> None:
        self._canned_funding = funding
        self._canned_oi = oi
        self._canned_liq = liq
        self._canned_lsr = lsr

    async def fetch_funding_rate_list(self) -> FundingRateListResponse | None:
        """Return canned FundingRateListResponse or None (simulates permanent 4xx)."""
        return self._canned_funding

    async def fetch_open_interest_history(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> OpenInterestHistoryResponse | None:
        """Return canned OpenInterestHistoryResponse or None."""
        return self._canned_oi

    async def fetch_liquidation_coin_history(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> LiquidationCoinHistoryResponse | None:
        """Return canned LiquidationCoinHistoryResponse or None."""
        return self._canned_liq

    async def fetch_long_short_account_ratio(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> LongShortAccountRatioResponse | None:
        """Return canned LongShortAccountRatioResponse or None."""
        return self._canned_lsr

    async def close(self) -> None:
        """No-op — fake has no network resources to close."""

    # ---------------------------------------------------------------------------
    # Legacy Phase 0 methods — kept for Protocol conformance (Phase 0 Protocol)
    # ---------------------------------------------------------------------------

    async def fetch_funding_aggregate(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]:
        raise NotImplementedError("Phase 1 uses fetch_funding_rate_list (batch endpoint D-53)")

    async def fetch_open_interest(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[tuple[datetime, str], ...]:
        raise NotImplementedError("Phase 1 uses fetch_open_interest_history (per-symbol D-53)")

    async def fetch_liquidations(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Liquidation, ...]:
        raise NotImplementedError("Phase 1 uses fetch_liquidation_coin_history (per-symbol D-53)")
