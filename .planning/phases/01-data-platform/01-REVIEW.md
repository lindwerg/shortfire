---
phase: 01-data-platform
reviewed: 2026-05-22T00:00:00Z
depth: standard
files_reviewed: 69
files_reviewed_list:
  - alembic/versions/0003_raw_mexc_candles_1m_1d.py
  - alembic/versions/0004_raw_mexc_funding.py
  - alembic/versions/0005_raw_mexc_oi.py
  - alembic/versions/0006_raw_mexc_trades.py
  - alembic/versions/0007_raw_mexc_l2_top20.py
  - alembic/versions/0008_raw_mexc_liquidations.py
  - alembic/versions/0009_raw_coinglass.py
  - alembic/versions/0010_raw_coingecko_market.py
  - alembic/versions/0011_universe_snapshots.py
  - alembic/versions/0012_symbols_lookup.py
  - alembic/versions/0013_dead_letter_and_ingest_runs.py
  - alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py
  - src/shortfire/clients/coingecko.py
  - src/shortfire/db/models/__init__.py
  - src/shortfire/db/models/dead_letter.py
  - src/shortfire/db/models/ingest_runs.py
  - src/shortfire/db/models/symbols.py
  - src/shortfire/db/timescale.py
  - src/shortfire/domain/market.py
  - src/shortfire/entrypoints/data_platform.py
  - src/shortfire/ingest/backup/__init__.py
  - src/shortfire/ingest/backup/pg_dump_r2.py
  - src/shortfire/ingest/base.py
  - src/shortfire/ingest/coingecko/__init__.py
  - src/shortfire/ingest/coingecko/client.py
  - src/shortfire/ingest/coingecko/schemas.py
  - src/shortfire/ingest/coingecko/universe.py
  - src/shortfire/ingest/coinglass/__init__.py
  - src/shortfire/ingest/coinglass/client.py
  - src/shortfire/ingest/coinglass/funding_agg.py
  - src/shortfire/ingest/coinglass/liq.py
  - src/shortfire/ingest/coinglass/lsr.py
  - src/shortfire/ingest/coinglass/oi.py
  - src/shortfire/ingest/coinglass/schemas.py
  - src/shortfire/ingest/context.py
  - src/shortfire/ingest/dead_letter/__init__.py
  - src/shortfire/ingest/dead_letter/alerter.py
  - src/shortfire/ingest/dead_letter/writer.py
  - src/shortfire/ingest/freshness/__init__.py
  - src/shortfire/ingest/freshness/alerter.py
  - src/shortfire/ingest/freshness/gauges.py
  - src/shortfire/ingest/gap.py
  - src/shortfire/ingest/mexc/__init__.py
  - src/shortfire/ingest/mexc/backfill.py
  - src/shortfire/ingest/mexc/client.py
  - src/shortfire/ingest/mexc/funding.py
  - src/shortfire/ingest/mexc/liquidations.py
  - src/shortfire/ingest/mexc/live_candles.py
  - src/shortfire/ingest/mexc/oi.py
  - src/shortfire/ingest/mexc/orderbook.py
  - src/shortfire/ingest/mexc/schemas.py
  - src/shortfire/ingest/mexc/streams.py
  - src/shortfire/ingest/mexc/trades.py
  - src/shortfire/ingest/rate_limit.py
  - src/shortfire/ingest/retry.py
  - src/shortfire/ingest/scheduler/__init__.py
  - src/shortfire/ingest/scheduler/bootstrap.py
  - src/shortfire/ingest/scheduler/jobs.py
  - src/shortfire/ingest/state/__init__.py
  - src/shortfire/ingest/state/kv_state.py
  - src/shortfire/ingest/storage/__init__.py
  - src/shortfire/ingest/storage/copy.py
  - src/shortfire/ingest/universe/__init__.py
  - src/shortfire/ingest/universe/snapshot.py
  - src/shortfire/ingest/universe/tier1.py
  - src/shortfire/observability/events.py
  - src/shortfire/observability/metrics_data_platform.py
  - src/shortfire/observability/telegram.py
  - src/shortfire/settings/data_platform.py
  - Dockerfile
  - pyproject.toml
findings:
  critical: 5
  warning: 8
  info: 4
  total: 17
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-05-22T00:00:00Z
**Depth:** standard
**Files Reviewed:** 69
**Status:** issues_found

## Summary

