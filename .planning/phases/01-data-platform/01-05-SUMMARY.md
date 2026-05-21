---
phase: 01
plan: 05
subsystem: ingest/mexc
tags:
  - python
  - ccxt
  - mexc
  - ingest
  - backfill
  - pydantic
  - tdd

dependency_graph:
  requires:
    - 01-01  # ingest seam: mexc_retry, MEXC_LIMITER, copy_into_hypertable, write_to_dead_letter
    - 01-02  # Candle/Funding/OrderBook domain types
    - 01-04  # dead_letter table, MexcClient Protocol (FOUND-08)
  provides:
    - src/shortfire/ingest/mexc/client.py — MexcClient concrete (ccxt 4.5 swap), build_mexc_swap_client
    - src/shortfire/ingest/mexc/schemas.py — 4 Pydantic v2 strict schemas (OhlcvRow, FundingRow, OIRow, TradeRow)
    - src/shortfire/ingest/mexc/backfill.py — paginated REST OHLCV + funding backfill
    - tests/fakes/mexc.py — FakeMexcClient with_synthetic_candles + generate_synthetic_candles
  affects:
    - 01-08  # live WS ingest consumes same MexcClient interface
    - 01-11  # STOR-08 6-day backfill CI test imports with_synthetic_candles

tech_stack:
  added:
    - ccxt==4.5.54 (pinned >=4.5.54,<4.6 per D-41)
  patterns:
    - Pydantic v2 ConfigDict(frozen=True, strict=True) on all wire-format schemas
    - asyncio.TaskGroup for backfill_universe (Pitfall 27)
    - Semaphore(8) bounded concurrency per D-42
    - copy_into_hypertable ON CONFLICT DO NOTHING (STOR-08 idempotency)
    - Dead-letter routing on every Pydantic/ccxt failure (DATA-11)

key_files:
  created:
    - src/shortfire/ingest/mexc/__init__.py
    - src/shortfire/ingest/mexc/schemas.py
    - src/shortfire/ingest/mexc/client.py
    - src/shortfire/ingest/mexc/backfill.py
    - tests/unit/ingest/mexc/__init__.py
    - tests/unit/ingest/mexc/test_mexc_client_construction.py
    - tests/unit/ingest/mexc/test_mexc_schemas.py
    - tests/unit/ingest/mexc/test_mexc_funding_schema.py
    - tests/unit/ingest/mexc/test_backfill_pagination.py
    - tests/integration/ingest/test_mexc_ohlcv.py
  modified:
    - pyproject.toml (ccxt pin tightened from >=4.5.54 to >=4.5.54,<4.6)
    - uv.lock (ccxt 4.5.54 resolved)
    - tests/fakes/mexc.py (with_synthetic_candles + generate_synthetic_candles + paginated fetch)

decisions:
  - "ccxt pinned >=4.5.54,<4.6 per D-41; actual resolved version is 4.5.54 (latest as of 2026-05-21)"
  - "backfill_ohlcv returns copy_into_hypertable batch input count (not INSERT count) because asyncpg COPY does not expose ON CONFLICT skip count; idempotency is verified by DB row count in integration test"
  - "TIMEFRAME_TO_TABLE contains only 1m and 1d; 5m/15m/1h/4h CAs are NOT backfilled directly (D-67 substrate is 1m base)"
  - "FakeMexcClient.with_synthetic_candles is a classmethod (not instance method) per W6 reconciliation — 01-11 STOR-08 test depends on this exact signature"
  - "Gap-detected quality_flag injection deferred to plan 01-08 per RESEARCH.md Open Question 7"

metrics:
  duration: "~35 minutes (wall clock, including context restore after compaction)"
  completed_date: "2026-05-21"
  tasks_completed: 2
  files_created: 10
  files_modified: 3
  tests_green: 15  # 14 unit + 1 integration
---

# Phase 01 Plan 05: MEXC Ingest — Concrete Client + Schemas + Paginated Backfill

**One-liner:** ccxt 4.5.54 MexcClient (swap-default, verbose=False, retry+limiter) + 4 Pydantic v2 strict schemas + paginated 1000-row OHLCV/funding REST backfill with Semaphore(8) + DATA-01 keystone integration test green against TimescaleDB testcontainer.

## What Was Built

### Task 1: Pydantic v2 schemas + ccxt 4.5 pin + MexcClient factory

