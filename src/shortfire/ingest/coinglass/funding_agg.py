"""Coinglass funding-rate-list batch fetcher.

D-53: funding_agg uses the BATCH endpoint — one call per 5-min tick covers ALL active symbols.
       No per-symbol polling required (unlike oi/liq/lsr which are per-symbol).
D-59: source='coinglass_aggregate' is hardcoded in every record (never from wire payload).
D-62: copy_into_hypertable uses ON CONFLICT DO NOTHING — idempotent re-ingest.
T-1-CG-06: Coinglass returns bare-coin symbols ("BTC"); caller provides coinglass_to_unified
            mapping from symbols.coinglass_symbol (plan 01-04). Unmapped symbols are SKIPPED
            with a structlog warning rather than written with wrong attribution.

RESEARCH.md §4.6: Batch funding endpoint preferred over per-symbol polling because:
  - One API call covers all symbols (lower quota pressure under 28/min Hobbyist cap)
  - Single timestamp for all rows in the batch (consistent funding-window snapshot)
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.coinglass.client import CoinglassClient
from shortfire.ingest.storage.copy import copy_into_hypertable

log = structlog.get_logger("ingest.coinglass.funding_agg")


async def fetch_and_write(
    engine: AsyncEngine,
    client: CoinglassClient,
    coinglass_to_unified: dict[str, str],
) -> int:
    """Batch funding-rate-list endpoint writer (D-53: every 5 min, one call covers all symbols).

    Args:
        engine: AsyncEngine — write target (raw_coinglass_funding_agg hypertable).
        client: CoinglassClient — Coinglass API read source.
        coinglass_to_unified: Mapping from Coinglass bare-coin symbol ("BTC") to
                              ccxt unified symbol ("BTC/USDT:USDT").
                              Built by the universe-snapshot job (plan 01-09) from
                              symbols.coinglass_symbol lookup table (plan 01-04).
                              This module's responsibility ends at insertion —
                              symbol mapping is the caller's concern.

    Returns:
        Number of rows in the batch (including skipped/conflict rows).
        0 if the API call failed (dead_letter already logged by client).
    """
    resp = await client.fetch_funding_rate_list()
    if resp is None:
        log.warning("funding_agg.skipped", reason="fetch returned None — dead_letter already logged")
        return 0

    ts_now = datetime.now(UTC)
    records = []

    for row in resp.data:
        unified = coinglass_to_unified.get(row.symbol)
        if unified is None:
            # T-1-CG-06: symbol not in mapping → skip with warning, never write wrong attribution
            log.warning("funding_agg.unmapped_symbol", coinglass_symbol=row.symbol)
            continue
        if row.funding_rate is None:
            # Coinglass returns null funding_rate for illiquid symbols — safe to skip
            log.debug("funding_agg.null_funding_rate", coinglass_symbol=row.symbol)
            continue
        # D-59: source='coinglass_aggregate' hardcoded — never from wire payload
        records.append((unified, ts_now, row.funding_rate, "coinglass_aggregate", "ok"))

    n = await copy_into_hypertable(
        engine,
        "raw_coinglass_funding_agg",
        records,
        columns=("symbol", "ts", "funding_rate", "source", "quality_flag"),
        conflict_columns=("symbol", "ts", "source"),
    )
    log.info("funding_agg.completed", rows_written=n)
    return n
