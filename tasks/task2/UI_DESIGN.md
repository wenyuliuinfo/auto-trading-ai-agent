# Task 2 — UI Design

Companion to `SPEC.md`. Scope: the report view. The UI framework was not
inspected; component names below are conceptual and can map to whatever the web
app uses. Everything renders from `report_data` (SPEC §7); reports without it
keep the existing markdown view.

Included recommendations: structured table (1), mini K-line with interactive
modal (2), summary header (3), explainability (4), trading-terminal polish (6),
responsive layout (7), export (8). **Not in scope:** risk matrix, collapsible
near-miss section, shareable links.

## 1. Principles

- **Dense but calm.** Tabular numbers, restrained color, clear hierarchy.
- **Never color alone.** Every up/down signal also has a sign and an arrow.
- **Data provenance visible.** Every chart and news item shows its source and
  as-of date.
- **Compliance first.** The disclaimer and the "hypothetical" label are always
  visible when their content is shown.
- **Degrade gracefully.** Missing chart, news or return never breaks a row.

## 2. Page layout (desktop, 1024 px and up)

```
┌────────────────────────────────────────────────────────────────────────┐
│ Theme name                         Run 2026-10-01 14:02   [Export ▾][☾]│
│ ● Screening ─ ● Analysis ─ ● Scoring ─ ● Basket ─ ● Charts ─ ● Report   │  PipelineStepper
├────────────────────────────────────────────────────────────────────────┤
│ ┌Holdings─┐ ┌Trailing 6M (hypothetical)─┐ ┌Top-3 weight┐ ┌Data as of─┐ │  SummaryHeader
│ │   9     │ │  +12.3%  coverage 100%    │ │   42%      │ │ 2026-09-30│ │
│ └─────────┘ └───────────────────────────┘ └────────────┘ └───────────┘ │
│ Allocation by sub-exposure  ████████ ██████ ████ ███ ██                │
│ Semis 35% · Software 22% · Cyber 18% · …                               │
├────────────────────────────────────────────────────────────────────────┤
│ Theme thesis (2-3 sentences)                                           │
├────────────────────────────────────────────────────────────────────────┤
│ Portfolio Holdings                           Sort: [Weight ▾]          │
│ ┌──────────┬────────┬──────────────┬────────────┬───────────────────┐  │
│ │ Stock    │ 6M Ret │ Recent news  │ 6M K-line  │ Why included      │  │
│ ├──────────┼────────┼──────────────┼────────────┼───────────────────┤  │
│ │ NVDA     │ ▲+18.4%│ Headline…    │ ▯▮▯▮▮▯▮    │ 2-4 sentences…    │  │
│ │ NVIDIA   │        │ Source · date│ (click)    │                   │  │
│ │ 12.5% #1 │        │              │            │            [▾]    │  │
│ └──────────┴────────┴──────────────┴────────────┴───────────────────┘  │
│   (expanded row: factor contribution bars, composite score, caveats)   │
├────────────────────────────────────────────────────────────────────────┤
│ Considered but excluded (existing style)                               │
│ Basket-level risks (existing style)                                    │
├────────────────────────────────────────────────────────────────────────┤
│ Disclaimer (from report_data.disclaimer)                               │
└────────────────────────────────────────────────────────────────────────┘
```

## 3. Summary header (rec 3)

All values come from `report_data.summary`; the UI does no business math.

| Card | Content | Rules |
|---|---|---|
| Holdings | `holdings_count` | |
| Trailing 6M return | `weighted_return_6m` with `+/-` sign and arrow; small subtext `coverage {return_coverage}`; label **"Trailing 6M return of current weights (hypothetical, not performance)"** | Shows `n/a` when coverage < 0.5; label is never hidden |
| Top-3 weight | `top3_weight` | |
| Data as of | Earliest/latest `data_as_of`; tooltip "Source: stock-sdk (public market data), may be delayed" | Shows a "stale" chip if any holding is stale |
| Allocation bar | Horizontal stacked bar of `allocation_by_sub_exposure` with legend and percentages | Top 6 segments plus "Other"; hover shows exact weight |

Theme name, run timestamp, export menu and theme toggle sit in the page
header above it.

## 4. Holdings table (rec 1)

### 4.1 Columns (exactly these five, in this order)

