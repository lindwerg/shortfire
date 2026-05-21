"""DashboardSettings — settings for the dashboard Railway service.

Minimal in Phase 0. Phase 5+ adds Telegram bot credentials.

Decisions honored:
  D-16: Separate subclass; only sees env vars relevant to dashboard
  D-19: Telegram credentials will be SecretStr when wired in Phase 5
  D-21: safe_summary() returns bool flags — never SecretStr values
"""

from pydantic import BaseModel, SecretStr

from shortfire.settings.base import BaseAppSettings


class TelegramSettings(BaseModel):
    """Telegram bot credentials for signal alerts.

    Phase 5+ only. Wired via TELEGRAM__BOT_TOKEN env var (D-18).
    """

    bot_token: SecretStr


class DashboardSettings(BaseAppSettings):
    """Settings for the dashboard Railway service.

    Phase 0: minimal — only base fields (service_name, port, db, common).
    Phase 5+: adds telegram for signal alert delivery.
    """

    service_name: str = "dashboard"

    # Phase 5+: Telegram bot for signal alerts (TELEGRAM__BOT_TOKEN)
    telegram: TelegramSettings | None = None

    def safe_summary(self) -> dict[str, object]:
        """Extend base summary with boolean flag for Telegram configuration (D-21)."""
        base = super().safe_summary()
        base.update(
            {
                "telegram_configured": self.telegram is not None,
            }
        )
        return base
