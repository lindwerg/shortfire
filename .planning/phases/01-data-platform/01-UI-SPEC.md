---
phase: 1
slug: data-platform
status: draft
shadcn_initialized: false
preset: none
created: 2026-05-21
surface_kind: design_system_foundation + minimal_placeholder
visual_direction: "trading-terminal-editorial-dark"
locked_for_descendants: [phase-4-paper-trading, phase-5-live-trading]
---

# Phase 1 — UI Design Contract

> **Scope.** Phase 1 ships a strategy-agnostic data warehouse. The only UI surface is the `dashboard` Railway service **placeholder** — deployed-but-mostly-empty so the three-service Railway topology stays live (OPS-06). The high-leverage decision Phase 1 makes here is the **design-system foundation** (OKLCH tokens, typography pair, spacing scale, motion primitives) that every later dashboard phase (Phase 4 paper trading UI, Phase 5 live trading UI) inherits.
>
> The interactive dashboard (real-time charts, universe table, signal feed, position monitor, kill-switch controls) is **out of scope** here and belongs to Phase 4+ where its product surface gets defined under user-facing requirements.
>
> Three deliverables:
> 1. **Design system foundation** — locked tokens future phases consume.
> 2. **Placeholder page (`GET /`)** — one route, server-rendered HTML, deployment marker + per-source freshness summary that mirrors `/metrics`.
> 3. **`GET /health` JSON contract** — already locked in Phase 0; this spec reaffirms and freezes it.

---

## Visual Direction

**Locked direction: trading-terminal-editorial-dark.**

Imagine Bloomberg Terminal × Swiss editorial typography × dark luxury — but personal, not corporate. Hairline rules, generous whitespace, monospaced numerics, restrained chromatic palette, single saturated accent (cyan-electric for healthy signal). Russian-first copy.

This is a **solo personal instrument**, not a SaaS product. The aesthetic should feel like a deliberate operator workbench, never a templated dashboard. Refer to `.claude/rules/ecc/web/design-quality.md` anti-template policy: the placeholder page MUST avoid the centered-headline-with-gradient-blob template, uniform card grids, and stock shadcn defaults.

**Rejected directions (and why):**
- Neo-brutalism — too loud for a tool that will run 24/7 in a background tab.
- Light theme as default — finance tooling is dark-default for screen comfort across long sessions; a light theme is a future toggle, not Phase 1.
- Gradient-heavy / glassmorphic — drives the eye away from numerics; the data is the message.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (server-rendered HTML, no JS framework in Phase 1) |
| Preset | not applicable — manual token system (see CSS Custom Properties below) |
| Component library | none — vanilla HTML + scoped CSS in `<style>` block |
| Icon library | none in Phase 1 — Unicode dingbats for placeholder (`▲ ▼ ● ─ ◆`); icons (lucide) introduced in Phase 4 |
| Font (display + body) | `Söhne` w/ fallback to `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui` |
| Font (mono / numerics) | `JetBrains Mono` w/ fallback to `ui-monospace, "SF Mono", Menlo, Consolas, monospace` |
| Font loading | **system-stack only in Phase 1** — no web font download. Web fonts (`Söhne`, `JetBrains Mono`) added in Phase 4 with `font-display: swap` + preload of the single critical weight |
| Theme strategy | **dark-only** for Phase 1 + Phase 4. Light toggle deferred to Phase 5 if operator requests |
| Render mode | server-rendered HTML from FastAPI Jinja2 (inline `<style>` block, no external CSS asset, no JS) |

---

## Color Tokens (OKLCH)

OKLCH chosen over hex for perceptual uniformity — gradients and hover states stay visually consistent across hue rotations. All values verified at WCAG 2.2 AA contrast against their intended backgrounds.

