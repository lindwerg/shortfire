"""Raw-httpx Telegram alert sender for the data-platform service (D-86).

Sends severity-prefixed text messages to the configured Telegram chat via the
Bot API. Uses a raw httpx.AsyncClient — NO python-telegram-bot framework dependency
(D-86: framework adoption deferred to Phase 4).

Failure policy (D-86):
- If settings.telegram is None: log and return (graceful skip).
- If the HTTP call raises (network error, timeout, 4xx/5xx): log the exception
  and return. NEVER re-raise — Telegram failure must not crash the caller.

Trust boundary (T-1-INF-03):
  The URL contains the bot token. We must never log the full URL.
  structlog log.error(..., exc_info=e) logs only the exception type + message,
  not the request URL, so the token is safe even when the request fails.

Client lifecycle (D-50 / WR-08):
  D-50 mandates ONE httpx.AsyncClient per process. The original implementation
  opened a new client per send_telegram_alert() call (every 1–5 min), creating
  unnecessary TCP+TLS setup overhead. A module-level lazy singleton _telegram_client
  is now used instead. The singleton is created on first alert and reused for the
  lifetime of the process. _close_telegram_client() is provided for test teardown.

Usage:
    from shortfire.observability.telegram import send_telegram_alert

    await send_telegram_alert(settings, "warn", "stale: mexc/candles_1m/BTC")
    await send_telegram_alert(settings, "crit", "DB connection lost")
"""

from __future__ import annotations

from typing import Literal

import httpx
import structlog

from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("observability.telegram")

# Severity prefix table — all entries are Unicode-safe and render in Telegram.
_SEVERITY_PREFIX: dict[str, str] = {
    "warn": "⚠️ WARN",
    "crit": "🚨 CRIT",
    "info": "ℹ️ INFO",
}

# Telegram Bot API enforces a 4096-char limit per message; we use 4000 as a
# conservative ceiling to leave room for future prefix changes.
_MAX_MESSAGE_LEN: int = 4000

# WR-08 / D-50: module-level singleton — ONE httpx.AsyncClient per process.
# Created lazily on first call so tests that never send alerts do not open connections.
_telegram_client: httpx.AsyncClient | None = None


def _get_telegram_client() -> httpx.AsyncClient:
    """Return the module-level singleton httpx.AsyncClient (WR-08 / D-50).

    Creates the client on first call with a 10s timeout (matches original per-call value).
    """
    global _telegram_client
    if _telegram_client is None:
        _telegram_client = httpx.AsyncClient(timeout=10.0)
    return _telegram_client


async def _close_telegram_client() -> None:
    """Close and discard the singleton client — for test teardown / process shutdown."""
    global _telegram_client
    if _telegram_client is not None:
        await _telegram_client.aclose()
        _telegram_client = None


async def send_telegram_alert(
    settings: DataPlatformSettings,
    severity: Literal["warn", "crit", "info"],
    body: str,
) -> None:
    """Send a severity-prefixed alert message to the operator's Telegram chat.

    Args:
        settings: DataPlatformSettings instance. If settings.telegram is None,
                  the call is a no-op (logs a warning and returns immediately).
        severity: One of "warn", "crit", "info" — selects the emoji prefix.
        body: Alert message body. Combined prefix+body is truncated to 4000 chars.

    Returns:
        None. Never raises — HTTP failures are logged and swallowed (D-86).
    """
    if settings.telegram is None:
        log.warning(
            "telegram.skipped",
            reason="telegram not configured in settings",
            severity=severity,
            body_preview=body[:200],
        )
        return

    prefix = _SEVERITY_PREFIX.get(severity, severity.upper())
    msg = f"{prefix} | {body}"[:_MAX_MESSAGE_LEN]
    url = f"https://api.telegram.org/bot{settings.telegram.bot_token.get_secret_value()}/sendMessage"

    try:
        client = _get_telegram_client()
        r = await client.post(url, json={"chat_id": settings.telegram.operator_chat_id, "text": msg})
        r.raise_for_status()
    except Exception as e:
        # Log the exception WITHOUT the URL (which contains the bot token — T-1-INF-03).
        log.error(
            "telegram.send.failed",
            severity=severity,
            exc_info=e,
        )
