"""Smoke import test — proves test framework + every top-level subpackage are importable.

TEST-01: pytest + pytest-asyncio + hypothesis + freezegun + respx + aioresponses installed.
TEST-06: freezegun used in a tz-aware freeze — proves tz-correct usage pattern is visible.
"""

from datetime import UTC, datetime


def test_import_shortfire() -> None:
    import shortfire

    assert shortfire.__version__ == "0.1.0"


def test_import_domain() -> None:
    import shortfire.domain

    assert shortfire.domain is not None


def test_import_settings() -> None:
    import shortfire.settings

    assert shortfire.settings is not None


def test_import_observability() -> None:
    import shortfire.observability

    assert shortfire.observability is not None


def test_import_db() -> None:
    import shortfire.db

    assert shortfire.db is not None


def test_import_clients() -> None:
    import shortfire.clients

    assert shortfire.clients is not None


def test_import_entrypoints() -> None:
    import shortfire.entrypoints

    assert shortfire.entrypoints is not None


def test_import_pytest_asyncio() -> None:
    import pytest_asyncio

    assert pytest_asyncio is not None


def test_import_hypothesis() -> None:
    import hypothesis.strategies as st
    from hypothesis import given

    assert st is not None
    assert given is not None


def test_import_freezegun() -> None:
    from freezegun import freeze_time

    assert freeze_time is not None


def test_import_respx() -> None:
    import respx

    assert respx is not None


def test_import_aioresponses() -> None:
    from aioresponses import aioresponses

    assert aioresponses is not None


def test_freezegun_tz_aware_freeze() -> None:
    """TEST-06: proves freezegun installed and tz-correct usage pattern.

    Always use freeze_time("...Z") with an explicit UTC suffix, not a naive string.
    """
    from freezegun import freeze_time

    with freeze_time("2026-05-21T00:00:00Z"):
        now = datetime.now(UTC)
        assert now.isoformat().startswith("2026-05-21"), (
            f"Expected frozen date 2026-05-21, got {now.isoformat()!r}. "
            "Pitfall 7: always freeze with 'Z' suffix to avoid naive datetime surprises."
        )