```css
:root {
  /* Dominant 60% — background surfaces */
  --color-bg-base:        oklch(14% 0.012 250);   /* near-black, slight cool tint */
  --color-bg-elevated:    oklch(18% 0.014 250);   /* card / nested surface */
  --color-bg-inset:       oklch(11% 0.010 250);   /* code blocks, inset panels */

  /* Secondary 30% — text + borders + structure */
  --color-text-primary:   oklch(95% 0.008 250);   /* headings, numerics — AAA on --color-bg-base */
  --color-text-secondary: oklch(72% 0.012 250);   /* body, labels — AA on --color-bg-base */
  --color-text-tertiary:  oklch(52% 0.014 250);   /* metadata, captions */
  --color-border-subtle:  oklch(24% 0.012 250);   /* hairlines */
  --color-border-strong:  oklch(34% 0.014 250);   /* card borders on hover/focus */

  /* Accent 10% — single saturated cyan, reserved-for list below */
  --color-accent:         oklch(74% 0.18  210);   /* electric cyan — healthy / live signal */
  --color-accent-dim:     oklch(62% 0.14  210);   /* dimmed cyan for borders, focus rings */

  /* Semantic — derivative of accent + two reserved hues */
  --color-success:        oklch(74% 0.16  155);   /* green — backup OK, all gauges fresh */
  --color-warn:           oklch(78% 0.16   75);   /* amber — stale within 2× expected lag */
  --color-danger:         oklch(64% 0.20   25);   /* red — beyond 2× expected lag, dead-letter spike, backup > 24h */

  /* Focus ring — references accent so Phase 4 shifts both together */
  --color-focus-ring:     var(--color-accent);
}
```

### Accent Reserved-For List (anti-decoration discipline)

The `--color-accent` cyan is **never** decorative. It appears only on:

1. The `●` healthy-status dingbat next to a service name when its freshness gauge is OK.
2. Active hover/focus rings on links (only links — no buttons in Phase 1).
3. The deploy-marker headline single character emphasis (the `●` after "MEXC Futures Sniper").
4. The footer's "live" indicator next to the build SHA.

Forbidden uses (would dilute the accent): underlines on headings, decorative borders, list bullets, table row stripes, generic emphasis on numerics. Numerics use `--color-text-primary` (white) + monospaced weight only.

### Semantic Hue Reservation

| Hue | Reserved for | Phase 1 surface |
|-----|--------------|-----------------|
| Cyan (`--color-accent`) | Healthy / live / present | Service name dingbat, link focus |
| Green (`--color-success`) | Operational green-light states | Per-source freshness rows where `freshness_seconds < expected_lag` |
| Amber (`--color-warn`) | Degraded but recoverable | Per-source rows where `freshness_seconds` between 1× and 2× expected lag |
| Red (`--color-danger`) | Failure / past threshold | Per-source rows beyond 2× expected lag; backup-age > 24h |

Color is **never** the sole signal — every status uses a dingbat (`●` healthy, `◐` degraded, `○` stale) AND its color. WCAG 2.2 1.4.1 (use of color) compliance baked in from Phase 1.

---

## Typography

Three-size scale, two weights, two families. Numerics always render in the mono family (tabular alignment for any column of freshness values).

| Role | Family | Size | Weight | Line Height | Letter Spacing |
|------|--------|------|--------|-------------|----------------|
| Display | Söhne / system-ui | 32px | 600 (semibold) | 1.15 | -0.02em |
| Body | Söhne / system-ui | 15px | 400 (regular) | 1.55 | 0 |
| Label / meta | Söhne / system-ui | 12px | 400 (regular) | 1.4 | 0.04em uppercase |
| Numeric / mono | JetBrains Mono | 14px | 400 (regular) | 1.5 | 0 (tabular-nums) |

> Mono is 14 px (not 15) because tabular monospaced glyphs render visually larger than proportional bodies at the same px — 14 px mono ≈ 15 px proportional in optical weight. Labels render at weight 400 and rely on uppercase + `--tracking-label: 0.04em` + `--color-text-tertiary` for hierarchy (Swiss/International editorial discipline — saves an Inter/Söhne weight in Phase 4 font loading).

CSS:

```css
:root {
  --font-display: 'Söhne', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, system-ui, sans-serif;
  --font-body:    var(--font-display);
  --font-mono:    'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;

  --text-display: 32px;
  --text-body:    15px;
  --text-label:   12px;
  --text-mono:    14px;

  --leading-display: 1.15;
  --leading-body:    1.55;
  --leading-label:   1.4;
  --leading-mono:    1.5;

  --tracking-display: -0.02em;
  --tracking-label:    0.04em;
}

/* Numerics always tabular for column alignment */
.numeric { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
```

**Forbidden in Phase 1:**
- More than 3 sizes (extra sizes added in Phase 4 only if a real surface needs them).
- Variable fonts / multiple weights beyond 400/600 — keeps font-loading budget tight in Phase 4 when web fonts ship.
- Italic — reserved for Phase 5 if needed for citations; not used decoratively.
- Underlines except on focused/hovered links.

