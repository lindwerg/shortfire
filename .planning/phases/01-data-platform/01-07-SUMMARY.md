---
phase: "01-data-platform"
plan: "01-07"
subsystem: "ingest.coingecko"
tags: ["coingecko", "httpx", "pydantic-v2", "hypertable", "tdd", "asyncpg", "copy"]
dependency_graph:
  requires:
    - "01-01"  # ingest seam: COINGECKO_LIMITER, coingecko_retry
    - "01-04"  # aux schema: raw_coingecko_market migration 0010
  provides:
    - "CoinGeckoClient — httpx Demo-tier client (D-36)"
    - "CoinsMarketsRow + CoinDetailResponse — Pydantic v2 strict schemas"
    - "fetch_and_write_daily — daily universe-metadata write to raw_coingecko_market"
    - "FakeCoinGeckoClient — canned-data fake for unit tests"
    - "CoinGeckoClient Protocol — updated from Phase 0 stub to Phase 1 real shape"
  affects:
    - "01-09"  # daily universe job APScheduler wiring calls fetch_and_write_daily
tech_stack:
  added:
    - "httpx[http2]>=0.28 — h2 package required for http2=True (D-50)"
    - "orjson.dumps — JSONB raw_payload serialization before asyncpg COPY"
  patterns:
    - "Pydantic v2 strict=True + pre-conversion (Decimal, datetime, date) before model_validate"
    - "extra='allow' forward-compat for CoinGecko schema drift (Pitfall G)"
    - "asyncpg binary COPY requires JSON string, not dict, for JSONB columns"
    - "Protocol structural typing for real + fake client interchangeability"
    - "Function-scoped AsyncEngine in integration tests to avoid event loop conflicts"
key_files:
  created:
    - "src/shortfire/ingest/coingecko/__init__.py"
    - "src/shortfire/ingest/coingecko/schemas.py"
    - "src/shortfire/ingest/coingecko/client.py"
    - "src/shortfire/ingest/coingecko/universe.py"
    - "tests/unit/ingest/coingecko/__init__.py"
    - "tests/unit/ingest/coingecko/test_coingecko_client.py"
    - "tests/unit/ingest/coingecko/test_coingecko_schemas.py"
    - "tests/unit/ingest/test_universe_coingecko.py"
    - "tests/integration/ingest/test_coingecko.py"
  modified:
    - "tests/fakes/coingecko.py — rewritten with FakeCoinGeckoClient + canned data"
    - "src/shortfire/clients/coingecko.py — Protocol updated to Phase 1 signatures"
    - "pyproject.toml — httpx[http2] dependency"
decisions:
  - "orjson.dumps().decode() in to_record() — asyncpg COPY protocol needs JSON string not dict for JSONB columns; confirmed by AttributeError: 'dict' object has no attribute 'encode'"
  - "Function-scoped AsyncEngine in integration tests — module-scoped engine creates 'Event loop is closed' errors with pytest-asyncio's per-function loop isolation"
  - "_CoinGeckoClientProtocol structural protocol in universe.py — enables duck-typing between concrete CoinGeckoClient and FakeCoinGeckoClient without circular imports"
metrics:
  duration: "approx 45 min (continuation agent, prior context exceeded)"
  completed: "2026-05-21"
  task_count: 2
  file_count: 13
---

# Phase 01 Plan 07: CoinGeckoClient + Daily Universe Fetcher

CoinGeckoClient (httpx Demo tier, D-36) mit Pydantic-v2-Strict-Schemas + `fetch_and_write_daily` — полная цепочка от API-вызова до записи в гипертаблицу `raw_coingecko_market`.

## Задачи

| # | Название | Тип | Коммит | Результат |
|---|----------|-----|--------|-----------|
| 1 | CoinGeckoClient + schemas | TDD RED→GREEN | `52343ca` (RED), `3233786` (GREEN) | 16 unit tests pass |
| 2 | fetch_and_write_daily + интеграционный тест DATA-08 | TDD RED→GREEN | `af3b590` (RED), `92388be` (GREEN) | 23 unit + 3 integration tests pass |

## Что сделано

### Task 1: CoinGeckoClient + Pydantic v2 схемы

- `schemas.py`: `CoinsMarketsRow` + `CoinDetailResponse` — strict=True, extra="allow"
  - Предконвертация float/int → Decimal через `Decimal(str(v))` (strict=True отклоняет неявное приведение)
  - Предпарсинг str → datetime/date через `TypeAdapter.validate_python()`
  - `raw_payload` сериализуется через `orjson.dumps().decode()` перед COPY (asyncpg требует строку)
