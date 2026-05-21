"""Unit tests for Phase 1 DataPlatformMetrics (D-84).

Tests:
  1. build_data_platform_metrics() returns a NamedTuple with 8 fields matching D-84 names.
  2. Each metric has the correct Prometheus name and label names.
  3. Idempotency: two calls return the same instances (cache works).
  4. All metrics are registered on the shared REGISTRY (not a fresh registry).
"""

from prometheus_client import Counter, Gauge, Histogram
from shortfire.observability.metrics_data_platform import DataPlatformMetrics, build_data_platform_metrics

from shortfire.observability.metrics import REGISTRY


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
    """Each metric's _name attribute matches the locked D-84 Prometheus name."""
    m = build_data_platform_metrics()
    assert m.ingest_rows_total._name == "shortfire_data_platform_ingest_rows_total"
    assert m.ingest_duration_seconds._name == "shortfire_data_platform_ingest_duration_seconds"
    assert m.source_freshness_seconds._name == "shortfire_data_platform_source_freshness_seconds"
    assert m.dead_letter_total._name == "shortfire_data_platform_dead_letter_total"
    assert m.universe_symbols_count._name == "shortfire_data_platform_universe_symbols_count"
    assert m.backup_age_seconds._name == "shortfire_data_platform_backup_age_seconds"
    assert m.ws_reconnects_total._name == "shortfire_data_platform_ws_reconnects_total"
    assert m.rate_limit_remaining._name == "shortfire_data_platform_rate_limit_remaining"


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
    assert list(m.ingest_rows_total._labelnames) == ["source", "dataset"]
    # Histogram with labels source, dataset
    assert list(m.ingest_duration_seconds._labelnames) == ["source", "dataset"]
    # Gauge with labels source, dataset, symbol
    assert list(m.source_freshness_seconds._labelnames) == ["source", "dataset", "symbol"]
    # Counter with labels source, error_type
    assert list(m.dead_letter_total._labelnames) == ["source", "error_type"]
    # Gauge with label status
    assert list(m.universe_symbols_count._labelnames) == ["status"]
    # Gauge with no labels
    assert list(m.backup_age_seconds._labelnames) == []
    # Counter with labels source, stream
    assert list(m.ws_reconnects_total._labelnames) == ["source", "stream"]
    # Gauge with label source
    assert list(m.rate_limit_remaining._labelnames) == ["source"]


def test_idempotency() -> None:
    """Calling build_data_platform_metrics() twice returns the same object instances (cache)."""
    m1 = build_data_platform_metrics()
    m2 = build_data_platform_metrics()
    assert m1 is m2, "build_data_platform_metrics() must return cached instance on second call"


def test_metrics_registered_on_shared_registry() -> None:
    """All metrics are on the shared REGISTRY from metrics.py — not a fresh registry (D-84)."""
    build_data_platform_metrics()
    registered_names = {c._name for c in REGISTRY.collect() if hasattr(c, "_name")}
    assert "shortfire_data_platform_ingest_rows_total" in registered_names, (
        "ingest_rows_total not found in shared REGISTRY"
    )
    assert "shortfire_data_platform_backup_age_seconds" in registered_names, (
        "backup_age_seconds not found in shared REGISTRY"
    )