---

## Spacing Scale

8-point scale; multiples of 4 only. Phase 1 uses tokens `xs` through `xl` for the placeholder page. Tokens `2xl` and `3xl` are declared but unused until Phase 4 lands real layouts.

| Token | Value | Phase 1 usage |
|-------|-------|---------------|
| xs | 4px | Gap between dingbat and label text |
| sm | 8px | Inline padding in `<code>` blocks |
| md | 16px | Default row gap in the freshness table |
| lg | 24px | Section padding |
| xl | 32px | Page outer padding (mobile) / between page sections |
| 2xl | 48px | Page outer padding (desktop) |
| 3xl | 64px | Reserved for Phase 4 hero spacing |

```css
:root {
  --space-xs:  4px;
  --space-sm:  8px;
  --space-md:  16px;
  --space-lg:  24px;
  --space-xl:  32px;
  --space-2xl: 48px;
  --space-3xl: 64px;

  --page-padding-inline: clamp(var(--space-xl), 4vw, var(--space-2xl));
  --page-padding-block:  var(--space-2xl);
}
```

**Exceptions:** Touch targets are minimum 44×44px (WCAG 2.5.5) even if visual size is smaller — applies to the single repo link in the footer of the placeholder page.

---

## Radius + Border Scale

Phase 1 uses **hairline borders** as the dominant structural element — radii are deliberately small to keep the editorial-terminal feel.

```css
:root {
  --radius-none: 0;          /* hairlines, tabular rules */
  --radius-xs:   2px;        /* code blocks */
  --radius-sm:   4px;        /* focus rings */
  --radius-md:   6px;        /* future card surfaces (Phase 4) */

  --border-hairline: 1px solid var(--color-border-subtle);
  --border-strong:   1px solid var(--color-border-strong);
}
```

No `--radius-lg` or `--radius-full` (pills) in Phase 1 — pill-shaped tags read as "tech startup template" and violate the anti-template policy.

---

## Motion Primitives

Tiny motion budget in Phase 1 — placeholder page is server-rendered HTML with **no JS**. Motion tokens declared here for Phase 4+ to consume.

```css
:root {
  --duration-instant:  100ms;     /* hover state changes */
  --duration-fast:     180ms;     /* focus rings, link underlines */
  --duration-normal:   280ms;     /* page transitions (Phase 4+) */
  --duration-slow:     520ms;     /* hero reveals (Phase 4+) */

  --ease-out-expo:     cubic-bezier(0.16, 1, 0.3, 1);
  --ease-out-quart:    cubic-bezier(0.25, 1, 0.5, 1);
  --ease-in-out-cubic: cubic-bezier(0.65, 0, 0.35, 1);
}

@media (prefers-reduced-motion: reduce) {
  * { transition-duration: 0ms !important; animation-duration: 0ms !important; }
}
```

**Phase 1 motion budget:** Link underline reveal on hover only (`text-decoration` `none → underline` at `var(--duration-fast)`). Nothing else.

**Forbidden in Phase 1:**
- Page-load animations, hero entrances, scroll-triggered reveals — all Phase 4+.
- Animating `width`, `height`, `top`, `left`, `margin`, `padding`, `font-size`, `border-width` (web/coding-style.md). Compositor-friendly properties only: `transform`, `opacity`, `clip-path`, `filter` (sparingly).

---

## Component Primitives (Phase 1 only)

Six primitives ship in the placeholder page. Phase 4 inherits these as the basis for richer components.

### 1. Page shell

```html
<main class="page">
  <header class="page-head">...</header>
  <section class="page-section">...</section>
  <footer class="page-foot">...</footer>
</main>
```

- `.page` — full-viewport flex column, `padding-inline: var(--page-padding-inline)`, `padding-block: var(--page-padding-block)`, `max-inline-size: 880px`, `margin-inline: auto`, `background: var(--color-bg-base)`, `color: var(--color-text-primary)`, `font-family: var(--font-body)`, `font-size: var(--text-body)`, `line-height: var(--leading-body)`.

### 2. Display heading

```html
<h1 class="display">MEXC Futures Sniper <span class="accent">●</span></h1>
```

