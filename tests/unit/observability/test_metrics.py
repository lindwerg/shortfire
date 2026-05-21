"""Tests for Prometheus metrics registry and ServiceMetrics factory.

Tests:
  5. REGISTRY is a custom CollectorRegistry (not prometheus_client.REGISTRY)
  6. build_metrics_for_service creates metrics with correct names
  7. Histogram has locked bucket list per UI-SPEC §Metric registry
  8. Empty-state contract: /metrics emits # HELP + # TYPE even before traffic
  9. build_info gauge can be set
"""

from prometheus_client import REGISTRY as DEFAULT_REGISTRY
from prometheus_client import CollectorRegistry, generate_latest
from shortfire.observability.metrics import (
    LATENCY_BUCKETS,
    REGISTRY,
    ServiceMetrics,
    build_metrics_for_service,
)


def test_registry_is_custom_collector_registry() -> None:
    """REGISTRY must be a custom CollectorRegistry, NOT prometheus_client.REGISTRY."""
    assert isinstance(REGISTRY, CollectorRegistry), (
        f"REGISTRY must be a CollectorRegistry instance, got {type(REGISTRY)!r}"
    )
    assert REGISTRY is not DEFAULT_REGISTRY, (
        "REGISTRY must NOT be the default global prometheus_client.REGISTRY — "
        "use a custom CollectorRegistry to avoid leaking process metrics (UI-SPEC §/metrics)"
    )


def test_build_metrics_for_service_returns_service_metrics() -> None:
    """build_metrics_for_service returns a ServiceMetrics NamedTuple with 4 metric attributes."""
    metrics = build_metrics_for_service("test_service_a")
    assert isinstance(metrics, ServiceMetrics)
    assert hasattr(metrics, "http_requests_total")
    assert hasattr(metrics, "http_request_duration_seconds")
    assert hasattr(metrics, "service_event_emitted_total")
    assert hasattr(metrics, "build_info")


def test_metric_names_follow_shortfire_naming_convention() -> None:
    """Metric names must follow shortfire_<svc>_<metric> convention (UI-SPEC §Metric naming)."""
    build_metrics_for_service("test_service_b")
    body = generate_latest(REGISTRY).decode()

    assert "shortfire_test_service_b_http_requests_total" in body, (
        "shortfire_test_service_b_http_requests_total not found in metrics output"
    )
    assert "shortfire_test_service_b_http_request_duration_seconds" in body, (
        "shortfire_test_service_b_http_request_duration_seconds not found in metrics output"
    )
    assert "shortfire_test_service_b_service_event_emitted_total" in body, (
        "shortfire_test_service_b_service_event_emitted_total not found in metrics output"
    )
    assert "shortfire_test_service_b_build_info" in body, (
        "shortfire_test_service_b_build_info not found in metrics output"
    )


def test_kebab_case_service_name_normalized_to_snake_case() -> None:
    """kebab-case service names must be normalized to snake_case for Prometheus (UI-SPEC §Metric naming)."""
    build_metrics_for_service("data-platform-x")
    body = generate_latest(REGISTRY).decode()
    assert "shortfire_data_platform_x_http_requests_total" in body, (
        "kebab-case normalization failed: hyphens must become underscores"
    )


def test_histogram_has_locked_bucket_list() -> None:
    """HTTP latency histogram must use the exact bucket list from UI-SPEC §Metric registry."""
    expected = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    assert expected == LATENCY_BUCKETS, (
        f"LATENCY_BUCKETS mismatch. Expected {expected}, got {LATENCY_BUCKETS}"
    )
    # Verify the buckets appear in the rendered output
    build_metrics_for_service("test_service_c")
    body = generate_latest(REGISTRY).decode()
    for bucket in expected:
        assert (
            f'le="{bucket}"' in body
            or f'le="{int(bucket)}.0"' in body
            or f'le="{bucket:.3f}"' in body
            or str(bucket) in body
        ), f"Bucket le={bucket} not found in metrics output"


def test_empty_state_contract_help_and_type_lines_present() -> None:
    """Even before traffic, /metrics must emit # HELP and # TYPE lines (UI-SPEC empty-state contract)."""
    build_metrics_for_service("test_service_d")
    body = generate_latest(REGISTRY).decode()

    for metric_suffix in (
        "shortfire_test_service_d_http_requests",
        "shortfire_test_service_d_http_request_duration_seconds",
        "shortfire_test_service_d_service_event_emitted",
        "shortfire_test_service_d_build_info",
    ):
        assert f"# HELP {metric_suffix}" in body or "# HELP shortfire_test_service_d" in body, (
            f"# HELP line for {metric_suffix} missing from metrics output"
        )
        assert f"# TYPE {metric_suffix}" in body or "# TYPE shortfire_test_service_d" in body, (
            f"# TYPE line for {metric_suffix} missing from metrics output"
        )


def test_build_info_gauge_can_be_set() -> None:
    """build_info gauge can be set to 1 with version/commit_sha/env labels."""
    metrics = build_metrics_for_service("test_service_e")
    metrics.build_info.labels(version="0.1.0", commit_sha="abc123", env="ci").set(1)
    body = generate_latest(REGISTRY).decode()
    assert "shortfire_test_service_e_build_info" in body, (
        "build_info metric not found in rendered output after set(1)"
    )
    assert "1.0" in body, "build_info value 1.0 not found in rendered output"
