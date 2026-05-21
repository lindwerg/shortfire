"""CoinGeckoClient Protocol — external boundary for CoinGecko market data (FOUND-08, D-06).

Phase 0: Protocol definition only.
Phase 1: httpx-backed concrete implementation.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CoinGeckoClient(Protocol):
    """Typed boundary for CoinGecko REST API interactions."""

    async def fetch_markets(self) -> tuple[dict[str, object], ...]: ...

    # raw market metadata; Phase 1 narrows the dict shape to a TypedDict

    async def fetch_global_data(self) -> dict[str, object]: ...