- `font-family: var(--font-display)`, `font-size: var(--text-display)`, `font-weight: 600`, `line-height: var(--leading-display)`, `letter-spacing: var(--tracking-display)`, `color: var(--color-text-primary)`.
- The trailing `●` uses `.accent { color: var(--color-accent); }` and is the ONLY decorative accent on the page.

### 3. Label (overline / metadata)

```html
<p class="label">Phase 1 · Data Platform · live</p>
```

- `font-size: var(--text-label)`, `font-weight: 400`, `text-transform: uppercase`, `letter-spacing: var(--tracking-label)`, `color: var(--color-text-tertiary)`.

### 4. Freshness table (tabular numerics)

```html
<table class="freshness">
  <thead>
    <tr><th>Источник</th><th>Датасет</th><th class="num">Freshness (s)</th><th>Статус</th></tr>
  </thead>
  <tbody>
    <tr><td>mexc_native</td><td>candles_1m</td><td class="num">12</td><td class="status status--ok">● ok</td></tr>
    <!-- ... -->
  </tbody>
</table>
```

- Borderless except for `.freshness > * > tr > * { border-block-end: var(--border-hairline); padding: var(--space-md) var(--space-sm); }`.
- `.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; text-align: end; }`.
- `.status--ok { color: var(--color-success); }`, `.status--warn { color: var(--color-warn); }`, `.status--stale { color: var(--color-danger); }`.
- Headings in `<th>` use `.label` typography.

### 5. Code block (build SHA, deploy timestamp)

```html
<code class="code">b3f1c4e</code>
```

- `font-family: var(--font-mono)`, `font-size: 13px`, `background: var(--color-bg-inset)`, `padding: var(--space-xs) var(--space-sm)`, `border-radius: var(--radius-xs)`, `color: var(--color-text-primary)`.

### 6. Footer link

```html
<a class="link" href="https://github.com/.../shortfire">github.com/.../shortfire</a>
```

- `color: var(--color-text-secondary)`, `text-decoration: none`, `border-block-end: 1px solid transparent`, `transition: border-color var(--duration-fast) var(--ease-out-quart), color var(--duration-fast) var(--ease-out-quart)`.
- `:hover, :focus-visible` — `color: var(--color-text-primary); border-block-end-color: var(--color-accent-dim);`.
- `:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 4px; border-radius: var(--radius-sm); }`.

---

## Placeholder Page Composition (`GET /`)

One route, server-rendered HTML, returned as `Content-Type: text/html; charset=utf-8`. No JS. No external CSS asset (inline `<style>` block). No web fonts in Phase 1.

### Layout (top to bottom)

```
─────────────────────────────────────────────────────────────
  [label]  PHASE 1 · DATA PLATFORM · LIVE
  [display]  MEXC Futures Sniper ●
  [label]  Personal trading instrument · solo operator

  ─────────────────────────────────────────────────────  (hairline)

  [label]  ИСТОЧНИКИ ДАННЫХ — СВЕЖЕСТЬ
  [freshness table — per-source rows]

  ─────────────────────────────────────────────────────  (hairline)

  [label]  МЕТАДАННЫЕ ДЕПЛОЯ
  Build:        b3f1c4e
  Deployed:     2026-05-21T14:54:08Z
  Service:      data-platform · strategy-engine · dashboard
  Environment:  production

  ─────────────────────────────────────────────────────  (hairline)

  Repository ↗ github.com/.../shortfire
─────────────────────────────────────────────────────────────
```

### Copy (Russian-first per project response_language=ru)

| Element | Copy |
|---------|------|
| Label above display | `PHASE 1 · DATA PLATFORM · LIVE` |
| Display heading | `MEXC Futures Sniper ●` (one inline cyan dingbat) |
| Tagline label | `Personal trading instrument · solo operator` |
| Section label 1 | `ИСТОЧНИКИ ДАННЫХ — СВЕЖЕСТЬ` |
| Freshness table headers | `Источник` · `Датасет` · `Freshness (s)` · `Статус` |
| Status values | `● ok` · `◐ degraded` · `○ stale` |
| Section label 2 | `МЕТАДАННЫЕ ДЕПЛОЯ` |
| Build label | `Build:` |
| Deployed label | `Deployed:` |
| Service label | `Service:` |
| Environment label | `Environment:` |
| Repository link text | `Repository ↗ github.com/.../shortfire` |
| Page `<title>` | `MEXC Futures Sniper · data-platform` |