- `client.py`: `CoinGeckoClient` — httpx.AsyncClient(http2=True)
  - Ключ только в заголовке `x-cg-demo-api-key` (T-1-CG-01)
  - `COINGECKO_LIMITER` acquire перед каждым запросом (D-56: 28/60)
  - 4xx (кроме 429) → dead_letter + return None; 429/5xx → raise для tenacity
  - `@coingecko_retry` на обоих публичных методах
- `tests/fakes/coingecko.py`: `FakeCoinGeckoClient` + `CANNED_MARKETS_ROWS` + `CANNED_DETAIL_BITCOIN`

### Task 2: fetch_and_write_daily (DATA-08)

- `universe.py`: `fetch_and_write_daily(engine, client, ts=None) → int`
  - Вызывает `/coins/markets` page 1 (250 монет, order=market_cap_desc)
  - Конвертирует через `row.to_record(ts)` в 10-tuple
  - Пишет через `copy_into_hypertable` в `raw_coingecko_market`
  - Идемпотентность: ON CONFLICT DO NOTHING (D-62)
  - ts по умолчанию — `datetime.now(UTC)`
- `clients/coingecko.py`: Protocol обновлён с Phase-0-заглушки на реальные сигнатуры Phase 1

## Отклонения от плана

### Автофиксы (Rules 1-2)

**1. [Rule 2 — Missing dep] httpx[http2] в pyproject.toml**
- **Обнаружено:** Task 1 — `ImportError: Using http2=True, but the 'h2' package is not installed`
- **Фикс:** `"httpx>=0.28"` → `"httpx[http2]>=0.28"` в pyproject.toml; `uv sync`
- **Коммит:** `3233786`

**2. [Rule 1 — Bug] orjson.dumps для raw_payload в to_record()**
- **Обнаружено:** Task 2 интеграционные тесты — `AttributeError: 'dict' object has no attribute 'encode'`
- **Причина:** asyncpg binary COPY требует JSON-строку для JSONB, не dict
- **Фикс:** `orjson.dumps(self.raw_payload).decode()` в `CoinsMarketsRow.to_record()`
- **Коммит:** `92388be`

**3. [Rule 1 — Bug] CoinGeckoClient Protocol не соответствовал FakeCoinGeckoClient**
- **Обнаружено:** Прогон полного unit suite — `test_fake_satisfies_protocol[FakeCoinGeckoClient]` падал
- **Причина:** `shortfire/clients/coingecko.py` содержал Phase 0 методы (`fetch_markets`, `fetch_global_data`), которые были заменены в реализации
- **Фикс:** Обновил Protocol до `fetch_coins_markets` + `fetch_coin_detail` + `close`
- **Коммит:** `92388be`

**4. [Rule 1 — Bug] Module-scoped AsyncEngine в интеграционных тестах**
- **Обнаружено:** Task 2 интеграционные тесты — "Event loop is closed" на 2-й и 3-й тест
- **Причина:** pytest-asyncio создаёт новый event loop на каждую test function; module-scoped engine привязывается к первому loop
- **Фикс:** Изменил `scope="module"` → `scope="function"` (function-scoped engine)
- **Коммит:** `92388be`

## Итоговые метрики

- **Юнит-тесты:** 344 passed (было 327 до плана 01-07)
- **Интеграционные тесты (DATA-08):** 3 passed — insert, idempotency, source=coingecko
- **pyright:** 0 errors, 0 warnings
- **pre-commit:** passed на всех коммитах

## Известные ограничения

- `fetch_and_write_daily` вызывает только page 1 (250 монет). Пагинация >250 монет — в плане 01-09.
- Планировщик APScheduler (00:30 UTC, D-77) — в плане 01-09, не здесь.
- `fetch_coin_detail` реализован в клиенте, но не вызывается в `fetch_and_write_daily` (слишком дорого при 30 req/min Demo квоте) — enrichment в плане 01-09 при обнаружении новых символов.

## Self-Check: PASSED

- [x] `src/shortfire/ingest/coingecko/schemas.py` — существует
- [x] `src/shortfire/ingest/coingecko/client.py` — существует
- [x] `src/shortfire/ingest/coingecko/universe.py` — существует
- [x] `tests/fakes/coingecko.py` — обновлён
- [x] `src/shortfire/clients/coingecko.py` — обновлён
- [x] `52343ca`, `3233786`, `af3b590`, `92388be` — все коммиты в git log
