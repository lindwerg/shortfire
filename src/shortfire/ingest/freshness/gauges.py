"""Freshness gauge helper — updates source_freshness_seconds to current unix timestamp.

RESEARCH.md Open Q1 option B: the gauge stores the unix-timestamp-of-last-write for each
(source, dataset, symbol) tuple, NOT a duration. The alerter computes lag = now - gauge_value.

Usage:
    from shortfire.ingest.freshness.gauges import update_freshness_gauge

    update_freshness_gauge("mexc_native", "candles_1m", records)
"""

from __future__ import annotations

import time
from collections.abc import Iterable

import structlog

from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.freshness.gauges")


def update_freshness_gauge(source: str, dataset: str, records: Iterable[tuple]) -> None:  # type: ignore[type-arg]
    """Set the source_freshness_seconds gauge to time.time() for each (source, dataset, symbol).

    Called after every successful ingest batch write to mark the data as fresh.

    RESEARCH.md Open Q1 option B: gauge holds unix-timestamp-of-last-write so the alerter
    can compute lag = now - gauge_value without requiring a separate freshness-age metric.

    Args:
        source: Data source identifier (e.g. "mexc_native", "coinglass_aggregate").
        dataset: Dataset name (e.g. "candles_1m", "funding_agg").
        records: Iterable of record tuples. The first element of each tuple must be the
                 symbol (e.g. "BTC/USDT:USDT"). Empty records are silently ignored.
    """
    seen_symbols: set[str] = {r[0] for r in records if r}
    if not seen_symbols:
        return
    metrics = build_data_platform_metrics()
    now = time.time()
    for sym in seen_symbols:
        metrics.source_freshness_seconds.labels(
            source=source,
            dataset=dataset,
            symbol=sym,
        ).set(now)
    log.debug(
        "freshness.gauge.updated",
        source=source,
        dataset=dataset,
        n_symbols=len(seen_symbols),
        ts=now,
    )
