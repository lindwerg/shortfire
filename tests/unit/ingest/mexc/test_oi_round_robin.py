"""Unit tests for OI REST round-robin scheduler (D-45).

Tests cover:
  - kv_state cursor advancement: [0:5], [5:10], [10:12]+wraparound
  - Symbol slice selection per step
  - kv_state["last_symbol_index"] correctness after each step

TDD cycle: RED phase — tests written before implementation.

Decisions honored:
  D-45: OI is REST-only; 5-min poll via round-robin over the universe
"""

from __future__ import annotations

from unittest.mock import AsyncMock


async def test_oi_round_robin_advances_cursor_correctly() -> None:
    """Round-robin advances kv_state cursor through 12 symbols in batches of 5."""
    from shortfire.ingest.mexc.oi import oi_round_robin_step

    symbols = [f"SYM{i}/USDT:USDT" for i in range(12)]

    # Build a mock MexcClient whose fetch_open_interest_history returns empty
    from tests.fakes.mexc import FakeMexcClient

    client = FakeMexcClient()

    # Patch fetch_open_interest_history to return empty (no DB needed)
    client.fetch_open_interest_history = AsyncMock(return_value=())  # type: ignore[method-assign]

    kv_state: dict = {"last_symbol_index": 0}

    # Step 1: should process symbols[0:5]
    kv_state = await oi_round_robin_step(None, client, symbols, batch_size=5, kv_state=kv_state)  # type: ignore[arg-type]
    assert kv_state["last_symbol_index"] == 5, "After first step, cursor should be at 5"

    # Step 2: should process symbols[5:10]
    kv_state = await oi_round_robin_step(None, client, symbols, batch_size=5, kv_state=kv_state)  # type: ignore[arg-type]
    assert kv_state["last_symbol_index"] == 10, "After second step, cursor should be at 10"

    # Step 3: should process symbols[10:12] → only 2 remaining → cursor wraps to 0
    kv_state = await oi_round_robin_step(None, client, symbols, batch_size=5, kv_state=kv_state)  # type: ignore[arg-type]
    assert kv_state["last_symbol_index"] == 0, "After reaching end, cursor should wrap to 0"


async def test_oi_round_robin_calls_correct_symbols() -> None:
    """Verify fetch_open_interest_history is called for the expected symbol slice."""
    from shortfire.ingest.mexc.oi import oi_round_robin_step

    symbols = [f"SYM{i}/USDT:USDT" for i in range(8)]

    from tests.fakes.mexc import FakeMexcClient

    client = FakeMexcClient()
    mock_fetch = AsyncMock(return_value=())
    client.fetch_open_interest_history = mock_fetch  # type: ignore[method-assign]

    kv_state = {"last_symbol_index": 3}

    await oi_round_robin_step(None, client, symbols, batch_size=3, kv_state=kv_state)  # type: ignore[arg-type]

    # Should have called for symbols[3], symbols[4], symbols[5]
    called_symbols = [call.args[0] for call in mock_fetch.call_args_list]
    assert called_symbols == [symbols[3], symbols[4], symbols[5]], (
        f"Expected symbols[3:6], got {called_symbols}"
    )


async def test_oi_round_robin_default_kv_state() -> None:
    """When kv_state is None, defaults to {'last_symbol_index': 0}."""
    from shortfire.ingest.mexc.oi import oi_round_robin_step

    symbols = ["BTC/USDT:USDT"]
    from tests.fakes.mexc import FakeMexcClient

    client = FakeMexcClient()
    client.fetch_open_interest_history = AsyncMock(return_value=())  # type: ignore[method-assign]

    # No kv_state passed → should not raise
    result = await oi_round_robin_step(None, client, symbols, batch_size=5, kv_state=None)  # type: ignore[arg-type]
    assert "last_symbol_index" in result
