"""Dual-source liquidations — ws-only in Phase 1 per D-48 revision.

D-48 (W3 reconciliation): Phase 1 ships ws-only liquidations:
  - If watch_liquidations is present in ccxt 4.5.x MEXC swap class: use it
  - If absent: emit liquidations.degraded event; set freshness gauge to 0 sentinel;
    exit cleanly so the TaskGroup continues with other streams

REST fallback is deferred to Phase 1.x patch per PHASE-1-DECISIONS.md §D-48-REVISION.
Coinglass aggregate liquidations (plan 01-06) carry the cross-exchange signal in the interim.

quality_flag='partial_capture' enum value is RESERVED in migration 0008 (D-60) for the
Phase 1.x REST fallback — not written in Phase 1 but kept for future use.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.base import ts_from_ms
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.mexc.client import MexcClient
from shortfire.ingest.storage.copy import copy_into_hypertable
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.liquidations")


async def liquidations_dual_source_loop(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
) -> None:
    """Liquidations ws-only (D-48 revision per 01-08 plan W3 reconciliation).

    REST fallback deferred to Phase 1.x or Phase 2 EDA follow-up.
    Decision recorded in docs/PHASE-1-DECISIONS.md §D-48-REVISION.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient; ws_client property used for watch_liquidations.
        symbols: List of ccxt-unified swap symbols.
    """
    metrics = build_data_platform_metrics()
    raw = mexc_client.ws_client  # ccxt.pro.mexc instance

    if not hasattr(raw, "watch_liquidations"):
        # D-48 revision: ws unavailable in this ccxt minor — degraded path
        log.warning(
            "liquidations.degraded",
            reason="ws_unavailable_phase1_ships_no_fallback",
            fallback="coinglass_aggregate_liquidations (plan 01-06)",
        )
        # Sentinel: set freshness gauge to 0 so the freshness alerter fires 'freshness.degraded'
        for sym in symbols:
            metrics.source_freshness_seconds.labels(
                source="mexc_native", dataset="liquidations", symbol=sym
            ).set(0)
        # partial_capture quality_flag is RESERVED for Phase 1.x REST fallback — not written here
        return  # exit cleanly; TaskGroup continues with other streams

    log.info("ws.connected", source="mexc_native", stream="liquidations", mode="ws")

    try:
        while True:
            try:
                # ccxt watch_liquidations may accept symbol or None (exchange-dependent)
                sym_arg: str | None = symbols[0] if len(symbols) == 1 else None
                liq: Any = await raw.watch_liquidations(sym_arg)
            except Exception as exc:
                metrics.ws_reconnects_total.labels(source="mexc_native", stream="liquidations").inc()
                log.warning(
                    "ws.reconnect",
                    source="mexc_native",
                    stream="liquidations",
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(2.0)
                continue

            events: list[Any] = liq if isinstance(liq, list) else [liq]  # type: ignore[assignment]
            for evt in events:
                try:
                    # Use amount or qty (ccxt field name varies by exchange version)
                    qty_raw = evt.get("amount") or evt.get("qty") or "0"
                    record: tuple[Any, ...] = (
                        evt["symbol"],
                        ts_from_ms(evt["timestamp"]),
                        evt["side"],
                        Decimal(str(qty_raw)),
                        Decimal(str(evt["price"])),
                        "mexc_native",
                        "ok",
                    )
                    await copy_into_hypertable(
                        engine,
                        "raw_mexc_liquidations",
                        [record],
                        columns=("symbol", "ts", "side", "qty", "price", "source", "quality_flag"),
                        conflict_columns=("symbol", "ts", "side", "qty", "price"),
                    )
                    metrics.source_freshness_seconds.labels(
                        source="mexc_native", dataset="liquidations", symbol=evt["symbol"]
                    ).set(time.time())
                    metrics.ingest_rows_total.labels(source="mexc_native", dataset="liquidations").inc()
                except Exception as exc:
                    await write_to_dead_letter(
                        "mexc_native",
                        "watch_liquidations",
                        evt.get("symbol"),
                        str(evt)[:8000],
                        type(exc).__name__,
                        str(exc)[:2000],
                    )

    except asyncio.CancelledError:
        log.info("ws.disconnected", source="mexc_native", stream="liquidations")
        raise
