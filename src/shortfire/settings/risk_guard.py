"""RiskGuardSettings — settings for the risk-guard Railway service (Phase 5).

risk-guard is a separate Railway service added in Phase 5 as a process-level
kill switch and position limit enforcer. It has NO external API keys — it only
talks to the shared Postgres database.

Decisions honored:
  D-16: Separate subclass; inherits base safe_summary() unchanged (no new creds)
  D-21: Inherits safe_summary() from BaseAppSettings — no extra fields needed
"""

from shortfire.settings.base import BaseAppSettings


class RiskGuardSettings(BaseAppSettings):
    """Settings for the risk-guard Railway service.

    Phase 5 only. No external API keys — only database access.
    Inherits base safe_summary() unchanged.
    """

    service_name: str = "risk-guard"

    # No external API keys. safe_summary() inherited from BaseAppSettings is sufficient.
