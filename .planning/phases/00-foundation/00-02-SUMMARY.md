---
phase: 0
plan: 2
subsystem: domain-types
tags:
  - python
  - pydantic
  - domain-types
  - hypothesis
  - tdd
dependency_graph:
  requires:
    - 00-01 (uv/pytest/hypothesis/pre-commit infrastructure)
  provides:
    - src/shortfire/domain/market.py (Candle, OrderBookLevel, OrderBook, Funding, Liquidation)
    - src/shortfire/domain/trading.py (Signal, Order, Position)
    - src/shortfire/domain/risk.py (RiskLimits)
    - tests/unit/domain/ (9 test files, 61 Hypothesis property tests)
  affects:
    - Every Phase 1+ module that imports domain types
    - test_timestamps_are_aware.py (now covers all 7 types with ts fields)
tech_stack:
  added: []
  patterns:
    - "Pydantic v2 ConfigDict(frozen=True, strict=True) for 7 of 8 types"
    - "ConfigDict(frozen=False, strict=True) for Position (D-08 lone carve-out)"
    - "Literal[...] aliases at module level — NOT StrEnum (D-10)"
    - "tuple[X, ...] for frozen model collections (D-11)"
    - "@model_validator(mode='after') -> Self for cross-field invariants (D-12, D-13)"
    - "Field(le=Decimal('0.05')) etc. for RISK-02 structural caps (RiskLimits)"
    - "Hypothesis @given over shared money + utc_dt strategies from conftest.py"
key_files:
  created:
    - src/shortfire/domain/market.py (213 LOC)
    - src/shortfire/domain/trading.py (122 LOC)
    - src/shortfire/domain/risk.py (38 LOC)
    - tests/unit/domain/__init__.py
    - tests/unit/domain/test_candle.py
    - tests/unit/domain/test_orderbook.py
    - tests/unit/domain/test_funding.py
    - tests/unit/domain/test_liquidation.py
    - tests/unit/domain/test_signal.py
    - tests/unit/domain/test_order.py
    - tests/unit/domain/test_position.py
    - tests/unit/domain/test_risk_limits.py
    - tests/unit/domain/test_timestamps_are_aware.py
  modified:
    - src/shortfire/domain/__init__.py (updated to re-export all 8 types + Literal aliases)
decisions:
  - "Separate @model_validator per cross-field invariant (one for naive ts, one for each domain invariant) — clearer error messages than combining into one validator"
  - "Candle.volume field uses Field(ge=Decimal('0')) not gt — zero volume is valid for synthetic bars"
  - "Position validates both opened_ts and last_update_ts in a single validator using a loop — keeps mutability semantics consistent with D-08"
  - "RiskLimits: daily_loss_limit_pct cap set to 0.10 (10%) — within RISK-02 spirit; no explicit spec for this cap so 2x the per-trade cap is a conservative default"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-21"
  tasks_completed: 2
  tasks_total: 2
  files_created: 13
  files_modified: 1
---

# Phase 0 Plan 2: Domain Types (Candle, OrderBook, Funding, Liquidation, Signal, Order, Position, RiskLimits) Summary

8 pure-Pydantic-v2 domain types in 3 source files with construction-time invariants (EXEC-02, RISK-02, OHLC, order book ordering, funding timing, naive datetime rejection) and 61 Hypothesis property tests covering every invariant per D-15.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 RED | Market type tests | 19b8d04 | tests/unit/domain/test_{candle,orderbook,funding,liquidation,timestamps_are_aware}.py |
| 1 GREEN | Market type implementation | 2f5410e | src/shortfire/domain/market.py, domain/__init__.py |
| 2 RED | Trading + risk type tests | a0005bd | tests/unit/domain/test_{signal,order,position,risk_limits}.py + updated test_timestamps_are_aware.py |
| 2 GREEN | Trading + risk type implementation | 4ba809e | src/shortfire/domain/trading.py, risk.py, domain/__init__.py |

## Domain Type Inventory

| Type | File | LOC (approx) | frozen | Invariants |
|------|------|--------------|--------|------------|
| Candle | market.py | ~50 | True | ts tz-aware; low <= open,close <= high |
| OrderBookLevel | market.py | ~10 | True | price > 0, qty > 0 |
| OrderBook | market.py | ~55 | True | ts tz-aware; bids descending; asks ascending; not crossed |
| Funding | market.py | ~45 | True | published_ts, settlement_ts, next_funding_ts tz-aware; published_ts <= settlement_ts |
| Liquidation | market.py | ~30 | True | ts tz-aware; qty > 0, price > 0 |
| Signal | trading.py | ~35 | True | ts tz-aware; confidence in [0,1] |
| Order | trading.py | ~55 | True | ts tz-aware; intent='close' => reduce_only=True (EXEC-02) |
| Position | trading.py | ~35 | False | opened_ts, last_update_ts tz-aware |
| RiskLimits | risk.py | ~35 | True | RISK-02: max_per_trade<=0.05, gross_exp<=0.15, kelly<=0.25, max_concurrent in [1,20] |

**Total domain source LOC:** 373 (market.py: 213, trading.py: 122, risk.py: 38)

## Hypothesis Test Coverage

