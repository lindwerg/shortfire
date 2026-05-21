"""Integration tests for continuous aggregates over raw_mexc_candles_1m.

STOR-05 keystone: CA refresh + SUM/MAX/MIN/FIRST/LAST parity vs hand-rolled SQL.

Requirements: STOR-05, D-67 (locked refresh policies), D-95 (CA carve-out via helper)

Security (T-1-CA-02): Test only refreshes within the uncompressed window (< 7 days of data)
so refresh never touches compressed chunks. Synthetic data is always recent.
"""

import decimal
from datetime import UTC, datetime

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Helper: asyncpg URL
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# Fixtures: synthetic 1m candle data
# ---------------------------------------------------------------------------

_SYMBOL = "BTC/USDT:USDT"
_SOURCE = "mexc_native"


def _make_candle_rows(base_dt: datetime, n: int = 60) -> list[tuple]:
    """Generate n synthetic 1m OHLCV candles starting at base_dt.

    Returns rows as tuples matching the raw_mexc_candles_1m column order:
    (symbol, ts, open, high, low, close, volume, source, quality_flag)
    """
    rows = []
    for i in range(n):
        ts = datetime(
            base_dt.year,
            base_dt.month,
            base_dt.day,
            base_dt.hour,
            base_dt.minute + (i % 60),
            0,
            tzinfo=UTC,
        )
        # Override hour if minutes overflow
        if i >= 60:
            ts = datetime(
                base_dt.year,
                base_dt.month,
                base_dt.day,
                base_dt.hour + (i // 60),
                i % 60,
                0,
                tzinfo=UTC,
            )
        open_ = decimal.Decimal("50000") + decimal.Decimal(str(i))
        high = open_ + decimal.Decimal("10")
        low = open_ - decimal.Decimal("5")
        close = open_ + decimal.Decimal("3")
        volume = decimal.Decimal("1.5") + decimal.Decimal(str(i % 10)) / decimal.Decimal("10")
        rows.append((_SYMBOL, ts, open_, high, low, close, volume, _SOURCE, "ok"))
    return rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_continuous_aggregates_exist(migrated_db: str) -> None:
    """All 4 continuous aggregates must exist after alembic upgrade head.

    D-67: CAs for 5m / 15m / 1h / 4h over raw_mexc_candles_1m.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows = await conn.fetch("SELECT view_name FROM timescaledb_information.continuous_aggregates")
        ca_names = {r["view_name"] for r in rows}
        expected = {
            "raw_mexc_candles_5m",
            "raw_mexc_candles_15m",
            "raw_mexc_candles_1h",
            "raw_mexc_candles_4h",
        }
        missing = expected - ca_names
        assert not missing, f"Missing continuous aggregates: {missing}. Found: {sorted(ca_names)}"
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ca_5m_sum_parity_vs_handrolled_sql(migrated_db: str) -> None:
    """STOR-05 keystone: 5m CA values match hand-rolled aggregate over same 1m source.

    Protocol:
    1. Seed 60 synthetic 1m candles into raw_mexc_candles_1m
    2. refresh_continuous_aggregate('raw_mexc_candles_5m', NULL, NULL)
    3. Hand-rolled aggregate via SQL SELECT ... GROUP BY time_bucket(...)
    4. CA query: SELECT from raw_mexc_candles_5m
    5. Compare row-by-row: open/high/low/close/volume must match exactly

    T-1-CA-02: synthetic data is recent (within the last 24h) so refresh
    never touches compressed chunks.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # Truncate for test isolation
        await conn.execute("TRUNCATE raw_mexc_candles_1m")

        # Use a recent timestamp so data is within the uncompressed window (< 7 days)
        # raw_mexc_candles_1m has chunk_interval=1day and compress_after=7days
        base_dt = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        rows = _make_candle_rows(base_dt, n=60)

        # Insert 60 synthetic 1m candles
        await conn.copy_records_to_table(
            "raw_mexc_candles_1m",
            records=rows,
            columns=[
                "symbol",
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "source",
                "quality_flag",
            ],
        )

        # Refresh the 5m CA
        await conn.execute("CALL refresh_continuous_aggregate('raw_mexc_candles_5m', NULL, NULL)")

        # Hand-rolled aggregate
        handrolled = await conn.fetch(
            """
            SELECT
                symbol,
                time_bucket('5 minutes', ts) AS bucket,
                first(open, ts) AS o,
                max(high) AS h,
                min(low) AS l,
                last(close, ts) AS c,
                sum(volume) AS v
            FROM raw_mexc_candles_1m
            WHERE symbol = $1
            GROUP BY symbol, time_bucket('5 minutes', ts)
            ORDER BY bucket
            """,
            _SYMBOL,
        )

        # CA query
        ca_rows = await conn.fetch(
            """
            SELECT
                symbol,
                ts AS bucket,
                open AS o,
                high AS h,
                low AS l,
                close AS c,
                volume AS v
            FROM raw_mexc_candles_5m
            WHERE symbol = $1
            ORDER BY bucket
            """,
            _SYMBOL,
        )

        assert len(handrolled) > 0, "Hand-rolled aggregate returned no rows"
        assert len(ca_rows) > 0, "CA query returned no rows"
        assert len(handrolled) == len(ca_rows), (
            f"Row count mismatch: hand-rolled={len(handrolled)}, CA={len(ca_rows)}"
        )

        # Row-by-row parity check (NUMERIC arithmetic is deterministic)
        for i, (hr, ca) in enumerate(zip(handrolled, ca_rows, strict=True)):
            assert hr["bucket"] == ca["bucket"], (
                f"Row {i}: bucket mismatch hr={hr['bucket']} ca={ca['bucket']}"
            )
            assert hr["o"] == ca["o"], (
                f"Row {i} bucket={hr['bucket']}: open mismatch hr={hr['o']} ca={ca['o']}"
            )
            assert hr["h"] == ca["h"], (
                f"Row {i} bucket={hr['bucket']}: high mismatch hr={hr['h']} ca={ca['h']}"
            )
            assert hr["l"] == ca["l"], (
                f"Row {i} bucket={hr['bucket']}: low mismatch hr={hr['l']} ca={ca['l']}"
            )
            assert hr["c"] == ca["c"], (
                f"Row {i} bucket={hr['bucket']}: close mismatch hr={hr['c']} ca={ca['c']}"
            )
            assert hr["v"] == ca["v"], (
                f"Row {i} bucket={hr['bucket']}: volume mismatch hr={hr['v']} ca={ca['v']}"
            )

    finally:
        # Cleanup: truncate to avoid polluting other tests
        await conn.execute("TRUNCATE raw_mexc_candles_1m")
        await conn.close()
