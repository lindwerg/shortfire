"""OI REST round-robin — fetch_open_interest_history with kv_state cursor (D-45).

D-45: MEXC OI ingest is REST-only (no reliable ws stream in ccxt 4.5.x for OI).
Round-robin pattern adapted from RESEARCH.md §4.6 (Coinglass round-robin):
  - On each step, fetch a batch of `batch_size` symbols starting at kv_state['last_symbol_index']
  - Advance the cursor; wrap to 0 when reaching end of universe
  - kv_state is caller-managed (APScheduler job stores it in ingest_runs.kv_state in Phase 1.x)
  - For Phase 1, pass kv_state dict as a mutable argument and persist externally if needed

D-49: freshness gauge updated on every successful COPY.
Pitfall 27: oi_round_robin_step is called by APScheduler-managed cron tasks, NOT spawned
            as a bare asyncio.create_task. The streams.py TaskGroup does not manage OI —
            OI scheduling lives in the APScheduler layer (D-78).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.mexc.client import MexcClient
from shortfire.ingest.storage.copy import copy_into_hypertable
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.oi")


async def oi_round_robin_step(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
    batch_size: int = 5,
    kv_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Round-robin fetch_open_interest_history over the symbol universe (D-45).

    On each call, polls `batch_size` symbols starting at kv_state['last_symbol_index'],
    COPYs records into raw_mexc_oi, and advances the cursor (wrapping at len(symbols)).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg. Can be None in unit tests
                when kv_state mutation is the only assertion.
        mexc_client: MexcClient instance with fetch_open_interest_history.
        symbols: Ordered symbol list (tier-1 first per D-46 priority convention).
        batch_size: Symbols to fetch per step (default 5).
        kv_state: Persistent cursor dict {'last_symbol_index': int}.
                  Mutated in-place and returned. Defaults to {'last_symbol_index': 0}.

    Returns:
        Updated kv_state dict with advanced cursor.
    """
    if kv_state is None:
        kv_state = {"last_symbol_index": 0}

    n_symbols = max(len(symbols), 1)
    start = kv_state.get("last_symbol_index", 0) % n_symbols
    end = min(start + batch_size, len(symbols))
    symbol_slice = symbols[start:end]

    metrics = build_data_platform_metrics()
    records: list[tuple[Any, ...]] = []

    for sym in symbol_slice:
        try:
            rows = await mexc_client.fetch_open_interest_history(sym, timeframe="1h")
            for row in rows:
                # MexcOpenInterestRow.timestamp is int (ms) — convert to tz-aware UTC (Pitfall 17)
                ts = datetime.fromtimestamp(row.timestamp / 1000, tz=UTC)
                records.append(
                    (
                        sym,
                        ts,
                        row.openInterestAmount if row.openInterestAmount else Decimal("0"),
                        "mexc_native",
                        "ok",
                    )
                )
        except Exception as exc:
            await write_to_dead_letter(
                "mexc_native",
                "fetch_open_interest_history",
                sym,
                "",
                type(exc).__name__,
                str(exc)[:2000],
            )

    if records:
        n = await copy_into_hypertable(
            engine,
            "raw_mexc_oi",
            records,
            columns=("symbol", "ts", "open_interest", "source", "quality_flag"),
            conflict_columns=("symbol", "ts"),
        )
        for sym in {r[0] for r in records}:
            metrics.source_freshness_seconds.labels(source="mexc_native", dataset="oi", symbol=sym).set(
                time.time()
            )
        metrics.ingest_rows_total.labels(source="mexc_native", dataset="oi").inc(n)

    # Advance cursor — wrap to 0 when the end of the universe is reached
    kv_state["last_symbol_index"] = end if end < len(symbols) else 0
    return kv_state
