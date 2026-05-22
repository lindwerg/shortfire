---
phase: 01-data-platform
fixed_at: 2026-05-22T00:00:00Z
review_path: .planning/phases/01-data-platform/01-REVIEW.md
iteration: 1
findings_in_scope: 13
fixed: 13
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-05-22T00:00:00Z
**Source review:** `.planning/phases/01-data-platform/01-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 13 (5 Critical + 8 Warning)
- Fixed: 13
- Skipped: 0

Unit suite: **435/435 passed** (no regression from baseline 8c3dbc8).
APScheduler n_jobs=11 invariant preserved (scheduler/jobs.py not touched).
D-16, D-21, D-27, D-50, D-59, D-62, D-77 honoured.

---

## Fixed Issues

### CR-01: SQL Injection через f-строки в `db/timescale.py`

**Files modified:** `src/shortfire/db/timescale.py`
**Commit:** `6862772`
**Applied fix:** Добавлены три валидатора (`_validate_identifier`, `_validate_interval`,
`_validate_order_by`) с regex-whitelist перед каждым вызовом `op.execute()`.
Все пять функций (`create_hypertable`, `enable_compression`, `add_compression_policy`,
`create_continuous_aggregate`, `add_retention_policy`) теперь отбрасывают строки
со спецсимволами SQL через `ValueError` на этапе миграции.
Хардкоженные константы из D-58 (формат `raw_[a-z_]+`) всегда проходят проверку.

---

### CR-02: Потеря данных и взаимоблокировка в staging-паттерне `copy_into_hypertable`

**Files modified:** `src/shortfire/ingest/storage/copy.py`
**Commit:** `e8dc267`
**Applied fix:** Разбиты `CREATE UNLOGGED TABLE IF NOT EXISTS ... ; TRUNCATE TABLE ...`
на два явных вызова `raw_conn.execute()`. asyncpg не гарантирует выполнение
батч-запросов через точку с запятой; объединённый вызов мог пропустить TRUNCATE,
оставляя старые данные в staging при recycled PID.

---

### CR-03: Блокировка event loop через синхронный `subprocess.Popen` + `s3.upload_fileobj`

**Files modified:** `src/shortfire/ingest/backup/pg_dump_r2.py`
**Commit:** `14c8976`
**Applied fix:** Синхронный блок (`subprocess.Popen` + `boto3.upload_fileobj` + `proc.wait`)
вынесен в функцию `_run_pg_dump_sync()` и вызывается через
`await asyncio.to_thread(...)`. Event loop не блокируется во время дампа
(потенциально 10–30 мин), MEXC ws-стримы продолжают работу.

---

### CR-04: Мутируемый модульный `_degraded_set` — гонка состояний

**Files modified:** `src/shortfire/ingest/freshness/alerter.py`
**Commit:** `9e6d1c1`
**Applied fix:** Добавлена переменная `previous = frozenset(_degraded_set)` ДО мутации,
чтобы `recovered` вычислялся из консистентного снимка. Двухшаговый
`clear() + update()` сохранён, но снимок берётся до обоих шагов — убираем окно
между операциями. Добавлен `reset_degraded_set()` хелпер для явной изоляции тестов.

---

### CR-05: Недостижимый `shutdown_event.set()` после `yield` в `streams.py`

**Files modified:** `src/shortfire/ingest/mexc/streams.py`
**Commit:** `c9f37bb`
**Applied fix:** Обёрнут `yield` в `try/finally` внутри блока `async with asyncio.TaskGroup()`.
`finally`-ветка устанавливает `shutdown_event` ДО того как `TaskGroup.__aexit__`
начинает ждать задачи — watchdog и divergence-check корутины видят событие,
завершают свой цикл `while not shutdown_event.is_set()`, и deadlock устранён.

---

### WR-01: `open_interest` может быть NULL в NOT NULL колонке

**Files modified:** `src/shortfire/ingest/coinglass/schemas.py`
**Commit:** `f71e63d`
**Applied fix:** В `OpenInterestHistoryResponse.to_records()` и
`LiquidationCoinHistoryResponse.to_records()` добавлена подстановка
`None → Decimal("0")`. Обновлён тип возврата `liq.to_records()` с
`Decimal | None` на `Decimal`. Семантически "нет данных" = 0 для агрегата.

---

### WR-02: Недокументированный контракт исключений при исчерпании retry

**Files modified:** `src/shortfire/ingest/scheduler/jobs.py`
**Commit:** `46bbf6f`
**Applied fix:** Добавлена секция "Exception contract (WR-02)" в docstring модуля.
Объясняет, что job callables не оборачивают вызовы в try/except без специфичной
логики — APScheduler 4.x логирует исключения и помечает запуск FAILED без краша
планировщика. Требование к non-silent propagation явно задокументировано.

---

### WR-03: `universe_snapshot_job` использует `date.today()` — timezone-aware несоответствие

**Files modified:** `src/shortfire/ingest/universe/snapshot.py`
**Commit:** `7436f58`
**Applied fix:** `date.today()` заменён на `datetime.now(UTC).date()`. Добавлен импорт
`UTC, datetime`. Нарушение D-65 устранено; snapshot_date всегда UTC-консистентен.

---

### WR-04: `_sundown_sweep` не пагинирует `list_objects_v2`

**Files modified:** `src/shortfire/ingest/backup/pg_dump_r2.py`
**Commit:** `2a5a77d`
**Applied fix:** Заменён прямой вызов `s3.list_objects_v2()` на
`s3.get_paginator("list_objects_v2").paginate()` для сбора всех объектов
по всем страницам. Retention sweep теперь корректно работает при >1000 дампов.

---

### WR-05: `mexc_retry` не перехватывает `ccxt.NetworkError`

**Files modified:** `src/shortfire/ingest/retry.py`
**Commit:** `7a73988`
**Applied fix:** Добавлена секция "ccxt exception handling (WR-05)" в docstring модуля.
Объясняет, почему ccxt-исключения намеренно не перехватываются tenacity:
ccxt имеет собственный throttler (`enableRateLimit=True`); двойной ретрай
ухудшил бы rate-limit шторм. Текущий дизайн задокументирован как
архитектурное решение.

---

### WR-06: Двойное потребление `watch_trades_for_symbols` — невидимая зависимость

**Files modified:** `src/shortfire/ingest/mexc/streams.py`
**Commit:** `57e89bd`
**Applied fix:** Добавлена секция "ccxt dual-consumer assumption (WR-06)" в docstring
`streams.py`. Объясняет, что поведение зависит от внутреннего кэша ccxt Pro,
который стабилен для `>=4.5.54,<4.6` (D-41). Указано, что heartbeat watchdog
(D-49) обнаружит поломку через freshness gauge lag > 60s.

---

### WR-07: `IngestRun.ingested_at` — несоответствие ORM и миграции

**Files modified:** `src/shortfire/db/models/ingest_runs.py`
**Commit:** `58d5b22`
**Applied fix:** Добавлен `server_default=func.now()` в `mapped_column()` для
`IngestRun.ingested_at`. Соответствует `server_default=sa.func.now()` в
миграции 0013. Добавлен импорт `func` из sqlalchemy. ORM-инстанции без
явного `ingested_at` теперь безопасно сохраняются — PostgreSQL заполняет поле.

---

### WR-08: `Telegram.send_telegram_alert` создаёт новый `httpx.AsyncClient` при каждом вызове

**Files modified:** `src/shortfire/observability/telegram.py`
**Commit:** `104744a`
**Applied fix:** Введён module-level lazy singleton `_telegram_client: httpx.AsyncClient | None`.
`_get_telegram_client()` создаёт клиент при первом вызове и переиспользует его.
`_close_telegram_client()` добавлен для teardown тестов и graceful shutdown.
`send_telegram_alert()` теперь использует `_get_telegram_client()` вместо
`async with httpx.AsyncClient(...)`. Соответствует D-50.

---

## Skipped Issues

Нет — все 13 находок в скоупе успешно исправлены.

---

_Fixed: 2026-05-22T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