| Column | Cell content |
|---|---|
| **Stock** | Ticker (monospace, bold) and company name; second line `12.5% weight · #3` (weight and rank live here, not in a sixth column, D6); warning icon with count if caveats exist |
| **6M Return** | Pill with sign, arrow and color (see §7); `n/a` when null; footnote marker `†` when `return_6m_source = factor_panel` |
| **Recent News** | Headline as a link (`target="_blank"`, `rel="noopener noreferrer"`, http/https only), then `Source · date` in muted text; two-line clamp with tooltip for the full headline; "No recent news available." when absent |
| **6M K-Line** | `KlineMini` image (weekly candles); clickable (§6); placeholder `Chart unavailable` with a tooltip showing the error code |
| **Why Included** | `why_included` text; clamped to 4 lines on desktop with "more" toggle |

### 4.2 Behavior

- **Default order:** weight descending (as built by the backend).
- **Sort control** above the table: Weight, 6M return, Composite score, Name.
  Column headers for Stock and 6M Return are also sortable (`aria-sort`,
  keyboard operable).
- **Sticky header** inside the scroll container; **sticky first column** when
  the viewport is 768–1024 px and horizontal scroll appears.
- **Row expand** (chevron): reveals the detail panel (§5). One row open at a
  time is optional; multiple open is allowed.
- **Numbers** use `font-variant-numeric: tabular-nums` and are right-aligned
  where numeric.
- Row hover highlight; no zebra striping (cleaner with dense charts).

## 5. Explainability panel (rec 4)

Shown in the expanded row; data from `holdings[].factor_contributions`,
`composite_score`, `rank`, `sub_exposure`, `caveats`.

- **Composite score** and **rank** as small stat chips.
- **Factor contribution bars:** one horizontal diverging bar per factor,
  centered on zero, positive to the right in the "up" color, negative to the
  left in the "down" color, value labeled at the bar end. Sort by absolute
  value descending; highlight the top two (these are the two the narrative is
  told to cite).
- **Dynamic keys:** do not hardcode the factor list. Map known keys to labels
  (`thematic_z` becomes "Thematic", `momentum_z` becomes "Momentum", and so on)
  and fall back to a title-cased key for unknown ones, so themes with 6 or 8
  factors (see Task 2) both render. Skip `null` values and show a muted "no
  data" note.
- **Caveats:** each caveat string as a warning chip (amber token) with an icon;
  chips also summarized by a count badge on the collapsed row.
- Also show `sub_exposure` as a neutral tag.

## 6. K-line (rec 2)

### 6.1 Mini chart in the cell

- Static `<img src={kline.mini_url}>`, about 160 x 48 px, weekly candles,
  `alt="{TICKER} 6-month candlestick chart, {start} to {end}"`.
- Hover shows a subtle outline and pointer cursor; focusable and activated with
  Enter/Space.
- Chips under the image when flags exist: `Stale`, `Check price adjustment`,
  `< 6M history`.
- Footer text in muted small type on hover/focus or in the modal:
  "Source: stock-sdk (public market data) · as of {as_of}".

### 6.2 Modal (`KlineModal`)

- Opens from the mini chart; loads `GET /runs/{id}/klines/{ticker}` (show a
  skeleton while loading, an error state with Retry on failure).
- **Chart:** daily candlesticks with a volume histogram beneath, crosshair and
  tooltip (date, O/H/L/C, volume, day change).
- **Controls:** range toggle 1M / 3M / 6M (slices the stored bars; no new
  fetch), MA5 and MA20 overlay toggles (simple moving averages computed
  client-side from stored bars, pure function with tests).
- **Header:** ticker, company, 6M return pill, as-of date, source line, flags.
- **Library:** TradingView Lightweight Charts by default, or Apache ECharts
  (D4); include the required attribution/notice.
- **Accessibility:** focus trap, Esc to close, focus returns to the trigger,
  `role="dialog"` with `aria-labelledby`; a visually hidden summary table
  (first/last close, high, low) for screen readers.

## 7. Visual system (rec 6)

### 7.1 Tokens (CSS variables; verify contrast with a tool)

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#f7f8fa` | `#0b0f14` |
| `--surface` | `#ffffff` | `#121821` |
| `--border` | `#e5e7eb` | `#1f2937` |
| `--text` | `#111827` | `#e5e7eb` |
| `--muted` | `#6b7280` | `#9ca3af` |
| `--up` | `#15803d` | `#22c55e` |
| `--down` | `#b91c1c` | `#ef4444` |
| `--accent` | `#2563eb` | `#3b82f6` |
| `--warn` | `#b45309` | `#f59e0b` |

Up/down colors are tokens so the convention can be flipped (D3). Theme follows
`prefers-color-scheme` by default with a manual toggle persisted in
`localStorage` (wrapped in try/catch). The server-rendered SVG uses mid-tone
candle colors that read on both backgrounds.

