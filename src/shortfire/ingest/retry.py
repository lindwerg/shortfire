"""Per-source tenacity retry decorators (D-72, RESEARCH.md §2 Pattern 2).

Three named decorators, one per external data source:
  - mexc_retry      — MEXC ccxt/websocket calls (most aggressive backoff, also catches TimeoutError)
  - coinglass_retry — Coinglass httpx calls
  - coingecko_retry — CoinGecko httpx calls

Invariant:
  Do NOT retry on 4xx-non-429 — those land in dead_letter at the call site.
  Only 5xx + 429 + network/transport errors are retried.
  TimeoutError is retried for MEXC only (MEXC websocket hangs are documented, D-49).

All three use wait_exponential_jitter to spread retry storms and reraise=True
so the caller observes the original exception after exhausted retries.

ccxt exception handling (WR-05):
  ccxt exceptions (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded)
  are NOT subclasses of httpx.* — they inherit from ccxt.BaseError.
  mexc_retry does NOT catch ccxt.NetworkError directly.

  This is INTENTIONAL: ccxt has its own internal retry and rate-limit handling
  when `enableRateLimit=True` (D-73 defense-in-depth). The ccxt client retries at the
  transport layer before raising to our code. When ccxt does raise:
    - ccxt.NetworkError / ccxt.ExchangeNotAvailable: propagate to the ingest loop's
      exception handler which writes to dead_letter and backs off via the outer
      reconnect protocol (D-49 points 1+2).
    - ccxt.RateLimitExceeded: same path — dead_letter + reconnect backoff.

  Adding ccxt.NetworkError to mexc_retry would create double-retry (tenacity ON TOP
  of ccxt's internal throttler), potentially worsening rate-limit storms. Current
  design: one retry layer per source (ccxt owns MEXC; tenacity owns httpx sources).
"""

import logging

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# coinglass_retry — Coinglass httpx REST (D-72)
# ---------------------------------------------------------------------------
# stop_after_attempt(5) — Coinglass Hobbyist has lower tolerance for retry storms
# wait_exponential_jitter(initial=1.0, max=60.0) — capped at 60s per D-72

coinglass_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    wait=wait_exponential_jitter(initial=1.0, max=60.0),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)

# ---------------------------------------------------------------------------
# mexc_retry — MEXC ccxt REST + websocket (D-72)
# ---------------------------------------------------------------------------
# stop_after_attempt(6) — MEXC ws reconnects need a bit more headroom
# Also catches TimeoutError — documented silent-hang failure mode for MEXC ws (D-49, ccxt#27253)
# wait_exponential_jitter(initial=2.0, max=120.0) — longer backoff for heavier ops

mexc_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError, TimeoutError)),
    wait=wait_exponential_jitter(initial=2.0, max=120.0),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)

# ---------------------------------------------------------------------------
# coingecko_retry — CoinGecko httpx REST (D-72)
# ---------------------------------------------------------------------------
# stop_after_attempt(4) — Daily-cadence calls; fewer retries needed
# Same wait shape as coinglass (initial=1.0, max=60.0)

coingecko_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    wait=wait_exponential_jitter(initial=1.0, max=60.0),
    stop=stop_after_attempt(4),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