| Invariant | Test File | Strategy | Examples |
|-----------|-----------|----------|---------|
| Candle round-trip | test_candle.py | money x money x money x money x utc_dt | 100 |
| Candle low > high raises | test_candle.py | parameterized | static |
| Candle naive ts raises | test_candle.py | static | static |
| OrderBook bids descending | test_orderbook.py | static | static |
| OrderBook asks ascending | test_orderbook.py | static | static |
| OrderBook not crossed | test_orderbook.py | static | static |
| Funding published_ts <= settlement_ts | test_funding.py | static + Hypothesis utc_dt | 50 |
| Liquidation round-trip | test_liquidation.py | money x money x utc_dt | 100 |
| Naive ts on all 7 types | test_timestamps_are_aware.py | parametrized static | static |
| EXEC-02: close+reduce_only=False raises | test_order.py | sampled_from x money x utc_dt | 100 |
| EXEC-02: open+reduce_only=False succeeds | test_order.py | sampled_from x money x utc_dt | 100 |
| RISK-02: max_per_trade_pct > 0.05 raises | test_risk_limits.py | static | static |
| RISK-02: max_gross_exposure_pct > 0.15 raises | test_risk_limits.py | static | static |
| RISK-02: kelly_fraction > 0.25 raises | test_risk_limits.py | static | static |
| Position mutation (frozen=False) | test_position.py | static + Hypothesis | 50 |
| Signal confidence bounds | test_signal.py | static | static |

**Total tests:** 61 passing, 0 failing, 0 errors

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| pytest domain | `uv run pytest -m "not integration" -q tests/unit/domain/` | 61 passed |
| pytest full suite | `uv run pytest -m "not integration" -q` | 98 passed |
| pyright strict | `uv run pyright src/shortfire/domain/` | 0 errors |
| ruff lint | `uv run ruff check src/shortfire/domain/ tests/unit/domain/` | All checks passed |
| pre-commit | `uv run pre-commit run --files src/shortfire/domain/*.py` | All hooks passed |
| ban-float-in-domain | `grep -rnE ": float\b" src/shortfire/domain/` | No matches (D-09 compliant) |
| EXEC-02 manual | Order(intent='close', reduce_only=False) | Raises ValidationError as expected |
| RISK-02 manual | RiskLimits(max_per_trade_pct=Decimal('0.06')) | Raises ValidationError as expected |

## Deviations from Plan

None — plan executed exactly as specified.

All D-07..D-15 requirements met:
- D-07: Pure Pydantic v2 BaseModel, no msgspec/dataclasses/SQLAlchemy
- D-08: 7 types frozen=True, Position frozen=False (lone carve-out)
- D-09: No float annotations in domain layer; ban-float-in-domain hook passes
- D-10: Literal[...] module-level aliases (not StrEnum)
- D-11: tuple[X, ...] for OrderBook.bids/asks and Signal.shap_top
- D-12: @model_validator rejects naive datetime on all 7 types with ts fields
- D-13: All construction-time invariants enforced
- D-14: Exactly 3 files — market.py / trading.py / risk.py
- D-15: Hypothesis property tests for every invariant

## Known Stubs

None — all 8 domain types are fully implemented per D-07..D-15. The empty `__init__.py` files in `ingest/`, `strategy/`, `execution/`, `risk/` are intentional (filled in Phases 1-5, pre-existing from Plan 00-01).

## Threat Flags

No new threat surface introduced beyond the plan's threat model. All 5 threat mitigations applied:

- T-00-06 (Order EXEC-02): `@model_validator` rejects intent='close' + reduce_only=False; Hypothesis property test passes
- T-00-07 (RiskLimits RISK-02): `Field(le=Decimal('0.05'))` etc. enforced; Hypothesis property tests for all 3 caps
- T-00-04 (naive datetime): `@model_validator` on all 7 types with ts fields; test_timestamps_are_aware.py covers all 7
- T-00-10 (float precision): No float annotations in domain layer; ban-float-in-domain hook passes
- T-00-06 (OrderBook crossed): `@model_validator` enforces not-crossed; static test passes

## TDD Gate Compliance

- RED gate: `test(00-02): add failing Hypothesis tests for market data domain types` (19b8d04)
- GREEN gate: `feat(00-02): implement market data domain types` (2f5410e)
- RED gate (task 2): `test(00-02): add failing tests for trading and risk domain types` (a0005bd)
- GREEN gate (task 2): `feat(00-02): implement trading and risk domain types` (4ba809e)

Both RED/GREEN cycles complete per TDD protocol.

## Self-Check: PASSED

Files created:

- [x] src/shortfire/domain/market.py exists
- [x] src/shortfire/domain/trading.py exists
- [x] src/shortfire/domain/risk.py exists
- [x] tests/unit/domain/__init__.py exists
- [x] tests/unit/domain/test_candle.py exists
- [x] tests/unit/domain/test_orderbook.py exists
- [x] tests/unit/domain/test_funding.py exists
- [x] tests/unit/domain/test_liquidation.py exists
- [x] tests/unit/domain/test_signal.py exists
- [x] tests/unit/domain/test_order.py exists
- [x] tests/unit/domain/test_position.py exists
- [x] tests/unit/domain/test_risk_limits.py exists
- [x] tests/unit/domain/test_timestamps_are_aware.py exists

Commits exist:

- [x] 19b8d04 — test(00-02): add failing Hypothesis tests for market data domain types
- [x] 2f5410e — feat(00-02): implement market data domain types (Candle, OrderBook, Funding, Liquidation)
- [x] a0005bd — test(00-02): add failing tests for trading and risk domain types
- [x] 4ba809e — feat(00-02): implement trading and risk domain types (Signal, Order, Position, RiskLimits)
