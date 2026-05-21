"""Repo hygiene test — verifies that .gitignore covers all D-23 required patterns.

Each pattern is parametrized into its own test case for granular failure reporting.
"""

import pytest

REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    ".env.local",
    ".env.*.local",
    "*.env.bak",
    ".venv/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".coverage",
    "htmlcov/",
    "coverage.xml",
    "dist/",
    "build/",
    "*.egg-info/",
    ".DS_Store",
    ".vscode/",
    ".idea/",
    ".claude/",
]


@pytest.mark.parametrize("pattern", REQUIRED_GITIGNORE_PATTERNS)
def test_gitignore_contains_pattern(pattern: str) -> None:
    """Assert that .gitignore contains the D-23 required pattern."""
    import pathlib

    gitignore_path = pathlib.Path(".gitignore")
    assert gitignore_path.exists(), ".gitignore does not exist — create it per D-23"
    content = gitignore_path.read_text(encoding="utf-8")
    assert pattern in content, (
        f".gitignore missing required pattern {pattern!r} (D-23). "
        "This pattern prevents sensitive files or generated artifacts from being tracked."
    )