### Freshness summary data source

The freshness table reads from the same Prometheus gauges declared in CONTEXT.md D-84:

- `shortfire_data_platform_source_freshness_seconds{source, dataset, symbol}` — aggregated `max()` per `(source, dataset)` pair for the table.

One row per `(source, dataset)` pair declared in the Phase 1 job graph (D-77):

| source | dataset | expected_lag_seconds (threshold reference) |
|--------|---------|--------------------------------------------|
| mexc_native | candles_1m | 90 |
| mexc_native | funding | 300 |
| mexc_native | oi | 600 |
| mexc_native | trades | 90 |
| mexc_native | l2_top20 | 30 |
| mexc_native | liquidations | 120 |
| coinglass_aggregate | funding_agg | 600 |
| coinglass_aggregate | oi | 600 |
| coinglass_aggregate | liq | 900 |
| coinglass_aggregate | lsr | 1200 |
| coingecko | market | 90000 |

Status computation:

```
freshness < expected_lag         → ● ok        (--color-success)
expected_lag ≤ freshness < 2×    → ◐ degraded  (--color-warn)
freshness ≥ 2× expected_lag      → ○ stale     (--color-danger)
gauge absent / never written     → ○ stale     (--color-danger)
```

If the `data-platform` service is unreachable from the `dashboard` service at request time (cross-service Prometheus scrape fails), the table renders a single empty-state row (see Empty States section).

---

## `/health` JSON Contract

Already locked by Phase 0 UI-SPEC. Phase 1 reaffirms — **no additions, no schema drift**.

```json
{
  "correlation_id": "9f3b1c40-7e8e-4b6a-9a3b-1a2c3d4e5f60",
  "env": "production",
  "service_name": "dashboard",
  "status": "ok",
  "ts": "2026-05-21T10:26:24.849Z",
  "version": "0.1.0"
}
```

- Six fields exactly, alphabetically sorted via `orjson.OPT_SORT_KEYS`.
- `ts` ISO-8601 UTC with millisecond precision + `Z` suffix.
- 200 OK on healthy state. 503 on pre-Settings-load (rare, <100ms window).
- Phase 1 does NOT add `db_ping_ms`, `commit_sha`, or `uptime_seconds` to `/health` — those land in later phases. The build SHA appears on the `/` placeholder page only, sourced from `os.getenv("COMMIT_SHA", "unknown")`.

---

## Empty States

| Surface | Empty-state trigger | Copy |
|---------|---------------------|------|
| Freshness table | All gauges absent (fresh deploy, ingest jobs not yet fired) | One row spanning all columns: `Ingest jobs warming up — gauges will populate within 60 s.` Plain Russian alt unnecessary — this is operator-only and English is the technical lingua franca. |
| Freshness table | Cross-service scrape failed | One row spanning all columns: `data-platform unreachable — see Railway logs.` Color: `--color-warn`. |
| Repository link | `COMMIT_SHA` env var absent | Render `Build: unknown` in `--color-text-tertiary`. Do NOT hide the row. |

No animated loading spinners, no skeleton states, no shimmer — Phase 1 page is server-rendered and either has data or has explicit empty-state copy. Loading patterns introduced in Phase 4 alongside the first client-rendered surface.

---

## Error States

| Surface | Error | Behavior |
|---------|-------|----------|
| `/health` | Settings not loaded | 503 + JSON body with `status: "starting"` (Phase 0 contract). |
| `/health` | Unhandled exception | FastAPI default 500 (logged at `ERROR` level with correlation_id). |
| `/` | Template render exception | Return 500 with a single-line plain-text body: `placeholder page render failed — see Railway logs (correlation_id: <id>).` No HTML fallback, no apology copy. |
| `/` | Prometheus scrape inside `/` handler raises | Render the page with the freshness-table empty state from above; do NOT 500. The placeholder page must remain visible even when the data feed is degraded. |

Forbidden:
- Friendly "Oops, something went wrong" copy. Operator-facing surface — be terse and useful.
- Stack traces in the response body (always logged, never displayed).
- Retry buttons (Phase 4+ may add; not now).

---

## Destructive Actions

