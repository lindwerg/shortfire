# MEXC Futures Sniper

## What This Is

Crypto data platform с first strategy = детекция оптимальных шорт-точек на фьючерсах MEXC после пампов и состояний перекупленности. Под капотом — широкий data warehouse (MEXC + Coinglass + CoinGecko), на котором сначала живёт short-after-pump ML-стратегия, а в будущем — другие торговые гипотезы. Solo-инструмент для личной торговли с поэтапной эскалацией автономности от сигнальных алертов до полностью автоматического исполнения. Развёртывание на Railway, разработка через TDD с первого коммита.

## Core Value

Найти асимметричные точки входа в шорт после пампов с положительным expected value, доказанным на walk-forward валидации и paper trading — прежде чем рисковать реальным капиталом.

Всё остальное (универсальность data layer, multi-strategy архитектура, dashboard, мониторинг) служит этой цели. Если EV-положительная стратегия не подтверждается в paper trading, проект не идёт в live — независимо от того, насколько красива остальная инфраструктура.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. All hypotheses until shipped and validated. -->

**Data Platform (strategy-agnostic foundation):**
- [ ] Сбор всех разумно доступных данных с MEXC API (свечи 1m/5m/15m/1h/4h/1d, order book snapshots, recent trades, funding history по всем USDT-perp символам)
- [ ] Сбор всех разумно доступных данных с Coinglass API (funding rates, open interest, liquidations, long/short ratio, OI-weighted funding)
- [ ] Сбор всех разумно доступных данных с CoinGecko API (цены, объёмы, market cap, категории, исторические данные)
- [ ] Time-series хранилище (PostgreSQL + TimescaleDB или ClickHouse) с универсальной схемой, поддерживающей multi-strategy backtesting
- [ ] Backfill исторических данных минимум 1–2 года
- [ ] Динамический фильтр universe: все MEXC futures с 24h volume > $500K (daily refresh)
- [ ] Идемпотентные ingest pipelines с retries, схема-валидацией и dead-letter handling

**Strategy #1: Short After Pump:**
- [ ] Алгоритмическая разметка исторических пампов (детектор + параметры порогов)
- [ ] Labeling точек входа и пост-сигнальных исходов для ML training set (метод — решение Phase 2)
- [ ] Feature engineering: multi-timeframe RSI, дивергенции, funding rate spikes, OI rate of change, liquidation cascades, volume profile/FRVP/POC, BTC/ETH correlation
- [ ] Baseline ML модели (logistic regression, XGBoost, LightGBM) с walk-forward валидацией без data leakage
- [ ] EDA в Jupyter (корреляции, feature importance, distribution shifts)
- [ ] Paper trading симулятор с реалистичным slippage, fee model MEXC, и логированием каждой сделки
- [ ] Минимум 1–2 месяца paper trading перед переходом в live

**Live Trading (gated on paper performance):**
- [ ] Интеграция с MEXC API для исполнения ордеров
- [ ] Risk management: quarter-Kelly position sizing, hard stop-loss, max concurrent positions, daily loss limit
- [ ] Telegram-алерты для сигналов и фатальных ошибок
- [ ] Kill switch (manual override и автоматический при breach risk limits)
- [ ] Эскалация автономности: signal-only → semi-auto (confirm in Telegram) → full-auto, по мере накопленного доверия к edge

**Observability:**
- [ ] Dashboard с метриками стратегии (win rate, EV, max drawdown, equity curve)
- [ ] Мониторинг pipeline health (data freshness, API failures, model staleness)

**DevOps / CI/CD:**
- [ ] GitHub репозиторий с защищённым main branch
- [ ] Railway проект подключён к GitHub репо
- [ ] Pipeline: commit → push → автоматический deploy на Railway после каждой завершённой задачи
- [ ] GitHub Actions: tests на каждый PR, блокировка merge при падении тестов

### Out of Scope

<!-- Explicit boundaries with reasoning to prevent re-adding. -->

- **Multi-user / SaaS / billing** — solo-инструмент только для меня. Auth, subscription tiers, public API ровно ничего не добавляют к main goal.
- **Спотовая торговля** — фьючерсные шорты с плечом критичны для гипотезы (асимметрия после пампов = с плечом, иначе R:R не работает).
- **Биржи кроме MEXC** — на v1. MEXC выбрана из-за богатства мемкоин-листинга и доступности экзотических пампов. Может быть пересмотрено после валидации edge.
- **Лонг-сетапы** — гипотеза специфична: пост-памп разворот вниз. Лонги — отдельная стратегия, может быть добавлена после валидации первой.
- **Sentiment через NLP / Twitter API** — слишком шумно для текущей гипотезы. Sentiment-прокси через объёмы и on-chain — приемлемо.
- **Mobile app** — Telegram-алертов + Railway-hosted dashboard достаточно для solo-юзера.
- **DEX-фьючерсы (dYdX, GMX и т.д.)** — другой класс инструментов, другая ликвидность, другая стоимость исполнения. Отложено.
- **Точное определение «разворота» для labeling** — это не constraint, а активное решение Phase 2 после EDA. Зафиксировано открытым.

