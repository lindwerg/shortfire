"""Tests for pre-commit grep guard logic (D-32, D-09, D-22).

These tests verify the grep LOGIC used by pre-commit hooks — not the hook-wrapper itself.
Using subprocess + temp directories to avoid mutating the real working tree.

Guards tested:
  ban-float-in-domain     : forbid ': float' annotations under src/shortfire/domain/
  ban-naive-timestamp     : forbid 'TIMESTAMP[^(]' under alembic/versions/ and src/
  ban-on-delete-cascade   : forbid 'ON DELETE CASCADE' under alembic/versions/
  gitleaks-config-valid   : assert .gitleaks.toml is valid TOML with correct allowlist
"""

import subprocess
import tomllib
from pathlib import Path


def test_ban_float_in_domain_grep(tmp_path: Path) -> None:
    """Grep for ': float' annotations in domain files — should FIND the violation."""
    # Arrange: create a scratch violator file
    domain_dir = tmp_path / "src" / "shortfire" / "domain"
    domain_dir.mkdir(parents=True)
    violator = domain_dir / "scratch_violator.py"
    violator.write_text("value: float = 0.0\n")

    # Act: run grep on the violator
    result = subprocess.run(
        ["grep", "-nrE", r": float\b", str(domain_dir)],
        capture_output=True,
        text=True,
    )

    # Assert: grep exits 0 (match found), meaning the guard WOULD trip
    assert result.returncode == 0, (
        f"Expected grep to find ': float' in domain scratch file but got no match. stdout={result.stdout!r}"
    )
    assert ": float" in result.stdout

    # Cleanup and verify no matches in an empty dir
    violator.unlink()
    result_clean = subprocess.run(
        ["grep", "-nrE", r": float\b", str(domain_dir)],
        capture_output=True,
        text=True,
    )
    assert result_clean.returncode == 1, (
        "After removing violator, grep should find no matches (exit 1). "
        f"Got returncode={result_clean.returncode}, stdout={result_clean.stdout!r}"
    )


def test_ban_naive_timestamp_grep(tmp_path: Path) -> None:
    """Grep for 'TIMESTAMP[^(]' in alembic migration files — should FIND the violation."""
    # Arrange: create a scratch alembic migration
    versions_dir = tmp_path / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    scratch = versions_dir / "scratch.py"
    scratch.write_text("op.execute('CREATE TABLE x (ts TIMESTAMP DEFAULT NOW())')\n")

    # Act: grep for TIMESTAMP without following parenthesis
    result = subprocess.run(
        ["grep", "-nrE", r"TIMESTAMP[^(]", str(versions_dir)],
        capture_output=True,
        text=True,
    )

    # Assert: grep finds the violation
    assert result.returncode == 0, (
        "Expected grep to find 'TIMESTAMP[^(]' in scratch migration but got no match. "
        f"stdout={result.stdout!r}"
    )
    assert "TIMESTAMP" in result.stdout

    # Cleanup
    scratch.unlink()
    result_clean = subprocess.run(
        ["grep", "-nrE", r"TIMESTAMP[^(]", str(versions_dir)],
        capture_output=True,
        text=True,
    )
    assert result_clean.returncode == 1


def test_ban_on_delete_cascade_grep(tmp_path: Path) -> None:
    """Grep for 'ON DELETE CASCADE' in alembic migration files — should FIND the violation."""
    # Arrange: create a scratch alembic migration with the forbidden pattern
    versions_dir = tmp_path / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    scratch = versions_dir / "scratch.py"
    scratch.write_text(
        "op.execute('ALTER TABLE orders ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE')\n"
    )

    # Act: grep for ON DELETE CASCADE (case-insensitive)
    result = subprocess.run(
        ["grep", "-nirE", "ON DELETE CASCADE", str(versions_dir)],
        capture_output=True,
        text=True,
    )

    # Assert: grep finds the violation
    assert result.returncode == 0, (
        "Expected grep to find 'ON DELETE CASCADE' in scratch migration but got no match. "
        f"stdout={result.stdout!r}"
    )
    assert "ON DELETE CASCADE" in result.stdout.upper()

    # Cleanup
    scratch.unlink()
    result_clean = subprocess.run(
        ["grep", "-nirE", "ON DELETE CASCADE", str(versions_dir)],
        capture_output=True,
        text=True,
    )
    assert result_clean.returncode == 1


def test_gitleaks_config_valid() -> None:
    """Assert .gitleaks.toml is valid TOML with the required allowlist configuration."""
    gitleaks_path = Path(".gitleaks.toml")
    assert gitleaks_path.exists(), ".gitleaks.toml does not exist — create it per Pattern 8"

    with open(gitleaks_path, "rb") as f:
        config = tomllib.load(f)

    # Must extend the default ruleset (D-22 / Pattern 8)
    assert config.get("extend", {}).get("useDefault") is True, (
        ".gitleaks.toml must have [extend] useDefault = true to inherit gitleaks' default ruleset"
    )

    # Must have at least one allowlist table (Pitfall 6 — prevent false positives on uv.lock)
    allowlists = config.get("allowlists", [])
    assert len(allowlists) > 0, (
        ".gitleaks.toml must have [[allowlists]] to allowlist uv.lock + test fixtures "
        "(Pitfall 6: false positives on lock-file hashes)"
    )

    # The first allowlist must include uv.lock
    paths = allowlists[0].get("paths", [])
    assert any("uv" in p for p in paths), (
        "[[allowlists]] in .gitleaks.toml must include a path matching uv.lock "
        f"to prevent false-positive CI failures. Got paths={paths!r}"
    )
