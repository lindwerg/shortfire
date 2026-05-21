"""BaseAppSettings — shared base for all per-service Settings subclasses.

Architecture:
- BaseAppSettings(BaseSettings): shared common fields
- SettingsConfigDict with env_nested_delimiter='__' (D-17)
- _env_file() helper returns None in production (D-20)
- safe_summary() returns sanitized dict for startup logs (D-21)
- NEVER call repr(settings) — only settings.safe_summary()

Env var routing (D-18):
  DATABASE_URL  -> database_url field, then db.url via model_validator
  LOG_LEVEL     -> common.log_level (via COMMON__LOG_LEVEL)
  ENV           -> common.env (via COMMON__ENV)
  PORT          -> port (top-level)
  MEXC__*       -> DataPlatformSettings.mexc.*
  COINGLASS__*  -> DataPlatformSettings.coinglass.*
  COINGECKO__*  -> DataPlatformSettings.coingecko.*
  MEXC_TRADE__* -> StrategyEngineSettings.mexc_trade.* (Phase 5 only)

Decisions honored:
  D-16: Per-service subclasses, not one big class
  D-17: SettingsConfigDict with env_nested_delimiter='__', no env_prefix
  D-18: DATABASE_URL top-level env var (not DB__URL)
  D-19: SecretStr for all credentials
  D-20: env_file=None in production, '.env.local' otherwise
  D-21: safe_summary() canonical pattern
"""

import os
from typing import Literal

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    """Return the env file path based on the current environment.

    Returns None in production so Railway env vars are used exclusively.
    Returns '.env.local' for all other environments (D-20).

    Public alias available as `env_file` for use in tests and entrypoints.
    """
    return ".env.local" if os.getenv("ENV", "local") != "production" else None


# Public alias — tests and entrypoints may import this by name
env_file = _env_file


class DBSettings(BaseModel):
    """Database connection settings.

    pool_recycle=1800 guards against Railway private network idle connection drops.
    Note: populated from DATABASE_URL top-level env var via BaseAppSettings model_validator.
    """

    url: str
    pool_size: int = 5
    pool_pre_ping: bool = True
    pool_recycle: int = 1800  # 30 min — Railway private network drops idle conns


class CommonSettings(BaseModel):
    """Common process-level settings shared across all services."""

    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
    env: Literal["local", "ci", "staging", "production"] = "local"


def _extract_db_url(data: dict[str, object]) -> str | None:
    """Extract DATABASE_URL from a settings data dict (case-insensitive key lookup)."""
    for key in data:
        if key.lower() == "database_url":
            val = data[key]
            if isinstance(val, str):
                return val
    return None


class BaseAppSettings(BaseSettings):
    """Shared base for all per-service Settings subclasses.

    Every subclass:
    1. Inherits env_nested_delimiter='__' routing (D-17)
    2. Only declares fields for env vars it is allowed to see (D-16 anti-leak)
    3. Overrides safe_summary() to extend with service-specific bool flags (D-21)

    Env var for DB: DATABASE_URL (top-level, not DB__URL).
    The model_validator maps DATABASE_URL -> db.url before validation.

    Anti-pattern to avoid: repr(settings) — always use safe_summary() instead (D-21).
    """

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",  # Railway injects many extra env vars; don't crash on them
    )

    service_name: str
    port: int = 8000
    database_url: str  # Receives DATABASE_URL env var directly; used to populate db.url
    db: DBSettings = DBSettings(url="placeholder")  # populated by _build_db before validation
    common: CommonSettings = CommonSettings()

    @model_validator(mode="before")
    @classmethod
    def _build_db(cls, data: object) -> object:
        """Populate db from database_url / DATABASE_URL before Pydantic validates fields."""
        if not isinstance(data, dict):
            return data

        raw: dict[str, object] = data  # type: ignore[assignment]
        typed_data: dict[str, object] = {str(k): v for k, v in raw.items()}

        db_url = _extract_db_url(typed_data)
        if db_url is not None:
            # Build DBSettings from the DATABASE_URL string
            db_entry = typed_data.get("db")
            if not isinstance(db_entry, dict):
                typed_data["db"] = {"url": db_url}

        return typed_data

    def safe_summary(self) -> dict[str, object]:
        """Return a sanitized dict for startup logging (D-21).

        NEVER returns SecretStr values, full DB URLs, or passwords.
        Canonical usage: log.info("settings.loaded", **settings.safe_summary())
        """
        db_host: str
        if "@" in self.db.url:
            # Strip credentials: 'postgresql://user:pass@host:5432/db' -> 'host:5432/db'
            after_at = self.db.url.split("@", 1)[-1]
            # Remove path: 'host:5432/db' -> 'host:5432'
            db_host = after_at.split("/")[0]
        else:
            db_host = "<unknown>"

        return {
            "service_name": self.service_name,
            "port": self.port,
            "env": self.common.env,
            "log_level": self.common.log_level,
            "db_host": db_host,
        }