**`src/shortfire/ingest/mexc/schemas.py`** — Four Pydantic v2 strict schemas:
- `MexcOhlcvRow`: 6-element ccxt array form via `from_ccxt_row()` classmethod; `to_domain()` → `Candle` with `source='mexc_native'`
- `MexcFundingRow`: dual-timestamp capture (`timestamp` = published_ts, `fundingTimestamp` = settlement_ts per D-44); `to_domain()` → `Funding`; domain `_published_le_settlement` validator enforced
- `MexcOpenInterestRow`: `to_record()` → 6-tuple for `raw_mexc_oi` hypertable
- `MexcTradeRow`: `to_record()` → 9-tuple for `raw_mexc_trades`; `side: Literal["buy","sell"]`

All schemas: `ConfigDict(frozen=True, strict=True, populate_by_name=True)`, `source="mexc_native"` hardcoded (D-59).

**`src/shortfire/ingest/mexc/client.py`** — `MexcClient` concrete class:
- `build_mexc_swap_client(settings)` factory: `options={'defaultType':'swap','recvWindow':10000}`, `enableRateLimit=True` (D-73), `verbose=False` (Pitfall 8)
- 4 public async methods (`fetch_ohlcv`, `fetch_funding_rate_history`, `fetch_open_interest_history`, `fetch_order_book`): each decorated `@mexc_retry` + `async with MEXC_LIMITER` + dead-letter on exception
- `place_order` / `cancel_order` raise `NotImplementedError` (Phase 5 gate — read-only data-platform client)
- Satisfies `runtime_checkable MexcClient` Protocol from `shortfire.clients.mexc` (FOUND-08)

**`pyproject.toml`**: `ccxt>=4.5.54,<4.6` — resolved to `ccxt==4.5.54` (latest as of 2026-05-21).

### Task 2: Paginated REST backfill + FakeMexcClient synthetic generator

**`src/shortfire/ingest/mexc/backfill.py`**:
- `TIMEFRAME_MS`: 1m=60_000ms through 1d=86_400_000ms
- `TIMEFRAME_TO_TABLE`: `{"1m": "raw_mexc_candles_1m", "1d": "raw_mexc_candles_1d"}` — only these two have dedicated hypertables; 5m/15m/1h/4h are continuous aggregates over `raw_mexc_candles_1m` and are silently skipped
- `backfill_ohlcv(engine, client, symbol, timeframe, since, until, semaphore) -> int`: pagination loop advancing `cursor = last_ts_ms + TIMEFRAME_MS[tf]`; semaphore held for the full loop; writes via `copy_into_hypertable`
- `backfill_universe(...)`: `asyncio.TaskGroup` per Pitfall 27; `Semaphore(max_concurrency=8)` per D-42
- `backfill_funding(...)`: `copy_into_hypertable` → `raw_mexc_funding`, conflict on `(symbol, settlement_ts)`

**`tests/fakes/mexc.py`** (extended):
- `with_synthetic_candles(cls, *, symbols, timeframe, since, until, base_price)` — classmethod constructor; canonical signature for 01-11 STOR-08 test
- `generate_synthetic_candles(self, symbol, timeframe, since, until, base_price)` — instance method; price walk: `close[i] = base_price + Decimal(i*10)`; high=close+50; low=close-50; volume=100
- `fetch_ohlcv` paginates from `_canned_per_symbol[symbol]` in 1000-row pages; backward-compatible with Phase-0 `FakeMexcClient(candles=...)` constructor
- `max_observed_concurrency` counter for Semaphore cap assertion

## Test Results

| Test Suite | Result | Count |
|------------|--------|-------|
| `tests/unit/ingest/mexc` | PASS | 14 tests |
| `tests/integration/ingest/test_mexc_ohlcv.py` (integration) | PASS | 1 test |

### Unit tests breakdown:
- `test_mexc_client_construction.py` (3): factory returns swap-default client; raises RuntimeError when mexc=None; satisfies Protocol isinstance check
- `test_mexc_schemas.py` (4): OhlcvRow from_ccxt_row roundtrip; Hypothesis valid row; negative non-numeric; tz-aware output
- `test_mexc_funding_schema.py` (3): Hypothesis t1≤t2 invariant holds; t1>t2 raises ValidationError; published_ts is UTC
- `test_backfill_pagination.py` (4): 2500-candle pagination (4 fetch calls = 3 data pages + 1 terminator); CA timeframe skip; idempotency with in-memory fake; Semaphore cap

### DATA-01 Keystone integration test:
Against fresh TimescaleDB testcontainer (after `alembic upgrade head`):
1. 100 synthetic candles backfilled via `FakeMexcClient.with_synthetic_candles`
2. SELECT COUNT(*) = 100
3. SELECT DISTINCT source = {'mexc_native'}
4. SELECT DISTINCT quality_flag = {'ok'}
5. OHLCV invariant query returns 0 violating rows
6. sample ts.tzinfo is not None (TIMESTAMPTZ)
7. Second backfill → row count still 100 (no duplicates; idempotency via ON CONFLICT DO NOTHING)