Ревью охватывает полный data-platform стек Phase 1: 12 Alembic-миграций, слой ingest (MEXC ws + REST, Coinglass, CoinGecko), слой хранилища (asyncpg COPY staging), APScheduler job graph, Prometheus-метрики, Telegram-алерты, R2-бэкап и settings. Безопасность антиутечки D-16 реализована корректно. SecretStr-дисциплина (D-21) выдержана: `safe_summary()` не раскрывает значений. D-27 (TimescaleDB DDL через хелперы) соблюдён — исключение для `DROP MATERIALIZED VIEW` в downgrade migration 0014 допустимо по carve-out.

Ключевые проблемы: SQLi-уязвимость высокого уровня в `db/timescale.py` из-за f-строк без экранирования; потеря данных в staging-паттерне `copy.py` при конкурентном выполнении; блокировка event loop в `pg_dump_r2.py`; гонка состояний в `freshness/alerter.py` через модульный изменяемый `_degraded_set`; недостижимый код в `streams.py` после `yield`.

---

## Critical Issues

### CR-01: SQL Injection через f-строки в `db/timescale.py` (все хелперы)

**File:** `src/shortfire/db/timescale.py:41-98`
**Issue:** Все функции (`create_hypertable`, `enable_compression`, `add_compression_policy`, `create_continuous_aggregate`, `add_retention_policy`) интерполируют аргументы `table`, `time_column`, `segment_by`, `order_by`, `chunk_interval` и т.д. прямо в f-строки, переданные в `text(...)`. Это создаёт SQL-инъекцию: любой вызывающий, передав строку вида `raw_mexc_candles_1m'); DROP TABLE symbols;--`, получит выполнение произвольного SQL.

Документация заявляет «Callers MUST pass hardcoded constants», но это соглашение, а не техническое ограничение. Pyright strict не гарантирует, что строковое значение не содержит специальных символов — он проверяет только тип `str`, а не содержимое. Реальный вектор атаки: любой путь кода (включая тесты с `@pytest.mark.parametrize`) может передать произвольную строку.

Аргументы, которые представляют SQL-идентификаторы (`table`, `time_column`, `segment_by`), должны быть экранированы через `sqlalchemy.sql.quoted_name` или белый список.

**Fix:**
```python
from sqlalchemy.sql.elements import quoted_name

def create_hypertable(
    table: str,
    time_column: str = "ts",
    chunk_interval: str = "7 days",
    if_not_exists: bool = True,
) -> None:
    # Whitelist validation for identifiers
    _validate_identifier(table)
    _validate_identifier(time_column)
    # chunk_interval is an interval string — validate against known set or regex
    _validate_interval(chunk_interval)
    op.execute(
        text("""
        SELECT create_hypertable(
            :table_name,
            :time_col,
            chunk_time_interval => :interval::INTERVAL,
            if_not_exists => :if_not_exists
        )
        """),
        {
            "table_name": table,
            "time_col": time_column,
            "interval": chunk_interval,
            "if_not_exists": if_not_exists,
        },
    )

_SAFE_IDENT = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,63}$')

def _validate_identifier(name: str) -> None:
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
```

Примечание: `create_hypertable` принимает имя таблицы как `regclass` через первый аргумент функции — его можно передать как параметр в `text()`. `segment_by` и `order_by` в `ALTER TABLE ... SET (...)` требуют идентификатора в DDL-контексте, где параметризация невозможна — для них нужна whitelist-валидация.

---

### CR-02: Потеря данных и взаимоблокировка в staging-паттерне `copy_into_hypertable`

**File:** `src/shortfire/ingest/storage/copy.py:79-99`
**Issue:** Три SQL-оператора объединены в одну строку через точку с запятой в одном вызове `raw_conn.execute()`:
```python
await raw_conn.execute(
    f"CREATE UNLOGGED TABLE IF NOT EXISTS {staging}"
    f" (LIKE {target_table} INCLUDING DEFAULTS);"
    f" TRUNCATE TABLE {staging};"
)
```
asyncpg по умолчанию разбивает батч-запросы (`execute` с `;`) на атомарные операции, но это поведение не гарантировано и зависит от версии драйвера. Если `TRUNCATE` не будет выполнен (driver-specific behaviour), следующий вызов на том же PID-staging-таблице вставит старые данные повторно.

