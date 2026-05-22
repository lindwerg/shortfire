---
status: partial
phase: 01-data-platform
source: [01-VERIFICATION.md]
started: 2026-05-22T11:00:00Z
updated: 2026-05-22T11:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. W5 Mandatory Gate — production ≥1-year backfill
expected: |
  `raw_mexc_candles_1m` ≥ 89.4M строк
  `raw_mexc_candles_1d` ≥ 62K
  `raw_mexc_funding` ≥ 186K
  `raw_mexc_oi` ≥ 1.49M
  `universe_snapshots` ≥ 200
  All sources represented (mexc_native, coinglass_aggregate, coingecko)
  Zero duplicates on re-run (ON CONFLICT DO NOTHING)
  Row-count table pasted into 01-11-SUMMARY.md
result: [pending]
why_human: API keys + 8-12h wall clock; depends on real exchange data

### 2. Railway 3-service live + freshness gauges with real data
expected: |
  data-platform/strategy-engine/dashboard /health 200 (already verified by orchestrator)
  After running, /metrics shortfire_data_platform_source_freshness_seconds shows real symbol values
  No freshness.degraded warnings in Grafana for first 24h
result: [pending — partial; orchestrator confirmed 200×3, scheduler n_jobs=11, but no real ingest rows yet without API keys]
why_human: Requires live ingest with real API keys

### 3. Telegram stale-data alert end-to-end
expected: |
  Telegram bot delivers a real message to operator chat when freshness gauge crosses 2× expected lag threshold
  Message format matches D-87 severity routing
result: [pending]
why_human: Requires TELEGRAM__BOT_TOKEN + TELEGRAM__OPERATOR_CHAT_ID in Railway data-platform service

### 4. STOR-10 restore drill — real R2 + pg_dump round-trip
expected: |
  Daily pg_dump → R2 bucket succeeds
  Restore from R2 dump on a fresh local TimescaleDB container per docs/RESTORE.md
  All hypertables and continuous aggregates restored intact
result: [pending]
why_human: Requires real R2 credentials + manual restore validation

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

(none yet — all 4 items are pending operator action, not technical gaps)