## Observed API Shape (Assumption A3 verification)

Could not verify `fundingTimestamp` field shape against live MEXC API (no real API key in CI). The schema uses `fundingTimestamp` as defined in RESEARCH.md §14 Assumption A3. The fallback `d.get("fundingTimestamp", d["timestamp"])` in `client.py` handles the case where the field is absent (same ms timestamp used for both).

OI field names `openInterestAmount`/`openInterestValue` are assumed correct per ccxt 4.5 unified schema — not smoke-tested against live API.

## Backfill Throughput

Integration test: 100 candles in ~3.5s (includes testcontainer overhead + alembic migration warmup). The actual copy path is asyncpg COPY protocol → UNLOGGED staging → INSERT ON CONFLICT DO NOTHING, which is optimized for bulk inserts. Estimated throughput for pure copy path (without container overhead): ~5,000–20,000 candles/second based on RESEARCH.md §2 Pattern 1 benchmarks. Full 1-year backfill (~525,600 candles per symbol at 1m) should complete in under 2 minutes per symbol at sustained throughput — within the D-38 backfill scope operational runbook target.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Idempotency test assertion: return value vs DB row count**
- **Found during:** Task 2 integration test run
- **Issue:** `copy_into_hypertable` returns `len(records_list)` (batch input count), not actual INSERT count. asyncpg COPY does not expose ON CONFLICT skip count via rowcount. The plan's acceptance criterion `n2 == 0` on second run was unreachable with the existing copy helper contract.
- **Fix:** Changed the idempotency assertion to verify DB row count stays at 100 after second run (the actual invariant that matters). The unit idempotency test (`test_backfill_ohlcv_idempotent_against_in_memory_fake`) correctly simulates ON CONFLICT behavior via a mock that returns 0 on re-insertion.
- **Files modified:** `tests/integration/ingest/test_mexc_ohlcv.py`
- **Commit:** d36c1e8

**2. [Rule 1 - Bug] Pagination call count: 3 vs 4**
- **Found during:** Task 2 RED → GREEN transition
- **Issue:** The test initially asserted `len(fetch_calls) == 3` (data-returning pages). Actual behavior: the backfill loop makes 3 data-returning calls (1000, 1000, 500) + 1 terminating call that returns an empty tuple (causing the `while cursor < end_ms` condition to break). Total = 4 calls.
- **Fix:** Updated assertion to `== 4` with inline comment explaining the terminator call.
- **Files modified:** `tests/unit/ingest/mexc/test_backfill_pagination.py`
- **Commit:** d36c1e8

## Open Items (Deferred)

| Item | Deferred to |
|------|-------------|
| gap_detected quality_flag injection (RESEARCH.md Open Question 7) | plan 01-08 |
| OI REST polling (D-45, REST-only per MEXC) | plan 01-08 (scheduler) |
| Live smoke test against real MEXC API key (Assumption A3 verification) | Manual validation before production backfill |

## Known Stubs

None — all data paths are wired. `place_order` / `cancel_order` raise `NotImplementedError` by design (Phase 5 gate — data-platform client is read-only).

## Threat Flags

No new security surface beyond the plan's threat model. All threats T-1-MEXC-01 through T-1-DEP-01 addressed:
- `verbose=False` verified in unit test and in grep guard
- Pydantic strict validation + dead-letter on all parse failures
- Dual-timestamp funding invariant tested via Hypothesis
- Source attribution hardcoded `"mexc_native"` in every record tuple in backfill.py

## Self-Check: PASSED

- [x] `src/shortfire/ingest/mexc/backfill.py` exists
- [x] `src/shortfire/ingest/mexc/client.py` exists
- [x] `src/shortfire/ingest/mexc/schemas.py` exists
- [x] `tests/fakes/mexc.py` has `with_synthetic_candles` classmethod
- [x] `tests/integration/ingest/test_mexc_ohlcv.py` exists
- [x] Commit `76aaf1b` (baseline + Task 1): verified `git log --oneline` shows it
- [x] Commit `d36c1e8` (Task 2): verified `git log --oneline` shows it
- [x] `uv run pytest tests/unit/ingest/mexc -x -q` → 14 passed
- [x] `uv run pytest -m integration tests/integration/ingest/test_mexc_ohlcv.py -v` → 1 passed
- [x] `uv run pre-commit run --all-files` → all hooks passed
- [x] `uv sync --locked` → resolved 89 packages, no changes
