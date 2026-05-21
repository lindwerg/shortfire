"""Async SQLAlchemy engine factory with URL rewriting — Pitfall 3 mitigation.

D-30: asyncpg 0.30+ is the only Postgres driver in v1 (no sync driver in use).
D-26: Engine is async-native via create_async_engine.

SECURITY (T-00-01): The raw DATABASE_URL is never logged. Callers use
Settings.db.url (which already masks credentials via safe_summary()).
"""

import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _rewrite_url(url: str) -> str:
    """Rewrite legacy URL forms to postgresql+asyncpg://.

    Railway and some Postgres providers emit `postgres://` or `postgresql://`.
    SQLAlchemy 2.x with asyncpg requires `postgresql+asyncpg://`.

    Args:
        url: The database URL to rewrite.

    Returns:
        URL with `postgresql+asyncpg://` scheme.

    Raises:
        ValueError: If url is empty.
    """
    if not url:
        raise ValueError("DATABASE_URL must not be empty")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


# Public alias — pyright strict mode treats _-prefixed names as private.
# Tests and the __init__.py re-export should use this alias.
rewrite_url = _rewrite_url


def create_engine_from_env() -> AsyncEngine:
    """Create an AsyncEngine from the DATABASE_URL environment variable.

    Reads DATABASE_URL from the environment, rewrites it to the asyncpg
    dialect, and returns a connection-pooled AsyncEngine.

    Returns:
        Configured SQLAlchemy AsyncEngine.

    Raises:
        KeyError: If DATABASE_URL is not set.
        ValueError: If DATABASE_URL is empty.
    """
    raw_url = os.environ["DATABASE_URL"]
    url = _rewrite_url(raw_url)
    return create_async_engine(
        url,
        pool_size=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )
