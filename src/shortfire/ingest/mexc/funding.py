"""Live funding rate ws stream — watch_funding_rate with dual-timestamp capture.

D-44: Captures BOTH fundingTimestamp (settlement_ts) AND timestamp (published_ts)
      to mitigate Pitfall 2/16 (published vs settlement ambiguity).
D-49: freshness gauge updated on every successful write.
Pitfall 27: funding_live_loop runs under asyncio.TaskGroup in streams.py.
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
from shortfire.observability.events import assert_event_registered
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.funding")


async def funding_live_loop(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
) -> None:
    """Per-symbol watch_funding_rate persistence with dual-timestamp capture.

    D-44: settlement_ts from fundingTimestamp field; published_ts from timestamp field.
    Invariant: both timestamps captured; feature pipelines can reconstruct the
    publication lag (published_ts → settlement_ts) for funding-rate timing features.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient wrapping a ccxt.pro.mexc instance.
        symbols: List of ccxt-unified swap symbols to subscribe to.
    """
    assert_event_registered("ws.connected")
    log.info("ws.connected", source="mexc_native", stream="funding")
    metrics = build_data_platform_metrics()
    raw = mexc_client.ws_client  # ccxt.pro.mexc instance (via ws_client property)

    try:
        while True:
            for sym in symbols:
                try:
                    f: dict[str, Any] = await raw.watch_funding_rate(sym)
                except Exception as exc:
                    metrics.ws_reconnects_total.labels(source="mexc_native", stream="funding").inc()
                    log.warning(
                        "ws.reconnect",
                        source="mexc_native",
                        stream="funding",
                        symbol=sym,
                        error_type=type(exc).__name__,
                    )
                    await asyncio.sleep(2.0)
                    continue

                try:
                    # D-44 dual-timestamp capture:
                    # settlement_ts = fundingTimestamp (when the funding is settled)
                    # published_ts  = timestamp       (when the rate was published)
                    settlement_ts = ts_from_ms(f.get("fundingTimestamp") or f["timestamp"])
                    published_ts = ts_from_ms(f["timestamp"])
                    next_funding_ts = (
                        ts_from_ms(f["nextFundingTimestamp"]) if f.get("nextFundingTimestamp") else None
                    )
                    record: tuple[Any, ...] = (
                        sym,
                        settlement_ts,
                        published_ts,
                        Decimal(str(f["fundingRate"])),
                        next_funding_ts,
                        "mexc_native",
                        "ok",
                    )
                    await copy_into_hypertable(
                        engine,
                        "raw_mexc_funding",
                        [record],
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
                    metrics.source_freshness_seconds.labels(
                        source="mexc_native", dataset="funding", symbol=sym
                    ).set(time.time())
                    metrics.ingest_rows_total.labels(source="mexc_native", dataset="funding").inc()
                except Exception as exc:
                    await write_to_dead_letter(
                        "mexc_native",
                        "watch_funding_rate",
                        sym,
                        str(f)[:8000],
                        type(exc).__name__,
                        str(exc)[:2000],
                    )

    finally:
        assert_event_registered("ws.disconnected")
        log.info("ws.disconnected", source="mexc_native", stream="funding")