Дополнительно: хотя PID-шардинг снижает вероятность гонки, `UNLOGGED TABLE IF NOT EXISTS` + `TRUNCATE` не атомарны даже при PID-шардинге: если один и тот же PID используется повторно (connection pool recycling), staging-таблица уже содержит данные с прошлого цикла. `TRUNCATE` должен выполняться в отдельном операторе после `CREATE`, а не через `;`-цепочку.

**Fix:**
```python
# Separate DDL and DML into two explicit execute calls:
await raw_conn.execute(
    f"CREATE UNLOGGED TABLE IF NOT EXISTS {staging}"
    f" (LIKE {target_table} INCLUDING DEFAULTS)"
)
await raw_conn.execute(f"TRUNCATE TABLE {staging}")
```

---

### CR-03: Блокировка event loop через синхронный `subprocess.Popen` + `s3.upload_fileobj` в `pg_dump_r2.py`

**File:** `src/shortfire/ingest/backup/pg_dump_r2.py:136-143`
**Issue:** `daily_pg_dump_to_r2` является `async` функцией, вызываемой из APScheduler. Внутри неё `subprocess.Popen` + `s3.upload_fileobj` (синхронный boto3) + `proc.wait(timeout=3600)` выполняются в event loop без `await asyncio.to_thread(...)` или `loop.run_in_executor(...)`. Это блокирует event loop на всё время pg_dump (потенциально несколько минут для продакшн-базы).

Комментарий `# noqa: ASYNC220` это признаёт, но не исправляет: он лишь отключает lint-предупреждение. В production с >100GB базой pg_dump займёт 10–30 минут, полностью блокируя MEXC ws-streams и все другие jobs в процессе.

**Fix:**
```python
import asyncio

async def daily_pg_dump_to_r2(settings=None):
    ...
    # Run the blocking pg_dump + S3 upload in a thread
    await asyncio.to_thread(_run_pg_dump_sync, cmd, env, settings, key)
    ...

def _run_pg_dump_sync(cmd, env, settings, key):
    """Synchronous wrapper: pg_dump → S3 upload. Safe to call from asyncio.to_thread."""
    s3 = _build_r2_client(settings)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        s3.upload_fileobj(proc.stdout, settings.r2_backup.bucket_name, key)
        ret = proc.wait(timeout=3600)
        if ret != 0:
            err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"pg_dump exit code {ret}: {err[:2000]}")
    finally:
        if proc.poll() is None:
            proc.kill()
```

---

### CR-04: Мутируемый модульный `_degraded_set` создаёт гонку состояний при конкурентном выполнении и утечку между тестами

**File:** `src/shortfire/ingest/freshness/alerter.py:49`
**Issue:** `_degraded_set: set[tuple[str, str, str]] = set()` является модульным состоянием. Функция `freshness_check_job` модифицирует его через `.clear()` и `.update()` в конце каждого запуска. Это создаёт несколько проблем:

1. **Гонка при конкурентном вызове**: APScheduler запускает `freshness_check_job` каждую минуту. Если предыдущий вызов ещё не завершился (slow Prometheus collection), а новый начался, обе корутины читают и пишут `_degraded_set` в разных точках выполнения. Python `asyncio` однопоточен, но операция `_degraded_set.clear()` + `_degraded_set.update()` занимает несколько инструкций — если между ними произойдёт `await`, состояние будет повреждено.

2. **Утечка между тестами**: модульная переменная не сбрасывается между тестами, что делает тесты, проверяющие `freshness.recovered`, зависимыми от порядка выполнения.

3. **Бесконечное накопление**: при отсутствии метрик для ранее виденных источников `_degraded_set` никогда не очищается от них.

**Fix:**
```python
# Использовать локальную переменную, передаваемую явно, или инкапсулировать
# в объект с явным жизненным циклом. Минимальный fix — атомарное обновление:
previous = frozenset(_degraded_set)
_degraded_set.clear()
_degraded_set.update(currently_degraded)
recovered = previous - currently_degraded
```
Для изоляции тестов — экспортировать `reset_degraded_set()` helper или преобразовать в класс с явным состоянием.

---

### CR-05: Недостижимый код после `yield` в `mexc_ws_streams` — watchdog tasks никогда не получат `shutdown_event.set()`

**File:** `src/shortfire/ingest/mexc/streams.py:248-252`
**Issue:**
```python
async with asyncio.TaskGroup() as tg:
    ...
    yield           # line 249
    shutdown_event.set()   # line 252 — NEVER reached
```

