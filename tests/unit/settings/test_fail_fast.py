"""Test FOUND-07: pydantic-settings validates required env vars at startup.

Fails fast with field-level error messages when required fields (e.g., DATABASE_URL) are absent.
"""

import pytest
from pydantic_settings import BaseSettings
from shortfire.settings.dashboard import DashboardSettings

# Import settings classes — will fail to import until Task 1 GREEN phase creates them
from shortfire.settings.data_platform import DataPlatformSettings
from shortfire.settings.risk_guard import RiskGuardSettings
from shortfire.settings.strategy_engine import StrategyEngineSettings

ALL_SETTINGS_CLASSES: list[type[BaseSettings]] = [
    DataPlatformSettings,
    StrategyEngineSettings,
    DashboardSettings,
    RiskGuardSettings,
]


@pytest.mark.parametrize("settings_cls", ALL_SETTINGS_CLASSES, ids=lambda c: c.__name__)
def test_missing_database_url_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch, settings_cls: type[BaseSettings]
) -> None:
    """FOUND-07: missing DATABASE_URL must cause ValidationError at construction time."""
    from pydantic import ValidationError

    # Use ENV=ci so _env_file() returns None (skip .env.local loading)
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        settings_cls()  # type: ignore[call-arg]

    # Confirm the error is field-level, not a generic catch-all
    errors = exc_info.value.errors()
    assert len(errors) >= 1, "Expected at least one field-level validation error"


@pytest.mark.parametrize("settings_cls", ALL_SETTINGS_CLASSES, ids=lambda c: c.__name__)
def test_missing_database_url_error_references_db_url_field(
    monkeypatch: pytest.MonkeyPatch, settings_cls: type[BaseSettings]
) -> None:
    """FOUND-07: the ValidationError must contain a field-level entry pointing to db.url."""
    from pydantic import ValidationError

    monkeypatch.setenv("ENV", "ci")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        settings_cls()  # type: ignore[call-arg]

    errors = exc_info.value.errors()
    # Confirm at least one error references the db / DATABASE_URL path
    error_locs = [e.get("loc", ()) for e in errors]
    error_msgs = [str(e.get("msg", "")) for e in errors]
    combined = str(error_locs) + str(error_msgs)
    assert "db" in combined or "DATABASE_URL" in combined or "url" in combined, (
        f"Expected error to reference db/DATABASE_URL/url; got: {errors}"
    )
