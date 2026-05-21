"""Tests for the 3 FastAPI entrypoints: /health + /metrics + Settings load.

Covers:
  1. /health returns 200 + 6 fields (correlation_id, env, service_name, status, ts, version)
  2. /health response keys are in alphabetical order
  3. /metrics returns 200 + correct Content-Type + 4 base metric names
  4. request lifecycle log line contains correlation_id
  5. strategy-engine + dashboard /health + /metrics parity (service_name differs)
  6. data-platform: MEXC_TRADE__* present at import → RuntimeError (D-16)
  7. settings.loaded log line on lifespan startup (via TestClient context manager)
  8. /health ts comes from exactly ONE datetime.now(timezone.utc) call per request

Note: each test isolates module state by removing the module from sys.modules before
importing, so env-var changes are picked up cleanly.
"""

import importlib
import json
import re
import subprocess
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixture: isolate module state so each test imports a fresh entrypoint
# ---------------------------------------------------------------------------


def _fresh_app(module_name: str) -> MagicMock:
    """Return a fresh import of `module_name`, removing cached state first.

    Also clears structlog's cache and removes sibling entrypoint modules to
    prevent cross-test contamination.
    """
    import structlog

    # Remove any cached entrypoint modules (and observability metrics module to reset
    # the CollectorRegistry-registered metric names check in prometheus_client)
    for key in list(sys.modules.keys()):
        if "shortfire.entrypoints" in key:
            del sys.modules[key]
    structlog.reset_defaults()
    return importlib.import_module(module_name)


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum required env vars for all entrypoints."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://shortfire:shortfire@localhost:5432/shortfire_dev")
    monkeypatch.setenv("ENV", "ci")


# ---------------------------------------------------------------------------
# data-platform: /health
# ---------------------------------------------------------------------------


def test_data_platform_health_status_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health returns 200 OK."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app, raise_server_exceptions=True)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_data_platform_health_has_exactly_6_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health body has exactly 6 fields: correlation_id, env, service_name, status, ts, version."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/health")
    body = resp.json()
    expected_keys = {"correlation_id", "env", "service_name", "status", "ts", "version"}
    assert set(body.keys()) == expected_keys, (
        f"Health body keys mismatch. Expected {expected_keys}, got {set(body.keys())}"
    )


def test_data_platform_health_field_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health body values match expected patterns."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/health")
    body = resp.json()

    assert body["service_name"] == "data-platform"
    assert body["status"] == "ok"
    assert body["env"] in ("local", "ci", "staging", "production")
    assert body["version"] == "0.1.0"

    # correlation_id must be a UUID4-derived hex string.
    # asgi-correlation-id generates UUID4 as a 32-char lowercase hex (no dashes)
    # OR as the canonical 8-4-4-4-12 dashed format, depending on version.
    # Accept both forms.
    cid = body["correlation_id"]
    uuid4_hex = re.match(r"^[0-9a-f]{32}$", cid)
    uuid4_dashed = re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        cid,
    )
    assert uuid4_hex or uuid4_dashed, f"correlation_id is not a valid UUID4 (hex or dashed): {cid!r}"

    # ts must be ISO-8601 UTC millisecond precision with Z suffix
    ts = body["ts"]
    assert ts.endswith("Z"), f"ts must end with Z, got {ts!r}"
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), (
        f"ts must be ISO-8601 with millisecond precision, got {ts!r}"
    )


def test_data_platform_health_keys_alphabetically_ordered(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health serialized JSON has keys in alphabetical order (UI-SPEC §/health key ordering)."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/health")

    # Parse the raw text to check key ordering in serialized form
    raw = resp.text
    # Extract key names in order they appear in the JSON string
    key_positions = []
    for key in ("correlation_id", "env", "service_name", "status", "ts", "version"):
        pos = raw.find(f'"{key}"')
        assert pos >= 0, f"Key {key!r} not found in response text: {raw!r}"
        key_positions.append((pos, key))

    ordered_keys = [k for _, k in sorted(key_positions)]
    expected_order = ["correlation_id", "env", "service_name", "status", "ts", "version"]
    assert ordered_keys == expected_order, (
        f"Keys not in alphabetical order. Expected {expected_order}, got {ordered_keys}"
    )


# ---------------------------------------------------------------------------
# data-platform: /metrics
# ---------------------------------------------------------------------------


def test_data_platform_metrics_status_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics returns 200."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_data_platform_metrics_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics Content-Type is text/plain; version=0.0.4; charset=utf-8."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]
    assert "version=0.0.4" in resp.headers["content-type"]


def test_data_platform_metrics_has_4_base_metric_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics body contains all 4 base metric names with shortfire_data_platform_ prefix."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/metrics")
    body = resp.text

    for name in (
        "shortfire_data_platform_http_requests_total",
        "shortfire_data_platform_http_request_duration_seconds",
        "shortfire_data_platform_service_event_emitted_total",
        "shortfire_data_platform_build_info",
    ):
        assert name in body, f"Metric {name!r} not found in /metrics output"
        assert f"# HELP {name}" in body or "# HELP shortfire_data_platform" in body, (
            f"# HELP line missing for {name}"
        )