## Context

**Technical environment:**
- Python-экосистема (FastAPI, pandas/polars для трансформаций, sklearn/XGBoost/LightGBM для baseline ML, потенциально PyTorch для sequence models позже)
- Railway как deployment платформа — managed PostgreSQL + TimescaleDB extension, GitHub Actions для CI/CD, встроенные метрики плюс возможно Grafana/Prometheus
- TDD-first culture: каждый модуль начинается с тестов (схемы API, синтетические свечи для детекторов, детерминизм бэктестера, отсутствие data leakage в ML pipeline)

**Strategy rationale:**
- Гипотеза: после резкого пампа + перекупленности появляются статистически значимые сигналы разворота. Комбинация derivatives данных (funding/OI/liquidations) + price action + on-chain proxies может детектировать асимметричные шорт-точки.
- MEXC специально из-за широкого листинга мемкоинов и low-cap альтов — именно там реальные памп-сетапы 50-200%+, дающие нужную асимметрию.

**Constraints inherited:**
- API rate limits: CoinGecko free tier строгий; Coinglass paid tier потребуется для аккуратных derivatives данных; MEXC public API — щадящие лимиты
- Coinglass подписка может стоить $30+/мес и стать gating factor для качества данных
- Backfill 1-2 года потребует продуманного storage layout и возможно paid tier на Coinglass для исторических snapshots

**Risk frame:**
- Капитал адаптивный — стартует малым, position sizing learns from current capital tier; система должна корректно работать от $500 до $50K+ счетов с разными leverage/slippage характеристиками
- Paper trading 1-2 месяца — hard gate перед любым реальным капиталом
- Hybrid autonomy: signal-only по умолчанию, продвижение к full-auto только по подтверждённой стратегии

**Prior experience referenced:**
- Quarter-Kelly position sizing уже использовался в смежных проектах (ClaudeBet); переиспользуем подход с поправкой на crypto-волатильность

## Constraints

- **Tech stack — Python, FastAPI, pandas/polars** — единый язык от ingest до ML до execution упрощает TDD и shared code
- **Tech stack — PostgreSQL + TimescaleDB на Railway** — managed time-series storage, без операционного оверхеда от ClickHouse-кластера; миграция в ClickHouse — fallback option если объёмы превысят TimescaleDB efficient sweet spot
- **Tech stack — XGBoost/LightGBM как baseline** — interpretable, быстрая итерация, понятные feature importance; PyTorch sequence models — только после того как baseline докажет edge
- **Deployment — Railway** — простота, predictable cost, managed Postgres рядом; GitHub Actions для CI
- **CI/CD — commit→push→deploy после каждой задачи** — Railway auto-deploy on push to main, GitHub Actions блокирует merge при падении тестов; быстрая обратная связь, тестируем в realistic окружении с первого дня
- **Testing — TDD с первого коммита** — non-negotiable; каждый модуль начинается с тестов
- **Validation — walk-forward only** — никаких random split на time-series; data leakage = деньги в утиль
- **Risk — quarter-Kelly + hard stops + max concurrent positions** — никаких "интуитивно увеличу размер"
- **Live trading — gated on ≥1-2 месяца positive paper trading** — нельзя пропустить
- **Audience — solo only** — никаких multi-user-зависимых решений
- **Universe — динамический фильтр $500K+ 24h volume** — компромисс между богатством сетапов и базовой ликвидностью
- **Autonomy — staged escalation** — full-auto только после подтверждённого edge в live signal-only/semi-auto

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Strategy-agnostic data platform vs single-strategy MVP | Универсальный data warehouse даёт reuse для будущих стратегий; затраты на правильную схему один раз vs многократный refactor | — Pending |
| MEXC как единственная биржа v1 | Богатый листинг мемкоинов = реальные памп-сетапы для гипотезы; multi-exchange = overhead без edge gain пока что | — Pending |
| Скальп + интрадей горизонт | Резкая перекупленность → быстрый разворот; даёт max trades для статистической значимости; работает с плечом | — Pending |
| Edge metric = max EV (балансовый) | Лучше чем оптимизация под win rate или R:R по отдельности; ML может балансировать оба автоматически | — Pending |
| ML target (labeling метод) откладывается на Phase 2 | Решение зависит от того что покажет EDA; преждевременная фиксация исключит варианты | — Pending |
| Hybrid autonomy escalation | Минимизирует риск багов в early production; full-auto только после доказанного edge | — Pending |
| TimescaleDB на Railway вместо ClickHouse | Managed, простой setup, достаточно для start; ClickHouse — fallback если объёмы потребуют | — Pending |
| Quarter-Kelly как baseline position sizing | Проверенный подход в смежных проектах; conservative по умолчанию | — Pending |
| TDD с первого коммита | Trading bugs = реальные потери; nothing-too-small-to-test culture | — Pending |
| Capital model = адаптивный | Position sizing learns from current capital tier; одна и та же стратегия должна работать на $500 и $50K | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-21 after initialization*
