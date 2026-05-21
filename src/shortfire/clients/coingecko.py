"""CoinGeckoClient Protocol — external boundary for CoinGecko market data (FOUND-08, D-06).

Phase 0: Protocol definition only.
Phase 1 (plan 01-07): Updated to match CoinGeckoClient + FakeCoinGeckoClient shapes.
  - fetch_coins_markets: /coins/markets paginated results (D-55, daily universe)
  - fetch_coin_detail: /coins/{id} per-coin enrichment (D-55, new-symbol detection)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from shortfire.ingest.coingecko.schemas import CoinDetailResponse, CoinsMarketsRow


@runtime_checkable
class CoinGeckoClient(Protocol):
    """Typed boundary for CoinGecko REST API interactions (Demo tier, D-36).

    Both the concrete CoinGeckoClient (httpx-backed) and FakeCoinGeckoClient
    satisfy this Protocol via structural subtyping.
    """

    async def fetch_coins_markets(
        self,
        vs_currency: str = ...,
        per_page: int = ...,
        page: int = ...,
    ) -> tuple[CoinsMarketsRow, ...] | None: ...

    async def fetch_coin_detail(self, coin_id: str) -> CoinDetailResponse | None: ...

    async def close(self) -> None: ...