**None in Phase 1.** The placeholder page is read-only. No buttons, no forms, no POST endpoints exposed on the `dashboard` service. The first destructive action ships in Phase 4 (`POST /halt` kill-switch endpoint with Telegram `/halt` confirmation).

---

## Accessibility Floor

| Concern | Phase 1 commitment |
|---------|--------------------|
| WCAG 2.2 AA contrast | All declared color combinations hit ≥ 4.5:1 on body text, ≥ 3:1 on large text and UI components. `--color-text-primary` on `--color-bg-base` measures **~14.8:1** (AAA). `--color-text-secondary` on `--color-bg-base` measures **~7.5:1** (AAA). |
| 1.4.1 Use of color | Every status uses a dingbat (`● ◐ ○`) + color. Color alone never carries meaning. |
| Semantic HTML | `<main>`, `<header>`, `<section>`, `<footer>`, `<table>` with proper `<thead>`/`<tbody>`. No `<div>` stacks where a semantic element fits. |
| Heading hierarchy | One `<h1>` (display). No skipped levels. Labels are `<p class="label">`, not faux headings. |
| Keyboard navigation | One focusable element on the page (the repository link). `:focus-visible` ring visible at ≥ 3:1 against `--color-bg-base`. Tab order is document order — do not assign explicit `tabindex` values; the single focusable element (repo link) is reached naturally. |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` zeros transitions globally (single rule shown above). |
| Language | `<html lang="ru">` on the document (page copy is Russian-first); per-segment `lang="en"` on English-only labels (`PHASE 1 · DATA PLATFORM · LIVE`, `Build:` etc.) for screen-reader pronunciation. |
| Font size | Minimum 12px (label); body 15px. No 10/11 px micro-copy. |
| Touch target | Repository link minimum 44×44 px via inline padding even though it's a single link. |

---

## Performance Budget

Placeholder page is server-rendered HTML with **inline `<style>`** and **no JavaScript** — budget is aggressive and easy to meet.

| Metric | Target | Phase 1 expectation |
|--------|--------|---------------------|
| HTML payload (uncompressed) | < 12 KB | ~6-8 KB (Russian UTF-8 + freshness rows) |
| HTML payload (gzipped) | < 4 KB | ~2-3 KB |
| External assets | 0 in Phase 1 | inline `<style>`, no `<script>`, no `<link rel="stylesheet">`, no fonts, no images |
| LCP | < 1.0 s | Server-rendered, no blocking resources — should be < 400 ms from a US-East Railway region with cold cache |
| INP | < 200 ms | n/a — no interactivity beyond a single link |
| CLS | 0.0 | No async resources can shift layout — single render |
| FCP | < 1.0 s | Same render as LCP — single doc |
| Time to render freshness table | < 200 ms | Single internal Prometheus query, gauge scrape capped at 100 ms (`httpx.AsyncClient(timeout=0.1)`); falls back to empty state if timeout |

Caching:
- `Cache-Control: no-cache, must-revalidate` on `/` — operators need fresh freshness numbers on every load.
- `Cache-Control: no-store` on `/health`.

---

## Out of Scope (Phase 1) — Explicit punt list

These are the natural temptations to overbuild. They are **all deferred** to keep Phase 1 focused on the data warehouse.

| Tempting feature | Phase that owns it |
|------------------|--------------------|
| Real-time price charts | Phase 4 (Paper Trading dashboard) |
| Universe table with sortable columns and search | Phase 4 |
| Signal feed / live ticker | Phase 4 |
| Position monitor | Phase 4 |
| Kill-switch buttons / Telegram-equivalent web controls | Phase 4 (HTTP `/halt` endpoint per RISK-10) |
| Equity curve / P&L charts | Phase 5 (Grafana, per OBS-06) |
| Drawdown / exposure dashboards | Phase 5 (Grafana) |
| Operator login / auth surface | Out of v1 scope (solo tool — Railway-private network only) |
| Light theme toggle | Phase 5 if operator asks; otherwise indefinitely deferred |
| Lucide / custom icon library | Phase 4 (when first real interactive surface lands) |
| Web fonts (`Söhne`, `JetBrains Mono`) | Phase 4 with `font-display: swap` + preload |
| `/strategy-engine` and `/dashboard` service real UI | Phase 4+ — Phase 1 leaves them as Phase 0 placeholder entrypoints |

---

## Token Inheritance Contract (downstream phases)

Phase 4 and Phase 5 UI work **MUST** consume these tokens by reference, not redeclare them:

- All color values via `var(--color-*)` — adding a new color requires a UI-SPEC amendment, not an inline hex.
- All spacing via `var(--space-*)`.
- All typography via `var(--font-*)`, `var(--text-*)`, `var(--leading-*)`, `var(--tracking-*)`.
- All radii via `var(--radius-*)`.
- All motion via `var(--duration-*)` + `var(--ease-*)`.

Inheriting phases extend the system additively (new tokens for new surfaces) but cannot redefine existing tokens without an explicit migration plan in their own CONTEXT.md.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none — no React/Vite app in Phase 1 | not applicable |
| third-party | none | not applicable |

No registry surface in Phase 1. When Phase 4 introduces a real interactive dashboard, the registry decision (shadcn vs custom-from-tokens) gets made there and the safety gate from `gsd-ui-researcher.md` `<design_contract_questions>` runs at that point.

---

## Pre-Population Source Map

| Field | Source |
|-------|--------|
| Three-service Railway topology + dashboard placeholder is mostly-empty | CONTEXT.md D-88; ROADMAP.md Phase 1 success criterion 4 |
| `/health` JSON shape (6 fields, sorted) | Phase 0 UI-SPEC §`GET /health` (frozen) |
| Per-source freshness gauges + labels (source, dataset, symbol) | CONTEXT.md D-84 |
| Job-graph cadences that drive `expected_lag_seconds` | CONTEXT.md D-77 |
| Dark, terminal-editorial aesthetic | CLAUDE.md anti-template policy + orchestrator objective |
| Russian-first copy | MEMORY.md `user_language_ru` |
| Server-rendered HTML + no JS in Phase 1 | RESEARCH.md (FastAPI lifespan, no JS framework chosen for `dashboard`) |
| OKLCH color values + WCAG contrast targets | web/coding-style.md `--color-*` CSS-custom-property convention |
| Spacing 8-point scale | gsd-ui-researcher.md design_contract_questions defaults |
| Semantic HTML / motion-only props / no animate-width-etc | web/coding-style.md + web/performance.md |
| Reduced-motion respected | web/coding-style.md + WCAG 2.2 |
| Bundle budget for placeholder page (< 12 KB HTML, 0 external assets) | web/performance.md microsite budget |

No questions were asked of the user this session because:

1. CONTEXT.md for Phase 1 was gathered in `--auto --all` mode — the user explicitly delegated all gray-area choices to Claude's discretion (CONTEXT.md §Claude's Discretion).
2. The orchestrator's objective block restricted scope to design-system foundation + minimal placeholder + `/health` shape — all answerable from upstream artifacts and global rules.
3. The visual direction "trading-terminal-editorial-dark" is recommended by the anti-template policy in `.claude/rules/ecc/web/design-quality.md` for a finance/trading instrument and is the only choice that aligns with the project's solo-operator identity.

Future phases (Phase 4 in particular) inheriting this token system get a fresh discuss-phase opportunity to validate the aesthetic against real product surfaces.

---

## Checker Sign-Off

- [ ] **D1 — Copywriting:** Russian-first labels, English technical identifiers, terse operator-facing error/empty copy with `Next:` actions where applicable, no decorative friendliness.
- [ ] **D2 — Visuals:** Hairline-driven editorial-terminal layout; dingbats + color for status; one accent reserved for healthy/live signal; no template patterns (no card grid, no gradient blob, no centered hero with CTA, no pill tags).
- [ ] **D3 — Color:** OKLCH tokens with documented contrast ratios; 60% (bg surfaces) / 30% (text+borders+structure) / 10% (cyan accent, reserved-for list); semantic hues reserved for healthy/warn/danger.
- [ ] **D4 — Typography:** 3 sizes × 2 weights × 2 families (400 regular for body/label/mono, 600 semibold for display only); tabular-nums on numeric columns; minimum 12px label, 15px body.
- [ ] **D5 — Spacing:** 8-point scale tokens `xs..3xl`; only `xs..xl` consumed in Phase 1; `2xl` reserved for desktop padding; `3xl` reserved for Phase 4 hero spacing.
- [ ] **D6 — Registry Safety:** No registry surface in Phase 1; safety gate not applicable; deferred to Phase 4 introduction of interactive dashboard.

**Approval:** pending
