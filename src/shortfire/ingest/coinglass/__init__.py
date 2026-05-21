"""Coinglass ingest package — httpx-backed client + 4 per-endpoint fetcher modules.

D-50: single httpx.AsyncClient per process (HTTP/2, locked timeout + limits)
D-51: COINGLASS_LIMITER (28 req/min, 5% headroom under Hobbyist quota)
D-52: Pydantic v2 strict schemas per endpoint; ValidationError → dead_letter
D-53: refresh cadences — funding_agg every 5 min (batch); oi/liq/lsr every 5 min (round-robin)
D-59: source attribution always 'coinglass_aggregate' in Phase 1
"""
