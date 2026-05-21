"""Deterministic fakes for external boundaries (FOUND-08, TEST-05).

These fakes conform to the Protocols defined in src/shortfire/clients/ and
serve as the test seam between Phase 0 (Protocol definitions) and Phase 1
(real ccxt/httpx/asyncpg implementations).
"""

from tests.fakes.coingecko import FakeCoinGeckoClient
from tests.fakes.coinglass import FakeCoinglassClient
from tests.fakes.mexc import FakeMexcClient
from tests.fakes.repos import InMemoryCandleRepo

__all__ = [
    "FakeCoinGeckoClient",
    "FakeCoinglassClient",
    "FakeMexcClient",
    "InMemoryCandleRepo",
]
