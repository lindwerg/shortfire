"""Integration test fixtures for testcontainers-based DB tests.

Session-scoped pattern (Pitfall 5 from RESEARCH.md):
- Container starts ONCE per session (~5-10s cold start) and is reused across all tests.
- alembic upgrade head runs ONCE per session after the container is ready.
- Per-test cleanup uses TRUNCATE (cheap, ~1ms) for isolation.

URL rewrite strategy (option a from PLAN.md §Task 1 IMPLEMENTATION DETAIL):
  PostgresContainer.get_connection_url() returns `postgresql+psycopg2://...`.
  Alembic env.py handles `postgresql://` → `postgresql+asyncpg://` but NOT the
  `+psycopg2` form. We strip `+psycopg2` before setting DATABASE_URL so env.py
  receives a clean `postgresql://` URL it knows how to rewrite.

  asyncpg.connect() does NOT accept the `+asyncpg` SQLAlchemy URL suffix either —
  strip it back to plain `postgresql://` for direct asyncpg calls.

Docker availability (Assumption A4 from RESEARCH.md):
  If Docker is unavailable, tests are skipped at collection time via a session-scoped
  fixture. The pre-check is done eagerly in `_docker_available()`.
"""

import asyncio
import os
import subprocess
from collections.abc import Generator

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Docker availability guard
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


_DOCKER_OK = _docker_available()


# ---------------------------------------------------------------------------
# URL conversion helpers
# ---------------------------------------------------------------------------


def _strip_driver_suffix(url: str) -> str:
    """Convert postgresql+psycopg2:// → postgresql:// for alembic env.py.

    PostgresContainer.get_connection_url() returns the psycopg2-dialect form.
    Alembic env.py from Plan 00-04 expects plain `postgresql://` and rewrites to
    `postgresql+asyncpg://` internally.
    """
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _to_asyncpg_url(url: str) -> str:
    """Convert any SQLAlchemy URL form to plain postgresql:// for asyncpg.connect().

    asyncpg.connect() does NOT accept SQLAlchemy-style driver suffixes
    (`+asyncpg`, `+psycopg2`). Strip any `+driver` component.
    """
    if "postgresql+" in url:
        # postgresql+asyncpg://user:pass@host/db  →  postgresql://user:pass@host/db
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# Session-scoped container fixture (Pitfall 5 mitigation)
# ---------------------------------------------------------------------------

_TIMESCALE_IMAGE = "timescale/timescaledb:2.18.0-pg16"


@pytest.fixture(scope="session")
def timescale_container() -> Generator[PostgresContainer, None, None]:
    """Start a TimescaleDB container once for the entire test session.

    Skips if Docker is not available (Assumption A4). Uses the same image tag
    as docker-compose.yml and Railway marketplace template (D-25, T-00-09).
    """
    if not _DOCKER_OK:
        pytest.skip("Docker not available — integration tests require Docker (Assumption A4)")

    with PostgresContainer(_TIMESCALE_IMAGE) as container:
        yield container


# ---------------------------------------------------------------------------
# Session-scoped migrated-DB fixture — runs alembic upgrade head ONCE
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_db(timescale_container: PostgresContainer) -> str:
    """Run `alembic upgrade head` once per session and return the connection URL.

    The URL is the plain `postgresql://...` form suitable for:
    - Passing to `DATABASE_URL` env var (alembic env.py rewrites to postgresql+asyncpg://)
    - Passing directly to asyncpg.connect() via _to_asyncpg_url()

    Returns:
        str: Plain `postgresql://` connection URL for the test container.
    """
    # Strip +psycopg2 suffix so alembic env.py can rewrite to postgresql+asyncpg://
    raw_url = timescale_container.get_connection_url()
    plain_url = _strip_driver_suffix(raw_url)

    # Inject DATABASE_URL and run alembic upgrade head from the project root
    env = {**os.environ, "DATABASE_URL": plain_url}

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        # Run from the repo root so alembic.ini is found
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (returncode={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    return plain_url


# ---------------------------------------------------------------------------
# Function-scoped cleanup fixture — TRUNCATE service_event between tests
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_service_event(migrated_db: str) -> Generator[None, None, None]:
    """Truncate service_event before and after each test for isolation.

    Uses asyncpg directly (no SQLAlchemy overhead; D-30 — asyncpg is the
    sole driver in v1).

    Yields after initial truncate so the test body runs with a clean table.
    Truncates again on teardown to prevent state from leaking to later tests.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)

    async def _truncate() -> None:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            await conn.execute("TRUNCATE service_event")  # type: ignore[attr-defined]
        finally:
            await conn.close()  # type: ignore[attr-defined]

    # Setup
    asyncio.run(_truncate())
    yield
    # Teardown
    asyncio.run(_truncate())