`TaskGroup.__aexit__` блокируется до завершения всех задач. После `yield` управление передаётся в тело блока `async with mexc_ws_streams(...)` в `data_platform.py` и остаётся там, пока lifespan не завершится. Когда lifespan завершается, `__aexit__` `asynccontextmanager` вызывает `throw(GeneratorExit)` или продолжает через `send(None)`, что поднимает управление обратно в `streams.py` за `yield`. Но `asyncio.TaskGroup` в этот момент ждёт завершения всех задач — ни одна из них не завершится, пока не будет установлен `shutdown_event`. Это создаёт взаимоблокировку при graceful shutdown: `shutdown_event.set()` никогда не достигается, потому что управление застряло в `TaskGroup.__aexit__`.

На практике это означает, что watchdog и divergence-check корутины никогда не получают сигнал на остановку — их убивает только отмена TaskGroup при exception propagation.

**Fix:** Установить `shutdown_event` ДО передачи управления вызывающему:
```python
async with asyncio.TaskGroup() as tg:
    ...
    # Register cleanup before yielding
    try:
        yield
    finally:
        shutdown_event.set()
```
Или переключить watchdog-задачи на проверку `asyncio.CancelledError` вместо `shutdown_event`.

---

## Warnings

### WR-01: `open_interest` может быть NULL в колонке `NOT NULL` `raw_coinglass_oi`

**File:** `src/shortfire/ingest/coinglass/schemas.py:101-116`
**Issue:** `OpenInterestHistoryRow.open_interest_usd: Decimal | None = None` и `to_records()` возвращает `row.open_interest_usd` без подстановки нулевого значения. В миграции 0009 колонка `open_interest` объявлена `nullable=False`. При попытке вставить `None` asyncpg выбросит `NotNullViolationError`, который попадёт в dead_letter, но данные за этот период будут потеряны без явного сигнала.

Аналогичная проблема в `raw_coinglass_liq.liquidation_usd` — тоже `nullable=False` в миграции, тогда как `LiquidationCoinHistoryRow.liquidation_long_usd/short_usd` оба `Decimal | None`.

**Fix:** В `to_records()` заменить `None` на `Decimal("0")`:
```python
row.open_interest_usd or Decimal("0"),
```
Или объявить колонки в миграции как `nullable=True`, если `None` семантически допустим.

---

### WR-02: `CoinglassClient._call()` может вернуть `None` с проглоченной ошибкой при `params.get()` на `None`

**File:** `src/shortfire/ingest/coinglass/client.py:94`
**Issue:**
```python
symbol: str | None = params.get("symbol") if params else None
```
Это корректно защищает от `params is None`. Однако блок выше:
```python
if r.status_code in _RETRY_STATUS_CODES:
    r.raise_for_status()
```
При статусе 429 `raise_for_status()` генерирует `httpx.HTTPStatusError`. `@coinglass_retry` ловит `httpx.HTTPStatusError` и повторяет. После 5 попыток `reraise=True` передаёт исключение дальше. Проблема: вызывающий (например, `coinglass_funding_agg_job_callable`) не оборачивает `await client.fetch_funding_rate_list()` в `try/except`. После исчерпания попыток необработанное `httpx.HTTPStatusError` поднимается до APScheduler, который его логирует, но не предпринимает специфичных действий. Это ожидаемое поведение — но оно не задокументировано как контракт. Потенциальный риск — неожиданная остановка всего job при 429-шторме.

**Fix:** Задокументировать, что job callables в `jobs.py` не должны оборачивать вызовы в try/except, так как APScheduler 4.x обрабатывает исключения. Или добавить `except Exception` в job callables с явным логированием, чтобы job не вылетал при исчерпании retries.

---

### WR-03: `universe_snapshot_job` использует `date.today()` — timezone-aware timestamp-несоответствие

**File:** `src/shortfire/ingest/universe/snapshot.py:112`
**Issue:**
```python
snapshot_date = date.today()
```
`date.today()` возвращает локальную дату Railway-контейнера. Если часовой пояс контейнера не UTC, дата может быть на день смещена от реального UTC. Вся остальная кодовая база использует `datetime.now(UTC)` — это исключение нарушает D-65.

**Fix:**
```python
from datetime import UTC, datetime
snapshot_date = datetime.now(UTC).date()
```

