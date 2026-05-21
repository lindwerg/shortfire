"""Dead-letter threshold alerter — fires Telegram warn when DLQ spikes.

D-74: threshold is 10 rows per (source, error_type) per hour. Any group exceeding
the threshold triggers a warn-severity Telegram alert.

D-87 severity routing: dead_letter spike → "warn".

Usage:
    # Registered in APScheduler via scheduler/jobs.py — called every 5 min.
    from shortfire.ingest.dead_letter.alerter import dead_letter_alerter_job
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

from shortfire.observability.events import assert_event_registered
from shortfire.observability.telegram import send_telegram_alert

if TYPE_CHECKING:
    from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.dead_letter.alerter")

DEAD_LETTER_THRESHOLD_PER_HOUR = 10  # D-74: alert when any group exceeds this per hour


async def dead_letter_alerter_job(settings: DataPlatformSettings | None = None) -> None:
    """APScheduler IntervalTrigger(minutes=5) callable.

    Queries dead_letter table for last 1h grouped by (source, error_type).
    Fires warn Telegram alert when any group count > DEAD_LETTER_THRESHOLD_PER_HOUR.

    D-74: threshold = 10 rows/source/error_type/hour.
    D-87: severity = "warn" (not crit — dead_letter rows are schema drift, not data loss).

    Args:
        settings: DataPlatformSettings. If None, loaded from get_settings() singleton.
    """
    from shortfire.ingest.context import get_engine, get_settings

    engine = get_engine()
    if settings is None:
        settings = get_settings()

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT source, error_type, count(*) AS n
                FROM dead_letter
                WHERE ts >= now() - INTERVAL '1 hour'
                GROUP BY source, error_type
                HAVING count(*) > :threshold
                ORDER BY n DESC
                """
            ),
            {"threshold": DEAD_LETTER_THRESHOLD_PER_HOUR},
        )
        offenders = [(r[0], r[1], r[2]) for r in rows]

    if not offenders:
        return

    body_lines = ["dead_letter spike (last 1h):"]
    for src, et, n in offenders:
        body_lines.append(f"  {src} / {et}: {n}")

    await send_telegram_alert(settings, "warn", "\n".join(body_lines))
    assert_event_registered("ingest.dead_letter")
    log.warning("dead_letter.alert.fired", offenders=offenders)
