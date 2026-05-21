"""Clients layer — Protocol definitions for external boundaries (FOUND-08, D-06).

Real implementations land in Phase 1.
Deterministic fakes live in tests/fakes/.
"""

from shortfire.clients.coingecko import CoinGeckoClient
from shortfire.clients.coinglass import CoinglassClient
from shortfire.clients.mexc import MexcClient
from shortfire.clients.repos import CandleRepo

__all__ = [
    "CandleRepo",
    "CoinGeckoClient",
    "CoinglassClient",
    "MexcClient",
]