---

### WR-04: `_sundown_sweep` не пагинирует результаты `list_objects_v2` — потери при > 1000 объектов

**File:** `src/shortfire/ingest/backup/pg_dump_r2.py:203-211`
**Issue:** `s3.list_objects_v2(Bucket=bucket, Prefix=prefix)` без параметра `MaxKeys` возвращает максимум 1000 объектов по S3-спецификации. Если в бакете накопилось > 1000 объектов в одном prefix (теоретически возможно через несколько лет), `_list_sorted_desc` вернёт только первую страницу. Retention sweep будет работать с неполным списком и может не удалить старые объекты.

**Fix:**
```python
def _list_sorted_desc(prefix: str) -> list[dict]:
    paginator = s3.get_paginator("list_objects_v2")
    all_objs = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        all_objs.extend(page.get("Contents", []))
    return sorted(all_objs, key=lambda o: o["Key"], reverse=True)
```

---

### WR-05: `mexc_retry` не перехватывает `ccxt.NetworkError` / `ccxt.ExchangeNotAvailable`

**File:** `src/shortfire/ingest/retry.py:51-57`
**Issue:**
```python
mexc_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError, TimeoutError)),
    ...
)
```
ccxt-исключения (`ccxt.NetworkError`, `ccxt.ExchangeNotAvailable`, `ccxt.RateLimitExceeded`) НЕ являются подклассами `httpx.*`. Они происходят от базового `ccxt.BaseError`. Когда ccxt бросает `ccxt.NetworkError` в `fetch_ohlcv`, tenacity не перехватит его, и исключение пойдёт напрямую в dead_letter (что по дизайну). Однако `ccxt.RateLimitExceeded` без retry создаёт риск потери всех последующих запросов. Комментарий в коде не упоминает эту ситуацию.

**Fix:** Либо добавить `ccxt.NetworkError` в список retry-исключений, либо явно задокументировать, что ccxt-исключения намеренно не ретраятся через tenacity (потому что ccxt имеет собственный rate-limit handle через `enableRateLimit=True`).

---

### WR-06: Двойное потребление `watch_trades_for_symbols` в двух TaskGroup-задачах создаёт невидимую зависимость от ccxt internal cache

**File:** `src/shortfire/ingest/mexc/streams.py:213-224`
**Issue:** Как задокументировано в `trades.py`, и `trades_aggregator_loop` и `trades_persist_loop` вызывают `raw.watch_trades_for_symbols(symbols)` на одном и том же ccxt.pro клиенте. Это работает только потому, что ccxt Pro кэширует ws-сообщения и отдаёт одни и те же данные обоим потребителям. Это недокументированное внутреннее поведение ccxt, которое может измениться между версиями `>=4.5.54,<4.6`.

Нет тестов, которые бы верифицировали это поведение. Если ccxt изменит логику кэширования, одна из двух задач начнёт получать неполный поток без каких-либо ошибок.

**Fix:** Задокументировать предположение о ccxt внутреннем кэше в `CONSTRAINTS.md` и добавить интеграционный тест с mock-ccxt, проверяющий, что оба потребителя получают одинаковое количество событий.

---

### WR-07: `ingest_runs` ORM-модель пропускает `ingested_at` в `kv_state.py` INSERT

**File:** `src/shortfire/ingest/state/kv_state.py:88-104`
**Issue:** В `save_kv_state` SQL-запрос не включает `ingested_at`:
```sql
INSERT INTO ingest_runs
    (id, ts, source, dataset, job_id, started_at, finished_at,
     status, rows_written, kv_state, quality_flag)
VALUES ...
```
Но в миграции 0013 `ingested_at` имеет `server_default=sa.func.now()` — INSERT должен работать. Тем не менее ORM-модель `IngestRun` объявляет `ingested_at: Mapped[datetime]` как `nullable=False` без `default`. Если код когда-либо создаст экземпляр `IngestRun()` напрямую и попытается его сохранить, он получит validation error. Несоответствие между raw SQL и ORM создаёт ложное ощущение безопасности.

**Fix:** Добавить `server_default` или `default=func.now()` в ORM-модель:
```python
ingested_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), nullable=False, server_default=func.now()
)
```

---

### WR-08: `Telegram.send_telegram_alert` создаёт новый `httpx.AsyncClient` при каждом вызове — нарушение D-50

