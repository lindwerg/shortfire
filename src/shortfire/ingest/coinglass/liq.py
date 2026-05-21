"""Coinglass liquidation coin-history per-symbol fetcher.

D-53: liquidation history fetched per-symbol; caller round-robins through universe.
D-59: source='coinglass_aggregate' hardcoded in every record.
D-62: copy_into_hypertable uses ON CONFLICT DO NOTHING — idempotent re-ingest.

Each Coinglass data point has separate liquidation_long_usd and liquidation_short_usd.
This module converts ONE API data point into TWO hypertable rows (one per side:
'long' and 'short'), as required by raw_coinglass_liq schema (plan 01-04):
  PK = (symbol, ts, source, side)
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.coinglass.client import CoinglassClient
from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.coinglass.liq")


async def fetch_and_write(
    engine: AsyncEngine,
    client: CoinglassClient,
    symbol_unified: str,
    coinglass_symbol: str,
    interval: str = "1h",
) -> int:
    """Per-symbol Coinglass liquidation history fetcher.

    Args:
        engine: AsyncEngine — write target (raw_coinglass_liq hypertable).
        client: CoinglassClient — Coinglass API read source.
        symbol_unified: ccxt unified symbol (e.g. "ETH/USDT:USDT") — used for DB insert.
        coinglass_symbol: Coinglass bare-coin symbol (e.g. "ETH") — used for API call.
        interval: Time granularity ("1h", "4h", "1d"). Default "1h" per D-53.

    Returns:
        Number of rows in the batch (2 × data_length on full response; 0 if API failed).
        Two records per data point: one with side='long', one with side='short'.
    """
    resp = await client.fetch_liquidation_coin_history(coinglass_symbol, interval=interval)
    if resp is None:
        log.warning("liq.skipped", symbol=symbol_unified, reason="fetch returned None")
        return 0

    # to_records() already produces two rows per data point (long + short)
    # Columns: (symbol, ts, side, liquidation_usd, source, quality_flag)
    records = resp.to_records(symbol_unified=symbol_unified, source="coinglass_aggregate")

    n = await copy_into_hypertable(
        engine,
        "raw_coinglass_liq",
        records,
        columns=("symbol", "ts", "side", "liquidation_usd", "source", "quality_flag"),
        conflict_columns=("symbol", "ts", "source", "side"),
    )
    log.info("liq.completed", symbol=symbol_unified, rows_written=n)
    return n
