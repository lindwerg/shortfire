---
phase: 1
plan: 02
subsystem: observability-settings
tags:
  - observability
  - prometheus
  - telegram
  - settings
  - events
dependency_graph:
  requires:
    - "00-foundation Phase 0 observability primitives (EVENTS frozenset, REGISTRY, DataPlatformSettings)"
  provides:
    - "29-entry EVENTS frozenset (D-85) consumable by all Phase 1 ingest/scheduler/backup modules"
    - "8 DataPlatformMetrics families on shared REGISTRY (D-84)"
    - "send_telegram_alert raw-httpx function (D-86)"
    - "TelegramSettings + R2BackupSettings nested blocks on DataPlatformSettings (D-83)"
  affects:
    - "All Phase 1 plans that emit events: they can now call assert_event_registered without raising"
    - "src/shortfire/ingest/* — metrics_data_platform module available for counter/gauge updates"
tech_stack:
  added:
    - "respx>=0.23 (test dep — already in pyproject.toml, now exercised in Telegram tests)"
  patterns:
    - "Module-level NamedTuple cache pattern for idempotent Prometheus metric registration"
    - "Graceful-None-degradation + exception-swallow pattern for optional alerting channels"
key_files:
  created:
    - "src/shortfire/observability/metrics_data_platform.py"
    - "src/shortfire/observability/telegram.py"
    - "tests/unit/observability/test_events_phase1_extensions.py"
    - "tests/unit/observability/test_data_platform_metrics.py"
    - "tests/unit/observability/test_telegram_client.py"
    - "tests/unit/settings/test_data_platform_phase1_blocks.py"
  modified:
    - "src/shortfire/observability/events.py (EVENTS 12 → 29)"
    - "src/shortfire/settings/data_platform.py (+TelegramSettings, +R2BackupSettings, safe_summary)"
    - "tests/unit/observability/test_event_taxonomy.py (Phase 0 count assertions updated)"
decisions:
  - "len(EVENTS) confirmed == 29 at execution time (12 Phase 0 + 17 Phase 1 per D-85)"
  - "respx url__regex=r'https://api\\.telegram\\.org/bot.+/sendMessage' pattern worked correctly — no special handling needed"
  - "LATENCY_BUCKETS imported directly from shortfire.observability.metrics on same line as REGISTRY (combined import) — no re-declaration required"
  - "prometheus_client Counter._name strips _total suffix; _original_name preserves it — tests use _original_name for Counters with pyright:ignore[reportPrivateUsage] comments"
metrics:
  duration: "~35 minutes"
  completed: "2026-05-21T17:42:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 6
  files_modified: 3
  tests_added: 38
  tests_baseline: 241
  tests_final: 279
---

# Phase 1 Plan 02: Observability + Settings Extensions Summary

**One-liner:** EVENTS frozenset расширен до 29 записей (D-85), 8 семейств Prometheus-метрик зарегистрированы на существующем REGISTRY (D-84), raw-httpx Telegram-клиент с graceful-None-деградацией и swallow-исключений (D-86), TelegramSettings + R2BackupSettings добавлены в DataPlatformSettings без нарушения D-16 anti-leak инварианта.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 RED | Phase 1 EVENTS + DataPlatformMetrics tests | 86ca60e | test_events_phase1_extensions.py, test_data_platform_metrics.py |
| 1 GREEN | Extend EVENTS + create metrics_data_platform.py | 51232da | events.py, metrics_data_platform.py, test_event_taxonomy.py |
| 2 RED | Telegram client + Settings blocks tests | c7e32e6 | test_telegram_client.py, test_data_platform_phase1_blocks.py |
| 2 GREEN | telegram.py + data_platform.py extensions | a0ba35a | telegram.py, data_platform.py, test_telegram_client.py, test_data_platform_phase1_blocks.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated Phase 0 test_event_taxonomy.py after EVENTS extension**
- **Found during:** Task 1 GREEN phase
- **Issue:** `test_events_has_exactly_12_strings` и `test_events_matches_ui_spec_taxonomy_exactly` жёстко проверяли `len(EVENTS) == 12` и точное совпадение с 12-элементным frozenset. После расширения EVENTS до 29 записей эти тесты неизбежно сломались бы.
- **Fix:** Переименовал тесты в `test_events_has_at_least_12_strings` (проверяет `>= 12`) и `test_events_contains_all_phase0_names` (проверяет подмножество — backward compat). Семантика тестов улучшена: Phase 0 тесты теперь корректно проверяют backward compatibility, а не точный размер.
- **Files modified:** `tests/unit/observability/test_event_taxonomy.py`
- **Commit:** 51232da

**2. [Rule 1 - Bug] respx.models.Request → httpx.Request в test_telegram_client.py**
- **Found during:** Task 2 GREEN phase — первый запуск тестов
- **Issue:** `respx.models.Request` не существует в respx 0.23+. Правильный тип callback-параметра — `httpx.Request`.
- **Fix:** Заменил тип на `httpx.Request`, добавил `import httpx`.
- **Files modified:** `tests/unit/observability/test_telegram_client.py`
- **Commit:** a0ba35a

**3. [Rule 1 - Bug] prometheus_client Counter._name vs _original_name**
- **Found during:** Task 1 GREEN phase — test_prometheus_metric_names падал
- **Issue:** `prometheus_client` Counter при регистрации с именем `shortfire_data_platform_ingest_rows_total` хранит `_name = "shortfire_data_platform_ingest_rows"` (без `_total`). Только `_original_name` содержит полное имя.
- **Fix:** Тест обновлён для использования `_original_name` для Counter и `_name` для Histogram/Gauge. Добавлены `# pyright: ignore[reportPrivateUsage]` комментарии — prometheus_client не предоставляет публичный API для интроспекции имён метрик.
- **Files modified:** `tests/unit/observability/test_data_platform_metrics.py`
- **Commit:** 51232da

## Output Notes (from PLAN.md `<output>` section)

1. **`len(EVENTS) == 29` подтверждён** — smoke test `uv run python -c "assert len(EVENTS) == 29; print('events ok')"` прошёл успешно.

2. **respx wildcard pattern** — `url__regex=r"https://api\.telegram\.org/bot.+/sendMessage"` сработал корректно без каких-либо адаптаций. respx 0.23 поддерживает `url__regex` keyword argument напрямую в `mock.post(...)`.

3. **LATENCY_BUCKETS из Phase 0 metrics.py** — импортируется напрямую единственной строкой: `from shortfire.observability.metrics import LATENCY_BUCKETS, REGISTRY`. Re-declaration не потребовалась.

## Threat Surface Scan

Новые security-relevant поверхности:

| Flag | File | Description |
|------|------|-------------|
| threat_flag: outbound_http | src/shortfire/observability/telegram.py | POST к `api.telegram.org` с bot_token в URL. Mitigation применена: URL не логируется, `log.error(..., exc_info=e)` пишет только тип исключения. Соответствует T-1-INF-03 из threat_model плана. |

## Known Stubs

None — все поля реализованы, нет placeholder-значений. `telegram: TelegramSettings | None = None` и `r2_backup: R2BackupSettings | None = None` — намеренные дефолты, не stubs (поведение graceful-skip полностью реализовано).

## Self-Check: PASSED

All 6 created files confirmed present on disk.
All 4 task commits (86ca60e, 51232da, c7e32e6, a0ba35a) confirmed in git log.
279 unit tests pass (241 Phase 0 baseline + 38 new Phase 1 tests).
pyright 0 errors on src/shortfire/observability + src/shortfire/settings.
ruff 0 errors on all modified/created source files.
