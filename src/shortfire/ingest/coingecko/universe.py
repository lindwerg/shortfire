"""Daily CoinGecko universe-metadata fetcher (D-55, D-77, DATA-08).

Architectural decisions:
  D-55:  CoinGecko is universe-metadata-only — daily cadence, NOT minute-cadence.
  D-56:  28/60 rate limit (5% headroom under 30 req/min Demo quota).
  D-62:  ON CONFLICT DO NOTHING — re-ingest cannot produce duplicates.
  D-77:  Scheduled 00:30 UTC by APScheduler (wiring in plan 01-09, not here).
  DATA-08: Keystone integration test — fetch → write → DB row count.
  T-1-CG-04: source='coingecko' literal in to_record (never from wire).

Columns match migration 0010 raw_coingecko_market:
  (symbol, ts, price_usd, volume_24h_usd, market_cap_usd, category,
   listing_date, raw_payload, source, quality_flag)

Conflict key: (symbol, ts, source) — PK from migration 0010.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.coingecko.schemas import CoinsMarketsRow
from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.coingecko.universe")


class _CoinGeckoClientProtocol(Protocol):
    """Structural protocol for CoinGeckoClient / FakeCoinGeckoClient duck-typing."""

    async def fetch_coins_markets(
        self,
        vs_currency: str = ...,
        per_page: int = ...,
        page: int = ...,
    ) -> tuple[CoinsMarketsRow, ...] | None: ...


_TABLE = "raw_coingecko_market"

_COLUMNS: tuple[str, ...] = (
    "symbol",
    "ts",
    "price_usd",
    "volume_24h_usd",
    "market_cap_usd",
    "category",
    "listing_date",
    "raw_payload",
    "source",
    "quality_flag",
)

_CONFLICT_COLUMNS: tuple[str, ...] = ("symbol", "ts", "source")


async def fetch_and_write_daily(
    engine: AsyncEngine,
    client: _CoinGeckoClientProtocol,
    ts: datetime | None = None,
) -> int:
    """Fetch /coins/markets page 1 (250 coins) and write to raw_coingecko_market.

    Idempotent: re-running with the same ts produces no duplicate rows
    (ON CONFLICT DO NOTHING via copy_into_hypertable, D-62).

    Args:
        engine: SQLAlchemy AsyncEngine for the TimescaleDB instance.
        client: CoinGeckoClient-compatible object with fetch_coins_markets().
                Accepts the concrete CoinGeckoClient or FakeCoinGeckoClient in tests.
        ts:     Snapshot timestamp. Defaults to datetime.now(UTC) when not supplied.
                All rows in the same daily batch share this ts for snapshot consistency.

    Returns:
        Number of records in the batch (0 on API failure or empty result).
    """
    if ts is None:
        ts = datetime.now(UTC)

    log.info("coingecko.universe.fetch_start", ts=ts.isoformat())

    rows: tuple[CoinsMarketsRow, ...] | None = await client.fetch_coins_markets(
        vs_currency="usd",
        per_page=250,
        page=1,
    )

    if not rows:
        log.warning("coingecko.universe.fetch_empty_or_failed", ts=ts.isoformat())
        return 0

    records: tuple[tuple[object, ...], ...] = tuple(row.to_record(ts) for row in rows)

    count = await copy_into_hypertable(
        engine=engine,
        target_table=_TABLE,
        records=records,
        columns=_COLUMNS,
        conflict_columns=_CONFLICT_COLUMNS,
    )

    log.info("coingecko.universe.wrote", count=count, ts=ts.isoformat())
    return count
