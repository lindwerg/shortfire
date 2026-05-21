"""Static-shape tests for Alembic env.py and migration files.

These tests verify the structure of the migration files without running
a real database. Integration tests in Plan 00-06 verify runtime behavior.
"""

import ast
from pathlib import Path

ALEMBIC_DIR = Path(__file__).parent.parent.parent.parent / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"
ENV_PY = ALEMBIC_DIR / "env.py"
MIGRATION_0001 = VERSIONS_DIR / "0001_init_timescaledb.py"
MIGRATION_0002 = VERSIONS_DIR / "0002_service_event_hypertable.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestMigration0001:
    def test_0001_contains_create_extension(self) -> None:
        """0001 must contain CREATE EXTENSION IF NOT EXISTS timescaledb (D-28)."""
        content = _read(MIGRATION_0001)
        assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in content

    def test_0001_down_revision_is_none(self) -> None:
        """0001 must have down_revision = None (it is the root migration)."""
        content = _read(MIGRATION_0001)
        assert "down_revision = None" in content

    def test_0001_revision_value(self) -> None:
        """0001 must have revision = '0001'."""
        content = _read(MIGRATION_0001)
        assert 'revision = "0001"' in content or "revision = '0001'" in content

    def test_0001_is_valid_python(self) -> None:
        """0001 migration file must be parseable as valid Python."""
        content = _read(MIGRATION_0001)
        ast.parse(content)  # raises SyntaxError on failure


class TestMigration0002:
    def test_0002_contains_timezone_aware_timestamp(self) -> None:
        """0002 must use sa.TIMESTAMP(timezone=True) — ban-naive-timestamp (D-32)."""
        content = _read(MIGRATION_0002)
        assert "sa.TIMESTAMP(timezone=True)" in content

    def test_0002_contains_jsonb(self) -> None:
        """0002 must define payload column as JSONB."""
        content = _read(MIGRATION_0002)
        assert "JSONB" in content

    def test_0002_calls_create_hypertable(self) -> None:
        """0002 must call create_hypertable (D-27 — no raw SQL)."""
        content = _read(MIGRATION_0002)
        assert "create_hypertable" in content

    def test_0002_calls_enable_compression(self) -> None:
        """0002 must call enable_compression (D-27 — no raw SQL)."""
        content = _read(MIGRATION_0002)
        assert "enable_compression" in content

    def test_0002_calls_add_compression_policy(self) -> None:
        """0002 must call add_compression_policy (D-27 — no raw SQL)."""
        content = _read(MIGRATION_0002)
        assert "add_compression_policy" in content

    def test_0002_imports_helpers_from_shortfire(self) -> None:
        """0002 must import DDL helpers from shortfire.db.timescale (D-27)."""
        content = _read(MIGRATION_0002)
        assert "from shortfire.db.timescale import" in content

    def test_0002_down_revision_points_to_0001(self) -> None:
        """0002's down_revision must be '0001' (Pitfall 3 — ordering)."""
        content = _read(MIGRATION_0002)
        assert 'down_revision = "0001"' in content or "down_revision = '0001'" in content

    def test_0002_no_on_delete_cascade(self) -> None:
        """0002 must NOT contain ON DELETE CASCADE (ban-on-delete-cascade D-32)."""
        content = _read(MIGRATION_0002).upper()
        assert "ON DELETE CASCADE" not in content

    def test_0002_no_naive_timestamp(self) -> None:
        """0002 must NOT match TIMESTAMP[^(] (ban-naive-timestamp D-32)."""
        import re

        content = _read(MIGRATION_0002)
        matches = re.findall(r"TIMESTAMP[^(]", content)
        assert matches == [], f"Found naive TIMESTAMP usages: {matches}"

    def test_0002_is_valid_python(self) -> None:
        """0002 migration file must be parseable as valid Python."""
        content = _read(MIGRATION_0002)
        ast.parse(content)  # raises SyntaxError on failure


class TestEnvPy:
    def test_env_imports_base(self) -> None:
        """env.py must import Base from shortfire.db.base (Pitfall 3 NAMING_CONVENTION)."""
        content = _read(ENV_PY)
        assert "from shortfire.db.base import Base" in content

    def test_env_sets_target_metadata(self) -> None:
        """env.py must set target_metadata = Base.metadata (Pitfall 3)."""
        content = _read(ENV_PY)
        assert "target_metadata = Base.metadata" in content

    def test_env_uses_async_engine_from_config(self) -> None:
        """env.py must use async_engine_from_config — NOT sync engine_from_config (Pitfall 3)."""
        content = _read(ENV_PY)
        assert "async_engine_from_config" in content

    def test_env_does_not_use_sync_engine_from_config(self) -> None:
        """env.py must NOT import the sync engine_from_config (Pitfall 3)."""
        content = _read(ENV_PY)
        # Check that engine_from_config is not used without the 'async_' prefix
        import re

        # Match 'engine_from_config' not preceded by 'async_'
        matches = re.findall(r"(?<!async_)engine_from_config", content)
        assert matches == [], f"Found sync engine_from_config usage: {matches}"

    def test_env_transaction_per_migration(self) -> None:
        """env.py must set transaction_per_migration=True (D-26)."""
        content = _read(ENV_PY)
        assert "transaction_per_migration=True" in content

    def test_env_compare_type(self) -> None:
        """env.py must set compare_type=True (D-26)."""
        content = _read(ENV_PY)
        assert "compare_type=True" in content

    def test_env_compare_server_default(self) -> None:
        """env.py must set compare_server_default=True (D-26)."""
        content = _read(ENV_PY)
        assert "compare_server_default=True" in content

    def test_env_rewrites_postgres_url(self) -> None:
        """env.py must contain URL-rewrite logic for both postgres:// and postgresql://."""
        content = _read(ENV_PY)
        # The env.py must handle at least one of the legacy URL forms
        assert "postgres://" in content or "postgresql://" in content
        assert "postgresql+asyncpg://" in content

    def test_env_is_valid_python(self) -> None:
        """env.py must be parseable as valid Python."""
        content = _read(ENV_PY)
        ast.parse(content)  # raises SyntaxError on failure
