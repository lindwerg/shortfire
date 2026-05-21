"""Integration tests for DATA-12: source CHECK constraint on all raw_mexc_* tables.

These tests prove:
  1. Unknown source values are rejected at the DB level (asyncpg.CheckViolationError).
  2. All four locked source values succeed on INSERT.
  3. Every raw_mexc_* table has a source CHECK constraint in pg_constraint.

Security (T-1-DDL-01): CHECK constraints are the last line of defence against
source-attribution tampering. Verification at integration level ensures the
constraint is present even if application-level validation is bypassed.

DATA-12 requirement: source column with CHECK constraint on every raw hypertable.
"""

from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Helper: asyncpg URL (copy-paste precedent from test_alembic_and_hypertables.py)
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# Shared insert helper
# ---------------------------------------------------------------------------

_CANDLE_COLUMNS = (
    "symbol",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "quality_flag",
)

_CANDLE_1M_INSERT = """
INSERT INTO raw_mexc_candles_1m (symbol, ts, open, high, low, close, volume, source, quality_flag)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""

_TS = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
_PRICE = Decimal("42000.00")
_VOL = Decimal("1.5")


# ---------------------------------------------------------------------------
# Test 1: Unknown source value is rejected
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_check_rejects_unknown_value(migrated_db: str) -> None:
    """INSERT with source='bogus_source' must raise asyncpg.CheckViolationError.

    DATA-12 / T-1-DDL-01: source CHECK is the integrity gate for multi-source
    attribution. An unknown source value MUST be rejected at the DB level.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        with pytest.raises(asyncpg.CheckViolationError):  # type: ignore[attr-defined]
            await conn.execute(  # type: ignore[attr-defined]
                _CANDLE_1M_INSERT,
                "BTC/USDT:USDT",
                _TS,
                _PRICE,
                _PRICE,
                _PRICE,
                _PRICE,
                _VOL,
                "bogus_source",  # <-- invalid source value
                "ok",
            )
    finally:
        await conn.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 2: All four valid source values are accepted
# ---------------------------------------------------------------------------

_VALID_SOURCES = [
    "mexc_native",
    "coinglass_aggregate",
    "coinglass_mexc_only",
    "coingecko",
]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("source", _VALID_SOURCES)
async def test_source_check_accepts_all_four_valid_values(migrated_db: str, source: str) -> None:
    """Each of the four locked source values must INSERT successfully.

    Tests both that the CHECK permits the value AND that the row is readable back.
    Table is TRUNCATED after each test invocation for isolation (mirrors clean_service_event).
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # Cleanup before insert (isolation)
        await conn.execute("TRUNCATE raw_mexc_candles_1m")  # type: ignore[attr-defined]

        # Use a unique ts per source to avoid PK collision if TRUNCATE races
        ts = datetime(2026, 5, 21, 12, 0, _VALID_SOURCES.index(source), tzinfo=UTC)
        await conn.execute(  # type: ignore[attr-defined]
            _CANDLE_1M_INSERT,
            "BTC/USDT:USDT",
            ts,
            _PRICE,
            _PRICE,
            _PRICE,
            _PRICE,
            _VOL,
            source,
            "ok",
        )

        rows = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT source FROM raw_mexc_candles_1m WHERE source = $1", source
        )
        assert len(rows) == 1, f"Row with source='{source}' not found after INSERT."
        assert rows[0]["source"] == source  # type: ignore[index]

        # Cleanup after insert (isolation)
        await conn.execute("TRUNCATE raw_mexc_candles_1m")  # type: ignore[attr-defined]
    finally:
        await conn.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 3: source CHECK is present on ALL raw_mexc_* tables (DATA-12 grep at DB level)
# ---------------------------------------------------------------------------

_RAW_MEXC_TABLES = [
    "raw_mexc_candles_1m",
    "raw_mexc_candles_1d",
    "raw_mexc_funding",
    "raw_mexc_oi",
    "raw_mexc_trades",
    "raw_mexc_l2_top20",
    "raw_mexc_liquidations",
]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_check_present_on_all_raw_tables(migrated_db: str) -> None:
    """Query pg_constraint to assert every raw_mexc_* table has a source CHECK.

    Validates DATA-12 coverage at the integration level — ensures the CHECK was
    not accidentally omitted in any migration file.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT conrelid::regclass::text AS tbl, conname "
            "FROM pg_constraint "
            "WHERE conname LIKE 'ck_raw_%_source' "
            "  AND contype = 'c' "
            "ORDER BY tbl"
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    tables_with_check = {row["tbl"] for row in rows}  # type: ignore[index]
    missing = set(_RAW_MEXC_TABLES) - tables_with_check
    assert not missing, (
        f"Missing source CHECK constraint on tables: {sorted(missing)}. "
        "Each raw_mexc_* table must have ck_raw_*_source CHECK (DATA-12)."
    )
