"""Integration tests for Coinglass ingest fetcher modules (DATA-07 keystone).

Tests verify the full pipeline:
  Coinglass response (respx-mocked) → schema validation → copy_into_hypertable →
  raw_coinglass_* hypertable rows with source='coinglass_aggregate'

Requires Docker (Assumption A4 from RESEARCH.md). Skipped if Docker is unavailable.
Uses session-scoped TimescaleDB container with alembic migrations applied once.
Per-test isolation via TRUNCATE fixtures.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from freezegun import freeze_time
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asyncpg_url(plain_url: str) -> str:
    """Convert plain postgresql:// URL to postgresql+asyncpg:// for SQLAlchemy."""
    if plain_url.startswith("postgresql://"):
        return plain_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return plain_url


def _build_test_settings(coinglass_api_key: str = "testtoken") -> object:
    from shortfire.settings.data_platform import CoinglassSettings, DataPlatformSettings

    return DataPlatformSettings.model_construct(
        coinglass=CoinglassSettings(api_key=SecretStr(coinglass_api_key)),
    )


# ---------------------------------------------------------------------------
# Per-test cleanup fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_coinglass_tables(migrated_db: str):
    """Truncate all four Coinglass hypertables before and after each test."""
    import asyncpg

    from tests.integration.conftest import _to_asyncpg_url

    asyncpg_url = _to_asyncpg_url(migrated_db)

    async def _truncate() -> None:
        conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)
        try:
            await conn.execute(
                "TRUNCATE raw_coinglass_funding_agg, raw_coinglass_oi, raw_coinglass_liq, raw_coinglass_lsr"
            )
        finally:
            await conn.close()

    asyncio.run(_truncate())
    yield
    asyncio.run(_truncate())


