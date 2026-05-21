"""Round-robin cursor persistence via ingest_runs.kv_state JSONB column (RESEARCH.md §4.6).

Every Coinglass and MEXC round-robin scheduler job uses this helper to read/write its
`last_symbol_index` cursor across scheduler restarts. Storing in ingest_runs (a hypertable)
instead of a separate `kv_store` table keeps the schema surface minimal — D-77 cron jobs
already write into ingest_runs on each completion, so this just adds a read path.

Schema reminder (from migration): ingest_runs has columns
    (id, ts, source, dataset, job_id, started_at, finished_at, status,
     rows_written, error_msg, kv_state JSONB, quality_flag, ingested_at)
Each job_id may have many rows; `load_kv_state` returns the latest `kv_state` value
for that job_id (ordered by ts DESC LIMIT 1). `save_kv_state` INSERTs a new row.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger("ingest.state.kv_state")


async def load_kv_state(engine: AsyncEngine, job_id: str) -> dict[str, Any]:
    """Return the latest persisted kv_state for `job_id`, or {} if none recorded.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        job_id: Scheduler job identifier (e.g. 'coinglass.oi', 'mexc.oi.poll').

    Returns:
        Latest kv_state dict for the given job_id, or {} if no rows found.
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
                    SELECT kv_state FROM ingest_runs
                    WHERE job_id = :j AND kv_state IS NOT NULL
                    ORDER BY ts DESC LIMIT 1
                """),
                {"j": job_id},
            )
        ).first()

    if row is None or row[0] is None:
        return {}
    # asyncpg returns JSONB as Python dict directly; SQLAlchemy passes it through.
    # Guard against string fallback just in case.
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


async def save_kv_state(engine: AsyncEngine, job_id: str, state: dict[str, Any]) -> None:
    """Insert a new ingest_runs row recording this job's updated kv_state cursor.

    Derives `source` and `dataset` from the job_id prefix/suffix convention:
      'coinglass.*'  → source='coinglass_aggregate'
      'coingecko.*'  → source='coingecko'
      'mexc.*'       → source='mexc_native'
      other          → source='mexc_native' (default)

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        job_id: Scheduler job identifier.
        state: Dict to persist as kv_state JSONB.
    """
    now = datetime.now(UTC)

    # Derive source from job_id prefix
    if job_id.startswith("coinglass"):
        source = "coinglass_aggregate"
    elif job_id.startswith("coingecko"):
        source = "coingecko"
    elif job_id.startswith("mexc"):
        source = "mexc_native"
    else:
        source = "mexc_native"

    # Derive dataset from job_id suffix
    dataset = job_id.split(".", 1)[1] if "." in job_id else job_id

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO ingest_runs
                    (id, ts, source, dataset, job_id, started_at, finished_at,
                     status, rows_written, kv_state, quality_flag)
                VALUES
                    (:id, :ts, :src, :ds, :jid, :ts, :ts, 'succeeded', 0, :st::jsonb, 'ok')
            """),
            {
                "id": uuid.uuid4(),
                "ts": now,
                "src": source,
                "ds": dataset,
                "jid": job_id,
                "st": json.dumps(state),
            },
        )

    log.debug("kv_state.saved", job_id=job_id, state_keys=list(state.keys()))
