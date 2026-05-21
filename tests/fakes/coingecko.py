"""FakeCoinGeckoClient — deterministic stub for Phase 1 unit tests (FOUND-08, TEST-05).

Phase 0: methods raised NotImplementedError.
Phase 1 (plan 01-07): real canned responses matching CoinsMarketsRow + CoinDetailResponse.

Usage:
    client = FakeCoinGeckoClient(
        canned_markets=(...),  # tuple of CoinsMarketsRow
        canned_detail={"bitcoin": CoinDetailResponse.from_raw(...)},
    )
    rows = await client.fetch_coins_markets()
    detail = await client.fetch_coin_detail("bitcoin")
"""

from __future__ import annotations

from shortfire.ingest.coingecko.schemas import CoinDetailResponse, CoinsMarketsRow


class FakeCoinGeckoClient:
    """Deterministic fake for Phase 1+ unit tests.

    Canned data is set at construction time. All methods are async and return
    the same types as the real CoinGeckoClient.
    """

    def __init__(
        self,
        canned_markets: tuple[CoinsMarketsRow, ...] | None = None,
        canned_detail: dict[str, CoinDetailResponse] | None = None,
    ) -> None:
        """
        Args:
            canned_markets: Rows returned by fetch_coins_markets (any page).
                            None simulates a permanent API failure.
            canned_detail: Mapping of coin_id → CoinDetailResponse for fetch_coin_detail.
                           Keys not present return None (simulates 404 / unknown coin).
        """
        self._canned_markets = canned_markets
        self._canned_detail: dict[str, CoinDetailResponse] = canned_detail or {}

    async def fetch_coins_markets(
        self,
        vs_currency: str = "usd",
        per_page: int = 250,
        page: int = 1,
    ) -> tuple[CoinsMarketsRow, ...] | None:
        """Return canned markets rows (paginated by per_page/page for test realism)."""
        if self._canned_markets is None:
            return None
        # Simple pagination: slice the canned data
        start = (page - 1) * per_page
        end = start + per_page
        return self._canned_markets[start:end]

    async def fetch_coin_detail(self, coin_id: str) -> CoinDetailResponse | None:
        """Return canned detail for coin_id, or None if not in canned_detail."""
        return self._canned_detail.get(coin_id)

    async def close(self) -> None:
        """No-op for the fake — no real HTTP client to close."""


# ---------------------------------------------------------------------------
# Canned payloads for test convenience
# ---------------------------------------------------------------------------

CANNED_MARKETS_PAYLOAD = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "current_price": 50000,
        "market_cap": 1_000_000_000_000,
        "total_volume": 30_000_000_000,
        "last_updated": "2026-05-21T12:00:00.000Z",
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "current_price": 2500,
        "market_cap": 300_000_000_000,
        "total_volume": 15_000_000_000,
        "last_updated": "2026-05-21T12:00:00.000Z",
    },
    {
        "id": "ripple",
        "symbol": "xrp",
        "name": "XRP",
        "current_price": 0.5,
        "market_cap": 30_000_000_000,
        "total_volume": 1_000_000_000,
        "last_updated": "2026-05-21T12:00:00.000Z",
    },
]

CANNED_MARKETS_ROWS: tuple[CoinsMarketsRow, ...] = tuple(
    CoinsMarketsRow.from_raw(raw) for raw in CANNED_MARKETS_PAYLOAD
)

CANNED_DETAIL_BITCOIN = CoinDetailResponse.from_raw(
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "categories": ["Cryptocurrency", "Proof of Work"],
        "genesis_date": "2009-01-03",
        "market_data": {"current_price": {"usd": 50000}},
    }
)
