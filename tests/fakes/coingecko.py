"""FakeCoinGeckoClient — deterministic stub conforming to CoinGeckoClient Protocol (FOUND-08, TEST-05).

Phase 0: all methods raise NotImplementedError — Phase 1 fills these in.
"""


class FakeCoinGeckoClient:
    """Deterministic fake for Phase 0+ unit tests. Phase 1 fills in real implementations."""

    async def fetch_markets(self) -> tuple[dict[str, object], ...]:
        raise NotImplementedError("Phase 1 fills this in")

    async def fetch_global_data(self) -> dict[str, object]:
        raise NotImplementedError("Phase 1 fills this in")
