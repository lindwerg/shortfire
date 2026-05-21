# Pitfalls Research

**Domain:** Crypto futures ML trading system — MEXC USDT-perp short-after-pump strategy, solo operator, Railway-deployed, paper-trading-gated escalation
**Researched:** 2026-05-21
**Confidence:** HIGH for ML/backtest/data-leakage classes (López de Prado canon + cross-verified crypto sources); HIGH for MEXC API quirks (vendor docs + ccxt issue tracker); HIGH for capital-destroying execution mistakes (well-documented across futures forums); MEDIUM for Coinglass/Railway combination edge cases (less written about)

Severity legend used throughout:
- **CAPITAL** — direct money loss (real $ or wasted infra spend)
- **RESEARCH-INVALID** — silently corrupts every conclusion built on top; the strategy that "works" doesn't exist
- **OPS** — bot stops working / data gaps / silent failures
- **ANNOY** — wastes a few hours but recoverable

"Wrong in research" vs "wrong in production" is called out per pitfall.

---

## Critical Pitfalls

These can destroy the project. Each is a single line on a roadmap-killing list.

### Pitfall 1: Survivorship-biased training universe (delisted MEXC perps absent)

**Severity:** RESEARCH-INVALID — inflates backtest returns by 17–400% (Coinbase Institutional: 17–22% annualized; StratBase: 200–400% on memecoin baskets). Discovered in production = months of wasted work.

**Research vs production:** Wrong in research. The bot trades just fine, it's just chasing a phantom edge.

**What goes wrong:**
You backfill historical candles by iterating "all MEXC USDT perpetuals currently listed" → call `fetch_ohlcv` per symbol → build training set. The strategy "works": short-after-pump labels look great. In live, the edge is invisible.

Why: 58%+ of crypto tokens ever listed have died or delisted. On MEXC specifically, **memecoin perp listing churn is weekly** — that's exactly the population this strategy is supposed to short. The dead coins are precisely the ones that pumped 200% and never recovered (the perfect short setups), but they're gone from the symbol list, so they're never in your training data. You train only on coins that pumped, dumped, and survived to keep trading. Two very different distributions.

**Why it happens:**
- ccxt's `exchange.load_markets()` returns only live markets — no API surface for "previously listed."
- No flag in MEXC schema for "this used to be a market and got delisted on date X."
- Adding it later requires reconstructing the historical universe from snapshots, which nobody has.

**How to avoid:**
1. **Phase 1 day 1**: Persist a daily snapshot of `exchange.load_markets()` results to a `universe_snapshots` hypertable (symbol, listed_at, last_seen_at, status). Cost: ~30s/day cron, ~1MB/yr storage. Without this, no historical universe is reconstructable.
2. **Phase 1**: Cross-reference Coinglass perps history — Coinglass tracks delisted markets across exchanges and gives at least a partial historical universe.
3. **Phase 2 labeling**: when generating training labels, the universe at each historical timestamp T must be "symbols listed AT T," not "symbols listed today."
4. **Backfill any delisted symbol you can identify** even if you only have the last 30 days before delisting — that's where the short-setup signal lives.

**Warning signs:**
- Backtest Sharpe > 2.5 on a memecoin universe → almost certainly survivorship-biased.
- Out-of-sample (later walk-forward windows) degrade systematically vs in-sample → universe drift may be the cause.
- Top-PnL trades in backtest are all on coins still listed today.

**Phase to address:** Phase 1 (Data Platform). Capturing daily universe snapshots is **non-negotiable from commit 1** of ingest. Cannot be retrofitted.

---

### Pitfall 2: Look-ahead bias in feature engineering (rolling windows that peek forward)

