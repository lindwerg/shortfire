"""Dead-letter queue writer — persists failed ingest rows (D-74).

Every Pydantic ValidationError AND every exhausted-retry exception landing from
any ingest path is captured here. The dead_letter hypertable is internal-only
(no external read path in Phase 1 — T-1-INF-02 accepted).

Column order (matches record tuple in write_to_dead_letter, D-74):
  0  id               UUID PRIMARY KEY
  1  ts               tz-aware UTC datetime
  2  source           TEXT NOT NULL  -- e.g. 'mexc_native', 'coinglass_aggregate'
  3  endpoint         TEXT NOT NULL  -- e.g. 'fetch_ohlcv', '/api/futures/funding-rate-list'
  4  symbol           TEXT           -- nullable; not every error is per-symbol
  5  raw_payload      JSONB NOT NULL -- raw API response
  6  error_type       TEXT NOT NULL  -- exception class name
  7  error_msg        TEXT NOT NULL  -- truncated to 2000 chars
  8  retries_attempted INTEGER NOT NULL DEFAULT 0
  9  quality_flag     TEXT NOT NULL DEFAULT 'schema_warn'

Phase 5 TODO: add payload redaction (T-1-INF-02 deferred mitigation).
"""

import uuid
from datetime import UTC, datetime

from shortfire.ingest.context import get_engine
from shortfire.ingest.storage.copy import copy_into_hypertable


async def write_to_dead_letter(
    source: str,
    endpoint: str,
    symbol: str | None,
    raw_payload: str | bytes,
    error_type: str,
    error_msg: str,
    retries_attempted: int = 0,
) -> None:
    """Write one row to the dead_letter hypertable (D-74).

    Uses copy_into_hypertable for idempotency (conflict on id UUID — D-62).
    Metrics increment is deferred to plan 01-02 companion (same Wave 1):
    dead_letter_total counter is registered there; at unit-test time the metric
    import is patched.

    Args:
        source: Data source identifier (e.g. 'mexc_native', 'coinglass_aggregate').
        endpoint: API endpoint or method name where the error occurred.
        symbol: Trading symbol if the error is per-symbol; None otherwise.
        raw_payload: Raw API response payload (str or bytes).
        error_type: Exception class name (e.g. 'ValidationError').
        error_msg: Human-readable error message — truncated to 2000 chars.
        retries_attempted: Number of retry attempts before giving up.
    """
    # Decode bytes payload to str (errors='replace' to avoid codec failures)
    if isinstance(raw_payload, bytes):
        payload_str = raw_payload.decode("utf-8", errors="replace")
    else:
        payload_str = raw_payload

    record: tuple[uuid.UUID, datetime, str, str, str | None, str, str, str, int, str] = (
        uuid.uuid4(),
        datetime.now(UTC),
        source,
        endpoint,
        symbol,
        payload_str,
        error_type,
        error_msg[:2000],  # truncate to 2000 chars (D-74)
        retries_attempted,
        "schema_warn",
    )

    engine = get_engine()

    await copy_into_hypertable(
        engine=engine,
        target_table="dead_letter",
        records=[record],
        columns=(
            "id",
            "ts",
            "source",
            "endpoint",
            "symbol",
            "raw_payload",
            "error_type",
            "error_msg",
            "retries_attempted",
            "quality_flag",
        ),
        conflict_columns=("id",),
    )
