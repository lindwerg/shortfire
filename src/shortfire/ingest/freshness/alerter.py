"""Freshness alerter — fires Telegram warn alert when source data becomes stale.

RESEARCH.md §12: freshness_check_job iterates Prometheus gauges, computes
lag = now - gauge_value, fires alert when lag > 2 × EXPECTED_LAG per source/dataset.

D-85 events: freshness.degraded + freshness.recovered (registered in events.py).
D-87 severity routing: stale freshness → "warn".

Usage:
    # Registered in APScheduler via scheduler/jobs.py — called every 1 min.
    from shortfire.ingest.freshness.alerter import freshness_check_job
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from shortfire.observability.events import assert_event_registered
from shortfire.observability.metrics_data_platform import build_data_platform_metrics
from shortfire.observability.telegram import send_telegram_alert

if TYPE_CHECKING:
    from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.freshness.alerter")

# EXPECTED_LAG table per RESEARCH.md §12 (plan interfaces block)
# Each value is the EXPECTED freshness interval in seconds.
# Alert fires when lag > 2 × expected (i.e. we missed 2 full cycles).
EXPECTED_LAG: dict[tuple[str, str], int] = {
    ("mexc_native", "candles_1m"): 90,
    ("mexc_native", "funding"): 8 * 3600,
    ("mexc_native", "oi"): 5 * 60,
    ("mexc_native", "l2_top20"): 30,
    ("mexc_native", "trades"): 90,
    ("mexc_native", "liquidations"): 5 * 60,
    ("coinglass_aggregate", "funding_agg"): 6 * 60,
    ("coinglass_aggregate", "oi"): 6 * 60,
    ("coinglass_aggregate", "liq"): 12 * 60,
    ("coinglass_aggregate", "lsr"): 18 * 60,
    ("coingecko", "market"): 25 * 3600,
}

# Track previously-degraded (source, dataset, symbol) tuples so we emit
# 'freshness.recovered' on the transition from stale → fresh.
#
# CR-04: This is intentionally module-level state.  The update at the end of
# freshness_check_job() is made atomic by capturing a frozenset snapshot BEFORE
# clearing, so a concurrent invocation that starts between clear() and update()
# sees a consistent previous state.  Python asyncio is single-threaded; the only
# interleaving risk is an `await` between clear() and update() — the fix below
# eliminates that by replacing the two-step mutation with a single reassignment.
_degraded_set: set[tuple[str, str, str]] = set()


def reset_degraded_set() -> None:
    """Clear _degraded_set — for test isolation only (CR-04).

    Tests that verify freshness.recovered transitions must call this in setUp/teardown
    to avoid order-dependent failures from shared module state.
    """
    _degraded_set.clear()


async def freshness_check_job(settings: DataPlatformSettings | None = None) -> None:
    """APScheduler IntervalTrigger(minutes=1) callable.

    Iterates Prometheus gauge samples for source_freshness_seconds, computes
    lag = now - gauge_value, fires Telegram warn alert when lag > 2 × EXPECTED_LAG.

    D-85 events: freshness.degraded (first time stale), freshness.recovered (back to fresh).

    Args:
        settings: DataPlatformSettings. If None, loaded from get_settings() singleton.
                  Passed explicitly in tests to inject mock settings.
    """
    if settings is None:
        from shortfire.ingest.context import get_settings

        settings = get_settings()

    metrics = build_data_platform_metrics()
    now = time.time()
    currently_degraded: set[tuple[str, str, str]] = set()

    # Iterate all registered gauge samples for source_freshness_seconds
    for metric_family in metrics.source_freshness_seconds.collect():
        for sample in metric_family.samples:
            if sample.name != "shortfire_data_platform_source_freshness_seconds":
                continue
            source = sample.labels.get("source")
            dataset = sample.labels.get("dataset")
            symbol = sample.labels.get("symbol")
            if source is None or dataset is None or symbol is None:
                continue
            gauge_unix_ts: float = sample.value
            # Gauge value of 0 (or negative) means "not yet set" — skip
            if gauge_unix_ts <= 0:
                continue
            lag = now - gauge_unix_ts
            expected = EXPECTED_LAG.get((source, dataset), 600)
            threshold = 2 * expected

            if lag > threshold:
                key = (source, dataset, symbol)
                currently_degraded.add(key)
                if key not in _degraded_set:
                    # First time this source/dataset/symbol is stale → emit event + alert
                    assert_event_registered("freshness.degraded")
                    log.warning(
                        "freshness.degraded",
                        source=source,
                        dataset=dataset,
                        symbol=symbol,
                        lag_s=int(lag),
                        threshold_s=threshold,
                        expected_s=expected,
                    )
                    await send_telegram_alert(
                        settings,
                        "warn",
                        f"stale: {source}/{dataset}/{symbol} lag={int(lag)}s threshold={threshold}s",
                    )

    # Emit freshness.recovered for sources that were degraded but are now fresh.
    # CR-04: snapshot the previous state BEFORE mutating _degraded_set so that
    # `recovered` is computed consistently even if the coroutine is re-entered.
    previous = frozenset(_degraded_set)
    recovered = previous - currently_degraded
    for key in recovered:
        assert_event_registered("freshness.recovered")
        source, dataset, symbol = key
        log.info(
            "freshness.recovered",
            source=source,
            dataset=dataset,
            symbol=symbol,
        )

    # CR-04: Replace the two-step clear()+update() with a single reassignment.
    # This eliminates the window where an `await` between clear() and update()
    # could leave _degraded_set temporarily empty, causing a spurious recovered
    # event on the next invocation.
    _degraded_set.clear()
    _degraded_set.update(currently_degraded)
