"""Tests for shortfire.db.base — DeclarativeBase NAMING_CONVENTION (D-29)."""

import sqlalchemy as sa
from shortfire.db.base import NAMING_CONVENTION, Base
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_naming_convention_keys() -> None:
    """NAMING_CONVENTION must have exactly the 5 keys specified in D-29."""
    assert set(NAMING_CONVENTION.keys()) == {"ix", "uq", "ck", "fk", "pk"}


def test_base_metadata_naming_convention() -> None:
    """Base.metadata.naming_convention must equal the NAMING_CONVENTION dict."""
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_pk_constraint_name() -> None:
    """A table's primary key constraint must be named pk_<table>."""
    # Use a unique table name to avoid conflicts with persistent Base.metadata
    table = sa.Table(
        "_test_nc_pk",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        keep_existing=True,
    )
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]
    assert "pk__test_nc_pk" in ddl


def test_uq_constraint_name() -> None:
    """A UNIQUE constraint must be named uq_<table>_<col>."""
    table = sa.Table(
        "_test_nc_uq",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, unique=True),
        keep_existing=True,
    )
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]
    assert "uq__test_nc_uq_name" in ddl