# ---------------------------------------------------------------------------
# Integration test: funding_agg.fetch_and_write
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coinglass_funding_agg_fetch_and_write_writes_attributed_rows(
    migrated_db: str,
    clean_coinglass_tables: None,
) -> None:
    """DATA-07 keystone: respx-mocked funding-rate-list → schema → copy_into_hypertable.

    Asserts:
    - 3 rows written to raw_coinglass_funding_agg
    - All rows have source='coinglass_aggregate'
    - All rows have quality_flag='ok'
    - Re-run produces 0 new rows (idempotency via ON CONFLICT DO NOTHING)
    """
    from shortfire.ingest.coinglass import funding_agg
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = create_async_engine(_asyncpg_url(migrated_db))
    settings = _build_test_settings()
    client = CoinglassClient(settings)  # type: ignore[arg-type]

    funding_payload = {
        "code": 0,
        "msg": "ok",
        "data": [
            {"symbol": "BTC", "funding_rate": "0.0001"},
            {"symbol": "ETH", "funding_rate": "-0.0002"},
            {"symbol": "XRP", "funding_rate": "0.0003"},
        ],
    }

    coinglass_to_unified = {
        "BTC": "BTC/USDT:USDT",
        "ETH": "ETH/USDT:USDT",
        "XRP": "XRP/USDT:USDT",
    }

    # Use freeze_time to ensure both calls share the same ts_now, making ON CONFLICT fire
    with freeze_time("2026-01-01T00:00:00Z"):
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=funding_payload)
                )
                n = await funding_agg.fetch_and_write(
                    engine, client, coinglass_to_unified=coinglass_to_unified
                )

            assert n == 3

            async with engine.begin() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT symbol, source, funding_rate, quality_flag "
                            "FROM raw_coinglass_funding_agg ORDER BY symbol"
                        )
                    )
                ).all()

            assert len(rows) == 3
            assert all(r.source == "coinglass_aggregate" for r in rows)
            assert all(r.quality_flag == "ok" for r in rows)

            # Verify idempotency: re-run at the SAME frozen timestamp triggers ON CONFLICT DO NOTHING
            # (symbol, ts, source) PK conflict — same ts means same rows
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=funding_payload)
                )
                await funding_agg.fetch_and_write(engine, client, coinglass_to_unified=coinglass_to_unified)

            # DB count must still be 3 — ON CONFLICT DO NOTHING prevents duplicates
            async with engine.begin() as conn:
                count = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM raw_coinglass_funding_agg"
                            " WHERE source='coinglass_aggregate'"
                        )
                    )
                ).scalar()
            assert count == 3, f"Expected 3 rows after idempotent re-run, got {count}"

        finally:
            await client.close()
            await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coinglass_funding_agg_unmapped_symbol_skipped(
    migrated_db: str,
    clean_coinglass_tables: None,
) -> None:
    """Symbols not in coinglass_to_unified mapping must be silently skipped (T-1-CG-06)."""
    from shortfire.ingest.coinglass import funding_agg
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = create_async_engine(_asyncpg_url(migrated_db))
    settings = _build_test_settings()
    client = CoinglassClient(settings)  # type: ignore[arg-type]

    funding_payload = {
        "code": 0,
        "msg": "ok",
        "data": [
            {"symbol": "BTC", "funding_rate": "0.0001"},
            {"symbol": "UNKNOWN_COIN", "funding_rate": "0.0002"},  # not in mapping
        ],
    }

    try:
        with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
            mock.get("/api/futures/funding-rate-list").mock(
                return_value=httpx.Response(200, json=funding_payload)
            )
            n = await funding_agg.fetch_and_write(
                engine, client, coinglass_to_unified={"BTC": "BTC/USDT:USDT"}
            )

        assert n == 1  # Only BTC written

        async with engine.begin() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM raw_coinglass_funding_agg"))).scalar()
        assert count == 1

    finally:
        await client.close()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coinglass_oi_fetch_and_write(
    migrated_db: str,
    clean_coinglass_tables: None,
) -> None:
    """OI fetcher writes rows to raw_coinglass_oi with correct source attribution."""
    from shortfire.ingest.coinglass import oi
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = create_async_engine(_asyncpg_url(migrated_db))
    settings = _build_test_settings()
    client = CoinglassClient(settings)  # type: ignore[arg-type]

    oi_payload = {
        "code": 0,
        "msg": "ok",
        "data": [
            {"time": 1700000000000, "open_interest_usd": "1234567.89"},
            {"time": 1700003600000, "open_interest_usd": "9876543.21"},
        ],
    }

    try:
        with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
            mock.get("/api/futures/open-interest/history").mock(
                return_value=httpx.Response(200, json=oi_payload)
            )
            n = await oi.fetch_and_write(
                engine, client, symbol_unified="BTC/USDT:USDT", coinglass_symbol="BTC"
            )

        assert n == 2

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT symbol, source, open_interest, quality_flag FROM raw_coinglass_oi ORDER BY ts"
                    )
                )
            ).all()

        assert len(rows) == 2
        assert all(r.source == "coinglass_aggregate" for r in rows)
        assert rows[0].symbol == "BTC/USDT:USDT"

    finally:
        await client.close()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coinglass_liq_fetch_and_write_two_rows_per_data_point(
    migrated_db: str,
    clean_coinglass_tables: None,
) -> None:
    """Liquidation fetcher produces 2 rows per data point (long + short sides)."""
    from shortfire.ingest.coinglass import liq
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = create_async_engine(_asyncpg_url(migrated_db))
    settings = _build_test_settings()
    client = CoinglassClient(settings)  # type: ignore[arg-type]

    liq_payload = {
        "code": 0,
        "msg": "ok",
        "data": [
            {"time": 1700000000000, "liquidation_long_usd": "10000.00", "liquidation_short_usd": "5000.00"},
            {"time": 1700003600000, "liquidation_long_usd": "20000.00", "liquidation_short_usd": "8000.00"},
        ],
    }

    try:
        with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
            mock.get("/api/futures/liquidation/coin-history").mock(
                return_value=httpx.Response(200, json=liq_payload)
            )
            n = await liq.fetch_and_write(
                engine, client, symbol_unified="ETH/USDT:USDT", coinglass_symbol="ETH"
            )

        # 2 data points × 2 sides = 4 rows
        assert n == 4

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text("SELECT symbol, source, side, quality_flag FROM raw_coinglass_liq ORDER BY ts, side")
                )
            ).all()

        assert len(rows) == 4
        assert all(r.source == "coinglass_aggregate" for r in rows)
        sides = {r.side for r in rows}
        assert sides == {"long", "short"}

    finally:
        await client.close()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coinglass_lsr_fetch_and_write(
    migrated_db: str,
    clean_coinglass_tables: None,
) -> None:
    """LSR fetcher writes rows to raw_coinglass_lsr with correct source attribution."""
    from shortfire.ingest.coinglass import lsr
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = create_async_engine(_asyncpg_url(migrated_db))
    settings = _build_test_settings()
    client = CoinglassClient(settings)  # type: ignore[arg-type]

    lsr_payload = {
        "code": 0,
        "msg": "ok",
        "data": [
            {"time": 1700000000000, "long_short_ratio": "1.23"},
            {"time": 1700003600000, "long_short_ratio": "0.87"},
        ],
    }

    try:
        with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
            mock.get("/api/futures/long-short-account-ratio").mock(
                return_value=httpx.Response(200, json=lsr_payload)
            )
            n = await lsr.fetch_and_write(
                engine, client, symbol_unified="XRP/USDT:USDT", coinglass_symbol="XRP"
            )

        assert n == 2

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT symbol, source, long_short_ratio, quality_flag "
                        "FROM raw_coinglass_lsr ORDER BY ts"
                    )
                )
            ).all()

        assert len(rows) == 2
        assert all(r.source == "coinglass_aggregate" for r in rows)
        assert rows[0].symbol == "XRP/USDT:USDT"

    finally:
        await client.close()
        await engine.dispose()
