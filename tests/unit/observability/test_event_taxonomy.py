"""Tests for event taxonomy registry.

Tests:
  4. EVENTS is a frozenset with exactly 12 strings from UI-SPEC §Event Taxonomy
  5. assert_event_registered("service.startup") returns None (no error)
  6. assert_event_registered("bogus.event") raises ValueError
"""

import pytest

from shortfire.observability.events import EVENTS, assert_event_registered

EXPECTED_EVENTS = frozenset(
    {
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
    }
)


def test_events_is_frozenset() -> None:
    """EVENTS must be a frozenset (immutable event taxonomy)."""
    assert isinstance(EVENTS, frozenset), f"EVENTS must be a frozenset, got {type(EVENTS)!r}"


def test_events_has_at_least_12_strings() -> None:
    """EVENTS must contain at least 12 event name strings (Phase 0 baseline from UI-SPEC §Event Taxonomy).

    Phase 1+ extensions add more events on top of the Phase 0 baseline; this test
    remains valid as long as the 12 Phase 0 names are present and every entry is a str.
    """
    assert len(EVENTS) >= 12, f"EVENTS must have at least 12 strings, got {len(EVENTS)}: {sorted(EVENTS)}"
    for event in EVENTS:
        assert isinstance(event, str), f"All EVENTS must be strings, got {type(event)!r}: {event!r}"


def test_events_contains_all_phase0_names() -> None:
    """EVENTS must contain all 12 Phase 0 events from UI-SPEC §Event Taxonomy (backward compat)."""
    missing = EXPECTED_EVENTS - EVENTS
    assert not missing, f"Phase 0 EVENTS missing from registry (backward-compat broken): {missing}"


def test_assert_event_registered_returns_none_for_known_event() -> None:
    """assert_event_registered('service.startup') returns None (no exception)."""
    result = assert_event_registered("service.startup")
    assert result is None, f"assert_event_registered should return None, got {result!r}"


def test_assert_event_registered_returns_none_for_all_known_events() -> None:
    """All 12 registered events pass assert_event_registered without raising."""
    for event in EXPECTED_EVENTS:
        result = assert_event_registered(event)
        assert result is None, f"assert_event_registered('{event}') should return None"


def test_assert_event_registered_raises_for_unknown_event() -> None:
    """assert_event_registered raises ValueError for unregistered event names."""
    with pytest.raises(ValueError, match="bogus.event"):
        assert_event_registered("bogus.event")


def test_assert_event_registered_raises_for_empty_string() -> None:
    """assert_event_registered raises ValueError for empty string."""
    with pytest.raises(ValueError):
        assert_event_registered("")


def test_boundary_events_present() -> None:
    """Verify the two boundary events that tests check: service.startup and secret.guard.tripped."""
    assert "service.startup" in EVENTS
    assert "secret.guard.tripped" in EVENTS
