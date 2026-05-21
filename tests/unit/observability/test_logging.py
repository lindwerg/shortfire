"""Tests for structlog logging configuration.

Tests:
  1. configure_logging + contextvars → NDJSON with mandatory base fields
  2. merge_contextvars is FIRST processor (Pitfall 2)
  3. JSONRenderer is LAST processor
  4. correlation_id from asgi-correlation-id appears in log line (Pitfall 2 mitigation)
"""

import json
import re

import structlog
from asgi_correlation_id import correlation_id
from shortfire.observability.logging import configure_logging


def test_json_log_line_has_mandatory_base_fields(capsys: object) -> None:
    """configure_logging + bound contextvars → log line contains all mandatory base fields."""
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service_name="test",
        env="ci",
        correlation_id="test-abc",
    )
    log = structlog.get_logger("test")
    log.info("service.startup", version="0.1.0", pid=1)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
    assert lines, f"Expected at least one log line, got empty output. stderr: {captured.err}"
    event = json.loads(lines[-1])

    # Mandatory base fields per UI-SPEC §Log Event Schema
    for field in ("ts", "level", "event", "service_name", "env", "correlation_id"):
        assert field in event, f"Mandatory field '{field}' missing from log line: {event}"

    assert event["level"] == "info"
    assert event["event"] == "service.startup"
    assert event["service_name"] == "test"
    assert event["correlation_id"] == "test-abc"

    # ts must end with Z and have millisecond precision (ISO-8601 UTC)
    ts = event["ts"]
    assert ts.endswith("Z"), f"ts must end with Z, got: {ts!r}"
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", ts), (
        f"ts must match ISO-8601 with sub-second precision, got: {ts!r}"
    )

    structlog.contextvars.clear_contextvars()


def test_processor_order_merge_contextvars_first() -> None:
    """merge_contextvars MUST be the first processor in the configured chain (Pitfall 2)."""
    configure_logging("INFO")
    cfg = structlog.get_config()
    processors = cfg["processors"]
    assert processors, "No processors configured"
    first = processors[0]
    assert first is structlog.contextvars.merge_contextvars, (
        f"First processor must be structlog.contextvars.merge_contextvars, "
        f"got {first!r} — Pitfall 2 violation: correlation_id will be lost across async boundaries"
    )


def test_json_renderer_is_last_processor() -> None:
    """JSONRenderer must be the last processor (guarantees NDJSON output)."""
    configure_logging("INFO")
    cfg = structlog.get_config()
    processors = cfg["processors"]
    last = processors[-1]
    assert isinstance(last, structlog.processors.JSONRenderer), (
        f"Last processor must be structlog.processors.JSONRenderer, got {type(last)!r}"
    )


def test_correlation_id_appears_in_log(capsys: object) -> None:
    """Setting asgi-correlation-id contextvar → log line carries request_id (Pitfall 2 mitigation)."""
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()

    # Manually set the asgi-correlation-id contextvar as the middleware would
    token = correlation_id.set("test-id-abc")
    try:
        log = structlog.get_logger("test-corr")
        log.info("service.health_check", status="ok")

        captured = capsys.readouterr()  # type: ignore[attr-defined]
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        assert lines, f"Expected at least one log line; got empty output. stderr: {captured.err}"
        event = json.loads(lines[-1])

        # The add_correlation_id processor should inject request_id
        assert "request_id" in event, (
            f"'request_id' not in log line — Pitfall 2 mitigation broken. Keys: {list(event.keys())}"
        )
        assert event["request_id"] == "test-id-abc", (
            f"request_id value mismatch: expected 'test-id-abc', got {event['request_id']!r}"
        )
    finally:
        correlation_id.reset(token)
        structlog.contextvars.clear_contextvars()
