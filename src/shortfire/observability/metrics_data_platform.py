"""Phase 1 data-platform metric families on the shared CollectorRegistry (D-84).

Registers 8 new Prometheus metric families on the SAME custom REGISTRY exported by
shortfire.observability.metrics — never on prometheus_client.REGISTRY (the default
global), and never on a freshly constructed CollectorRegistry.

Per D-84 and PATTERNS.md Group 11, all metric families follow the naming convention:
    shortfire_data_platform_<subsystem>_<metric_name>_<unit>

Idempotency guarantee: build_data_platform_metrics() is safe to call multiple times;
the module-level cache ensures prometheus_client never receives duplicate registrations
(which would raise ValueError("Duplicated timeseries") at runtime).

Usage:
    from shortfire.observability.metrics_data_platform import build_data_platform_metrics

    dp = build_data_platform_metrics()
    dp.ingest_rows_total.labels(source="mexc", dataset="candles_1m").inc()
    dp.source_freshness_seconds.labels(source="mexc", dataset="candles_1m", symbol="BTC/USDT:USDT").set(30.0)
"""

from typing import NamedTuple

from prometheus_client import Counter, Gauge, Histogram

from shortfire.observability.metrics import LATENCY_BUCKETS, REGISTRY


class DataPlatformMetrics(NamedTuple):
    """8 Prometheus metric families for the data-platform service (D-84).

    Field names mirror the metric suffix for readability at call sites.
    """

    ingest_rows_total: Counter
    ingest_duration_seconds: Histogram
    source_freshness_seconds: Gauge
    dead_letter_total: Counter
    universe_symbols_count: Gauge
    backup_age_seconds: Gauge
    ws_reconnects_total: Counter
    rate_limit_remaining: Gauge


# Module-level cache — ensures idempotent calls across re-imports (same singleton
# REGISTRY persists for the lifetime of the process, so attempting to re-register
# a metric raises ValueError; the cache short-circuits that).
_dp_metrics_cache: DataPlatformMetrics | None = None


def build_data_platform_metrics() -> DataPlatformMetrics:
    """Build (or return cached) DataPlatformMetrics registered on the shared REGISTRY.

    Per D-84: all metrics use the existing custom REGISTRY from
    shortfire.observability.metrics — NEVER a new CollectorRegistry.
    Per PATTERNS.md Group 11: use the shared LATENCY_BUCKETS for histogram bucket sets.

    Returns:
        DataPlatformMetrics NamedTuple with 8 registered metric families.
    """
    global _dp_metrics_cache
    if _dp_metrics_cache is not None:
        return _dp_metrics_cache

    _dp_metrics_cache = DataPlatformMetrics(
        ingest_rows_total=Counter(
            "shortfire_data_platform_ingest_rows_total",
            "Total rows written per ingest run, by source and dataset",
            ["source", "dataset"],
            registry=REGISTRY,
        ),
        ingest_duration_seconds=Histogram(
            "shortfire_data_platform_ingest_duration_seconds",
            "Duration of a single ingest batch in seconds, by source and dataset",
            ["source", "dataset"],
            buckets=LATENCY_BUCKETS,
            registry=REGISTRY,
        ),
        source_freshness_seconds=Gauge(
            "shortfire_data_platform_source_freshness_seconds",
            "Seconds since last successful row written for (source, dataset, symbol)",
            ["source", "dataset", "symbol"],
            registry=REGISTRY,
        ),
        dead_letter_total=Counter(
            "shortfire_data_platform_dead_letter_total",
            "Count of rows routed to dead_letter by source and error_type",
            ["source", "error_type"],
            registry=REGISTRY,
        ),
        universe_symbols_count=Gauge(
            "shortfire_data_platform_universe_symbols_count",
            "Current count of universe symbols by status (active, delisted, new)",
            ["status"],
            registry=REGISTRY,
        ),
        backup_age_seconds=Gauge(
            "shortfire_data_platform_backup_age_seconds",
            "Seconds since the most recent successful R2 backup completed",
            registry=REGISTRY,
        ),
        ws_reconnects_total=Counter(
            "shortfire_data_platform_ws_reconnects_total",
            "WebSocket reconnect attempts by source and stream name",
            ["source", "stream"],
            registry=REGISTRY,
        ),
        rate_limit_remaining=Gauge(
            "shortfire_data_platform_rate_limit_remaining",
            "Remaining rate-limit tokens for the given source API",
            ["source"],
            registry=REGISTRY,
        ),
    )
    return _dp_metrics_cache
