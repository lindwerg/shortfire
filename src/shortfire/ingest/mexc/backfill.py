"""Paginated REST OHLCV + funding backfill for MEXC futures.

Decisions honored:
  D-38: backfill scope — 1 year of 1m candles per symbol in the initial load
  D-42: OHLCV pagination — limit=1000 per page; cursor advances by data[-1][0] + TIMEFRAME_MS[tf];
        bounded Semaphore(8) per symbol; only 1m and 1d tables are backfilled directly
        (5m/15m/1h/4h materialize from continuous aggregates over raw_mexc_candles_1m)
  D-44: funding REST backfill — historical settlement window; live ws is plan 01-08
  D-45: OI is REST-only; REST polling belongs with the scheduler in plan 01-08
  STOR-08: copy_into_hypertable with ON CONFLICT DO NOTHING gives first-write-wins idempotency
  Pitfall 27: asyncio.TaskGroup for backfill_universe — no fire-and-forget tasks

Open (RESEARCH.md Open Question 7): gap_detected quality_flag injection deferred to plan 01-08.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.mexc.backfill")

# ---------------------------------------------------------------------------
# Timeframe constants
# ---------------------------------------------------------------------------

TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

# Only 1m and 1d have dedicated hypertables; other timeframes are continuous aggregates
# over raw_mexc_candles_1m — they MUST NOT be backfilled directly (D-67 substrate = 1m base).
TIMEFRAME_TO_TABLE: dict[str, str] = {
    "1m": "raw_mexc_candles_1m",
    "1d": "raw_mexc_candles_1d",
}


# ---------------------------------------------------------------------------
# Single-symbol OHLCV backfill
# ---------------------------------------------------------------------------


async def backfill_ohlcv(
    engine: AsyncEngine,
    client: Any,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
    semaphore: asyncio.Semaphore,
) -> int:
    """Paginated REST OHLCV backfill for a single symbol — D-42.

    Pagination rule: each page is limit=1000 candles; the cursor advances by
    `last_candle_ts_ms + TIMEFRAME_MS[timeframe]` after each page, ensuring no
    off-by-one gaps or duplicate boundary rows.

    Semaphore: the caller passes `asyncio.Semaphore(8)` (default per D-42) to
    cap concurrent in-flight requests. This method holds the semaphore for its
    entire pagination loop, so one Semaphore slot = one symbol being backfilled.

    Idempotency: `copy_into_hypertable` uses ON CONFLICT (symbol, ts) DO NOTHING
    (STOR-08); re-running backfill against an already-populated range inserts 0 rows.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        client: Any object satisfying the MexcClient Protocol (fetch_ohlcv method).
        symbol: ccxt-unified swap symbol e.g. 'BTC/USDT:USDT' (D-40).
        timeframe: OHLCV timeframe string — must be '1m' or '1d' to write to a hypertable.
                   CA timeframes ('5m','15m','1h','4h') are silently skipped (returns 0).
        since: Start of the backfill window (inclusive), tz-aware UTC.
        until: End of the backfill window (exclusive), tz-aware UTC.
        semaphore: Bounded concurrency semaphore. Held for the full pagination loop.

    Returns:
        Total number of records written (sum across all pages). Returns 0 immediately
        if `timeframe` is a continuous-aggregate timeframe.
    """
    if timeframe not in TIMEFRAME_TO_TABLE:
        log.warning(
            "ohlcv.backfill.skipped_ca_timeframe",
            symbol=symbol,
            timeframe=timeframe,
            reason="5m/15m/1h/4h materialize from continuous aggregates over raw_mexc_candles_1m",
        )
        return 0

    target_table = TIMEFRAME_TO_TABLE[timeframe]
    ms_step = TIMEFRAME_MS[timeframe]
    cursor = int(since.timestamp() * 1000)
    end_ms = int(until.timestamp() * 1000)
    total_written = 0

    async with semaphore:
        while cursor < end_ms:
            since_dt = datetime.fromtimestamp(cursor / 1000, tz=UTC)
            until_dt = datetime.fromtimestamp(end_ms / 1000, tz=UTC)

            candles = await client.fetch_ohlcv(symbol, timeframe, since_dt, until_dt)
            if not candles:
                break  # No more data in this window

            # Build records tuple matching raw_mexc_candles_1m column order
            records = [
                (c.symbol, c.ts, c.open, c.high, c.low, c.close, c.volume, "mexc_native", "ok")
                for c in candles
            ]

            n = await copy_into_hypertable(
                engine,
                target_table,
                records,
                columns=("symbol", "ts", "open", "high", "low", "close", "volume", "source", "quality_flag"),
                conflict_columns=("symbol", "ts"),
            )
            total_written += n

            # Advance cursor past the last received candle
            last_ts_ms = int(candles[-1].ts.timestamp() * 1000)
            cursor = last_ts_ms + ms_step

    log.info(
        "ohlcv.backfill.completed",
        symbol=symbol,
        timeframe=timeframe,
        total_written=total_written,
    )
    return total_written


# ---------------------------------------------------------------------------
# Universe-wide OHLCV backfill (TaskGroup — Pitfall 27)
# ---------------------------------------------------------------------------


async def backfill_universe(
    engine: AsyncEngine,
    client: Any,
    symbols: list[str],
    timeframes: list[str],
    since: datetime,
    until: datetime,
    max_concurrency: int = 8,
) -> dict[str, int]:
    """Backfill OHLCV for all (symbol, timeframe) combinations.

    Uses asyncio.TaskGroup (Pitfall 27 — no fire-and-forget tasks) and a shared
    Semaphore(max_concurrency) to cap concurrent in-flight REST pages.

    Args:
        engine: SQLAlchemy AsyncEngine.
        client: MexcClient Protocol instance.
        symbols: List of ccxt-unified swap symbols (D-40).
        timeframes: List of timeframe strings — non-CA timeframes only ('1m','1d').
        since: Backfill window start, tz-aware UTC.
        until: Backfill window end, tz-aware UTC.
        max_concurrency: Maximum simultaneous backfill coroutines (default 8 per D-42).

    Returns:
        Dict mapping '{symbol}.{timeframe}' → rows_written.
    """
    sem = asyncio.Semaphore(max_concurrency)
    results: dict[str, int] = {}

    async with asyncio.TaskGroup() as tg:
        tasks: dict[tuple[str, str], asyncio.Task[int]] = {}
        for sym in symbols:
            for tf in timeframes:
                tasks[(sym, tf)] = tg.create_task(
                    backfill_ohlcv(engine, client, sym, tf, since, until, sem),
                    name=f"backfill.ohlcv.{sym}.{tf}",
                )

    for (sym, tf), task in tasks.items():
        results[f"{sym}.{tf}"] = task.result()

    return results


# ---------------------------------------------------------------------------
# Per-symbol funding history REST backfill — D-44
# ---------------------------------------------------------------------------


async def backfill_funding(
    engine: AsyncEngine,
    client: Any,
    symbol: str,
    since: datetime,
    until: datetime,
    semaphore: asyncio.Semaphore,
) -> int:
    """Per-symbol funding rate history REST backfill — D-44.

    Writes through copy_into_hypertable → raw_mexc_funding with conflict on
    (symbol, settlement_ts). OI REST polling is deferred to plan 01-08 (scheduler).

    Args:
        engine: SQLAlchemy AsyncEngine.
        client: MexcClient Protocol instance.
        symbol: ccxt-unified swap symbol.
        since: Backfill window start, tz-aware UTC.
        until: Backfill window end, tz-aware UTC.
        semaphore: Bounded concurrency semaphore.

    Returns:
        Number of funding rows written.
    """
    async with semaphore:
        fundings = await client.fetch_funding_rate_history(symbol, since, until)
        if not fundings:
            return 0

        records = [
            (
                f.symbol,
                f.settlement_ts,
                f.published_ts,
                f.rate,
                f.next_funding_ts,
                "mexc_native",
                "ok",
            )
            for f in fundings
        ]

        n = await copy_into_hypertable(
            engine,
            "raw_mexc_funding",
            records,
            columns=(
                "symbol",
                "settlement_ts",
                "published_ts",
                "funding_rate",
                "next_funding_ts",
                "source",
                "quality_flag",
            ),
            conflict_columns=("symbol", "settlement_ts"),
        )
        log.info("funding.backfill.completed", symbol=symbol, total_written=n)
        return n
