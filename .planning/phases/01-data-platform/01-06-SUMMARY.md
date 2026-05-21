---
phase: 1
plan: "06"
subsystem: ingest/coinglass
tags:
  - python
  - httpx
  - coinglass
  - ingest
  - pydantic
  - tdd
dependency_graph:
  requires:
    - "01-01"  # coinglass_retry, COINGLASS_LIMITER, copy_into_hypertable, write_to_dead_letter
    - "01-04"  # raw_coinglass_* hypertables, migration 0009
  provides:
    - "CoinglassClient (httpx, HTTP/2, D-50)"
    - "4 Pydantic v2 response schemas (D-52)"
    - "funding_agg.fetch_and_write — batch endpoint, all symbols"
    - "oi.fetch_and_write — per-symbol round-robin"
    - "liq.fetch_and_write — per-symbol, 2 rows/data-point"
    - "lsr.fetch_and_write — per-symbol long/short ratio"
    - "FakeCoinglassClient — Phase 1 canned stubs"
  affects:
    - "01-09"  # scheduler jobs will call funding_agg/oi/liq/lsr with universe mapping
tech_stack:
  added:
    - "h2==4.3.0 (HTTP/2 for httpx[http2])"
    - "hpack==4.1.0"
    - "hyperframe==6.1.0"
  patterns:
    - "respx.mock для unit/integration тестов Coinglass"
    - "freeze_time для детерминированной idempotency проверки"
    - "respx.mock(base_url=...) как контекстный менеджер с mock.<method> внутри"
key_files:
  created:
    - "src/shortfire/ingest/coinglass/__init__.py"
    - "src/shortfire/ingest/coinglass/client.py"
    - "src/shortfire/ingest/coinglass/schemas.py"
    - "src/shortfire/ingest/coinglass/funding_agg.py"
    - "src/shortfire/ingest/coinglass/oi.py"
    - "src/shortfire/ingest/coinglass/liq.py"
    - "src/shortfire/ingest/coinglass/lsr.py"
    - "tests/unit/ingest/coinglass/__init__.py"
    - "tests/unit/ingest/coinglass/test_coinglass_client.py"
    - "tests/unit/ingest/coinglass/test_coinglass_schemas.py"
    - "tests/unit/ingest/coinglass/test_coinglass_dead_letter_routing.py"
    - "tests/integration/ingest/test_coinglass.py"
  modified:
    - "tests/fakes/coinglass.py (Phase 0 stubs заменены на Phase 1 canned responses)"
    - "pyproject.toml (httpx -> httpx[http2])"
decisions:
  - "D-50 CoinglassClient использует ОДИН httpx.AsyncClient(http2=True) на весь процесс"
  - "D-52 Схемы strict=False extra='allow' — strict=True на DecimalField через Pydantic coerce"
  - "D-59 source='coinglass_aggregate' захардкожен во всех fetcher модулях"
  - "Coinglass endpoint paths подтверждены: /api/futures/funding-rate-list, /api/futures/open-interest/history, /api/futures/liquidation/coin-history, /api/futures/long-short-account-ratio"
metrics:
  duration: "~40 минут"
  completed: "2026-05-21"
  tasks_completed: 2
  tests_added: 39
  files_created: 12
  files_modified: 2
---

# Phase 1 Plan 06: CoinglassClient + 4 Endpoint Fetchers Summary

CoinglassClient (httpx HTTP/2, single AsyncClient D-50) с 4 Pydantic v2 strict
схемами (Pitfall G `extra='allow'`), rate limiter 28/min (D-51) и tenacity retry (D-72);
4 per-endpoint fetcher модуля пишут с `source='coinglass_aggregate'` через `copy_into_hypertable`.

## Задачи

### Task 1: CoinglassClient + 4 Pydantic v2 schemas + unit tests

**Коммит:** `079732d`

Реализован `CoinglassClient` с одним `httpx.AsyncClient(http2=True)` на процесс (D-50).
API ключ передаётся в заголовке `CG-API-KEY` — никогда в URL (T-1-CG-01).
Все публичные методы декорированы `@coinglass_retry` и используют `async with COINGLASS_LIMITER`.

Маршрутизация ошибок:
- 4xx (кроме 429) → `write_to_dead_letter` + возврат `None` (tenacity не ретраит)
- 429 / 5xx / TransportError → `raise_for_status()` (tenacity перехватит)
- Pydantic `ValidationError` на 200 → `write_to_dead_letter` + возврат `None`

4 схемы (все `ConfigDict(frozen=True, strict=False, extra='allow')`):
- `FundingRateListResponse` — батч-эндпоинт, массив bare-coin символов
- `OpenInterestHistoryResponse` — per-symbol история OI
- `LiquidationCoinHistoryResponse` — per-symbol ликвидации (long + short)
- `LongShortAccountRatioResponse` — per-symbol long/short ratio

`FakeCoinglassClient` расширен canned response объектами вместо Phase 0 `NotImplementedError`.

34 unit теста: конструктор, схемы, dead-letter маршрутизация — все зелёные.

### Task 2: Per-endpoint fetchers + integration test

**Коммит:** `41083f1`

4 thin-fetcher модуля:
- `funding_agg.fetch_and_write(engine, client, coinglass_to_unified)` — батч, один вызов на все символы; пропускает unmapped символы с warning (T-1-CG-06)
- `oi.fetch_and_write(engine, client, symbol_unified, coinglass_symbol)` — per-symbol history
- `liq.fetch_and_write(engine, client, symbol_unified, coinglass_symbol)` — 2 записи на data point (side='long' и side='short')
- `lsr.fetch_and_write(engine, client, symbol_unified, coinglass_symbol)` — per-symbol ratio

