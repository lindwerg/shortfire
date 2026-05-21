"""Phase 0 event taxonomy registry — UI-SPEC §Event Taxonomy.

Adding a new event in Phase 1+ requires editing this file AND getting reviewed.
This is the single source of truth that prevents Sprache drift across services.

All structlog `event` values MUST come from this registry. Free-form event names
are forbidden per UI-SPEC §Log Event Schema.

Usage:
    from shortfire.observability.events import EVENTS, assert_event_registered

    assert_event_registered("service.startup")  # returns None — registered
    assert_event_registered("bogus.event")       # raises ValueError — not registered
"""

EVENTS: frozenset[str] = frozenset(
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
"""Frozenset of 12 registered event names for Phase 0.

Each entry corresponds to a row in UI-SPEC §Event Taxonomy table.
Phase 1+ extends this set by adding new entries — never by removing existing ones
(backward compatibility with Loki queries and Grafana alert expressions).
"""


def assert_event_registered(name: str) -> None:
    """Assert that `name` is a registered event taxonomy entry.

    Args:
        name: The structlog event name to validate.

    Raises:
        ValueError: If `name` is not in EVENTS. Includes the file path for
                    easy discovery of where to add new events.
    """
    if name not in EVENTS:
        raise ValueError(
            f"Event {name!r} not in registered taxonomy. "
            f"Add to EVENTS in src/shortfire/observability/events.py before using it."
        )
