---
phase: 01-data-platform
plan: 08
subsystem: ingest
tags: [mexc, ccxt-pro, websocket, asyncio, taskgroup, timescaledb, asyncpg, structlog, prometheus, orjson, hypothesis]

# Dependency graph
requires:
  - phase: 01-03
    provides: TimescaleDB schema (hypertables raw_mexc_candles_1m, raw_mexc_funding, raw_mexc_trades, raw_mexc_oi, raw_mexc_l2_top20, raw_mexc_liquidations)
  - phase: 01-05
    provides: MexcClient with REST + ccxt.pro ws methods, copy_into_hypertable, dead_letter writer, DataPlatformMetrics, EVENTS frozenset

provides:
  - MinuteAggregator + trades_aggregator_loop: client-side 1m candle building from watch_trades (D-43, watch_ohlcv BANNED)
  - funding_live_loop: watch_funding_rate with dual settlement_ts/published_ts timestamps (D-44)
  - trades_persist_loop: 1-min batched COPY into raw_mexc_trades (D-47)
  - oi_round_robin_step: REST-only OI polling with kv_state cursor round-robin (D-45)
  - l2_sample_loop: per-symbol ws L2 sampler, tier-1=5s/tier-2=10s cadences, orjson JSONB encoding (D-46)
  - liquidations_dual_source_loop: ws-only + degraded path with sentinel gauge (D-48)
  - flag_gap: gap-injection helper with Decimal("0") sentinel rows + quality_flag='gap_detected' (STOR-09)
  - mexc_ws_streams: AsyncContextManager TaskGroup orchestrator, heartbeat watchdog, cross-REST divergence check (D-49)
  - ws_client property on MexcClient for pyright-safe ccxt.pro access
  - docs/PHASE-1-DECISIONS.md: D-48-REVISION, D-08-OI-SENTINEL, D-08-GAP-SENTINEL, D-08-WS-CLIENT-PROPERTY recorded

affects: [01-09, 01-10, 01-11, strategy-research, backtester]

# Tech tracking
tech-stack:
  added: [orjson (JSONB encoding), hypothesis (property-based testing for aggregator + watchdog)]
  patterns:
    - MinuteAggregator state machine: per-symbol bucket tracking with immutable Decimal updates, minute-boundary finalization
    - kv_state cursor pattern: dict-based round-robin cursor for REST polling without external state
    - TaskGroup structured concurrency: all ws tasks under one asyncio.TaskGroup (zero bare asyncio.create_task per Pitfall 27)
    - Degraded-path sentinel: hasattr guard + freshness gauge set to 0 + clean return (not raise) for optional ws capabilities
    - Dual-timestamp funding: fundingTimestamp (settlement) vs timestamp (published) per D-44/Pitfall 2
    - Heartbeat watchdog reads Prometheus gauge (not ccxt internal state) for stream health monitoring
    - PEP 654 except*: ExceptionGroup from TaskGroup propagated to FastAPI lifespan for respawn

key-files:
  created:
    - src/shortfire/ingest/mexc/live_candles.py
    - src/shortfire/ingest/mexc/funding.py
    - src/shortfire/ingest/mexc/trades.py
    - src/shortfire/ingest/mexc/oi.py
    - src/shortfire/ingest/mexc/orderbook.py
    - src/shortfire/ingest/mexc/liquidations.py
    - src/shortfire/ingest/mexc/streams.py
    - src/shortfire/ingest/gap.py
    - docs/PHASE-1-DECISIONS.md
    - tests/unit/ingest/mexc/test_minute_aggregator.py
    - tests/unit/ingest/mexc/test_l2_sampling.py
    - tests/unit/ingest/mexc/test_liquidations.py
    - tests/unit/ingest/mexc/test_oi_round_robin.py
    - tests/unit/ingest/mexc/test_heartbeat_watchdog.py
    - tests/integration/ingest/test_live_candle_aggregator_writes.py
  modified:
    - src/shortfire/ingest/mexc/client.py (added ws_client property)

key-decisions:
  - "D-43: watch_ohlcv BANNED (ccxt#27253 silent hangs) — client-side MinuteAggregator from watch_trades instead"
  - "D-44: Dual-timestamp funding rate capture — fundingTimestamp (settlement_ts) + timestamp (published_ts)"
  - "D-45: OI is REST-only; 5-min poll via round-robin over universe via kv_state cursor"
  - "D-46: L2 sampler uses watch_order_book(symbol, limit=20); tier-1=5s cadence, tier-2=10s"
  - "D-47: trades_persist_loop uses same watch_trades_for_symbols as aggregator; 1-min batched COPY"
  - "D-48-REVISION: Phase 1 ships ws-only liquidations; REST fallback deferred to Phase 1.x reconciliation"
  - "D-49: mexc_ws_streams TaskGroup with heartbeat watchdog (60s staleness → RuntimeError) + cross-REST divergence (0.5% threshold)"
  - "STOR-09: flag_gap uses Decimal(0) for OHLCV sentinel rows (avoids ALTER COLUMN migration)"
  - "Pitfall 27: zero bare asyncio.create_task — all tasks via TaskGroup.create_task"
  - "ws_client property on MexcClient exposes self._client for pyright-safe access from ws stream coroutines"

