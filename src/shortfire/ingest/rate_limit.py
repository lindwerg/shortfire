"""Per-source aiolimiter token-bucket rate limiters (D-35, D-51, D-56, D-73).

Three module-level AsyncLimiter constants, one per external data source.
These are process-wide singletons — import them directly in any ingest module.

Rate decisions (CONTEXT.md decisions):
  D-35:  Coinglass tier = Hobbyist, 30 req/min actual quota
  D-36:  CoinGecko tier ≈ Demo, 30 req/min actual quota
  D-51:  COINGLASS_LIMITER = 28/60  (5% headroom under 30 req/min)
  D-56:  COINGECKO_LIMITER = 28/60  (same 5% headroom shape)
  D-73:  MEXC_LIMITER = 18/1  (defense-in-depth; MEXC public quota is 20 req/s)
         ccxt internal throttler is also ON (enableRateLimit=True) — double guard.

Layering rule (D-73):
  aiolimiter acquires BEFORE the request, releases AFTER response.
  This limiter is the project-level budget guard.
  ccxt's own throttler is the exchange-level guard for MEXC.
  Both must be satisfied simultaneously (aiolimiter is the outer layer).
"""

from aiolimiter import AsyncLimiter

# MEXC: 18 req/s (D-73, 10% headroom under 20 req/s MEXC public quota)
MEXC_LIMITER = AsyncLimiter(max_rate=18, time_period=1)

# Coinglass: 28 req/min (D-51, 5% headroom under 30 req/min Hobbyist cap per D-35)
COINGLASS_LIMITER = AsyncLimiter(max_rate=28, time_period=60)

# CoinGecko: 28 req/min (D-56, same headroom shape as Coinglass; Demo tier = 30/min per D-36)
COINGECKO_LIMITER = AsyncLimiter(max_rate=28, time_period=60)
