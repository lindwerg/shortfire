"""Tests for shortfire.db.engine._rewrite_url — URL prefix rewriting to postgresql+asyncpg://."""

import pytest
from shortfire.db.engine import _rewrite_url


@pytest.mark.parametrize(
    "input_url, expected",
    [
        (
            "postgres://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        (
            "postgresql://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        (
            "postgresql+asyncpg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
    ],
    ids=["postgres://", "postgresql://", "already-asyncpg"],
)
def test_rewrite_url_forms(input_url: str, expected: str) -> None:
    assert _rewrite_url(input_url) == expected


def test_rewrite_url_empty_raises() -> None:
    """Empty string is not a valid URL — must raise ValueError."""
    with pytest.raises(ValueError, match="empty"):
        _rewrite_url("")
