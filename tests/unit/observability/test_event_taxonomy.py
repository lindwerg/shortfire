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


def test_events_has_exactly_12_strings() -> None:
    """EVENTS must contain exactly 12 event name strings (UI-SPEC §Event Taxonomy)."""
    assert len(EVENTS) == 12, f"EVENTS must have 12 strings, got {len(EVENTS)}: {sorted(EVENTS)}"
    for event in EVENTS:
        assert isinstance(event, str), f"All EVENTS must be strings, got {type(event)!r}: {event!r}"


def test_events_matches_ui_spec_taxonomy_exactly() -> None:
    """EVENTS must match the exact set of 12 events from UI-SPEC §Event Taxonomy."""
    assert EVENTS == EXPECTED_EVENTS, (
        f"EVENTS mismatch.\nMissing: {EXPECTED_EVENTS - EVENTS}\nExtra: {EVENTS - EXPECTED_EVENTS}"
    )


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