patterns-established:
  - "MinuteAggregator: on_trade(symbol, ts, price, qty) → bucket dict | None; finalizes on minute boundary"
  - "kv_state cursor: oi_round_robin_step returns updated dict; caller passes back next iteration"
  - "L2 JSONB: orjson.dumps([[str(p), str(q)] for level in bids[:20]]).decode() → TEXT cast to JSONB by PG"
  - "Degraded path: hasattr(raw, method) guard → log.warning(event, reason=...) → gauge.set(0) → return"
  - "Heartbeat: reads source_freshness_seconds prometheus gauge; lag > HEARTBEAT_TIMEOUT_S → RuntimeError for supervisor respawn"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-09, DATA-11, DATA-12, STOR-09]

# Metrics
duration: 120min
completed: 2026-05-22
---

# Phase 01 Plan 08: MEXC Live WS Ingest Layer Summary

**Full MEXC ws ingest stack: client-side 1m candle aggregator (MinuteAggregator), funding/trades/OI/L2/liquidations loops, gap sentinel helper, and TaskGroup orchestrator with 60s heartbeat watchdog + cross-REST divergence check**

## Performance

- **Duration:** ~120 min
- **Started:** 2026-05-21T19:30:00Z
- **Completed:** 2026-05-22T00:30:00Z
- **Tasks:** 2 (TDD: RED tests + GREEN implementation)
- **Files modified:** 17 (16 created + 1 modified)

## Accomplishments

- Full ws ingest layer covering all 6 MEXC data streams: candles (aggregated from trades), funding rates, raw trades, open interest (REST poll), L2 order book snapshots, and liquidations
- `mexc_ws_streams` context manager wires all streams into a single `asyncio.TaskGroup` with heartbeat watchdog and cross-REST divergence checker; `except* RuntimeError` (PEP 654) propagates stale-stream errors to FastAPI lifespan for respawn
- TDD discipline maintained: 29 unit tests (including Hypothesis property tests) + 1 Docker-backed integration test all passing; pre-commit hooks clean

## Task Commits

1. **Task 1: RED tests + MinuteAggregator, funding_live_loop, trades_persist_loop** - `0a2191b` (feat)
2. **Task 2: OI round-robin, L2 sampler, liquidations, gap helper, TaskGroup orchestrator** - `6aaed9f` (feat)

## Files Created/Modified

- `src/shortfire/ingest/mexc/live_candles.py` - MinuteAggregator state machine + trades_aggregator_loop
- `src/shortfire/ingest/mexc/funding.py` - funding_live_loop with dual-timestamp D-44 capture
- `src/shortfire/ingest/mexc/trades.py` - trades_persist_loop, 1-min batched COPY into raw_mexc_trades
- `src/shortfire/ingest/mexc/oi.py` - oi_round_robin_step with kv_state cursor advancement
- `src/shortfire/ingest/mexc/orderbook.py` - l2_sample_loop with tier cadences + orjson JSONB
- `src/shortfire/ingest/mexc/liquidations.py` - liquidations_dual_source_loop + degraded path
- `src/shortfire/ingest/mexc/streams.py` - mexc_ws_streams TaskGroup orchestrator + watchdog + divergence
- `src/shortfire/ingest/gap.py` - flag_gap gap-injection helper (STOR-09)
- `src/shortfire/ingest/mexc/client.py` - added ws_client property for pyright-safe ccxt.pro access
- `docs/PHASE-1-DECISIONS.md` - D-48-REVISION, D-08-* decisions recorded
- `tests/unit/ingest/mexc/test_minute_aggregator.py` - 4 tests (3 deterministic + 1 Hypothesis)
- `tests/unit/ingest/mexc/test_oi_round_robin.py` - 3 async tests (cursor advancement, symbol slice, default state)
- `tests/unit/ingest/mexc/test_l2_sampling.py` - 2 tests (cadence + JSONB serialization)
- `tests/unit/ingest/mexc/test_liquidations.py` - 3 tests (ws path + 2 degraded path variants)
- `tests/unit/ingest/mexc/test_heartbeat_watchdog.py` - 3 tests (fresh + stale + Hypothesis threshold boundary)
- `tests/integration/ingest/test_live_candle_aggregator_writes.py` - Docker-backed integration test

## Decisions Made

