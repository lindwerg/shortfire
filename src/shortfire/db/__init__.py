"""DB layer — SQLAlchemy AsyncEngine, DeclarativeBase, TimescaleDB DDL helpers.

Public re-exports for the db subpackage.
"""

from shortfire.db.base import NAMING_CONVENTION, Base
from shortfire.db.engine import create_engine_from_env, rewrite_url
from shortfire.db.timescale import (
    add_compression_policy,
    add_retention_policy,
    create_hypertable,
    enable_compression,
)

__all__ = [
    "Base",
    "NAMING_CONVENTION",
    "create_engine_from_env",
    "rewrite_url",
    "add_compression_policy",
    "add_retention_policy",
    "create_hypertable",
    "enable_compression",
]
