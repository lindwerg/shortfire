"""Coinglass long/short account ratio per-symbol fetcher.

D-53: LSR history fetched per-symbol; caller round-robins through universe.
D-59: source='coinglass_aggregate' hardcoded in every record.
D-62: copy_into_hypertable uses ON CONFLICT DO NOTHING — idempotent re-ingest.

long_short_ratio is the ratio of accounts holding long positions to accounts holding short.
Values > 1 indicate more longs than shorts; values < 1 indicate more shorts than longs.
Phase 2 feature engineering: divergence between Coinglass aggregated LSR and
MEXC-native LSR is a candidate short-after-pump signal feature.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.coinglass.client import CoinglassClient
from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.coinglass.lsr")


async def fetch_and_write(
    engine: AsyncEngine,
    client: CoinglassClient,
    symbol_unified: str,
    coinglass_symbol: str,
    interval: str = "1h",
) -> int:
    """Per-symbol Coinglass long/short account ratio history fetcher.

    Args:
        engine: AsyncEngine — write target (raw_coinglass_lsr hypertable).
        client: CoinglassClient — Coinglass API read source.
        symbol_unified: ccxt unified symbol (e.g. "XRP/USDT:USDT") — used for DB insert.
        coinglass_symbol: Coinglass bare-coin symbol (e.g. "XRP") — used for API call.
        interval: Time granularity ("1h", "4h", "1d"). Default "1h" per D-53.

    Returns:
        Number of rows in the batch (0 if API call failed).
    """
    resp = await client.fetch_long_short_account_ratio(coinglass_symbol, interval=interval)
    if resp is None:
        log.warning("lsr.skipped", symbol=symbol_unified, reason="fetch returned None")
        return 0

    records = resp.to_records(symbol_unified=symbol_unified, source="coinglass_aggregate")

    n = await copy_into_hypertable(
        engine,
        "raw_coinglass_lsr",
        records,
        columns=("symbol", "ts", "long_short_ratio", "source", "quality_flag"),
        conflict_columns=("symbol", "ts", "source"),
    )
    log.info("lsr.completed", symbol=symbol_unified, rows_written=n)
    return n
