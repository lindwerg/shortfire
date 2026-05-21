"""Tier-1 designation by 7-day rolling volume (D-46).

Reranks all non-delisted symbols by their last-7-days sum volume from
raw_mexc_candles_1d. Top 50 symbols → tier=1; remainder → tier=2.

Called from:
  - universe_snapshot_job (after daily snapshot write, per CONTEXT.md <specifics> §1)
  - register_all_jobs() via universe_snapshot_job_callable (plan 01-09 jobs.py)

D-46: tier-1 cohort = top-50 symbols by 7d rolling volume.
STOR-07: soft-delete aware — delisted symbols (delisted_at IS NOT NULL) are excluded
         from tier promotion but not touched if they're somehow present.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger("ingest.universe.tier1")


async def recompute_tier1(engine: AsyncEngine, top_n: int = 50) -> None:
    """Rerank symbols by last-7d volume; top-N → tier=1, rest → tier=2 (D-46).

    Uses raw_mexc_candles_1d SUM(volume) for last 7 days. If no candle data
    is available yet (e.g. first boot), sets all symbols to tier=2 gracefully.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        top_n: Number of top symbols to designate tier=1 (default 50 per D-46).
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                WITH vol AS (
                    SELECT symbol, SUM(volume) AS v7d
                    FROM raw_mexc_candles_1d
                    WHERE ts >= now() - INTERVAL '7 days'
                    GROUP BY symbol
                )
                SELECT symbol FROM vol ORDER BY v7d DESC LIMIT :n
            """),
            {"n": top_n},
        )
        top_set = {row[0] for row in rows}

    if not top_set:
        log.info("universe.tier1.recomputed", n_tier1=0, reason="no 1d candle data available")
        return

    async with engine.begin() as conn:
        # Set tier=1 for top symbols
        await conn.execute(
            text("UPDATE symbols SET tier = 1 WHERE symbol = ANY(:syms) AND delisted_at IS NULL"),
            {"syms": list(top_set)},
        )
        # Set tier=2 for the rest (not in top_set, not delisted)
        await conn.execute(
            text("""
                UPDATE symbols
                SET tier = 2
                WHERE symbol != ALL(:syms) AND delisted_at IS NULL
            """),
            {"syms": list(top_set)},
        )

    log.info("universe.tier1.recomputed", n_tier1=len(top_set))