**Severity:** RESEARCH-INVALID — silently inflates model accuracy by 5–30 percentage points. The most common ML-quant failure mode (López de Prado's "the reasons most ML quant funds fail" lecture).

**Research vs production:** Wrong in research; bot will lose money in production.

**What goes wrong:**
Specific failure modes to call out by name:
- `df['rsi_14'] = ta.rsi(df['close'], 14)` computed on a frame that includes the future → RSI at row T uses closes from T-13 to T (correct), but only because pandas-ta happens to be causal. Many indicators are not. **Z-score / standardization** computed across the full training set, then "split" later: every row sees the global mean → leak.
- `df['volume_zscore'] = (df['volume'] - df['volume'].mean()) / df['volume'].std()` — leaks. Use rolling z-score with `min_periods` and `closed='left'`.
- Labels generated with forward-looking returns (`df['ret_60m'] = df['close'].shift(-60) / df['close'] - 1`), then feature columns include same-row values that were ALSO computed using forward data because of a stray `.fillna(method='bfill')` somewhere upstream. Backfill is the silent killer.
- **Funding rate features**: funding settles every 8h on MEXC. If you write `df['funding_rate']` at minute T = "the most recently published funding rate," you must verify the publication timestamp, not the settlement timestamp. Many feeds (Coinglass aggregates included) publish the settlement-window's rate AT settlement time, which means using it at T = settlement_time is fine, but using it at T = settlement_time − 30min is a leak.

**Why it happens:**
- pandas/polars don't know "now" — they happily compute statistics over the future.
- `bfill` and `interpolate` look both directions by default.
- ccxt and Coinglass timestamps don't all mean the same thing (publish time vs settlement time vs window-start time).
- ML practitioners trained on IID problems instinctively reach for `train_test_split` or k-fold.

**How to avoid:**
1. **All features computed via causal rolling: `df.rolling(window, closed='left')` or `polars.col.rolling_*` with shift(1).** Adopt this as a project-wide invariant.
2. **Hypothesis property test** for every feature: "if I duplicate row T and shift it by N seconds, the feature value at original T must not change." This catches every backfill leak.
3. **Hypothesis property test** for labels: "if I corrupt all rows after T, the label at T must not change."
4. **Funding timestamps standardized in schema**: every funding row has BOTH `settlement_ts` and `published_ts`. Feature pipeline can use `published_ts` only. Document the difference per data source (`mexc_funding` vs `coinglass_aggregate`) — they're not the same.
5. **Walk-forward with purging AND embargo** (López de Prado): purge training samples whose label window overlaps the test set's feature window; embargo training samples immediately FOLLOWING the test set (autocorrelation leak forward in time too).
6. **No `bfill`, no `interpolate(method='time')` without explicit causal limit**. Use `ffill` only, or leave NaN and let the model handle.

**Warning signs:**
- Backtest accuracy > 80% on imbalanced classification (short-after-pump is ~5–15% positive rate) → almost certainly a leak.
- Removing a feature makes performance better → that feature was leaking.
- First out-of-sample fold beats in-sample fold → suspicious; usually means in-sample was incorrectly purged.

**Phase to address:** Phase 2 (Strategy #1, before any labeling/feature work). Set the invariant + Hypothesis tests as Phase-2 commit-zero.

---

### Pitfall 3: Walk-forward done wrong (no purging, no embargo, label horizon overlap)

**Severity:** RESEARCH-INVALID — same class as Pitfall 2 but specifically about validation methodology. Even a clean feature pipeline leaks if the splitter doesn't purge.

**Research vs production:** Pure research.

**What goes wrong:**
- Using `sklearn.model_selection.TimeSeriesSplit` directly. It splits on time but does NOT purge overlapping labels or embargo neighbors. If your label is "max forward 30m return," a sample at T=test_start-15m has its label computed from data inside the test window. Leak.
- Optuna hyperparameter optimization over the wrong CV scheme: TPE sampler converges to hyperparameters that exploit the leakage. The "best" model is the one most overfit to the leak.
- "Anchored" vs "rolling" walk-forward picked without thought — anchored grows training set monotonically (good for stationary edges) but is wrong for crypto regime changes; rolling discards old data (better for crypto) but needs more history.

**Why it happens:**
- `TimeSeriesSplit` is what sklearn documentation shows; people copy it.
- López de Prado's `PurgedKFold` / `CombinatorialPurgedKFold` requires implementing it yourself or pulling in `mlfinlab` (heavy, partly paid).
- Embargo size depends on label horizon; nobody documents this so it gets skipped.

**How to avoid:**
1. **Implement `PurgedWalkForward` as a small in-repo utility class** (or vendor a small public implementation). Take `label_horizon` and `embargo_pct` as explicit parameters. Hypothesis test for: "no training index is within `label_horizon` of any test index."
2. **Embargo ≥ label horizon**: if labels look forward 60 minutes, embargo at least 60 minutes after the test fold.
3. **Optuna study uses the purged splitter**, not a custom CV that bypasses it.
4. **Document the choice**: rolling walk-forward with 90-day training window, 14-day test window, 60m embargo (or whatever the label horizon is). Write it in `STRATEGY.md` and never change without re-running the full sweep.
5. **Cross-validation diagnostic**: compute mean(in-sample score) − mean(out-of-sample score). If this gap is large and stable, you have leakage or overfitting (López de Prado: this gap is the canonical leakage detector).

**Warning signs:**
- Optuna best trial has wildly different hyperparameters from second-best (TPE found a leak-exploiting outlier).
- IS/OOS gap > 20% on classification AUC → leak suspected.
- Test scores have negligible variance across folds → folds are not actually independent.

**Phase to address:** Phase 2 (Strategy #1 ML). Build the splitter BEFORE the first hyperparameter sweep.

---

### Pitfall 4: Unrealistic slippage on illiquid MEXC memecoin perps

**Severity:** CAPITAL — backtested edge of +1.5% per trade can become −0.5% in production purely from slippage. Has killed more crypto strategies than any other single factor.

**Research vs production:** Wrong in research; manifests on first real trade.

**What goes wrong:**
- Backtest uses flat fee + flat 0.05% slippage. Then live order on a $500K-daily-volume memecoin perp eats 1–3% of book depth on a position size that looked fine in backtest.
- Stop-loss "at $X" in backtest fills exactly at $X; in production it fills 0.5–5% worse on a low-volume coin during a liquidation cascade — and the cascade is partly caused by your own stop hitting the book.
- The strategy is SHORTING POST-PUMP — these are exactly the moments when liquidity is most asymmetric: ask side thin (everyone wants to short the top), bid side getting hit by liquidations. Your short entry might fill cheap; your stop-out fill might be catastrophic.

**Why it happens:**
- Easy default: pick a number, apply it uniformly. Looks rigorous, isn't.
- Order book depth data wasn't collected, so the backtester has no choice but to use a constant.
- Self-impact (your trade moves the book) is invisible until you're trading the size that triggers it.

**How to avoid:**
1. **Collect L2 order book snapshots at ingest time** — top 20 levels every 5–10s for active universe. This is what makes a realistic slippage model possible. Without it, no remediation works later.
2. **Slippage model in backtester**: walk the book — compute the VWAP fill for the position size against the snapshot nearest to signal time. Add a multiplier (1.5–3x) for self-impact when position size > 5% of top-of-book.
3. **Stop-loss fills modeled as taker against the bid side AT or AFTER the stop trigger**, with the same book-walk logic. Never fill at the exact stop price.
4. **Per-symbol liquidity tier**: classify symbols into tiers by 24h volume; have different slippage assumptions per tier. Below $500K daily volume = exclude from universe entirely (your `$500K+ 24h volume` filter exists for this reason — enforce it strictly).
5. **Paper-trading parity test**: before going live, take 100 paper signals, compute what slippage the backtester predicted, compare to what ccxt's `fetch_order_book` would currently show. If average paper slippage < live slippage by >30%, fix the model before live.

**Warning signs:**
- Backtest "perfect" trades concentrated in the lowest-volume symbols → those are unrealistic and need to be downweighted.
- Backtest assumes 100% fill rate → never true on memecoin perps.
- Equity curve in backtest is monotonic during pump windows → real-world it would have nasty drawdowns from slippage.

**Phase to address:** Phase 1 (must collect L2 snapshots from day 1 of ingest — cannot be retrofitted) + Phase 2 (slippage model in backtester) + Pre-Live (parity test).

---

### Pitfall 5: MEXC fee model wrong — paper/live divergence

**Severity:** CAPITAL — fee error of 0.02% per trade × 10 trades/day × 365 = ~73% annual P&L difference at scale. Compounds with slippage.

**Research vs production:** Wrong in both — the backtest is wrong, AND production results don't match what was modeled.

**What goes wrong:**
- Backtest hardcodes 0.05% taker / 0.02% maker.
- MEXC futures fees as of May 1, 2026 changed — see [MEXC announcement](https://www.mexc.com/announcements/article/updates-to-api-futures-trading-fees-may-1-2026-17827791535194). VIP tiers exist; API users sometimes get different rates than UI users.
- MEXC occasionally runs **zero-fee promos** on specific perps (memecoin listings often). Your backtest doesn't reflect them and underestimates real-world edge during promo windows — or worse, your live bot triggers more aggressively expecting zero fees and the promo has already ended.
- Maker assumption: backtest fills limit orders at the limit price assuming maker rebate; live, your aggressive limit might cross the spread and be charged taker.

**Why it happens:**
- Fee schedules change quarterly; nobody updates the constant in the backtester.
- ccxt has `exchange.calculate_fee()` but its accuracy depends on `exchange.fees` dict being up-to-date for MEXC futures (which historically lags).
- The maker/taker classification is non-trivial — order type alone doesn't determine it.

**How to avoid:**
1. **Single source of truth for fees**: a `fees.py` module that reads from ccxt + a local override (`fees_override.yaml`) for VIP discounts and promo overrides. Both backtester and live executor import from here. Never hardcode.
2. **Fee schedule has effective dates**: `fees_override.yaml` stores `{symbol_pattern, taker_bps, maker_bps, valid_from, valid_to}`. Backtester respects the date.
3. **Maker classification rule explicit**: in backtester, a limit order is maker iff its price is on the passive side of the spread at fill time. Anything else is taker. Document this rule.
4. **Live-vs-paper fee reconciliation report**: weekly cron that compares paper-trade fee estimates to live-trade actual fees (`info.fee` from ccxt's order response). Surface divergence > 5%.
5. **Subscribe to MEXC announcements** — the [API updates feed](https://www.mexc.com/announcements/api-updates) is the canonical place fee/endpoint changes are published.

**Warning signs:**
- Paper P&L > live P&L by a consistent percentage → fee model wrong.
- ccxt `fees` dict returns stale data (check `exchange.fees['trading']['percentage']` versus current MEXC page).
- More trades = bigger divergence → linear-in-trades = fee bug; quadratic = compounding return bug.

**Phase to address:** Phase 2 (backtester) + Phase 4 (paper trading; reconciliation test) + Phase 5 (live; weekly reconciliation cron).

---

### Pitfall 6: Reduce-only flag missing on exits → accidental new position

**Severity:** CAPITAL — has wiped accounts in single incidents. Exit order intended to close a short becomes a long open, doubling effective exposure during a pump exactly when you needed to flatten.

**Research vs production:** Pure production. Cannot reproduce in backtest. This is the single most expensive solo-developer mistake in crypto futures.

**What goes wrong:**
- Bot wants to close a short of size 100. Sends a BUY order for size 100 to "cover."
- Order endpoint accepts it. If `reduceOnly=true` is not set, MEXC treats it as a new long. You now hold 100 short + 100 long → on net flat **but**, depending on margin/position mode, you're using 2x margin and paying funding on both. On a sudden pump, your "short" gets liquidated even though you "closed" it; the long sits there.
- Worse case: position mode is one-way; the order partially closes and partially opens a long, leaving an unintended directional position.

**Why it happens:**
- ccxt's unified order params include `reduceOnly` but it's not always passed by default in tutorials/examples.
- MEXC's hedge mode vs one-way mode changes what "close" means. Many bots assume the wrong mode.
- Testnet behavior differs from live (some venues silently ignore `reduceOnly` on testnet).

**How to avoid:**
1. **Wrap every order in a `place_order(intent: Literal['open', 'close'])` function** that mechanically sets `reduceOnly=True` when intent='close'. Make the raw ccxt order call inaccessible outside this wrapper. Hypothesis test for invariant: "every order with intent='close' has params.reduceOnly == True."
2. **At startup, assert MEXC position mode**: query account config, fail-fast if not the expected mode. Refuse to start in the wrong mode.
3. **Pre-trade balance assertion**: before sending a close order, fetch open position; if open size < close size, abort. Catches "close 100 when you only have 80 open" → which would otherwise open a 20-unit reverse position.
4. **Post-trade position assertion**: after every close, re-fetch the position; if expected closed but it's still open or reversed, alert immediately AND set the kill switch.
5. **Paper trading must simulate the bug**: write a test where the close intent omits `reduceOnly` and verify the simulator opens a reverse position. This proves your paper layer faithfully models the failure mode.

**Warning signs:**
- Position count diverges from intended (you think you have 3 open, exchange shows 4) → probable reduce-only bug.
- Funding payment higher than expected → likely paying on more notional than intended.
- "Close" order increases used margin → guaranteed bug.

**Phase to address:** Phase 4 (paper trading wrapper) MUST establish the `place_order(intent=...)` contract before any live key is created. Phase 5 (live) gates on these tests passing.

---

### Pitfall 7: Liquidation cascade self-impact not modeled (you ARE the cascade)

**Severity:** CAPITAL — moderate-frequency, high-magnitude. Most likely to happen exactly when you're least able to recover (during a real pump → reversal where bot scales in).

**Research vs production:** Wrong in research, costly in production but only on size.

**What goes wrong:**
- Backtester treats your orders as price-takers — fills against historical book, doesn't perturb anything.
- In reality: your short fills add to existing sell pressure during the post-pump reversal. The reversal happens partly because of your trade. The historical book you backtested against ALREADY contains the cascades that happened — those happened with someone else's flow, not yours.
- Worse: if you scale into the short across multiple symbols correlated by BTC reversal, you exit them at the same time, eating book depth in parallel.

**Why it happens:**
- No simple model for "self-impact" — Almgren-Chriss and successors require fitting parameters from your own historical flow.
- Backtesting historical book snapshots is already hard; adding self-impact is harder.

**How to avoid:**
1. **Position-size cap as % of order book depth** at the symbol's relevant timeframe. Rule of thumb: ≤ 10% of average 1-minute volume; ≤ 25% of top-20-levels notional. Enforce in `risk.py`.
2. **Correlation-aware concurrent position cap**: max 1 short open in BTC-correlated memecoins simultaneously OR scale down each by 0.5× when N>1 are open (concrete rule, written down).
3. **Backtest with a pessimistic slippage premium** when position size > liquidity threshold — e.g., 2x book-walk VWAP for size in tier 3.
4. **Paper trade size = intended live size** — don't paper trade 100x smaller, you won't see the slippage you'll see live.
5. **Daily liquidation-cascade attribution**: when liquidations spike on a symbol in your universe, log it; if your bot was trading that symbol, flag for review.

**Warning signs:**
- Worst-case trades in paper or live are systematically on the lowest-volume symbols → liquidity-impact issue.
- Backtested entry fills are at "ideal" prices but live fills are systematically 0.3–1% worse → first-pass slippage problem; bigger gap → impact issue.
- During backtested period, sum of strategy notional > 30% of symbol volume in any single minute → you weren't a price-taker, the backtest is fiction.

**Phase to address:** Phase 1 (capture liquidations data from Coinglass) + Phase 2 (size cap rules in backtester) + Phase 4 (paper at full size).

---

### Pitfall 8: API key leakage → drained account

**Severity:** CAPITAL (total) — has happened to many solo traders. Recovery: $0 → start over.

**Research vs production:** Pure production.

**What goes wrong:**
- API key committed to git (even briefly, even private repo — GitHub indexes all of it).
- Key in plaintext `.env.local` synced via Dropbox/iCloud.
- Key printed in logs during error, logs scraped by attacker who got read access via a leaked Railway dashboard credential.
- Withdraw permission enabled on the trading key "to be safe."

**Why it happens:**
- Convenience: one .env, one key, less rotation pain.
- Logs print full request including signed URL.
- ccxt errors sometimes include the full request URL with `api_key=` parameter (older versions; less common now but verify).

**How to avoid:**
1. **Two MEXC keys**: `READ_KEY` (read-only, used for ingest) and `TRADE_KEY` (trade-only, NO withdraw). Trade key created only when Phase 5 begins. **Withdraw permission disabled on both.**
2. **Keys live in Railway Variables only.** Never in code, never in `.env` committed to git. `.env.example` has placeholder values only.
3. **`.gitignore` includes `.env*` from commit 1.** Pre-commit hook runs `git diff --cached` for known secret patterns (`mx0v...`, `sk-...`, etc).
4. **Log redaction middleware**: structlog processor that scrubs request bodies and headers matching credential patterns. Test that scrubbing actually works by injecting fake creds in a unit test.
5. **ccxt request logging disabled in production** (`exchange.verbose = False`) — verbose mode prints signing material.
6. **IP allowlist on MEXC key** if Railway gives you a stable egress IP (it doesn't always — verify with `curl ifconfig.me` from a deployed service).
7. **Kill switch via a separate, manually-rotated emergency API key**: a panic button that uses a different key with `cancel all orders + close all positions` only. Tested monthly.
8. **GitHub secret scanning enabled on the repo.** GitHub will refuse pushes containing detected secrets.

**Warning signs:**
- Unexpected positions in MEXC account → key compromised, act immediately.
- API key rate-limit errors from an endpoint your bot doesn't call → someone else is using it.
- Withdraw attempts in MEXC security log → instant alert.

**Phase to address:** Phase 0 / Phase 1 (gitignore, secret patterns) and Phase 5 (two-key setup, kill switch, allowlist).

---

### Pitfall 9: Imbalanced classes — short-after-pump positives are rare, false positives dominate

**Severity:** RESEARCH-INVALID + CAPITAL — model "works" by always predicting negative; if rebalanced naively, false-positive rate destroys live trading.

**Research vs production:** Wrong in research; expensive in production.

**What goes wrong:**
- Post-pump reversal events are rare (estimate 1–5% of all minute bars per symbol). Default XGBoost on raw labels learns "predict 0 always" → accuracy 95–99% → looks great → zero actual signals.
- "Fix" by `class_weight='balanced'` or oversampling → model now over-predicts positives → many false signals → many losing trades after fees/slippage.
- ROC-AUC reported, but precision at the operating threshold (low recall + high precision is the only useful regime here) is what matters and rarely measured.

**Why it happens:**
- sklearn examples use balanced datasets; defaults don't fit imbalanced classification.
- Accuracy is the wrong metric; people report it anyway.
- The right metric (precision at top-K signals per day) requires deciding K ahead of time.

**How to avoid:**
1. **Metric chosen explicitly = precision @ top-N signals per day per symbol**, where N is the expected live trading rate (e.g., 1–3 trades/symbol/day). Optimize this, not AUC.
2. **Threshold tuning is a separate step**, done on a held-out window AFTER model selection. Never tune threshold on the same data used to select the model.
3. **Class weighting only if Optuna picks it as a hyperparameter** (search `scale_pos_weight` in `[1, 5, 25, ...]`), and only with purged walk-forward.
4. **Cost-sensitive loss**: each false positive in this strategy costs ~fee+slippage (~0.2%); each true positive earns expected return. Encode the asymmetry directly: use focal loss or custom objective that approximates expected value, not log-loss.
5. **Calibration check** (`sklearn.calibration.calibration_curve`): if predicted prob of 0.7 means real prob 0.2, your sizing logic (Kelly) will be catastrophically wrong. Re-calibrate via isotonic regression.
6. **Sanity baseline**: write a "always short the strongest pump" rule-based strategy. If your ML can't beat it on out-of-sample, ML adds no value.

**Warning signs:**
- Reported metric is "accuracy" → wrong metric, redo.
- Model predicts the rare class > 30% of the time → over-aggressive rebalancing.
- ROC-AUC = 0.7+ but precision at operating threshold < 0.3 → ROC-AUC was misleading; in extreme class imbalance use PR-AUC.

**Phase to address:** Phase 2 (ML metric framework before any model training).

---

### Pitfall 10: Regime change blindness (trained on bull, deployed in bear or vice versa)

**Severity:** RESEARCH-INVALID + CAPITAL — strategy's edge can be regime-conditional, e.g., short-after-pump works in distribution markets, fails in trending markets.

**Research vs production:** Wrong in research; manifests when market regime shifts in live.

**What goes wrong:**
- Train on 2022–2023 (declining → ranging crypto), test on early 2024 (bull). Pumps in bull market often DON'T reverse — they keep pumping. Short-after-pump = repeatedly stopped out.
- Model has no signal for "what regime are we in." Even if regime is implicit in features (e.g., BTC drawdown rolling 30d), the labels for short-after-pump in different regimes are differently distributed → model learns an average that fits neither.

**Why it happens:**
- Walk-forward across a single bull cycle looks fine — the test fold is similar to the train fold.
- Crypto regime shifts ~quarterly; need 4+ years of training data for regime diversity, and MEXC perps barely existed at scale 4 years ago.

**How to avoid:**
1. **Walk-forward must span at least one regime change.** Document the regime change boundaries (e.g., BTC 6-month return crossing zero, or 200d MA cross). If your training/validation windows don't span both, you don't know if the edge generalizes.
2. **Add explicit regime features**: BTC 30d realized vol, BTC drawdown from 90d high, market-wide funding rate average. Let the model learn regime-conditional behavior.
3. **Regime-stratified evaluation**: report metrics separately for bull/bear/range periods. If edge exists in only one regime, that's a smaller addressable trading window — accept it, don't paper over it.
4. **Auto-disable on regime detection**: if regime classifier flips to "we're now in a state where the strategy underperformed historically," reduce position sizing or pause. Better: make this an explicit decision rule, written down.
5. **Re-train cadence**: monthly walk-forward refit. Model staleness is the silent regime-mismatch killer; see Pitfall 14.

**Warning signs:**
- Walk-forward training windows all look similar (same regime) → invalid validation.
- Out-of-sample performance correlates with BTC trend → regime-conditional edge.
- Recent live performance diverges from backtest in a particular direction during a regime move → regime blindness confirmed.

**Phase to address:** Phase 2 (regime features in baseline) and Phase 5 (re-train cadence + circuit breaker).

---

### Pitfall 11: Stale websocket / silent data starvation (signal fires on yesterday's price)

**Severity:** CAPITAL — bot trades based on stale data, especially during the high-volatility moments the strategy targets.

**Research vs production:** Pure production. ccxt issue #27253 specifically calls out MEXC `watch_ohlcv` hangs.

**What goes wrong:**
- MEXC websocket connection silently dies; ccxt's reconnect logic occasionally misfires.
- Last update time is 30 minutes ago but no exception is raised.
- Signal pipeline operates on the cached last value → "current" price is wrong → enters position based on phantom signal → wakes up to a 10% adverse move.

**Why it happens:**
- Websocket libraries treat "no recent messages" as fine — TCP keepalive may still be working.
- ccxt Pro's `watch_*` methods can hang on MEXC specifically (documented in [ccxt#27253](https://github.com/ccxt/ccxt/issues/27253)).
- No heartbeat assertion in the consumer loop.

**How to avoid:**
1. **Per-symbol last-update-time gauge**, exposed to Prometheus. Alert if `now - last_update > 30s` for an active universe symbol.
2. **Per-process freshness assertion at signal time**: before computing a signal, assert the most recent candle close is within ≤ 2 × candle_interval of now. Refuse to trade if stale.
3. **Use `watch_trades` + client-side candle aggregation**, not `watch_ohlcv` (ccxt's MEXC OHLCV stream is the documented hang point; trades stream is more reliable).
4. **Heartbeat ping loop**: every 30s, post a synthetic ping → expect echo within 5s, otherwise reconnect.
5. **Cross-check against REST**: every 60s, fetch the last candle via REST for a single symbol and compare to websocket-derived value. If they diverge > 0.5%, websocket is stale.
6. **On reconnect, replay-backfill the gap**: REST `fetch_ohlcv(since=last_seen_close_time)` before resuming signals.

**Warning signs:**
- Bot trades during a known exchange-wide event but Prometheus shows zero new candles in last 5 minutes.
- Logs show no errors but signal frequency dropped to zero.
- Sentry shows "no errors in 24h" while Telegram shows no signals — both should be raising alarms.

**Phase to address:** Phase 1 (ingest health metrics) and Phase 5 (pre-signal freshness assertion).

---

### Pitfall 12: API rate limit hit mid-pump → signal lost

**Severity:** CAPITAL (opportunity) — you correctly identified the setup, the bot tried to enter, MEXC threw 429, position never opened. Worse: it sometimes partially opened.

**Research vs production:** Pure production.

**What goes wrong:**
- MEXC futures rate limits per [MEXC API docs](https://www.mexc.com/api-docs/futures/account-and-trading-endpoints): 20 req/s for order endpoints, 10 req/s elsewhere.
- During a pump, your bot polls candles, ticker, book, position, account, then fires an order. Bursty.
- ccxt's built-in throttler queues requests — a 429 may not happen, but the order may queue behind 5 seconds of polling requests and miss the entry window.
- Coinglass Startup tier: 80 req/min. Easy to blow if you naively poll funding/OI for 200 symbols.

**How to avoid:**
1. **Priority queue for outbound API calls**: order placement is `priority=HIGH`, market data polling is `LOW`. Bypass throttle for HIGH-priority calls (within hard limit).
2. **Pre-trade budget reservation**: when a signal fires, reserve 5 API requests in the bucket before sending the first; if budget insufficient, log + alert + skip the signal (better to miss than half-execute).
3. **Per-endpoint budgets**, not one global budget. ccxt's `enableRateLimit` is global; for fine control, layer `aiolimiter` per endpoint group.
4. **Websocket-first data flow**: book + trades + account updates via websocket subscription, REST polling only for things that aren't streamed. Cuts REST volume 90%+.
5. **Coinglass batch endpoints**: use `/api/futures/funding-rate-list` (one call returns all symbols) instead of per-symbol polling. Confirms within Coinglass Startup 80 req/min budget.
6. **Track rate-limit headers**: MEXC returns remaining quota; ingest into Prometheus; alert at < 20% remaining.

**Warning signs:**
- ccxt logs `Throttled` messages preceding signal failures → throttler is delaying critical orders.
- 429 responses in Sentry → already exceeded; need budget headroom.
- Signal-to-order latency > 2s on average → polling is starving order endpoint.

**Phase to address:** Phase 1 (per-endpoint budget tracking) and Phase 5 (priority queue for live).

---

### Pitfall 13: Stop-loss too tight for crypto volatility OR stops fill nowhere near intended

**Severity:** CAPITAL — common death-by-a-thousand-cuts.

**Research vs production:** Both. Backtest models stop fills perfectly; live is messier.

**What goes wrong:**
- Tight stops (0.5–1%): on memecoin perps with 5–15% intraday range, you get stopped repeatedly on noise even when the directional thesis is correct.
- Loose stops (3–5%): drawdown per trade dominates Kelly sizing — your "edge" can't survive the implied position size shrink.
- Stop trigger price ≠ fill price: market-stop on a thin book during a cascade fills 1–5% away from the trigger.
- Stop placed as `stopMarket` is sometimes rejected by MEXC during halts or extreme volatility (rare but exists).

**How to avoid:**
1. **Stop distance proportional to ATR**, not a fixed %. e.g., `stop = entry + k * ATR(14, 5m)` with k tuned per regime. Hardcoded % stops are wrong.
2. **Stop fills modeled as slippage from trigger price** in backtester (book-walk against bid side), never at trigger price exactly.
3. **Time-based stop in addition to price-based**: if position open > X minutes without progress, close manually. Doesn't rely on exchange stop logic.
4. **Validate stops are accepted at order placement**: when sending the parent + stop pair, confirm both `info.status` from MEXC. Refuse to keep position open if stop rejected.
5. **Daily-loss circuit breaker** as a backstop to per-trade stops. Per-trade stops are easy to misconfigure; the daily breaker is the safety net.

**Warning signs:**
- Stop-out rate > 60% in backtest → stops are tighter than noise; either widen or expect false-positive losses.
- Average loss > average stop distance → fills are bad; slippage model needs work.
- All losing trades occur near "round" levels (0.5%, 1.0%) → fixed % stops, switch to ATR.

**Phase to address:** Phase 2 (ATR-based stops in backtester) + Phase 4 (paper validation of stop fills).

---

### Pitfall 14: Kelly applied to overestimated edge → ruin

**Severity:** CAPITAL — quarter-Kelly mitigates but doesn't eliminate. The bigger issue: leaked/biased backtest produces inflated edge estimate → "quarter" of inflated edge is still too large.

**Research vs production:** Both, compounded. Inflated estimate is a research error; ruin is the production result.

**What goes wrong:**
- Backtest claims +0.8% expected return per trade with 0.5% std-dev → Kelly says "huge position." Reality: actual edge is +0.1% / 0.5% std (5x smaller). Quarter-Kelly of phantom 0.8% = full-Kelly of real 0.2% → guaranteed ruin given any sustained losing streak.
- Edge estimate doesn't account for the regime/survivorship/leakage biases already discussed.

**How to avoid:**
1. **Edge estimate uses out-of-sample only — never the training fold.** Backtester reports OOS PnL stats separately and conspicuously.
2. **Apply confidence-interval shrinkage**: lower-bound of the 95% CI of historical edge, not the mean. (Better: bootstrap CI from OOS trades.)
3. **Quarter-Kelly is the SCALE FACTOR ON A BIAS-CORRECTED EDGE ESTIMATE**, not a cure for biased estimates. Documented in `risk.py` with the formula.
4. **Hard position-size cap** independent of Kelly: max 5% of account per trade, max 15% gross exposure across positions. Kelly can only suggest smaller.
5. **Live edge tracking**: after 30 live trades, compare realized edge to backtested edge. If realized < 50% of backtested, recalibrate sizing immediately downward.
6. **Drawdown circuit breakers** in addition to per-trade caps: pause trading after 5% account drawdown in a week; halt after 10%; manual restart required.

**Warning signs:**
- Sharpe in backtest > 3 → almost certainly biased; trust the position-size cap, not Kelly.
- Backtested edge > 1% per trade after fees on memecoin perps → suspicious; sanity check feature engineering.
- Live realized edge after 30+ trades < 30% of backtest → sizing is over-leveraged for true edge.

**Phase to address:** Phase 2 (edge estimation with CI) + Phase 3 (Kelly formula with caps documented in `risk.py`) + Phase 5 (live edge tracking circuit breaker).

---

### Pitfall 15: Funding rate surprise — negative funding on shorts during quiet markets

**Severity:** CAPITAL (moderate) — turns a flat trade into a slow bleed.

**Research vs production:** Both — easy to forget in backtest; surprising in production.

**What goes wrong:**
- Post-pump positions held across funding settlement (8h on MEXC) → short pays funding when funding > 0 (typical after pumps — longs paid premium, so funding > 0 → shorts collect). But on coins where reversal is slow, funding flips negative → short PAYS.
- Backtest doesn't model funding cash flows → P&L overstated by funding paid OR understated when funding earned (depending on regime).

**How to avoid:**
1. **Backtester ALWAYS marks positions to funding at every funding window crossing.** Apply realized funding flow (positive = paid to position, negative = paid from position).
2. **Funding rate stored separately from price data** with `settlement_ts` and per-symbol cadence (MEXC mostly 8h, some pairs differ).
3. **Position-holding-time horizon awareness**: if average holding time > 4h, funding matters; design strategy to either close before funding or include funding sign as a feature (negative funding on short = good).
4. **Daily funding P&L attribution report** in paper trading and live — sums funding payments separately from price PnL.
5. **Don't double-count**: MEXC funding feed and Coinglass aggregate funding are DIFFERENT (Coinglass aggregates across exchanges). Use MEXC's own feed for backtest of MEXC trades. Pitfall 16 details this.

**Warning signs:**
- Backtest P&L > live P&L by a near-constant amount per day → unmodeled funding outflow.
- Funding column missing from trade ledger → instant red flag.
- "Profitable" trades that were actually flat after funding subtraction → backtest was lying.

**Phase to address:** Phase 1 (funding ingestion with schemas) + Phase 2 (backtester models funding) + Phase 4 (paper trading reports funding P&L separately).

---

### Pitfall 16: Confusing Coinglass aggregate funding/OI with MEXC-specific values

**Severity:** RESEARCH-INVALID — silent.

**Research vs production:** Pure research, but corrupts everything downstream including live.

**What goes wrong:**
- Coinglass `/api/futures/funding-rate-list` returns BTC funding aggregated across Binance, Bybit, OKX, MEXC, etc. You back-test "MEXC short when funding > +0.05%" using Coinglass aggregate funding → the value differs from MEXC's own.
- Open interest: Coinglass aggregate OI is a sum/average across venues — divergence from MEXC's own OI can be 20%+.
- In live, your signals fire on aggregate values that bear no relation to what's happening on the exchange you actually trade on.

**Why it happens:**
- Coinglass docs are not always explicit about aggregation.
- Schema lazily uses one `funding_rate` column with no source attribution.

**How to avoid:**
1. **Schema mandates `source` column on every derivatives row**: `mexc_funding`, `coinglass_aggregate`, `coinglass_mexc_only` (Coinglass also provides per-exchange breakdowns). Featurize them as separate features if both are useful.
2. **Default policy**: train/trade on MEXC's own funding/OI for the symbol traded; use Coinglass aggregate only as a cross-exchange signal feature (e.g., "MEXC funding extreme relative to aggregate" = potentially mispriced).
3. **Schema validation test**: every funding row must have `source IS NOT NULL`. CI gate.
4. **Documented in `DATA_DICTIONARY.md`**: which features use which source, with rationale.

**Warning signs:**
- Feature importance dominated by "funding" when source is ambiguous → likely a leak via wrong source.
- MEXC funding column and Coinglass funding column have correlation < 0.95 for the same symbol → that's expected; treat them as different features.

**Phase to address:** Phase 1 (schema design with source attribution).

---

### Pitfall 17: Time zone bugs (UTC vs MEXC server time vs local time)

**Severity:** RESEARCH-INVALID + OPS — subtle until it isn't.

**Research vs production:** Both.

**What goes wrong:**
- Backfilling from Coinglass returns naive datetimes that look UTC but are exchange-local for some endpoints (varies by endpoint). Off-by-8h on Asia-hosted exchanges.
- MEXC funding windows: 00:00 / 08:00 / 16:00 UTC. Code that schedules "every 8h starting now" drifts.
- Server clock on Railway not NTP-locked → trade signed with timestamp that fails MEXC's recv_window check (5s default).

**How to avoid:**
1. **All datetimes UTC, all timezone-aware, schema enforces `TIMESTAMPTZ` in Postgres.** Naive datetime → schema validation fail.
2. **Pydantic models reject naive datetimes** at all boundaries (API responses, file imports).
3. **Funding window scheduler uses pinned UTC anchors** (`00:00`, `08:00`, `16:00`) regardless of when the bot starts.
4. **Time sync check at startup**: query MEXC server time, compare to local `datetime.utcnow()`, fail-fast if drift > 1s.
5. **Periodic time-sync gauge**: Prometheus metric `time_drift_seconds`; alert at > 0.5s. NTP can fail silently on managed hosts.
6. **freezegun in every time-sensitive test**, with explicit UTC tzinfo.

**Warning signs:**
- MEXC returns `"recv window exceeded"` or `"timestamp expired"` errors → clock drift.
- Funding cash flows applied at wrong day → tz bug in storage.
- Off-by-N-hour patterns in features (some symbol's "midnight" doesn't match others) → mixed tz sources.

**Phase to address:** Phase 1 (schema enforcement) + Phase 1 (startup time sync) + Phase 5 (periodic drift gauge).

---

### Pitfall 18: Hyperparameter overfitting via too many Optuna trials on the same test set

**Severity:** RESEARCH-INVALID — produces a hyperparameter set that's specifically tuned to the OOS noise.

**Research vs production:** Pure research.

**What goes wrong:**
- Run Optuna with 1,000 trials on a walk-forward CV. Best trial has unusually high score. You ship that. Live performance regresses to the mean.
- This is "selection on noise" — by trying enough configurations, one will look great by chance.

**How to avoid:**
1. **Three-set protocol**: train → validation (Optuna search target) → holdout (never touched until ONE final evaluation).
2. **Cap Optuna trials**: 100–200 trials max for boosters with TPE + median pruner. More trials = more selection-on-noise risk. Document the budget upfront.
3. **Stability test**: take top-5 Optuna trials by validation score; compare their holdout scores. If holdout rank order doesn't match validation rank order, you're selecting on noise.
4. **Multiple seeds for the final model**: train the chosen hyperparameter set with 5 different seeds; if variance across seeds is comparable to the gap between candidate hyperparameter sets, you don't actually have a winner — you have noise.
5. **Combinatorial purged cross-validation** (López de Prado) provides multiple test paths and a "probability of backtest overfitting" metric. Use for the final candidate before live.

**Warning signs:**
- Top Optuna trial significantly better than top 10 → likely noise.
- Holdout score < validation score of the same trial by > 20% → noise selection.
- Optuna study converged to hyperparameters at the boundary of the search space → search wasn't wide enough OR you're chasing noise at the edge.

**Phase to address:** Phase 2 (ML methodology) — specifically the protocol for going from Optuna to production model.

---

### Pitfall 19: No kill switch / no daily loss circuit breaker

**Severity:** CAPITAL — bot misbehaves, nobody home, account drains.

**Research vs production:** Pure production. The Knight Capital scenario, scaled down.

**What goes wrong:**
- Strategy bug opens a position, signal generator gets stuck in a loop, position size escalates → margin call cascade.
- Or: model breaks down silently (regime change), strategy enters consistently losing trades, no automatic stop.
- Manual kill takes minutes when seconds matter. By the time you SSH in, the damage is done.

**How to avoid:**
1. **Telegram kill switch command** (`/halt`) handled by a dedicated handler that calls `cancel_all_orders` + `close_all_positions` (with `reduceOnly=True`) and sets a `paused: true` flag in Redis/Postgres. The bot refuses to trade while paused. Tested monthly.
2. **Daily PnL circuit breaker**: at every position close, compute realized + unrealized PnL since UTC midnight. If < `-MAX_DAILY_LOSS_PCT * account_equity`, set paused.
3. **Per-trade-burst circuit breaker**: if N consecutive losing trades or X% drawdown in the last hour, pause.
4. **Order-rate circuit breaker**: if order rate > expected by 3x, pause — runaway bug.
5. **Heartbeat dead-man switch**: if the controller hasn't pinged in 5 minutes, an external Railway cronjob (separate service) cancels all orders.
6. **The kill switch service runs on a DIFFERENT Railway service** with its own deploy lifecycle than the trading bot — deploying the bot can't accidentally take down the kill switch.

**Warning signs:**
- "I'll add the kill switch later, after the strategy works" → never do this. Add it before the first live trade.
- Kill switch hasn't been tested in 30 days → broken without you knowing.
- No daily-loss circuit breaker active in `risk.py` → instant red flag.

**Phase to address:** Phase 5 (live) — but **kill-switch code skeleton exists from Phase 4 (paper)** and is tested against paper trading.

---

### Pitfall 20: Solo-dev premature optimization (building infra before edge is proven)

**Severity:** ANNOY → eventually CAPITAL (opportunity cost of months wasted).

**Research vs production:** Process-level.

**What goes wrong:**
- 3 months in: beautiful dashboard, Grafana panels, k8s Helm charts, Prefect DAGs, custom backtesting engine, monitoring observability stack. Strategy has not been validated. Solo developer is exhausted.
- Or: building the next strategy (#2, #3) before #1 has paper-traded for a month.
- Or: porting to ClickHouse before TimescaleDB has been measured against its limits.

**Why it happens:**
- Infrastructure work is concrete; strategy validation is uncertain and frustrating.
- "It'll be needed eventually."
- YAGNI is hard to enforce solo (no PR review).

**How to avoid:**
1. **Roadmap-level: edge validation gate.** No Phase-3+ infra work until paper trading shows OOS-positive EV for ≥2 months. Written into milestone exit criteria.
2. **One strategy at a time.** Strategy #2 not even discussed until #1 is in live signal-only mode.
3. **Dashboard last, not first.** Grafana panels live only after live trades are flowing; before that, structured logs + ad-hoc Polars queries are enough.
4. **Stop optimizing the backtester once it answers the question** — "is there OOS edge after fees/slippage?" — even if the code is ugly.
5. **TDD discipline as a focus tool**: writing the test forces "what does this need to do?" before "what could it do?".
6. **Honest weekly self-review**: "did this week's work advance edge validation or infrastructure?" Two infrastructure weeks in a row → red flag.

**Warning signs:**
- Branch with `feat/observability` open for 2+ weeks while no model training has happened.
- "I rewrote the backtester for the third time" → freeze it.
- Considering ClickHouse migration before TimescaleDB is at 80%+ disk full or query latency > 1s → premature.

**Phase to address:** Roadmap discipline (every phase exit criteria). Specifically: no Phase 6+ work until Phase 4 paper EV-positive.

---

## Important But Not Fatal Pitfalls

### Pitfall 21: Backfill data quality issues — exchange downtime gaps, partial candles

**Severity:** OPS / RESEARCH-INVALID

**What goes wrong:**
- MEXC outages leave gaps in 1m candle history. Backfilling from REST returns NULL or skipped buckets.
- Backfill via `fetch_ohlcv(since=...)` capped at 1000 rows per request → naive loop can desync timestamps on retries.
- Some Coinglass historical caps: 1m candles only 6–12 days on lower tiers (per current Coinglass pricing, see STACK.md). 1–2 year backfill of 1m derivatives features impossible on free/hobbyist tiers.

**How to avoid:**
1. Detect gaps post-ingest: assert that for every symbol, `count(*) per UTC day >= expected - allowed_missing_pct`. Alert on violations.
2. Three-way reconcile: MEXC REST + websocket-derived + (optionally) a second public archive. Mark missing rows with a `quality_flag` column rather than interpolating.
3. Coinglass: accept the constraint — 1m derivatives features can only use a rolling window. Stash longer-horizon derivatives at 5m or 1h.
4. Document expected coverage per source in `DATA_DICTIONARY.md`: "MEXC 1m candles: ≥99.5% expected; gaps flagged. Coinglass 1m funding: rolling last 12 days only."

**Warning signs:**
- Sudden distribution shifts in features around specific dates → ingestion gap; not a real regime change.
- Models trained on different runs of backfill produce different results → backfill non-deterministic.

**Phase to address:** Phase 1.

---

### Pitfall 22: Order book snapshot vs trade tape mismatch

**Severity:** RESEARCH-INVALID for backtest fidelity.

**What goes wrong:**
- Backtester uses snapshot book taken every 5s; trades happen continuously. A trade between snapshots can move the book substantially. Backtester thinks the book at signal time was X; reality was X ± significant.
- For short-after-pump strategy: pumps eat through ask depth; snapshot at T may be pre-pump, trade at T+1s is during pump.

**How to avoid:**
1. Pair snapshots with trade tape; reconstruct effective book at any T by applying intervening trades.
2. Higher snapshot frequency for active universe (1–5s during volume spikes).
3. Diagnostic: backtester output reports per-trade "snapshot age" — if > 5s on most trades, your simulation is too coarse.

**Phase to address:** Phase 1 / Phase 2.

---

### Pitfall 23: Margin insufficient → order rejected during pump

**Severity:** CAPITAL (opportunity) + ANNOY.

**What goes wrong:**
- Bot tries to open short during a pump; margin calculation didn't account for the price move since last position fetch. MEXC rejects with `insufficient margin`. Position not opened, signal lost.
- Or: position opened at one size, additional add-on at another size → second order rejected.

**How to avoid:**
1. Pre-trade margin reservation: compute required margin using current mark price + 2% buffer.
2. Check available balance via fresh `fetchBalance` immediately before order placement.
3. Treat `insufficient margin` as a configuration error, not a market issue — pause and alert if it happens > 1x/day.
4. Leverage tier awareness: MEXC futures have per-symbol max leverage; verify symbol's current tier before sizing.

**Phase to address:** Phase 5.

---

### Pitfall 24: Model staleness — training data 6 months old

**Severity:** RESEARCH-INVALID → CAPITAL.

**What goes wrong:**
- Model trained in January, still running in June. Crypto regime shifted twice. Edge is gone but bot still trades.
- No retraining cadence → silent decay.

**How to avoid:**
1. Monthly re-fit cadence, automated via APScheduler/Prefect.
2. Champion/challenger: new model trained monthly competes against current; promote only if challenger beats champion OOS by > threshold.
3. Live-vs-backtest performance tracker — if 30-day live deviates from expected by > 2σ, auto-pause and demand human re-evaluation.
4. Model registry (MLflow) with explicit `current_production` tag; rollback to previous version is a one-command operation.

**Phase to address:** Phase 5.

---

### Pitfall 25: Schema migration in production breaking historical reads

**Severity:** OPS → potentially RESEARCH-INVALID if you can't reproduce results.

**What goes wrong:**
- Alembic migration renames a column or changes a dtype. Queries that pull historical data for backtesting now break. Or worse, silently return wrong types (Decimal→Float coercion losing precision).
- Hypertable migrations on TimescaleDB have specific rules — adding columns to a hypertable is OK; renaming requires care; changing partition column is hard.

**How to avoid:**
1. **Additive migrations only** during data-platform phase. New columns nullable, defaults set. Never drop or rename.
2. **Versioned schemas in queries**: data access layer pins the column names used; if a migration adds a column, code doesn't break.
3. **Backup before every migration**: Railway Postgres → manual snapshot before any `alembic upgrade head` in production.
4. **Reproducibility test**: backfill a known-good 1-week period of data into a fresh DB; verify backtest output exactly matches a recorded reference.
5. **TimescaleDB-specific**: continuous aggregates need refresh policies after underlying table changes; don't forget the `CALL refresh_continuous_aggregate(...)` step in migrations.

**Phase to address:** Phase 1 (schema discipline) onward.

---

### Pitfall 26: Backup strategy missing — lose ingestion data

**Severity:** OPS (high) — re-backfilling 1–2 years of MEXC + Coinglass would take days and cost API quota.

**What goes wrong:**
- Railway Postgres volume deleted accidentally, or service deleted, or you migrate plans.
- No off-Railway backup → 1–2 years of ingestion gone.

**How to avoid:**
1. Daily `pg_dump` to a separate Railway volume or external S3/B2 bucket (Cloudflare R2 is cheap).
2. Weekly full snapshots; retain 4 weeks.
3. Monthly archive to cold storage (Backblaze B2 is ~$5/TB/mo).
4. Restore drill: once a quarter, restore the latest backup to a scratch DB and verify counts + sample queries.
5. Critical for ingestion data: write daily archives of raw API responses (Parquet on Railway volume) — even if DB dies, raw responses survive.

**Phase to address:** Phase 1.

---

### Pitfall 27: Silent task failures from `asyncio.create_task` without tracking

**Severity:** OPS → CAPITAL (if a critical task dies silently).

**What goes wrong:**
- Fire-and-forget `asyncio.create_task(ingest_funding())` — coroutine raises, task is garbage-collected, exception silently swallowed (or only logged as a warning that nobody sees).
- Equivalent in production: ingestion stops, no alert, model trains on stale data tomorrow.

**How to avoid:**
1. **Use `asyncio.TaskGroup`** (Python 3.11+) for structured concurrency — exceptions propagate.
2. For long-lived background tasks, keep a reference and add `task.add_done_callback(handle_task_exception)` that logs + alerts.
3. APScheduler 4.x has `event listeners` for `JOB_ERROR` — wire them to Sentry/Telegram.
4. Heartbeat per critical task: every task writes "last alive" timestamp to Postgres; cron alerts on staleness.

**Phase to address:** Phase 1.

---

### Pitfall 28: Paper-trading fills better than live would (lookahead in paper)

**Severity:** RESEARCH-INVALID — paper "passes" the live gate, live underperforms.

**What goes wrong:**
- Paper simulates fills using the candle close immediately after signal time → fills are slightly forward-looking. Live wouldn't see this price.
- Paper assumes maker fills when in reality you'd cross the spread.
- Paper has zero network latency; live has 50–500ms data→signal→order latency.

**How to avoid:**
1. **Paper trading uses the SAME book-walk slippage model as the backtester** — no shortcuts. Fills against the live order book at signal-time (top-of-book + book-walk).
2. **Inject artificial latency in paper**: 200–500ms delay from signal generation to "order placed" → "fill recorded against book at fill_time = signal_time + latency".
3. **Maker/taker classification rule** identical to live: paper limit order at price X gets maker iff X is on passive side of spread at fill_time, else taker.
4. **Paper-vs-backtest reconciliation**: paper PnL should match backtest PnL ± 10% over the same period. If not, one of them is wrong.

**Phase to address:** Phase 4 (paper trading methodology).

---

### Pitfall 29: Survivorship in paper period — keeping only profitable model versions

**Severity:** RESEARCH-INVALID — same selection-on-noise pattern as hyperparameter overfitting but at the strategy level.

**What goes wrong:**
- Run 5 model versions in parallel paper trading. Keep the best. Go live. Live regresses to mean.
- "Soft restart" the bot whenever it loses → only good streaks make it to live.

**How to avoid:**
1. **Pre-register the model version that goes live BEFORE paper trading starts.** No mid-paper switching to the winner.
2. **One model in paper at a time** (or many in parallel but evaluated as a multi-model committee, not "pick the best").
3. **Documented gate**: paper EV must be positive after fees over ≥2 months, ≥N trades, with specific Sharpe and max-DD limits. Failure → back to research, not "try another model."

**Phase to address:** Phase 4.

---

### Pitfall 30: Building dashboard before edge is proven

**Severity:** ANNOY (time-sink) — see Pitfall 20 for the general pattern; this is the most common specific case.

**What goes wrong:**
- "I need to see my trades" → Grafana panels, then beautiful equity curves, then drawdown waterfall, then per-symbol attribution. Two weeks gone, zero new signals tested.

**How to avoid:**
1. For Phase 1–3, output = Polars + Jupyter + structured logs. No dashboards.
2. Grafana enters at Phase 5 (live) when actual observability matters.
3. Telegram alerts are dashboards-lite — they're enough for the paper-trading phase.

**Phase to address:** Roadmap ordering — defer dashboard work explicitly.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use raw ccxt without paper/live abstraction | Faster to first trade | Paper-live divergence; can't swap to NautilusTrader cleanly | Never for execution; OK for ingest-only |
| Hardcode fees in backtester | Saves 10 min | Wrong P&L when MEXC changes fees; silent strategy regression | Never; trivial to centralize |
| Single MEXC API key for ingest + trade | One env var | Compromise drains account | Never once trading goes live |
| Skip universe snapshot ingestion in Phase 1 | Less code | Cannot reconstruct historical universe; survivorship bias permanent | Never |
| Skip L2 book snapshots in Phase 1 | Less storage | No realistic slippage model; backtest unreliable | Never |
| Use sklearn `TimeSeriesSplit` | Comes for free | Leak via no purge/embargo; OOS scores wrong | Maybe for "is the pipeline even running" smoke tests; never for model selection |
| Naive `class_weight='balanced'` for imbalanced labels | One-liner | Over-aggressive false-positive rate; live unprofitable | Only as Optuna search option, not default |
| Defer kill switch | Faster to first live trade | Account drained on first bug | Never |
| Defer secrets rotation | "I'll do it later" | Same | Never |
| Defer time-zone discipline | "It's all UTC anyway" | Off-by-8h on Coinglass; data invalid | Never; cheap to enforce upfront |
| Polars-only pipeline (skip pandas boundary) | Cleaner | XGBoost/sklearn incompatibility; rework when modeling | Acceptable if model boundary is conversion only |
| Inline notebooks → production | Fast | Notebook code paths diverge from prod silently | Notebooks for EDA only; production imports nothing from `notebooks/` |
| Self-host MLflow without backups | $0 | Lose experiment history | OK while experiments are recent; back up monthly |
| Custom backtester instead of NautilusTrader | Avoid 1.x API churn | Maintain backtester forever | Acceptable until strategy proven; Nautilus once stable |
| Single Railway service for ingest + signal + execution | Simpler | Deploys can interrupt open positions | Acceptable Phase 1–4; MUST split before live |
| No CI gate on type checking | Faster commits | Type errors slip in; runtime KeyError in trading hot path | Never; pyright/mypy is non-negotiable |
| Skip Hypothesis property tests | "Unit tests are fine" | Misses look-ahead leaks; misses size-cap edge cases | Never for trading invariants |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| MEXC REST | Polling per-symbol when batch endpoints exist | Use batch endpoints; websockets where possible |
| MEXC websocket | Using `watch_ohlcv` directly | Use `watch_trades` + client-side aggregation ([ccxt#27253](https://github.com/ccxt/ccxt/issues/27253)) |
| MEXC orders | Closing position without `reduceOnly=True` | Mandatory wrapper sets `reduceOnly` on intent='close' |
| MEXC orders | Assuming hedge mode vs one-way mode | Assert position mode at startup; refuse to start otherwise |
| MEXC fees | Hardcoded 0.05% taker | Read from ccxt + `fees_override.yaml` with effective dates |
| MEXC time sync | Local clock used to sign | Sync to MEXC server time at startup; periodic drift check |
| MEXC rate limits | Single global throttle | Per-endpoint budgets; priority queue for order calls |
| MEXC listings | Static universe | Daily universe snapshot; persist delisted symbols |
| Coinglass funding | Using aggregate as MEXC-specific | Tag every row with `source`; use MEXC's own feed for trading MEXC |
| Coinglass tiers | Free tier in production | Minimum Coinglass Startup ($79/mo); Standard ($299/mo) for >12d 1m derivatives |
| Coinglass rate limits | Bursting on hourly cron | Persistent token-bucket via `aiolimiter`; batch endpoints |
| CoinGecko | Per-symbol calls when batch exists | `/coins/markets` returns 250 per call; cache aggressively |
| CoinGecko | Free tier hits 30/min in normal use | Daily universe refresh, not per-tick |
| Railway | Single deploy unit for all services | Split ingest/signal/execution into separate services pre-live |
| Railway secrets | Using `.env` instead of Railway Variables | Railway Variables only; `.env.example` placeholders in repo |
| Railway Postgres | No automated backups | Daily pg_dump to external storage (R2/B2) |
| ccxt | Pinning to latest minor without testing | Pin to exact minor; gate upgrades behind paper smoke test |
| MLflow | SQLite backend in production | Postgres backend (same Railway instance) |
| Optuna | RDB-less in-memory storage | Postgres-backed storage; resumable studies |
| Telegram | Plain text alert messages with no formatting | Structured messages with trade context (symbol, size, PnL, links) |
| GitHub Actions | Tests without DB | Use Railway preview environments OR docker-compose Timescale in CI |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| pandas in ingest hot path | Ingestion lag > 1s, CPU spikes | Polars for batch, asyncpg COPY for bulk inserts | Universe > 50 symbols streaming |
| SQLAlchemy ORM for hypertable inserts | Insert throughput < 1K rows/s | Use SQLAlchemy Core or raw asyncpg COPY | Active streaming on 100+ symbols |
| Per-row insert | TimescaleDB write amplification, disk fills | Batch inserts (100–1000 rows), use COPY | Anywhere >100 rows/min |
| Continuous aggregates without policies | Stale rollups; queries slow | Define `add_continuous_aggregate_policy` with start/end/schedule | After first month of data |
| No TimescaleDB compression | DB size 5–10x larger than needed | `ALTER TABLE ... SET (timescaledb.compress=true)`; compression policies | After 30d of candle data |
| Polars `df.collect()` on full lazy chain in tight loop | Memory spikes, slow | Streaming engine; chunk by date range | Backfill across multi-year history |
| `pd.read_sql` on full history | OOM | Stream via server-side cursor; chunk by date | Multi-year historical reads |
| XGBoost `tree_method='exact'` | Training 10x slower than `hist` | `tree_method='hist'` is the default in 3.x; verify | Feature matrix > 100K rows |
| Optuna trials without pruner | Wasted compute on bad trials | `MedianPruner` or `HyperbandPruner`; report intermediate scores | Trials > 50 |
| Per-trade ccxt call to refresh position | Latency spikes, rate limit pressure | Maintain local position cache from order updates websocket | When `position_count > 5` concurrent |
| `print()` instead of structured logging | Logs unsearchable in Grafana/Loki | `structlog` with JSON output | From day 1 |
| MLflow local file backend | Concurrent runs corrupt store | Postgres backend | Multiple training runs in parallel |
| Single asyncio task pulling all data | Sequential bottleneck | `asyncio.TaskGroup`; per-symbol tasks with concurrency cap | Universe > 20 symbols |
| Loading full DB to memory for backtest | OOM | Range scan + streaming feature pipeline | Backtest period > 1 month at 1m granularity |
| Naive cron scheduling overlap | Two jobs of the same type running concurrently | APScheduler `max_instances=1`; Postgres jobstore for distributed lock | Long-running jobs |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Withdraw permission on trading key | Total account loss on key compromise | Never enable withdraw on bot keys |
| Single key for ingest + trade | Wider blast radius on compromise | Two keys: read-only for ingest, trade-only for execution |
| Key in `.env` committed to git | Permanent leak (GitHub indexes everything) | `.gitignore` `.env*`; pre-commit secret scanner; GitHub secret scanning enabled |
| Key in logs / Sentry breadcrumbs | Leak via observability stack | structlog redaction processor; `ccxt.verbose = False` in prod |
| Key in ccxt verbose mode | Logs include full signed URL | Disable verbose mode in production |
| Long-lived keys | Replay potential | Rotate every 90 days; document rotation date in `OPS.md` |
| No IP allowlist | Anyone with the key can trade from anywhere | MEXC supports IP allowlist; use Railway egress IP (verify it's stable) |
| Public Railway service URL | Anyone can hit your control endpoints | All control endpoints require auth; private service-to-service tokens |
| Telegram bot token in repo | Bot impersonation | Railway Variables; revoke via @BotFather on leak |
| MLflow exposed publicly | Model weights + training data exposed | MLflow behind auth (basic auth or Railway private networking) |
| Postgres exposed to internet | DB compromise → trading history, keys-in-tables (don't do this either!) | Railway private networking; no public endpoint |
| No kill switch | Bug → drain | Telegram `/halt` + dead-man switch service |
| No audit log of trade decisions | Can't reconstruct what bot did when things go wrong | Append-only `trade_decisions` table with `signal_id, model_version, features_hash, action, params` |
| Production = dev environment | One bug breaks live | Separate Railway projects: `shortfire-dev` and `shortfire-prod`; promote via tagged releases |
| Manual SQL on production | Wrong UPDATE = data loss | All schema changes via Alembic migrations; manual queries via PgAdmin read-only role |
| No 2FA on MEXC account | Account compromise | Enable 2FA; recovery codes printed and offline |

---

## UX Pitfalls (Solo Operator UX)

| Pitfall | Operator Impact | Better Approach |
|---------|----------------|-----------------|
| Telegram alert spam | Alerts ignored when real one fires | Severity-tagged channels: `#info` (signals), `#warn` (drawdown), `#critical` (halt). Mute info channel during deep work. |
| No context in alerts | "Trade closed" — what trade? | Every alert: symbol, side, size, entry, exit, P&L, link to trade detail |
| Signal-only mode flooded with too many signals to track | Manual mode useless | Top-N signals per day cap; daily digest of all signals at fixed time |
| No confirmation in semi-auto | Tap wrong button on phone | Two-step confirm in Telegram: signal → "confirm /yes /no" → execution |
| No way to inspect why a signal fired | Trust gap; can't validate | SHAP per-trade attribution attached to every signal in Telegram (top-5 features) |
| Bot trades while operator is asleep without limits | Wakes to drawdown | Off-hours position size cap; or off-hours pause toggle in Telegram |
| Dashboard requires laptop | Slow to respond on phone | Telegram is the primary interface; dashboard is post-mortem only |
| Logs only in Grafana | Slow lookup during incident | Critical alerts include log links; Telegram message is itself the log line |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Ingest pipeline:** Often missing **universe snapshots** — verify daily snapshot of `load_markets()` is being persisted and queryable.
- [ ] **Ingest pipeline:** Often missing **L2 book snapshots** — verify top-20 levels at ≥5s for active universe (not just trades + 1m candles).
- [ ] **Ingest pipeline:** Often missing **gap detection** — verify `count(*) per day per symbol` assertions are running with alerts.
- [ ] **Ingest pipeline:** Often missing **source attribution column** on derivatives data — verify every `funding_rate` row has `source` set.
- [ ] **Backtester:** Often missing **funding mark-to-market** at every funding window — verify funding P&L appears in trade ledger.
- [ ] **Backtester:** Often missing **realistic slippage** — verify book-walk against L2 snapshot, not flat % assumption.
- [ ] **Backtester:** Often missing **stop-loss fill modeling** — verify stops fill via book-walk from trigger price, not at trigger price.
- [ ] **Backtester:** Often missing **fee mode by date** — verify fee table supports valid_from/valid_to.
- [ ] **Walk-forward:** Often missing **purge** — verify training indices have no overlap with test label horizon.
- [ ] **Walk-forward:** Often missing **embargo** — verify training indices >= test_end + label_horizon.
- [ ] **Feature pipeline:** Often missing **causal rolling assertion** — Hypothesis test confirms feature value at T doesn't change if data after T is corrupted.
- [ ] **ML metrics:** Often missing **precision at top-N** — verify the operating metric, not just AUC/accuracy.
- [ ] **Model registry:** Often missing **production tag** — verify exactly one MLflow run is tagged `current_production`.
- [ ] **Risk module:** Often missing **daily-loss circuit breaker** — verify it triggers on simulated drawdown.
- [ ] **Risk module:** Often missing **gross-exposure cap** — verify it rejects positions that would exceed cap.
- [ ] **Risk module:** Often missing **correlated-position cap** — verify multiple BTC-correlated memecoins shorted simultaneously are limited.
- [ ] **Execution:** Often missing **`reduceOnly` invariant** — Hypothesis test confirms close orders always have `reduceOnly=True`.
- [ ] **Execution:** Often missing **post-trade position assertion** — verify executor confirms expected position after every order.
- [ ] **Execution:** Often missing **rate-limit priority** — verify order calls bypass low-priority polling queue.
- [ ] **Paper trading:** Often missing **latency injection** — verify paper introduces 200–500ms delay matching live.
- [ ] **Paper trading:** Often missing **same slippage model as backtester** — verify paper-vs-backtest PnL reconciliation runs.
- [ ] **Kill switch:** Often missing **monthly test** — verify `/halt` was last invoked in test mode within 30 days.
- [ ] **Kill switch:** Often missing **dead-man switch service** — verify a separate Railway service cancels orders if controller stops heartbeating.
- [ ] **Secrets:** Often missing **withdraw-disabled assertion** — verify trade key cannot withdraw via test transaction.
- [ ] **Secrets:** Often missing **two-key separation** — verify ingest and trade use different MEXC keys.
- [ ] **Observability:** Often missing **freshness gauge per symbol** — verify Prometheus shows last-update-time per symbol.
- [ ] **Observability:** Often missing **time-drift gauge** — verify `time_drift_seconds` metric is < 0.5s.
- [ ] **Backups:** Often missing **restore drill** — verify within the last 90 days a backup was restored to a scratch DB successfully.
- [ ] **CI:** Often missing **secret scanning** — verify GitHub secret scanning + pre-commit hook block known credential patterns.
- [ ] **CI:** Often missing **type-check gate** — verify pyright/mypy strict mode fails the build on errors.
- [ ] **Schema:** Often missing **TIMESTAMPTZ enforcement** — verify every timestamp column is timezone-aware in Postgres.
- [ ] **Live edge tracking:** Often missing — verify a job compares realized vs backtested edge every N trades and alerts on divergence.
- [ ] **Model staleness:** Often missing — verify retraining cron exists and a "last trained" gauge is monitored.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Survivorship bias discovered post-deployment | HIGH | (1) Reconstruct historical universe from Coinglass delisted lists + any captured snapshots. (2) Identify candidate delisted symbols; backfill what's available. (3) Re-run backfill of universe-aware labeling. (4) Re-train; re-evaluate. (5) Treat as Phase 2 redo. |
| Look-ahead leak discovered | MEDIUM | (1) Add Hypothesis tests for the affected feature. (2) Rebuild feature pipeline with causal-only operations. (3) Re-run walk-forward. (4) If edge survives → ship; if not → strategy invalidated, but at least honestly. |
| Walk-forward done without purging | MEDIUM | (1) Implement purged walk-forward. (2) Re-run hyperparameter search. (3) Compare new OOS to old OOS — gap tells you how biased prior results were. |
| Unrealistic slippage discovered in live | MEDIUM-HIGH | (1) Immediately reduce position size to 30% of prior. (2) Compare 30 days of paper vs live; tune slippage model. (3) Update backtester. (4) Re-evaluate Kelly fraction. (5) Scale back up only after parity. |
| Reduce-only flag missing | HIGH (one event can wipe account) | (1) Immediately halt bot. (2) Manually flatten any unintended positions. (3) Patch `place_order` wrapper. (4) Add Hypothesis invariant. (5) Restart only after paper trading confirms new behavior. |
| Liquidation cascade self-impact | HIGH | (1) Reduce per-symbol size cap; reduce correlated-position concurrency. (2) Re-tune slippage premium for tier-3 symbols. (3) Accept reduced expected edge or exit illiquid tier. |
| API key leaked | CRITICAL | (1) Revoke key in MEXC immediately. (2) Check transaction history. (3) Rotate ALL keys including dependent integrations. (4) Audit how it leaked; fix root cause. (5) Enable IP allowlist; enable 2FA if not on. (6) Forensics on logs/git history. |
| Imbalanced class trap | LOW-MEDIUM | (1) Switch metric to precision@N. (2) Re-tune threshold on holdout. (3) Re-evaluate edge. |
| Regime change | MEDIUM | (1) Pause via daily-loss breaker (should be automatic). (2) Re-train on most recent regime. (3) Add regime feature. (4) Adjust live edge tracker thresholds. |
| Stale websocket | LOW | (1) Restart consumer; reconnect. (2) Replay-backfill the gap. (3) Add freshness assertion if not present. (4) Investigate root cause (ccxt version, MEXC outage). |
| Rate limit hit mid-pump | LOW (per incident) | (1) Implement priority queue if not yet. (2) Reduce polling frequency. (3) Move to websockets. |
| Stop-loss filling far from trigger | MEDIUM | (1) Switch to time-based + ATR-based stops. (2) Reduce per-position size in illiquid tier. (3) Update backtester stop model. |
| Kelly over-leveraged | HIGH | (1) Reduce Kelly fraction to 1/8 or fixed-fractional. (2) Re-evaluate edge estimate with CI shrinkage. (3) Add per-trade size cap. |
| Funding surprise | LOW | (1) Add funding mark-to-market to backtester if absent. (2) Include funding-sign as feature. (3) Avoid holding through funding window if expected funding > expected return. |
| Coinglass aggregate confused with MEXC | MEDIUM | (1) Add `source` column to derivatives schema. (2) Rebuild affected features. (3) Re-train. |
| Time-zone bug | LOW-MEDIUM | (1) Audit all datetime columns; fix any naive ones. (2) Add startup time-sync. (3) Add Hypothesis tests crossing day boundary. |
| Hyperparameter overfitting | LOW | (1) Reduce trial budget. (2) Use combinatorial purged CV. (3) Verify top-N trials' holdout rank stability. |
| Kill switch failure | CRITICAL if needed | (1) Test monthly so this doesn't happen. (2) Independent dead-man service. (3) Manual MEXC web UI access path documented. |
| Premature infra optimization | MEDIUM (lost time) | (1) Freeze infrastructure. (2) Force focus on edge validation for N weeks. (3) Track weekly: edge-validation work / infra work ratio. |
| Backfill gap | LOW | (1) `quality_flag` mark; don't interpolate. (2) Re-fetch via REST when API quota permits. (3) Models filter by `quality_flag`. |
| Snapshot vs trade mismatch | MEDIUM | (1) Increase snapshot rate during volume spikes. (2) Reconstruct effective book by applying trades between snapshots. |
| Margin insufficient | LOW | (1) Add pre-trade margin reservation. (2) Buffer 2% above current mark. (3) Treat repeated occurrences as config bug. |
| Model staleness | LOW-MEDIUM | (1) Schedule monthly refit. (2) Champion/challenger gate. (3) Live-vs-backtest tracker. |
| Schema migration broke reads | LOW-HIGH (depends) | (1) Restore from backup if data corrupt. (2) Roll back migration. (3) Adopt additive-only migration policy going forward. |
| Lost ingestion data | HIGH | (1) Restore from daily backup. (2) Re-fetch any gap via paid Coinglass tier if recent. (3) Implement backup strategy if absent. |
| Silent task failure | LOW per incident, cumulative HIGH | (1) Audit all `asyncio.create_task` calls. (2) Migrate to `asyncio.TaskGroup`. (3) Add heartbeat per critical task. |
| Paper-vs-live divergence | MEDIUM | (1) Reconcile fee model, slippage, latency. (2) Run paper alongside live; track divergence. (3) Recalibrate sizing if divergence > 30%. |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls. Phases are placeholder names matching PROJECT.md sequence (Foundation → Data Platform → Strategy ML → Backtest+Paper → Live Signal-only → Live Semi-auto → Live Full-auto).

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1 Survivorship bias | Phase 1 (Data Platform, commit 1) | `SELECT count(distinct symbol) FROM universe_snapshots WHERE date BETWEEN ...` returns expected count; delisted symbols present |
| P2 Look-ahead in features | Phase 2 (ML methodology) | Hypothesis property test: `feature(T)` invariant under perturbation of `t > T` |
| P3 Walk-forward done wrong | Phase 2 (ML methodology) | Test: no training index within `label_horizon + embargo` of any test index |
| P4 Slippage unrealistic | Phase 1 (L2 capture) + Phase 2 (model) + Pre-live (parity) | Paper-vs-live slippage divergence < 30% over 100 trades |
| P5 Fee model wrong | Phase 2 (backtester) + Phase 4 (paper) + Phase 5 (live recon) | Weekly fee reconciliation report; divergence < 5% |
| P6 Reduce-only missing | Phase 4 (paper wrapper) — gating Phase 5 | Hypothesis invariant: every close has `reduceOnly=True`; post-trade position assertion |
| P7 Liquidation cascade self-impact | Phase 2 (size caps) + Phase 4 (paper at live size) | Per-symbol position size as % of book never exceeds threshold |
| P8 API key leakage | Phase 0/1 (gitignore, scanning) + Phase 5 (two-key, allowlist) | GitHub secret scanning passes; trade key has no withdraw permission |
| P9 Imbalanced classes | Phase 2 (metric framework) | Documented metric = precision@N; calibration curve in MLflow |
| P10 Regime change blindness | Phase 2 (regime features) + Phase 5 (retrain cadence) | Walk-forward spans both BTC trend regimes; regime-stratified report |
| P11 Stale websocket | Phase 1 (ingest health) + Phase 5 (pre-signal freshness) | Per-symbol freshness gauge; alert if > 30s stale |
| P12 Rate limit mid-pump | Phase 1 (per-endpoint budgets) + Phase 5 (priority queue) | Order endpoint never throttled in last 24h |
| P13 Stop-loss too tight / mis-modeled | Phase 2 (ATR + book-walk fills) + Phase 4 (paper validates) | Stop-fill divergence between backtest and paper < 0.2% |
| P14 Kelly over-leveraged | Phase 2 (edge CI) + Phase 3 (formula) + Phase 5 (live tracker) | Realized edge / backtest edge tracker in `risk.py`; pause if < 0.5x |
| P15 Funding surprise | Phase 1 (funding ingest) + Phase 2 (mark-to-market) + Phase 4 (paper P&L break down) | Trade ledger separates funding P&L |
| P16 Coinglass aggregate confusion | Phase 1 (schema source column) | `SELECT source, count(*) FROM funding` shows expected split; no NULL sources |
| P17 Time-zone bugs | Phase 1 (schema enforcement) + Phase 5 (drift gauge) | All `TIMESTAMPTZ`; startup time-sync; freezegun tests cross day boundary |
| P18 Hyperparameter overfitting | Phase 2 (3-set protocol) | Top-5 trial holdout rank stability check |
| P19 Kill switch missing | Phase 4 (skeleton) + Phase 5 (live) | Monthly `/halt` drill recorded in `OPS.md` |
| P20 Premature optimization | Roadmap discipline (all phases) | Weekly self-review; phase exit gates |
| P21 Backfill quality | Phase 1 (gap detection) | Daily count assertion job runs; gaps flagged |
| P22 Book/trade mismatch | Phase 1 / Phase 2 (snapshot frequency + reconstruction) | Snapshot age < 5s at signal time in backtest |
| P23 Margin insufficient | Phase 5 (pre-trade reservation) | < 1 rejection/day in live logs |
| P24 Model staleness | Phase 5 (retrain cadence) | "Last trained" gauge updates monthly |
| P25 Schema migration breakage | Phase 1 (additive policy) + Phase 5 (backup before migration) | Reproducibility test passes after each migration |
| P26 Backup missing | Phase 1 (backup cron) | Quarterly restore drill recorded |
| P27 Silent task failure | Phase 1 (TaskGroup + heartbeats) | Heartbeat staleness alert configured |
| P28 Paper better than live | Phase 4 (latency + same slippage) | Paper-vs-backtest PnL within 10% |
| P29 Paper survivorship | Phase 4 (pre-registered model) | One declared model version per paper period |
| P30 Dashboard before edge | Phase 5+ only (defer Grafana) | No Grafana panels exist before live trade #1 |

---

## Sources

- López de Prado, M. — "Advances in Financial Machine Learning" — canonical reference for purged k-fold and embargo. Cross-referenced via:
  - [Quantinsti — Cross Validation in Finance: Purging, Embargoing, Combinatorial](https://blog.quantinsti.com/cross-validation-embargo-purging-combinatorial/) — HIGH
  - [Wikipedia — Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation) — HIGH (well-sourced)
  - [Towards AI — Combinatorial Purged Cross-Validation](https://towardsai.net/p/l/the-combinatorial-purged-cross-validation-method) — MEDIUM
  - [Medium — Andrejs summary of López de Prado lecture on why most ML quant funds fail](https://fluentnumbers.medium.com/the-reasons-most-ml-quant-funds-fail-human-generated-summary-of-marcos-lopez-de-prado-lecture-e7d6bd95ef50) — MEDIUM
- [StratBase — Survivorship Bias: Dead Coins Your Backtest Ignores](https://stratbase.ai/en/blog/survivorship-bias-crypto) — HIGH (specific crypto numbers: 58%+ delisted, 200-400% inflation on memecoin baskets)
- [CoinAPI — How to Eliminate Survivorship Bias in Crypto Backtesting](https://www.coinapi.io/blog/how-to-eliminate-survivorship-bias-in-crypto-backtesting) — MEDIUM (vendor-adjacent, but methodology sound)
- [CoinAPI — Backtest Crypto Strategies with Real Market Data (Not Just OHLCV)](https://www.coinapi.io/blog/backtest-crypto-strategies-with-real-market-data) — MEDIUM
- [Gainium — Common Backtesting Problems](https://gainium.io/blog/common-backtesting-problems) — MEDIUM
- [adventuresofgreg — How to Avoid Overfitting When Testing Trading Rules](http://adventuresofgreg.com/blog/2025/12/18/avoid-overfitting-testing-trading-rules/) — MEDIUM
- [adventuresofgreg — Survivorship Bias in Backtesting (Jan 2026)](http://adventuresofgreg.com/blog/2026/01/14/survivorship-bias-backtesting-avoiding-traps/) — MEDIUM
- [QuantifiedStrategies — How to Backtest a Futures Strategy: 2026 Guide](https://www.quantifiedstrategies.com/how-to-backtest-futures-strategy/) — MEDIUM
- MEXC official:
  - [MEXC API Updates feed](https://www.mexc.com/announcements/api-updates) — HIGH (vendor)
  - [Introducing API Futures Trading on Mar 31, 2026](https://www.mexc.com/announcements/article/introducing-api-futures-trading-on-mar-31-2026-17827791534551) — HIGH
  - [Updates to API Futures Trading Fees (May 1, 2026)](https://www.mexc.com/announcements/article/updates-to-api-futures-trading-fees-may-1-2026-17827791535194) — HIGH
  - [MEXC Futures Account and Trading Endpoints](https://www.mexc.com/api-docs/futures/account-and-trading-endpoints) — HIGH
  - [MEXC Futures Market Endpoints](https://www.mexc.com/api-docs/futures/market-endpoints) — HIGH
- ccxt issue tracker:
  - [ccxt#27253 — MEXC `watch_ohlcv` hang](https://github.com/ccxt/ccxt/issues/27253) — HIGH (referenced in STACK.md)
  - [ccxt#28532 — MEXC swap order endpoint fix (May 2026)](https://github.com/ccxt/ccxt) — HIGH (referenced in STACK.md)
- STACK.md (this project's stack research) — HIGH for stack-specific quirks (Coinglass tiers, ccxt MEXC behavior, ML library versions, time-zone discipline)
- PROJECT.md (this project's brief) — HIGH for scope-specific risks (solo, paper-gated, hybrid autonomy, $500K universe filter)

---

## Confidence Reflection

- HIGH confidence on ML/research pitfalls (Pitfalls 1, 2, 3, 9, 10, 18) — canonical literature plus multiple independent crypto-specific sources.
- HIGH confidence on MEXC quirks (Pitfalls 6, 11, 12, 16, 17) — vendor docs + ccxt issue tracker + STACK.md prior research.
- HIGH confidence on execution/risk pitfalls (Pitfalls 4, 5, 7, 13, 14, 19) — well-documented in crypto futures forums and trading literature.
- MEDIUM confidence on Railway-specific operational pitfalls (Pitfalls 25, 26) — less written about for this exact platform; standard Postgres ops knowledge applies.
- MEDIUM confidence on solo-developer-specific patterns (Pitfalls 20, 30) — opinion-heavy but matches widespread post-mortem patterns.
- Gaps: I haven't deeply verified MEXC's exact behavior around `reduceOnly` in hedge mode vs one-way mode for the May 2026 API — this should be confirmed with a paper-trade test before going live. Treat Pitfall 6's specific mechanics as needing field verification.

---
*Pitfalls research for: MEXC futures short-after-pump ML strategy (solo, Railway, paper-gated escalation)*
*Researched: 2026-05-21*