**File:** `src/shortfire/observability/telegram.py:75`
**Issue:**
```python
async with httpx.AsyncClient(timeout=10.0) as client:
    r = await client.post(...)
```
Telegram-алерты отправляются каждые 1–5 минут (freshness.check + dead_letter.alert). Каждый вызов открывает и закрывает TCP+TLS соединение. D-50 требует ONE `httpx.AsyncClient` per process. Хотя Telegram — не основной источник данных (не Coinglass/CoinGecko), частое создание клиентов противоречит тому же принципу и создаёт дополнительную latency.

**Fix:** Использовать модульный singleton:
```python
_telegram_client: httpx.AsyncClient | None = None

def _get_telegram_client() -> httpx.AsyncClient:
    global _telegram_client
    if _telegram_client is None:
        _telegram_client = httpx.AsyncClient(timeout=10.0)
    return _telegram_client
```

---

## Info

### IN-01: `FundingRateListRow.to_record()` возвращает `None` для `ts` — нарушение ожидаемого контракта схемы

**File:** `src/shortfire/ingest/coinglass/schemas.py:49-56`
**Issue:** `to_record()` возвращает кортеж `(symbol, None, funding_rate, source, quality_flag)` с явным `None` для `ts`. Вызывающий `funding_agg.fetch_and_write` никогда не использует этот метод — он вручную конструирует записи с `ts_now`. Метод `to_record()` существует в схеме, но не используется в production-коде. Это мёртвый код, потенциально создающий замешательство для следующего разработчика.

**Fix:** Удалить `FundingRateListRow.to_record()` или переименовать/задокументировать как deprecated.

---

### IN-02: `db/timescale.py` — `create_continuous_aggregate` строит `group_by` по умолчанию некорректно при нестандартном `bucket`

**File:** `src/shortfire/db/timescale.py:134-135`
**Issue:**
```python
if group_by is None:
    group_by = f"symbol, time_bucket('{bucket}', ts)"
```
Если значение `bucket` содержит специальные символы (например, вызывающий передаст `"5 minutes'; DROP TABLE"` — см. CR-01), этот дефолт также будет уязвим. Это производная проблема CR-01.

**Fix:** Применить ту же whitelist-валидацию bucket-параметра, что и в CR-01.

---

### IN-03: `mexc/streams.py` — `except* RuntimeError` никогда не re-raise ExceptionGroup как RuntimeError

**File:** `src/shortfire/ingest/mexc/streams.py:254-263`
**Issue:**
```python
except* RuntimeError as eg:
    ...
    raise  # re-raise ExceptionGroup
```
`raise` здесь поднимает `ExceptionGroup`, а не `RuntimeError`. Вызывающий в `data_platform.py` не имеет явного обработчика `ExceptionGroup`. FastAPI lifespan просто получит необработанное `ExceptionGroup` и завершит процесс. Это не ошибка логики (respawn через process supervisor — правильное поведение для Railway), но комментарий «caller (FastAPI lifespan) is responsible for respawning» неточен: Railway перезапустит весь контейнер, а не только ws-streams.

**Fix:** Задокументировать явно, что respawn происходит на уровне Railway container restart, а не внутри process lifespan.

---

### IN-04: `copy_into_hypertable` возвращает `len(records_list)`, а не реальное количество вставленных строк

**File:** `src/shortfire/ingest/storage/copy.py:101`
**Issue:**
```python
return len(records_list)
```
С `ON CONFLICT DO NOTHING` реальное количество вставленных строк меньше `len(records_list)` при повторном инgesте. Все caller'ы используют возвращённое значение как `rows_written` в метриках (`ingest_rows_total.inc(n)`) и в `save_kv_state`. Метрики будут завышены при идемпотентном повторном запуске. В частности, `kv_state.py` сохраняет `rows_written=0` (захардкоженное), так что kv проблемы нет — но метрики неточны.

**Fix:** Использовать `RETURNING` или `pg_affected_rows`:
```python
result = await raw_conn.execute(
    f"INSERT INTO {target_table} ({col_list})"
    f" SELECT {col_list} FROM {staging}"
    f" ON CONFLICT ({conflict_cols}) DO NOTHING"
)
# asyncpg возвращает строку вида "INSERT 0 N"
inserted = int(result.split()[-1]) if result else 0
return inserted
```

---

_Reviewed: 2026-05-22T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
