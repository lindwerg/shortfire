"""Shared ingest helpers — logger and timestamp utilities (D-65, Pitfall 17).

All ingest modules import from here to share consistent:
  - Structured logger (structlog, named "ingest")
  - Timestamp conversion from exchange millisecond timestamps to tz-aware UTC datetime

Timestamp discipline (D-65, RESEARCH.md Pitfall 17):
  Exchange APIs return timestamps as milliseconds since Unix epoch.
  ALL internal timestamps MUST be tz-aware UTC datetime.
  NEVER use datetime.utcfromtimestamp() — it returns a naive datetime.
  Always use datetime.fromtimestamp(ms / 1000, tz=timezone.utc).
"""

from datetime import UTC, datetime

import structlog

log = structlog.get_logger("ingest")


def ts_from_ms(ms: int) -> datetime:
    """Convert a millisecond Unix timestamp to a tz-aware UTC datetime (D-65, Pitfall 17).

    Args:
        ms: Millisecond Unix timestamp from exchange API response.

    Returns:
        Timezone-aware UTC datetime.

    Example:
        >>> ts_from_ms(1716307200000)
        datetime.datetime(2024, 5, 21, 16, 0, tzinfo=datetime.timezone.utc)
    """
    return datetime.fromtimestamp(ms / 1000, tz=UTC)
