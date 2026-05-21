"""Daily pg_dump → Cloudflare R2 backup (D-80, D-81, STOR-10).

pg_dump --format=custom --compress=zstd:9 → S3-compatible Cloudflare R2 via boto3.

Security (T-1-BCK-01 / RESEARCH.md Open Q8):
  DSN password is passed via PGPASSWORD environment variable, NOT as part of argv.
  This prevents exposure in /proc/<pid>/cmdline.

Retention (D-81 / B3 reconciliation — implemented in-phase, NOT deferred):
  _sundown_sweep() implements the full D-81 retention policy:
    - 7 most recent daily/ dumps
    - 4 most recent weekly/ dumps (promoted every UTC Monday)
    - 6 most recent monthly/ dumps (promoted on 1st of month)
    - unlimited annual/ dumps (promoted Jan 1; never swept)
  ~17 dumps at steady state.

Usage:
    from shortfire.ingest.backup.pg_dump_r2 import daily_pg_dump_to_r2

    # In APScheduler daily 01:00 UTC job
    result = await daily_pg_dump_to_r2()
    # result == 0 → skipped (r2_backup not configured)
    # result == 1 → success
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import boto3
import structlog
from botocore.config import Config

from shortfire.observability.events import assert_event_registered
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

if TYPE_CHECKING:
    from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.backup.pg_dump_r2")


def _build_r2_client(settings: DataPlatformSettings) -> boto3.client:  # type: ignore[valid-type]
    """Build a boto3 S3 client configured for Cloudflare R2 (S3-compatible API)."""
    r2 = settings.r2_backup
    assert r2 is not None  # caller guards
    return boto3.client(
        "s3",
        endpoint_url=f"https://{r2.account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=r2.access_key_id.get_secret_value(),
        aws_secret_access_key=r2.secret_access_key.get_secret_value(),
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )


def _parse_dsn(database_url: str) -> tuple[str, str, str, int, str]:
    """Parse a SQLAlchemy / asyncpg DSN into (user, password, host, port, dbname).

    Normalizes postgresql+asyncpg:// → postgresql:// before parsing.
    """
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://")
    u = urlparse(normalized)
    return (
        u.username or "",
        u.password or "",
        u.hostname or "localhost",
        u.port or 5432,
        (u.path or "/postgres").lstrip("/"),
    )


async def daily_pg_dump_to_r2(settings: DataPlatformSettings | None = None) -> int:
    """Daily 01:00 UTC backup: pg_dump → R2.

    pg_dump is invoked with --format=custom --compress=zstd:9 --no-owner --no-acl.
    DSN password is passed via PGPASSWORD env (T-1-BCK-01: avoids /proc/<pid>/cmdline
    exposure per RESEARCH.md Open Q8).

    Args:
        settings: DataPlatformSettings. If None, loaded from get_settings() singleton.

    Returns:
        0 — skipped (r2_backup not configured; logs backup.skipped)
        1 — success (backup.completed event logged)

    Raises:
        RuntimeError: If pg_dump exits with a non-zero return code.
        Any boto3 / subprocess exception propagates so APScheduler records the failure.
    """
    if settings is None:
        from shortfire.ingest.context import get_settings

        settings = get_settings()

    if settings.r2_backup is None:
        log.warning("backup.skipped", reason="r2_backup not configured")
        return 0

    assert_event_registered("backup.started")
    log.info("backup.started")

    database_url = os.environ["DATABASE_URL"]
    user, password, host, port, dbname = _parse_dsn(database_url)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = f"daily/{ts}.dump.zst"

    s3 = _build_r2_client(settings)

    # PGPASSWORD env — password never in argv (T-1-BCK-01)
    env = {**os.environ, "PGPASSWORD": password}
    cmd = [
        "pg_dump",
        "--format=custom",
        "--compress=zstd:9",
        "--no-owner",
        "--no-acl",
        "--host",
        host,
        "--port",
        str(port),
        "--username",
        user,
        "--dbname",
        dbname,
    ]

    proc = subprocess.Popen(  # noqa: ASYNC220 — pg_dump must stream stdout to S3; asyncio.create_subprocess_exec lacks upload_fileobj streaming; this runs in a daily APScheduler cron at 01:00 UTC (not a hot path)
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        s3.upload_fileobj(proc.stdout, settings.r2_backup.bucket_name, key)
        ret = proc.wait(timeout=3600)
        if ret != 0:
            err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"pg_dump exit code {ret}: {err[:2000]}")
    finally:
        if proc.poll() is None:
            proc.kill()

    # Update backup_age_seconds gauge (0 = just completed)
    metrics = build_data_platform_metrics()
    metrics.backup_age_seconds.set(0)

    # Run D-81 retention sundown sweep (best-effort; failures logged but not re-raised)
    try:
        _sundown_sweep(s3, settings.r2_backup.bucket_name)
    except Exception as exc:
        log.warning("backup.sundown.failed", exc_info=exc)

    assert_event_registered("backup.completed")
    log.info("backup.completed", key=key, bucket=settings.r2_backup.bucket_name)
    return 1


def _parse_key_dt(key: str) -> datetime | None:
    """Parse the UTC datetime from a dump key like 'daily/20260105T010000Z.dump.zst'.

    Returns None if the key does not match the expected naming pattern.
    """
    # Extract the timestamp portion from the key name
    # Key format: <prefix>/<YYYYMMDDTHHMMSSZ>.dump.zst
    basename = key.rsplit("/", 1)[-1]  # e.g. '20260105T010000Z.dump.zst'
    ts_part = basename.split(".")[0]  # e.g. '20260105T010000Z'
    try:
        return datetime.strptime(ts_part, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _sundown_sweep(s3: object, bucket: str) -> None:  # type: ignore[type-arg]
    """D-81 retention sweep: keep 7 daily + 4 weekly + 6 monthly + unlimited annual.

    B3 reconciliation: this implements the FULL D-81 retention policy in-phase (not deferred).

    Promotion strategy (server-side S3 copy — no download/re-upload bandwidth):
    - Every UTC Monday: promote newest daily/ → weekly/
    - Every 1st of month: promote newest daily/ → monthly/
    - Every Jan 1: promote newest daily/ → annual/
    - Then sweep each prefix: keep N most-recent, delete the rest
    - annual/ is NEVER swept (indefinite historical record per D-81)

    Day-of-week/month/year determination is based on the timestamp embedded in the KEY NAME
    (format: 'daily/YYYYMMDDTHHMMSSZ.dump.zst'), not on LastModified. This is robust against
    upload clock skew and is the canonical approach (D-81).

    Args:
        s3: Configured boto3 S3 client (R2-compatible or moto mock).
        bucket: S3 bucket name.
    """

    def _list_sorted_desc(prefix: str) -> list[dict]:  # type: ignore[type-arg]
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)  # type: ignore[attr-defined]
        return sorted(
            resp.get("Contents", []),
            key=lambda o: o[
                "Key"
            ],  # sort by key name (contains ISO timestamp — lexicographic == chronological)
            reverse=True,
        )

    # Step 1: identify the newest daily dump by key-name timestamp
    daily_objs = _list_sorted_desc("daily/")
    if not daily_objs:
        log.warning("sundown.no_daily_dumps")
        return

    newest_daily = daily_objs[0]
    newest_key: str = newest_daily["Key"]

    # Parse the calendar date from the key name (not from LastModified)
    dt = _parse_key_dt(newest_key)
    if dt is None:
        log.warning("sundown.key_parse_failed", key=newest_key)
        return

    promoted_keys: list[str] = []

    def _copy_to(prefix: str) -> str:
        """Server-side S3 copy of newest daily dump to the given prefix."""
        target_key = f"{prefix}{dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"  # type: ignore[union-attr]
        # Idempotent: skip if target already exists
        existing = s3.list_objects_v2(Bucket=bucket, Prefix=target_key)  # type: ignore[attr-defined]
        if not existing.get("Contents"):
            s3.copy_object(  # type: ignore[attr-defined]
                Bucket=bucket,
                Key=target_key,
                CopySource={"Bucket": bucket, "Key": newest_key},
            )
            log.info("sundown.promoted", from_key=newest_key, to_key=target_key)
        promoted_keys.append(target_key)
        return target_key

    # Step 2: promote to upper tiers based on UTC calendar of the key's timestamp
    # Weekly: Monday (weekday == 0)
    if dt.weekday() == 0:
        _copy_to("weekly/")
    # Monthly: 1st day of month
    if dt.day == 1:
        _copy_to("monthly/")
    # Annual: Jan 1
    if dt.month == 1 and dt.day == 1:
        _copy_to("annual/")

    # Step 3: sweep each prefix, keeping the most-recent N objects (D-81)
    retention_counts: dict[str, int] = {
        "daily/": 7,
        "weekly/": 4,
        "monthly/": 6,
        # "annual/" is intentionally absent — never swept
    }
    for prefix, keep_n in retention_counts.items():
        objs = _list_sorted_desc(prefix)
        for o in objs[keep_n:]:
            s3.delete_object(Bucket=bucket, Key=o["Key"])  # type: ignore[attr-defined]
            log.info("sundown.deleted", key=o["Key"], prefix=prefix, kept=keep_n)

    # annual/ is never swept — indefinite historical record (D-81)
    log.info("sundown.completed", promoted=promoted_keys, retention=retention_counts)
