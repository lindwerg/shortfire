"""Event taxonomy registry — UI-SPEC §Event Taxonomy.

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
        # --- Phase 0 (12 events) ---
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
        # --- Phase 1 — ingest pipeline (5 events) — D-85 ---
        "ingest.started",
        "ingest.completed",
        "ingest.failed",
        "ingest.rate_limited",
        "ingest.dead_letter",
        # --- Phase 1 — universe tracking (3 events) — D-85 ---
        "universe.snapshot.created",
        "universe.symbol.new",
        "universe.symbol.delisted",
        # --- Phase 1 — freshness monitor (2 events) — D-85 ---
        "freshness.degraded",
        "freshness.recovered",
        # --- Phase 1 — backup lifecycle (3 events) — D-85 ---
        "backup.started",
        "backup.completed",
        "backup.failed",
        # --- Phase 1 — websocket lifecycle (4 events) — D-85 ---
        "ws.connected",
        "ws.disconnected",
        "ws.reconnect",
        "ws.stale",
    }
)
"""Frozenset of 29 registered event names (12 Phase 0 + 17 Phase 1).

Each entry corresponds to a row in UI-SPEC §Event Taxonomy table.
Phase 1 adds 17 new event names per D-85 covering the ingest, universe,
freshness, backup, and WebSocket lifecycle event families.
Phase 2+ extends this set by adding new entries — never by removing existing ones
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
