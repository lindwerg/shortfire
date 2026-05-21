"""Unit tests for Phase 1 DataPlatformMetrics (D-84).

Tests:
  1. build_data_platform_metrics() returns a NamedTuple with 8 fields matching D-84 names.
  2. Each metric has the correct Prometheus name and label names.
  3. Idempotency: two calls return the same instances (cache works).
  4. All metrics are registered on the shared REGISTRY (not a fresh registry).

Note: prometheus_client metrics expose internals (_name, _labelnames, _original_name)
that carry no public typed API. The pyright: ignore comments on those assertions are
intentional — testing library internals is the only way to assert metric configuration.
"""

from prometheus_client import Counter, Gauge, Histogram

from shortfire.observability.metrics import REGISTRY
from shortfire.observability.metrics_data_platform import DataPlatformMetrics, build_data_platform_metrics


def test_returns_data_platform_metrics_namedtuple() -> None:
    """build_data_platform_metrics() returns a DataPlatformMetrics NamedTuple."""
    m = build_data_platform_metrics()
    assert isinstance(m, DataPlatformMetrics)


def test_has_all_8_fields() -> None:
    """Returned NamedTuple has all 8 metric family fields from D-84."""
    m = build_data_platform_metrics()
    expected_fields = {
        "ingest_rows_total",
        "ingest_duration_seconds",
        "source_freshness_seconds",
        "dead_letter_total",
        "universe_symbols_count",
        "backup_age_seconds",
        "ws_reconnects_total",
        "rate_limit_remaining",
    }
    actual_fields = set(m._fields)
    assert actual_fields == expected_fields, f"Field mismatch. Missing: {expected_fields - actual_fields}"


def test_prometheus_metric_names() -> None:
    """Each metric's Prometheus name matches the locked D-84 name.

    prometheus_client Counter strips the '_total' suffix from ._name but preserves
    it in ._original_name. We use ._original_name for Counters and ._name for others.
    """
    m = build_data_platform_metrics()
    # Counters: _original_name preserves the full name including '_total'
    assert m.ingest_rows_total._original_name == "shortfire_data_platform_ingest_rows_total"  # pyright: ignore[reportPrivateUsage]
    assert m.dead_letter_total._original_name == "shortfire_data_platform_dead_letter_total"  # pyright: ignore[reportPrivateUsage]
    assert m.ws_reconnects_total._original_name == "shortfire_data_platform_ws_reconnects_total"  # pyright: ignore[reportPrivateUsage]
    # Histogram and Gauges: _name holds the full name
    assert m.ingest_duration_seconds._name == "shortfire_data_platform_ingest_duration_seconds"  # pyright: ignore[reportPrivateUsage]
    assert m.source_freshness_seconds._name == "shortfire_data_platform_source_freshness_seconds"  # pyright: ignore[reportPrivateUsage]
    assert m.universe_symbols_count._name == "shortfire_data_platform_universe_symbols_count"  # pyright: ignore[reportPrivateUsage]
    assert m.backup_age_seconds._name == "shortfire_data_platform_backup_age_seconds"  # pyright: ignore[reportPrivateUsage]
    assert m.rate_limit_remaining._name == "shortfire_data_platform_rate_limit_remaining"  # pyright: ignore[reportPrivateUsage]


def test_metric_types() -> None:
    """Each metric is the correct prometheus_client type per D-84."""
    m = build_data_platform_metrics()
    assert isinstance(m.ingest_rows_total, Counter)
    assert isinstance(m.ingest_duration_seconds, Histogram)
    assert isinstance(m.source_freshness_seconds, Gauge)
    assert isinstance(m.dead_letter_total, Counter)
    assert isinstance(m.universe_symbols_count, Gauge)
    assert isinstance(m.backup_age_seconds, Gauge)
    assert isinstance(m.ws_reconnects_total, Counter)
    assert isinstance(m.rate_limit_remaining, Gauge)


def test_label_names() -> None:
    """Each metric has the correct label names per D-84."""
    m = build_data_platform_metrics()
    # Counter with labels source, dataset
    assert list(m.ingest_rows_total._labelnames) == ["source", "dataset"]  # pyright: ignore[reportPrivateUsage]
    # Histogram with labels source, dataset
    assert list(m.ingest_duration_seconds._labelnames) == ["source", "dataset"]  # pyright: ignore[reportPrivateUsage]
    # Gauge with labels source, dataset, symbol
    assert list(m.source_freshness_seconds._labelnames) == ["source", "dataset", "symbol"]  # pyright: ignore[reportPrivateUsage]
    # Counter with labels source, error_type
    assert list(m.dead_letter_total._labelnames) == ["source", "error_type"]  # pyright: ignore[reportPrivateUsage]
    # Gauge with label status
    assert list(m.universe_symbols_count._labelnames) == ["status"]  # pyright: ignore[reportPrivateUsage]
    # Gauge with no labels
    assert list(m.backup_age_seconds._labelnames) == []  # pyright: ignore[reportPrivateUsage]
    # Counter with labels source, stream
    assert list(m.ws_reconnects_total._labelnames) == ["source", "stream"]  # pyright: ignore[reportPrivateUsage]
    # Gauge with label source
    assert list(m.rate_limit_remaining._labelnames) == ["source"]  # pyright: ignore[reportPrivateUsage]


def test_idempotency() -> None:
    """Calling build_data_platform_metrics() twice returns the same object instances (cache)."""
    m1 = build_data_platform_metrics()
    m2 = build_data_platform_metrics()
    assert m1 is m2, "build_data_platform_metrics() must return cached instance on second call"


def test_metrics_registered_on_shared_registry() -> None:
    """All metrics are on the shared REGISTRY from metrics.py — not a fresh registry (D-84).

    REGISTRY.collect() returns Metric objects whose .name attribute strips the '_total'
    suffix from Counter names (prometheus_client internal representation).
    We check by the stripped names that appear in REGISTRY.collect().
    """
    build_data_platform_metrics()
    registered_names = {c.name for c in REGISTRY.collect()}
    # Counters appear without _total in collect() output
    assert "shortfire_data_platform_ingest_rows" in registered_names, (
        "ingest_rows_total not found in shared REGISTRY"
    )
    # Gauge — full name preserved
    assert "shortfire_data_platform_backup_age_seconds" in registered_names, (
        "backup_age_seconds not found in shared REGISTRY"
    )