- **D-48-REVISION**: Phase 1 ships ws-only liquidations; the `watch_liquidations` degraded path (hasattr guard + freshness gauge sentinel 0 + clean return) allows the TaskGroup to continue when ccxt's MEXC driver doesn't expose the method. REST fallback deferred to Phase 1.x (W3 reconciliation plan).
- **D-08-WS-CLIENT-PROPERTY**: Added `ws_client` property to MexcClient to expose `self._client` — pyright correctly flags direct `_client` access outside the class (`reportPrivateUsage`). Property is the clean solution.
- **D-08-DUPLICATE-WATCH-TRADES**: Both `trades_aggregator_loop` (candle building) and `trades_persist_loop` (raw trade storage) consume `watch_trades_for_symbols`. ccxt Pro caches the underlying WS connection so both loops receive the same stream. This is intentional architectural redundancy, not a bug.
- **Heartbeat reads Prometheus gauge**: Rather than probing ccxt internal timestamps (fragile across minor versions), the watchdog reads the `source_freshness_seconds` gauge that each ingest loop updates on every successful write — more reliable and decoupled.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Removed `if engine is not None:` guard from copy_into_hypertable calls**
- **Found during:** Task 2 (liquidations + orderbook + OI unit tests)
- **Issue:** Unit tests pass `engine=None` and mock `copy_into_hypertable`. The guard `if engine is not None:` caused the patched function to never be called, making tests fail with `assert len(copied_records) == 1` failures.
- **Fix:** Removed engine guards from `liquidations.py`, `orderbook.py`, and `oi.py`. Unit tests that pass `None` as engine patch `copy_into_hypertable` to avoid real DB calls — the engine parameter flows through to the patched function, which is correct.
- **Files modified:** src/shortfire/ingest/mexc/liquidations.py, src/shortfire/ingest/mexc/orderbook.py, src/shortfire/ingest/mexc/oi.py
- **Verification:** All 29 unit tests pass; engine=None with patched copy function is the correct test pattern.
- **Committed in:** 6aaed9f (Task 2 commit)

**2. [Rule 1 - Bug] Fixed L2 sampling cadence test: fake_mono returning 0.0 prevented emit**
- **Found during:** Task 2 (test_l2_sampling.py bids/asks test)
- **Issue:** `fake_mono` returned `0.0` on first call → `now - last_emit = 0.0 - 0.0 = 0.0 < 5.0` → cadence guard fired, no COPY called.
- **Fix:** Changed `fake_mono` to always return `999.0` so `now - last_emit = 999.0 - 0.0 > 5.0` on first call.
- **Files modified:** tests/unit/ingest/mexc/test_l2_sampling.py
- **Verification:** Test `test_l2_sampler_bids_asks_are_json_serializable` passes; `assert len(copied_records) == 1` succeeds.
- **Committed in:** 6aaed9f (Task 2 commit)

**3. [Rule 1 - Bug] Fixed Hypothesis heartbeat test: infinite loop for fresh gauge cases**
- **Found during:** Task 2 (test_heartbeat_watchdog.py Hypothesis property test)
- **Issue:** `shutdown_event.is_set = MagicMock(return_value=False)` meant the watchdog loop ran forever for lag <= 60s cases (no RuntimeError to break the loop).
- **Fix:** Used counter-based `fake_is_set` that returns `True` on second call, allowing exactly one loop iteration then clean exit.
- **Files modified:** tests/unit/ingest/mexc/test_heartbeat_watchdog.py
- **Verification:** Hypothesis test completes 50 examples in <3s; all fresh/stale boundaries correct.
- **Committed in:** 6aaed9f (Task 2 commit)

**4. [Rule 1 - Bug] Fixed pyright asynccontextmanager return type annotation**
- **Found during:** Task 2 (streams.py pyright check)
- **Issue:** `mexc_ws_streams` was annotated `-> Any` but `@asynccontextmanager` requires the decorated function to return `AsyncGenerator`.
- **Fix:** Changed return type to `-> AsyncGenerator[None, None]` and added `from collections.abc import AsyncGenerator`.
- **Files modified:** src/shortfire/ingest/mexc/streams.py
- **Verification:** pyright shows 0 errors on src/ (only ccxt stub warnings from 3rd-party library).
- **Committed in:** 6aaed9f (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bugs, 1 Rule 2 missing critical, 1 Rule 1 type annotation bug)
**Impact on plan:** All fixes necessary for correctness and testability. No scope creep.

## Issues Encountered

- **ccxt private attribute access**: pyright `reportPrivateUsage` fired for `mexc_client._client` in all ws stream modules. Resolved cleanly via `ws_client` property on MexcClient (Rule 2 — missing interface).
- **ruff SIM105/SIM117 hooks**: Pre-commit required replacing `try/except CancelledError: pass` with `contextlib.suppress(CancelledError)`, and merging nested `with` statements using parenthesized multi-context form. Both idiomatic Python 3.10+ patterns.
- **ruff F841**: Removed unused `orig_is_set` variable in heartbeat watchdog test.

## User Setup Required

None — no external service configuration required for this plan.

## Next Phase Readiness

- Full MEXC ws ingest layer is implemented and tested; all 29 unit + 1 integration test passing
- `mexc_ws_streams` is the FastAPI lifespan entry point for plan 01-09 (FastAPI app + lifespan wiring)
- `flag_gap` is ready for plan 01-10 (gap detection scheduler)
- All hypertable COPY paths use the same `copy_into_hypertable` abstraction established in plan 01-03

---
*Phase: 01-data-platform*
*Completed: 2026-05-22*
