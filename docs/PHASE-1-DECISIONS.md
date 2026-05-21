# Phase 1 Architecture Decisions

This file captures decisions that deviate from or refine the original plan decisions
during Phase 1 execution. Each entry has a unique ID, source, and rationale.

---

## D-48-REVISION: Liquidations dual-source → ws-only in Phase 1

**Date:** 2026-05-22
**Source:** 01-08 plan revision per checker W3
**Original decision:** D-48 mandated `mexc_native` liquidations via ws + REST-poll fallback
marking `quality_flag='partial_capture'` on partial capture events.

**Revised decision:** Phase 1 ships ws-only. REST fallback deferred to Phase 1.x or Phase 2 EDA.

**Rationale:** ccxt 4.5.x MEXC swap class lacks a stable implicit-API path for
`/api/v1/contract/liquidation/orders`. Implementing a custom httpx call would bypass
ccxt's signing + throttling discipline (RESEARCH.md Pitfall 8). Risk/reward does not
justify in-phase work when the Coinglass aggregate (plan 01-06) already provides adequate
cross-exchange liquidation fidelity for Phase 2 EDA.

**Implementation in Phase 1:**
- `liquidations_dual_source_loop` in `src/shortfire/ingest/mexc/liquidations.py` checks
  `hasattr(raw, "watch_liquidations")` at startup.
- If present: ws stream used, `quality_flag='ok'` on every record.
- If absent: emits structlog `liquidations.degraded` event with
  `reason="ws_unavailable_phase1_ships_no_fallback"`, sets freshness gauge to 0 sentinel
  (so plan 01-10 freshness alerter fires `freshness.degraded`), then exits cleanly.

**`quality_flag='partial_capture'` status:** RESERVED in migration 0008 (D-60) for the
Phase 1.x REST fallback path. Not written in Phase 1 but kept in the enum for future use.

**Operator impact:** If pinned ccxt 4.5.x lacks `watch_liquidations`, the
`raw_mexc_liquidations` table stays empty until Phase 1.x. Coinglass aggregate
liquidations (plan 01-06, `source='coinglass_aggregate'`) carry the cross-exchange
signal in the interim. The freshness gauge sentinel ensures the alerter fires so
the operator is notified.

**Owner:** solo operator
**Ticket:** N/A (solo project)
**Follow-up:** Phase 1.x patch plan to implement REST fallback via ccxt implicit API
              or validated httpx call against MEXC liquidation endpoint.

---

## D-08-OI-SENTINEL: OI module uses Decimal("0") for null-like openInterestAmount

**Date:** 2026-05-22
**Source:** 01-08 implementation

**Decision:** `oi_round_robin_step` uses `Decimal("0")` when `openInterestAmount` is None.

**Rationale:** The `raw_mexc_oi.open_interest` column has a NOT NULL constraint from
migration 0003. Inserting NULL would fail. Using `Decimal("0")` as a sentinel is safe
because `quality_flag='ok'` on the same row distinguishes this from a real zero OI
(which almost never occurs for active perpetuals). Operator should treat zero OI rows
with caution but the constraint is not violated.

---

## D-08-GAP-SENTINEL: flag_gap() uses Decimal("0") for synthetic OHLCV rows

**Date:** 2026-05-22
**Source:** 01-08 plan W3 reconciliation (see PLAN.md §D-48 action step 4 note)

**Decision:** `flag_gap()` in `src/shortfire/ingest/gap.py` inserts synthetic rows with
`Decimal("0")` for OHLC and volume columns rather than NULL.

**Rationale:** `raw_mexc_candles_1m` OHLCV columns have NOT NULL constraints from
migration 0003. Altering to nullable mid-phase would be a schema change requiring a
new Alembic migration (architectural change per Rule 4). The `Decimal("0")` sentinel
approach avoids this entirely: `quality_flag='gap_detected'` unambiguously identifies
the synthetic origin; zero OHLCV never occurs in real perpetual futures candles; Phase 2
FEAT-14 lint rule bans bfill which would silently propagate zeros.

**Alternative considered:** ALTER COLUMN to nullable via migration 0015. Rejected because:
(a) mid-phase schema change has broader blast radius; (b) sentinel-zero is simpler;
(c) downstream code already gates on `quality_flag` before using OHLCV values.

---

## D-08-WS-CLIENT-PROPERTY: MexcClient.ws_client property added

**Date:** 2026-05-22
**Source:** 01-08 implementation (pyright strict mode enforcement)

**Decision:** Added `ws_client` property to `MexcClient` that exposes the underlying
`ccxt.pro.mexc` instance for ws stream operations in live-ingest modules.

**Rationale:** pyright strict mode flags `_client` as a private attribute access violation
when used outside the class. Live-ingest modules (live_candles, funding, trades, orderbook,
liquidations) need direct access to ccxt Pro watch_* methods not exposed through the public
`MexcClient` Protocol. The `ws_client` property is a clean, documented public surface for
this access pattern. The alternative (`# type: ignore[reportPrivateUsage]`) would suppress
a legitimate warning.

---

## D-08-DUPLICATE-WATCH-TRADES: Both aggregator and trades persister consume watch_trades

**Date:** 2026-05-22
**Source:** 01-08 plan §Action Step 3 note

**Decision:** `trades_aggregator_loop` (live_candles.py) and `trades_persist_loop`
(trades.py) both call `watch_trades_for_symbols`. This is intentional duplication.

**Rationale:** ccxt Pro caches the underlying ws connection and multiplexes subscribers
to the same stream. The two consumers serve different concerns (OHLCV aggregation vs raw
tape persistence) and merging them would tightly couple the two concerns. The duplication
cost is minimal (no extra ws connection; only in-process message dispatch overhead).

**Follow-up:** If profiling shows non-trivial overhead, consider a fan-out pattern where
one consumer dispatches to both channels. Deferred to Phase 2 performance tuning.
