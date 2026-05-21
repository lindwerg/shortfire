"""Gap-injection helper — flag_gap() inserts synthetic rows with quality_flag='gap_detected'.

STOR-09 + Pitfall 21: never interpolate or back-fill missing candles.
Instead, inject synthetic rows with quality_flag='gap_detected' and Decimal("0") OHLCV
so Phase 2 feature pipelines can branch on the flag (FEAT-14 lint rule bans bfill).

OHLC sentinel decision (01-08 plan): Decimal("0") is used for synthetic gap rows rather
than ALTER columns to nullable (which would touch the schema mid-phase). The quality_flag
carries the semantics; zero OHLCV never occurs in real candle data. This is documented
in 01-08-SUMMARY.md.

Usage:
    n = await flag_gap(engine, "raw_mexc_candles_1m", "BTC/USDT:USDT",
                       gap_start=t1, gap_end=t2, timeframe_ms=60_000)
    # Inserts synthetic rows for every minute in [t1, t2) with quality_flag='gap_detected'
    # ON CONFLICT DO NOTHING → safe to call multiple times; never overwrites real data
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.storage.copy import copy_into_hypertable

_ZERO = Decimal("0")


async def flag_gap(
    engine: AsyncEngine,
    target_table: str,
    symbol: str,
    gap_start: datetime,
    gap_end: datetime,
    timeframe_ms: int,
    source: str = "mexc_native",
) -> int:
    """Insert synthetic rows with quality_flag='gap_detected' for missing intervals.

    STOR-09 + Pitfall 21: the gap detector marks explicit gap rows so Phase 2 feature
    pipelines see explicit gap markers rather than silently missing data.

    OHLCV sentinel: Decimal("0") for all OHLC and volume columns (not NULL).
    Rationale: this avoids altering NOT NULL schema constraints mid-phase while still
    making gap rows unambiguously identifiable via quality_flag='gap_detected'.
    Zero OHLCV never occurs in real candle data.

    ON CONFLICT DO NOTHING is non-destructive — safe to call multiple times; never
    overwrites real data already in the target table (D-62 first-write-wins).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        target_table: Hardcoded table name (e.g. 'raw_mexc_candles_1m'). Must be a
            literal constant from D-58 — never user-controlled.
        symbol: ccxt-unified swap symbol.
        gap_start: Start of the gap window (inclusive), tz-aware UTC.
        gap_end: End of the gap window (exclusive), tz-aware UTC.
        timeframe_ms: Bucket size in milliseconds (e.g. 60_000 for 1m).
        source: Data source identifier (default 'mexc_native').

    Returns:
        Number of synthetic rows inserted (0 if gap_start >= gap_end or all conflicted).
    """
    if gap_start >= gap_end or timeframe_ms <= 0:
        return 0

    records: list[tuple[Any, ...]] = []
    cursor_ms = int(gap_start.timestamp() * 1000)
    end_ms = int(gap_end.timestamp() * 1000)

    while cursor_ms < end_ms:
        ts = datetime.fromtimestamp(cursor_ms / 1000, tz=UTC)
        records.append(
            (
                symbol,
                ts,
                _ZERO,  # open — sentinel (see OHLCV sentinel decision above)
                _ZERO,  # high
                _ZERO,  # low
                _ZERO,  # close
                _ZERO,  # volume
                source,
                "gap_detected",
            )
        )
        cursor_ms += timeframe_ms

    if not records:
        return 0

    return await copy_into_hypertable(
        engine,
        target_table,
        records,
        columns=("symbol", "ts", "open", "high", "low", "close", "volume", "source", "quality_flag"),
        conflict_columns=("symbol", "ts"),
    )