Все модули hardcode `source='coinglass_aggregate'` (D-59) и используют `ON CONFLICT DO NOTHING` (D-62).

5 integration тестов против testcontainer TimescaleDB:
- DATA-07 keystone: 3 строки с `source='coinglass_aggregate'`
- Idempotency: `freeze_time` → повторный запуск 0 новых строк (PK conflict)
- Unmapped symbol skipped
- OI, liquidation (2 sides), LSR — все зелёные

## Endpoint paths (Coinglass v4, подтверждено планировщиком)

| Endpoint | Path | Метод |
|----------|------|-------|
| Funding rate list | `/api/futures/funding-rate-list` | GET, batch |
| Open interest history | `/api/futures/open-interest/history` | GET, symbol+interval |
| Liquidation history | `/api/futures/liquidation/coin-history` | GET, symbol+interval |
| Long/short ratio | `/api/futures/long-short-account-ratio` | GET, symbol+interval |

**Примечание:** Endpoint paths не проверялись против live Coinglass API (нет реального ключа в dev).
Пути взяты из RESEARCH.md §4.6 + официальной документации Coinglass v4.
Если реальная проверка в paper-trading обнаружит drift — обновить в 01-09 (scheduler jobs).

## Пространство схем (wire format)

Coinglass возвращает:
- `symbol`: bare-coin строка ("BTC", не "BTC/USDT:USDT") — `funding_agg.py` маппит через `coinglass_to_unified`
- `funding_rate`: строка Decimal или null
- `time`: Unix timestamp в миллисекундах
- `open_interest_usd`, `liquidation_long_usd`, `liquidation_short_usd`, `long_short_ratio`: строки Decimal

Schema drift (Pitfall G): `extra='allow'` в каждой top-level схеме — неизвестные поля проходят без ошибок.
Если переименование затронет ОБЯЗАТЕЛЬНОЕ поле — `ValidationError` → `dead_letter`.

## Примечание о `coinglass_to_unified` mapping

`funding_agg.fetch_and_write` ожидает mapping от caller'а (plan 01-09 — universe snapshot).
Этот модуль **не строит mapping самостоятельно** — caller читает `symbols.coinglass_symbol`
из БД и передаёт dict. Это сознательное решение: fetcher stateless, mapping stateful.

## Отклонения от плана

### Автоисправленные проблемы

**1. [Rule 3 - Blocking] httpx[http2] отсутствовал в зависимостях**
- **Обнаружено при:** Task 1, первый запуск тестов
- **Проблема:** `httpx.AsyncClient(http2=True)` требует пакет `h2`, который устанавливается через `httpx[http2]`
- **Исправление:** `pyproject.toml`: `httpx>=0.28` → `httpx[http2]>=0.28`; `uv sync` установил h2==4.3.0
- **Файлы:** `pyproject.toml`, `uv.lock`
- **Коммит:** `079732d`

**2. [Rule 1 - Bug] respx.mock в тестах использован некорректно**
- **Обнаружено при:** Task 1, запуск тестов
- **Проблема:** `with respx.mock(base_url=...) as mock:` + `respx.get(...)` вне контекста → `AllMockedAssertionError`
- **Исправление:** все mock регистрации перемещены внутрь `with respx.mock() as mock:` → `mock.get(...)`
- **Файлы:** test_coinglass_client.py, test_coinglass_dead_letter_routing.py

**3. [Rule 1 - Bug] Idempotency тест в integration suite**
- **Обнаружено при:** Task 2, integration test
- **Проблема:** `ts_now = datetime.now(UTC)` меняется между двумя вызовами → PK не срабатывает → 6 строк вместо 3
- **Исправление:** `freeze_time("2026-01-01T00:00:00Z")` стабилизирует timestamp для обоих вызовов
- **Файлы:** tests/integration/ingest/test_coinglass.py

**4. [Rule 1 - Bug] pyright ошибки типов**
- **Обнаружено при:** финальная верификация
- **Проблема:** `dict | None` без type args, `list[]` без type args, доступ к приватным полям в тестах
- **Исправление:** добавлены явные type args; `# type: ignore[reportPrivateUsage]` в тестах

## Результаты финальной верификации

- `uv run pytest tests/unit/ingest/coinglass -q`: 34 passed, 0 failed
- `uv run pytest tests/integration/ingest/test_coinglass.py -m integration -v`: 5 passed, 0 failed
- `uv run pyright src/shortfire/ingest/coinglass tests/unit/ingest/coinglass`: 0 errors

## Известные stubs

Нет. Все методы реализованы и подключены к реальному коду (не заглушки).

## Threat Surface Scan

Новые сетевые вызовы идут в уже задекларированной в плане точке: `https://open-api-v4.coinglass.com`.
API ключ в заголовке (не URL) — T-1-CG-01 выполнен.
Новой threat surface, не задекларированной в `<threat_model>` плана, не обнаружено.

## Self-Check: PASSED

| Файл | Существует |
|------|-----------|
| src/shortfire/ingest/coinglass/client.py | FOUND |
| src/shortfire/ingest/coinglass/schemas.py | FOUND |
| src/shortfire/ingest/coinglass/funding_agg.py | FOUND |
| src/shortfire/ingest/coinglass/oi.py | FOUND |
| src/shortfire/ingest/coinglass/liq.py | FOUND |
| src/shortfire/ingest/coinglass/lsr.py | FOUND |
| tests/integration/ingest/test_coinglass.py | FOUND |

Коммиты:
- Task 1: 079732d
- Task 2: 41083f1