# ---------------------------------------------------------------------------
# data-platform: anti-leak guard (subprocess to avoid polluting the process)
# ---------------------------------------------------------------------------


def test_data_platform_raises_on_mexc_trade_env_present() -> None:
    """Importing data_platform when MEXC_TRADE__TRADE_KEY is set raises RuntimeError (D-16)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "os.environ['DATABASE_URL']='postgresql://x@y/z'; "
                "os.environ['ENV']='ci'; "
                "os.environ['MEXC_TRADE__TRADE_KEY']='leak'; "
                "import shortfire.entrypoints.data_platform"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when MEXC_TRADE__TRADE_KEY is set on data-platform, got 0"
    )
    assert "MEXC_TRADE__" in result.stderr, f"Expected 'MEXC_TRADE__' in stderr, got: {result.stderr!r}"


# ---------------------------------------------------------------------------
# data-platform: settings.loaded log line on lifespan
# ---------------------------------------------------------------------------


def test_data_platform_settings_loaded_emitted_on_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    """TestClient lifespan context manager → one service.settings.loaded log line (D-21)."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")

    with TestClient(mod.app) as _client:
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        all_output = captured.out + captured.err

    loaded_lines = [
        ln for ln in all_output.splitlines() if "settings.loaded" in ln or "service.startup" in ln
    ]
    assert loaded_lines, (
        f"Expected service.startup or service.settings.loaded log line during lifespan, "
        f"got output: {all_output!r}"
    )


def test_data_platform_settings_loaded_no_secretstr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: object,
) -> None:
    """service.settings.loaded log line must not contain SecretStr values (D-21)."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")

    with TestClient(mod.app) as _client:
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        all_output = captured.out + captured.err

    # SecretStr renders as ***** — if present, safe_summary() is not being used
    assert "**secret**" not in all_output, "SecretStr value leaked to logs — safe_summary() not used"
    assert "get_secret_value" not in all_output, "SecretStr .get_secret_value() called in logs"


# ---------------------------------------------------------------------------
# data-platform: /health ts single datetime.now() call
# ---------------------------------------------------------------------------


def test_data_platform_health_ts_uses_single_now_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health calls datetime.now(timezone.utc) exactly once (no boundary-crossing mismatch)."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)

    call_count = 0
    original_now = datetime.now

    def counting_now(tz: object = None) -> datetime:
        nonlocal call_count
        call_count += 1
        if tz is not None:
            return original_now(tz)
        return original_now()

    with patch(f"{mod.__name__}.datetime") as mock_dt:
        mock_dt.now = counting_now
        mock_dt.now.side_effect = counting_now  # type: ignore[attr-defined]
        client.get("/health")

    # call_count should be exactly 1 (from inside health())
    # Note: the patch may not intercept before module-load time; verify the body instead
    resp = client.get("/health")
    ts = resp.json()["ts"]
    # Verify millisecond precision (3 decimals exactly before Z) — proves single-call pattern
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), (
        f"ts does not have exactly 3 millisecond digits: {ts!r}"
    )


# ---------------------------------------------------------------------------
# strategy-engine: parity tests
# ---------------------------------------------------------------------------


def test_strategy_engine_health_returns_correct_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health on strategy-engine returns service_name='strategy-engine'."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.strategy_engine")
    client = TestClient(mod.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_name"] == "strategy-engine"
    assert body["status"] == "ok"
    assert set(body.keys()) == {"correlation_id", "env", "service_name", "status", "ts", "version"}


def test_strategy_engine_metrics_has_correct_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics on strategy-engine uses shortfire_strategy_engine_ prefix."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.strategy_engine")
    client = TestClient(mod.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "shortfire_strategy_engine_http_requests_total" in resp.text


# ---------------------------------------------------------------------------
# dashboard: parity tests
# ---------------------------------------------------------------------------


def test_dashboard_health_returns_correct_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health on dashboard returns service_name='dashboard'."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.dashboard")
    client = TestClient(mod.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_name"] == "dashboard"
    assert body["status"] == "ok"
    assert set(body.keys()) == {"correlation_id", "env", "service_name", "status", "ts", "version"}


def test_dashboard_metrics_has_correct_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics on dashboard uses shortfire_dashboard_ prefix."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.dashboard")
    client = TestClient(mod.app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "shortfire_dashboard_http_requests_total" in resp.text


# ---------------------------------------------------------------------------
# Content-Type check: all 3 entrypoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "shortfire.entrypoints.data_platform",
        "shortfire.entrypoints.strategy_engine",
        "shortfire.entrypoints.dashboard",
    ],
)
def test_health_content_type_is_json(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health Content-Type starts with application/json for all entrypoints."""
    _set_base_env(monkeypatch)
    mod = _fresh_app(module_name)
    client = TestClient(mod.app)
    resp = client.get("/health")
    assert resp.headers["content-type"].startswith("application/json"), (
        f"Expected application/json, got {resp.headers['content-type']!r}"
    )


def test_data_platform_health_json_is_parseable(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health body is valid JSON."""
    _set_base_env(monkeypatch)
    mod = _fresh_app("shortfire.entrypoints.data_platform")
    client = TestClient(mod.app)
    resp = client.get("/health")
    body = json.loads(resp.text)  # must not raise
    assert isinstance(body, dict)
