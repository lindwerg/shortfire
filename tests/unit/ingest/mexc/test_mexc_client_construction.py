"""Unit tests for MexcClient construction and Protocol compliance.

Covers:
- build_mexc_swap_client: swap default, recvWindow, verbose=False (D-40, D-41, D-73, Pitfall 8)
- build_mexc_swap_client raises RuntimeError when settings.mexc is None
- MexcClient concrete class satisfies runtime_checkable MexcClient Protocol (FOUND-08)
"""

from __future__ import annotations

import pytest

_DB_URL = "postgresql://user:pass@localhost:5432/testdb"


@pytest.mark.asyncio
async def test_build_mexc_swap_client_returns_concrete_with_swap_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_mexc_swap_client returns MexcClient with defaultType=swap, recvWindow=10000,
    enableRateLimit=True, verbose=False per D-40, D-41, D-73, Pitfall 8."""
    from shortfire.ingest.mexc.client import MexcClient, build_mexc_swap_client
    from shortfire.settings.data_platform import DataPlatformSettings

    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    monkeypatch.setenv("MEXC__READ_KEY", "test_key")
    monkeypatch.setenv("MEXC__READ_SECRET", "test_secret")

    settings = DataPlatformSettings()
    built = build_mexc_swap_client(settings)
    assert isinstance(built, MexcClient)
    assert built._client.options["defaultType"] == "swap"
    assert built._client.options["recvWindow"] == 10000
    assert built._client.enableRateLimit is True
    assert built._client.verbose is False
    await built._client.close()


def test_build_mexc_swap_client_raises_when_mexc_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_mexc_swap_client raises RuntimeError when settings.mexc is None."""
    from shortfire.ingest.mexc.client import build_mexc_swap_client
    from shortfire.settings.data_platform import DataPlatformSettings

    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    # No MEXC env vars — mexc=None
    settings = DataPlatformSettings()
    with pytest.raises(RuntimeError, match="must be configured"):
        build_mexc_swap_client(settings)


def test_mexc_client_satisfies_protocol() -> None:
    """Concrete MexcClient satisfies the runtime_checkable MexcClient Protocol (FOUND-08)."""
    from unittest.mock import MagicMock

    from shortfire.clients.mexc import MexcClient as MexcClientProto
    from shortfire.ingest.mexc.client import MexcClient as MexcClientImpl

    dummy = MagicMock()
    instance = MexcClientImpl(dummy)
    assert isinstance(instance, MexcClientProto)
