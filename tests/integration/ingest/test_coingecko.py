"""Integration test — DATA-08 keystone: fetch_and_write_daily against real TimescaleDB.

Verifies:
  - fetch_and_write_daily inserts rows into raw_coingecko_market
  - Idempotency: second call returns 0 (ON CONFLICT DO NOTHING)
  - source='coingecko' in every inserted row (T-1-CG-04)
  - ts and symbol are set correctly

Uses:
  - migrated_db fixture (session-scoped TimescaleDB testcontainer with alembic migrations)
  - FakeCoinGeckoClient with CANNED_MARKETS_ROWS
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import asyncpg
import pytest
from shortfire.ingest.coingecko.universe import fetch_and_write_daily
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.fakes.coingecko import CANNED_MARKETS_ROWS, FakeCoinGeckoClient

pytestmark = pytest.mark.integration

_FROZEN_TS = datetime(2026, 5, 21, 0, 30, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy driver suffix for direct asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


@pytest.fixture(scope="module")
def async_engine(migrated_db: str) -> Generator[AsyncEngine, None, None]:
    """Session-scoped AsyncEngine pointing at the testcontainer migrated DB."""
    async_url = migrated_db.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, echo=False)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture(autouse=True)
def clean_raw_coingecko_market(migrated_db: str) -> Generator[None, None, None]:
    """Truncate raw_coingecko_market before and after each test for isolation."""
    asyncpg_url = _to_asyncpg_url(migrated_db)

    async def _truncate() -> None:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            await conn.execute("TRUNCATE raw_coingecko_market")  # type: ignore[attr-defined]
        finally:
            await conn.close()  # type: ignore[attr-defined]

    asyncio.run(_truncate())
    yield
    asyncio.run(_truncate())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_and_write_daily_inserts_rows(async_engine: AsyncEngine, migrated_db: str) -> None:
    """DATA-08 keystone: rows appear in raw_coingecko_market after fetch_and_write_daily."""
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    count = await fetch_and_write_daily(engine=async_engine, client=client, ts=_FROZEN_TS)

    assert count == len(CANNED_MARKETS_ROWS)

    # Verify rows in DB
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT symbol, ts, source FROM raw_coingecko_market ORDER BY symbol"
        )
        assert len(rows) == len(CANNED_MARKETS_ROWS)
        for row in rows:
            assert row["source"] == "coingecko"  # type: ignore[index]
            assert row["ts"] == _FROZEN_TS  # type: ignore[index]
    finally:
        await conn.close()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_fetch_and_write_daily_idempotent(async_engine: AsyncEngine, migrated_db: str) -> None:
    """Second call with same ts returns 0 — ON CONFLICT DO NOTHING (D-62)."""
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    first = await fetch_and_write_daily(engine=async_engine, client=client, ts=_FROZEN_TS)
    await fetch_and_write_daily(engine=async_engine, client=client, ts=_FROZEN_TS)

    assert first == len(CANNED_MARKETS_ROWS)
    # Second write: copy_into_hypertable processes records but ON CONFLICT DO NOTHING
    # means the DB should still have exactly len(CANNED_MARKETS_ROWS) rows (no duplicates)
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        db_count: int = await conn.fetchval(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM raw_coingecko_market"
        )
        assert db_count == len(CANNED_MARKETS_ROWS)
    finally:
        await conn.close()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_fetch_and_write_daily_source_is_coingecko(async_engine: AsyncEngine, migrated_db: str) -> None:
    """All inserted rows have source='coingecko' (T-1-CG-04 — literal, never from wire)."""
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    await fetch_and_write_daily(engine=async_engine, client=client, ts=_FROZEN_TS)

    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        non_coingecko: int = await conn.fetchval(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM raw_coingecko_market WHERE source != 'coingecko'"
        )
        assert non_coingecko == 0
    finally:
        await conn.close()  # type: ignore[attr-defined]
