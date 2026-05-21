"""Unit tests for Phase 1 EVENTS frozenset extensions (D-85).

Tests:
  1. All 17 new Phase 1 event names pass assert_event_registered (no raise).
  2. All 12 Phase 0 event names are still present after extension.
  3. len(EVENTS) == 29 (12 Phase 0 + 17 Phase 1).
"""

import pytest

from shortfire.observability.events import EVENTS, assert_event_registered

PHASE_1_EVENTS: list[str] = [
    "ingest.started",
    "ingest.completed",
    "ingest.failed",
    "ingest.rate_limited",
    "ingest.dead_letter",
    "universe.snapshot.created",
    "universe.symbol.new",
    "universe.symbol.delisted",
    "freshness.degraded",
    "freshness.recovered",
    "backup.started",
    "backup.completed",
    "backup.failed",
    "ws.connected",
    "ws.disconnected",
    "ws.reconnect",
    "ws.stale",
]

PHASE_0_EVENTS: list[str] = [
    "service.startup",
    "service.settings.loaded",
    "service.settings.failed",
    "service.shutdown",
    "service.health_check",
    "db.engine.created",
    "db.migration.applied",
    "request.received",
    "request.completed",
    "request.failed",
    "service_event.emitted",
    "secret.guard.tripped",
]


@pytest.mark.parametrize("event_name", PHASE_1_EVENTS)
def test_phase1_event_registered(event_name: str) -> None:
    """Each of the 17 Phase 1 event names (D-85) must pass assert_event_registered without raising."""
    result = assert_event_registered(event_name)
    assert result is None, f"assert_event_registered({event_name!r}) should return None, got {result!r}"


def test_phase0_events_still_present() -> None:
    """All 12 Phase 0 event names must remain in EVENTS after Phase 1 extension."""
    for event in PHASE_0_EVENTS:
        assert event in EVENTS, f"Phase 0 event {event!r} was removed — backward compatibility broken"


def test_events_total_count_equals_29() -> None:
    """EVENTS frozenset must contain exactly 29 entries: 12 Phase 0 + 17 Phase 1 (D-85)."""
    assert len(EVENTS) == 29, f"Expected 29 events, got {len(EVENTS)}: {sorted(EVENTS)}"
