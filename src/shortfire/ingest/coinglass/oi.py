"""Coinglass open-interest history per-symbol fetcher.

D-53: OI history fetched per-symbol; caller round-robins through universe (RESEARCH.md §4.6).
      Each call: one symbol, one interval ("1h" default).
D-59: source='coinglass_aggregate' hardcoded in every record.
D-62: copy_into_hypertable uses ON CONFLICT DO NOTHING — idempotent re-ingest.
D-54: 1m OI backfill capped at ~6 days (Hobbyist tier); Phase 1 uses "1h" interval.

RESEARCH.md §4.6 round-robin pattern:
  The scheduler job (plan 01-09) maintains a position cursor in ingest_runs.kv_state
  and advances it by one symbol per tick. This module is stateless — it simply
  fetches one symbol's OI history and writes it. The caller owns the cursor.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.coinglass.client import CoinglassClient
from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.coinglass.oi")


async def fetch_and_write(
    engine: AsyncEngine,
    client: CoinglassClient,
    symbol_unified: str,
    coinglass_symbol: str,
    interval: str = "1h",
) -> int:
    """Per-symbol Coinglass OI history fetcher.

    Args:
        engine: AsyncEngine — write target (raw_coinglass_oi hypertable).
        client: CoinglassClient — Coinglass API read source.
        symbol_unified: ccxt unified symbol (e.g. "BTC/USDT:USDT") — used for DB insert.
        coinglass_symbol: Coinglass bare-coin symbol (e.g. "BTC") — used for API call.
        interval: Time granularity ("1h", "4h", "1d"). Default "1h" per D-53.

    Returns:
        Number of rows in the batch (0 if API call failed).
    """
    resp = await client.fetch_open_interest_history(coinglass_symbol, interval=interval)
    if resp is None:
        log.warning("oi.skipped", symbol=symbol_unified, reason="fetch returned None")
        return 0

    records = resp.to_records(symbol_unified=symbol_unified, source="coinglass_aggregate")

    n = await copy_into_hypertable(
        engine,
        "raw_coinglass_oi",
        records,
        columns=("symbol", "ts", "open_interest", "source", "quality_flag"),
        conflict_columns=("symbol", "ts", "source"),
    )
    log.info("oi.completed", symbol=symbol_unified, rows_written=n)
    return n