### 7.2 Typography and shape

System UI font stack for text; monospace for tickers; tabular numerals for all
figures; 8 px spacing grid; 8 px corner radius on cards, 4 px on chips; 1 px
borders, minimal shadow.

### 7.3 Return pill

`▲ +18.4%` in `--up`, `▼ -3.2%` in `--down`, `n/a` muted. Background is a
10–15 percent tint of the color. The sign and arrow remain even in print and
grayscale.

### 7.4 Data freshness and provenance

- Header "Data as of" card (§3) and per-chart source line (§6).
- News items show `Source · date` when `published_at` exists, otherwise
  `Source` only.
- Stale snapshots show a `Stale` chip.

### 7.5 Pipeline stepper

Six stages: Screening, Analysis, Scoring, Basket, Charts, Report. States:
pending, running (animated), done, failed (with message). While a run is in
progress the report area shows skeletons; on completion it swaps to the report.
Requires per-stage status from the API (PLAN Step 0.7); if none exists, show
only an overall status until it is added.

### 7.6 States

| State | Treatment |
|---|---|
| Loading | Skeleton summary cards and table rows |
| No holdings | Empty message with the reason if provided |
| Partial data | Row-level placeholders (`n/a`, `Chart unavailable`) |
| Error | Inline message with Retry |
| Legacy report | Existing markdown renderer, no summary/table enhancements |

## 8. Responsive layout (rec 7)

| Width | Layout |
|---|---|
| 1024 px and up | Full table, summary cards in one row |
| 768–1023 px | Table with sticky first column and horizontal scroll inside its own container; summary cards wrap to 2 columns |
| Below 768 px | **Card per holding** (no table) |

Mobile card, top to bottom: ticker + company + weight; return pill aligned
right; mini chart at full card width (tap opens modal); headline + source;
`why_included` clamped to 4 lines with "Read more"; expand control for the
explainability panel. The page body never scrolls horizontally. Allocation
bar and legend stack vertically.

## 9. Export (rec 8)

`ExportMenu` with three actions:

- **Markdown:** `GET /runs/{id}/report/export?format=md` (download).
- **CSV:** `GET /runs/{id}/report/export?format=csv` (download).
- **PDF:** `window.print()` using a print stylesheet; no server PDF service.

Print stylesheet: force the light theme; hide the stepper, sort control,
export menu, theme toggle and expand chevrons; show full (unclamped) text; keep
the table layout fixed; `break-inside: avoid` on rows; repeat the table header
on each page; show the disclaimer at the end; use the static mini SVG images;
add a footer line with theme name, run date and data source.

## 10. Accessibility checklist

- Semantic `<table>` with `<th scope>`; cards use headings and lists.
- All interactive elements are keyboard reachable with visible focus.
- `aria-sort` on sortable headers; `aria-expanded` on expand controls.
- Color is never the only signal; AA contrast in both themes.
- Images have meaningful `alt`; modal follows the dialog pattern (§6.2).
- Reduced motion: respect `prefers-reduced-motion` for stepper animation.

## 11. Copy

| Where | Text |
|---|---|
| Weighted return label | Trailing 6M return of current weights (hypothetical, not performance) |
| Chart source | Source: stock-sdk (public market data) · as of {date} |
| Missing chart | Chart unavailable |
| Missing news | No recent news available. |
| Fallback return marker | † 6-month return from the scoring model (no chart data) |
| Adjustment chip | Check price adjustment |

Final wording of the hypothetical-return label requires compliance review (D10).

## 12. Component inventory

`PipelineStepper`, `ReportSummaryHeader`, `AllocationBar`, `HoldingsTable`,
`HoldingCard` (mobile), `ReturnPill`, `KlineMini`, `KlineModal`, `FactorBars`,
`CaveatChip`, `ExportMenu`, `ThemeToggle`, `LegacyMarkdownReport`.

## 13. Visual QA checklist

- [ ] Five columns in the specified order; default weight order.
- [ ] Return pills correct in light, dark, and grayscale print.
- [ ] Mini charts crisp at 1x and 2x pixel density.
- [ ] Modal MA lines and volume match stored bars.
- [ ] 6-key and 8-key factor sets both render.
- [ ] Caveat chips and count badge visible.
- [ ] Disclaimer visible on every layout and in print.
- [ ] Phone (390 px): no horizontal scroll, charts tappable.
- [ ] Legacy report still renders.
