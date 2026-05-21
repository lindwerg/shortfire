"""Alembic async env.py — D-26 / Pattern 6 / Pitfall 3.

Key wiring:
- Reads DATABASE_URL from environment; rewrites to postgresql+asyncpg:// (Pitfall 3).
- Imports Base from shortfire.db.base to propagate NAMING_CONVENTION (Pitfall 3).
- Uses async_engine_from_config (NOT engine_from_config — sync variant crashes on asyncpg URL).
- Sets transaction_per_migration=True, compare_type=True, compare_server_default=True (D-26).
- Offline mode raises RuntimeError — TimescaleDB DDL helpers require a live connection.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from shortfire.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Propagates NAMING_CONVENTION to Alembic autogenerate (Pitfall 3)
target_metadata = Base.metadata


def _resolved_url() -> str:
    """Read DATABASE_URL and rewrite to postgresql+asyncpg:// if needed.

    Railway sometimes provides the legacy `postgres://` form; SQLAlchemy 2.x
    with asyncpg requires `postgresql+asyncpg://` (Pitfall 3).
    """
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


def do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
        # Naming convention is inherited from target_metadata (Base.metadata)
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolved_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migrations are not supported — TimescaleDB DDL helpers require a live database connection."
    )
else:
    run_migrations_online()
