"""STOR-10 integration keystone: pg_dump → S3-compatible mock (moto).

Plan 01-10, Task 2: integration tests for daily_pg_dump_to_r2 and sundown sweep.
Uses moto's mock_aws to simulate Cloudflare R2 S3-compatible storage without
real credentials.

Note on moto's mock_aws + custom endpoint_url:
moto's mock_aws decorator intercepts boto3 calls at the botocore layer, regardless
of the endpoint_url passed to boto3.client(). The mock works transparently even when
endpoint_url points to an R2-style URL — the mock captures the underlying HTTP transport.

Note on async + moto:
moto's @mock_aws decorator does not work directly on pytest-asyncio async test functions
(it wraps coroutines as sync functions). Use mock_aws() as a context manager instead.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st
from moto import mock_aws
from pydantic import SecretStr


def _make_r2_settings():  # type: ignore[no-untyped-def]
    """Build DataPlatformSettings with R2BackupSettings configured."""
    from shortfire.settings.data_platform import DataPlatformSettings, R2BackupSettings

    return DataPlatformSettings.model_construct(
        r2_backup=R2BackupSettings(
            account_id="test_account",
            access_key_id=SecretStr("test_key"),
            secret_access_key=SecretStr("test_secret"),
            bucket_name="shortfire-backups-test",
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_pg_dump_to_r2_writes_object_to_bucket(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STOR-10 keystone: daily_pg_dump_to_r2 uploads dump to S3-compatible mock bucket.

    Requires pg_dump binary on PATH. Skips if not available.
    Uses mock_aws() as context manager (not decorator) for async compatibility.

    moto's mock_aws() intercepts boto3 at the botocore transport layer. However,
    botocore validates endpoint_url format before moto can intercept it, so we must
    patch _build_r2_client to return a standard boto3 client (no custom endpoint_url)
    within the moto mock context.
    """
    if shutil.which("pg_dump") is None:
        pytest.skip("pg_dump not installed — required for STOR-10 integration test")

    monkeypatch.setenv("DATABASE_URL", migrated_db)

    settings = _make_r2_settings()

    import unittest.mock

    from shortfire.ingest.backup.pg_dump_r2 import daily_pg_dump_to_r2

    with mock_aws():
        # Create mock bucket inside the mock context
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="shortfire-backups-test")

        # Patch _build_r2_client to return the standard moto-intercepted client
        # (moto validates endpoint_url format; the real R2 URL fails validation in test)
        def _mock_build_r2_client(settings_arg):  # type: ignore[no-untyped-def]
            return boto3.client("s3", region_name="us-east-1")

        with unittest.mock.patch(
            "shortfire.ingest.backup.pg_dump_r2._build_r2_client",
            side_effect=_mock_build_r2_client,
        ):
            result = await daily_pg_dump_to_r2(settings=settings)

        assert result == 1, f"Expected return value 1 (success), got {result}"

        resp = s3.list_objects_v2(Bucket="shortfire-backups-test")
        keys = [o["Key"] for o in resp.get("Contents", [])]
        assert any(k.startswith("daily/") and k.endswith(".dump.zst") for k in keys), (
            f"Expected at least one dump object with key daily/<ts>.dump.zst, got {keys}"
        )


@pytest.mark.integration
def test_daily_pg_dump_skips_when_r2_not_configured() -> None:
    """When r2_backup is None, daily_pg_dump_to_r2 returns 0 (graceful degradation)."""
    from shortfire.ingest.backup.pg_dump_r2 import daily_pg_dump_to_r2
    from shortfire.settings.data_platform import DataPlatformSettings

    settings = DataPlatformSettings.model_construct(r2_backup=None)
    result = asyncio.run(daily_pg_dump_to_r2(settings=settings))
    assert result == 0


@pytest.mark.integration
def test_sundown_sweep_enforces_d81_retention_basic() -> None:
    """Basic D-81 retention test: after 10 daily uploads, daily/ keeps at most 7."""
    from shortfire.ingest.backup.pg_dump_r2 import _sundown_sweep

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-bucket-retention-basic"
        s3.create_bucket(Bucket=bucket)

        # Upload 10 daily dumps (Monday-anchored to ensure weekly promotion triggers)
        start_date = datetime(2026, 1, 5, 1, 0, 0, tzinfo=UTC)  # Monday
        for i in range(10):
            dt = start_date + timedelta(days=i)
            key = f"daily/{dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"
            s3.put_object(Bucket=bucket, Key=key, Body=b"x")
            _sundown_sweep(s3, bucket)

        daily = s3.list_objects_v2(Bucket=bucket, Prefix="daily/").get("Contents", [])
        weekly = s3.list_objects_v2(Bucket=bucket, Prefix="weekly/").get("Contents", [])
        monthly = s3.list_objects_v2(Bucket=bucket, Prefix="monthly/").get("Contents", [])

        assert len(daily) <= 7, f"daily/ kept {len(daily)} > 7 after sweep (D-81)"
        assert len(weekly) <= 4, f"weekly/ kept {len(weekly)} > 4 after sweep (D-81)"
        assert len(monthly) <= 6, f"monthly/ kept {len(monthly)} > 6 after sweep (D-81)"


@pytest.mark.integration
def test_sundown_sweep_promotes_on_monday() -> None:
    """Weekly promotion fires on Monday (UTC weekday == 0)."""
    from shortfire.ingest.backup.pg_dump_r2 import _sundown_sweep

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-bucket-weekly-promotion"
        s3.create_bucket(Bucket=bucket)

        # 2026-01-05 is a Monday UTC
        monday_dt = datetime(2026, 1, 5, 1, 0, 0, tzinfo=UTC)
        key = f"daily/{monday_dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"
        s3.put_object(Bucket=bucket, Key=key, Body=b"x")

        _sundown_sweep(s3, bucket)

        weekly = s3.list_objects_v2(Bucket=bucket, Prefix="weekly/").get("Contents", [])
        assert len(weekly) >= 1, "Expected at least one weekly/ dump after Monday promotion"


@pytest.mark.integration
def test_sundown_sweep_promotes_on_first_of_month() -> None:
    """Monthly promotion fires on day 1 of any month (UTC)."""
    from shortfire.ingest.backup.pg_dump_r2 import _sundown_sweep

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-bucket-monthly-promotion"
        s3.create_bucket(Bucket=bucket)

        # 2026-02-01 is day 1 of Feb → monthly promotion
        first_dt = datetime(2026, 2, 1, 1, 0, 0, tzinfo=UTC)
        key = f"daily/{first_dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"
        s3.put_object(Bucket=bucket, Key=key, Body=b"x")

        _sundown_sweep(s3, bucket)

        monthly = s3.list_objects_v2(Bucket=bucket, Prefix="monthly/").get("Contents", [])
        assert len(monthly) >= 1, "Expected at least one monthly/ dump after 1st-of-month promotion"


@pytest.mark.integration
def test_sundown_sweep_promotes_annual_on_jan_1() -> None:
    """Annual promotion fires on Jan 1 UTC."""
    from shortfire.ingest.backup.pg_dump_r2 import _sundown_sweep

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-bucket-annual-promotion"
        s3.create_bucket(Bucket=bucket)

        # 2026-01-01 → annual + monthly promotion (Jan 1 is day 1 AND month 1)
        jan1_dt = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
        key = f"daily/{jan1_dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"
        s3.put_object(Bucket=bucket, Key=key, Body=b"x")

        _sundown_sweep(s3, bucket)

        annual = s3.list_objects_v2(Bucket=bucket, Prefix="annual/").get("Contents", [])
        assert len(annual) >= 1, "Expected at least one annual/ dump after Jan 1 promotion"


@pytest.mark.integration
@given(n_days=st.integers(min_value=8, max_value=400))
@h_settings(max_examples=8, deadline=15_000)
def test_sundown_sweep_enforces_d81_retention(n_days: int) -> None:
    """B3 Hypothesis property: retention invariants hold across N=8..400 daily uploads."""
    from shortfire.ingest.backup.pg_dump_r2 import _sundown_sweep

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = f"test-bucket-hyp-{n_days}"
        s3.create_bucket(Bucket=bucket)

        start_date = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
        for i in range(n_days):
            dt = start_date + timedelta(days=i)
            key = f"daily/{dt.strftime('%Y%m%dT%H%M%SZ')}.dump.zst"
            s3.put_object(Bucket=bucket, Key=key, Body=b"x")
            _sundown_sweep(s3, bucket)

        daily = s3.list_objects_v2(Bucket=bucket, Prefix="daily/").get("Contents", [])
        weekly = s3.list_objects_v2(Bucket=bucket, Prefix="weekly/").get("Contents", [])
        monthly = s3.list_objects_v2(Bucket=bucket, Prefix="monthly/").get("Contents", [])
        annual = s3.list_objects_v2(Bucket=bucket, Prefix="annual/").get("Contents", [])

        assert len(daily) <= 7, f"daily/ kept {len(daily)} > 7 after {n_days} uploads"
        assert len(weekly) <= 4, f"weekly/ kept {len(weekly)} > 4 after {n_days} uploads"
        assert len(monthly) <= 6, f"monthly/ kept {len(monthly)} > 6 after {n_days} uploads"
        if n_days < 365:
            assert len(annual) <= 1, f"annual/ kept {len(annual)} > 1 before full year"
        if n_days >= 60:
            assert len(daily) + len(weekly) + len(monthly) >= 8
