"""Unit tests for kv_state helpers (load_kv_state + save_kv_state).

Uses in-memory mocks — no real DB, no network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from shortfire.ingest.state.kv_state import load_kv_state, save_kv_state

# ---------------------------------------------------------------------------
# Helpers to build minimal mock AsyncEngine
# ---------------------------------------------------------------------------


def _make_engine_with_row(row_value: Any) -> Any:
    """Return a mock engine whose connect().execute() returns row_value as first row."""
    mock_row = MagicMock()
    mock_row.__getitem__ = MagicMock(side_effect=lambda i: row_value)
    mock_first = None if row_value is None else (row_value,)

    mock_result = MagicMock()
    mock_result.first = MagicMock(return_value=mock_first)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=mock_ctx)
    return engine


def _make_engine_for_save() -> tuple[Any, AsyncMock]:
    """Return (engine, execute_mock) for save_kv_state tests."""
    execute_mock = AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.execute = execute_mock

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.begin = MagicMock(return_value=mock_ctx)
    return engine, execute_mock


# ---------------------------------------------------------------------------
# load_kv_state tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_kv_state_returns_dict_from_db() -> None:
    """load_kv_state returns the dict stored in ingest_runs.kv_state."""
    expected = {"last_symbol_index": 7}
    engine = _make_engine_with_row(expected)

    result = await load_kv_state(engine, "coinglass.oi")

    assert result == expected


@pytest.mark.asyncio
async def test_load_kv_state_returns_empty_dict_when_no_row() -> None:
    """load_kv_state returns {} when no matching row exists."""
    engine = _make_engine_with_row(None)

    result = await load_kv_state(engine, "coinglass.oi")

    assert result == {}


@pytest.mark.asyncio
async def test_load_kv_state_parses_json_string_fallback() -> None:
    """load_kv_state parses JSON string if asyncpg returns string instead of dict."""
    import json

    json_str = json.dumps({"last_symbol_index": 3})

    mock_result = MagicMock()
    mock_result.first = MagicMock(return_value=(json_str,))

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=mock_ctx)

    result = await load_kv_state(engine, "coinglass.oi")

    assert result == {"last_symbol_index": 3}


# ---------------------------------------------------------------------------
# save_kv_state tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_kv_state_inserts_row() -> None:
    """save_kv_state calls engine.begin().execute() with an INSERT statement."""
    engine, execute_mock = _make_engine_for_save()

    await save_kv_state(engine, "mexc.oi.poll", {"last_symbol_index": 42})

    assert execute_mock.call_count == 1


@pytest.mark.asyncio
async def test_save_kv_state_derives_source_mexc() -> None:
    """save_kv_state derives source='mexc_native' for 'mexc.*' job IDs."""
    import json

    engine, execute_mock = _make_engine_for_save()

    await save_kv_state(engine, "mexc.oi.poll", {"last_symbol_index": 42})

    call_kwargs = execute_mock.call_args[0][1]  # second positional arg = params dict
    assert call_kwargs["src"] == "mexc_native"
    assert call_kwargs["ds"] == "oi.poll"
    assert json.loads(call_kwargs["st"]) == {"last_symbol_index": 42}


@pytest.mark.asyncio
async def test_save_kv_state_derives_source_coinglass() -> None:
    """save_kv_state derives source='coinglass_aggregate' for 'coinglass.*' job IDs."""
    engine, execute_mock = _make_engine_for_save()

    await save_kv_state(engine, "coinglass.liq", {"last_symbol_index": 10})

    call_kwargs = execute_mock.call_args[0][1]
    assert call_kwargs["src"] == "coinglass_aggregate"
    assert call_kwargs["ds"] == "liq"
    assert call_kwargs["jid"] == "coinglass.liq"
