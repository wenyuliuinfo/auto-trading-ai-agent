# Task 2 — Report agent: holdings table with 6-month K-line

Status: DRAFT for review. Items marked **VERIFY** depend on code or SDK
behavior that was not inspected when drafting; resolve them in PLAN Step 0
and update this file. Open decisions are in §13.

## 1. Goal and non-goals

**Goal.** Replace the per-holding paragraphs in the report's "Portfolio
Holdings" section with a table whose columns are:

1. Stock (ticker + company name)
2. 6-month return
3. Recent news
4. 6-month K-line (candlestick chart)
5. Reason to pick this stock

K-line data comes from `stock-sdk` (https://github.com/chengzuopeng/stock-sdk)
using **Option B**: a snapshot taken at run time by a Node bridge, stored with
the run, and served from storage. Chart and return figures never change after
a run completes.

**Non-goals.**

- No change to Modeling, Trader, Screener or Analyst logic.
- The "considered but excluded" and "basket-level risks" sections keep their
  current content and style (no risk matrix, no collapsible near-miss UI).
- No FMP/yfinance fallback for K-lines in v1 (decision D1). A holding without a
  snapshot shows "Chart unavailable"; the report still completes.
- No real-time quotes, intraday charts, or shareable links.
- The LLM never produces numbers, news, or chart data (§2, Hard Rule 1).

## 2. Policy changes to REPORT_SKILL.md

| Rule | Change |
|---|---|
| **Hard Rule 7** (holdings are paragraphs, never tables) | **Reversed.** Holdings render as a five-column table **built by code** from structured rows. The LLM supplies only the "why included" text. `_reformat_holdings_table()` is deleted. |
| **Hard Rule 5** (one LLM call, no tools) | Preserved. Still one call; it now returns JSON via `complete_json` instead of free text via `complete_text`. |
| **Hard Rule 1** (zero new facts) | Preserved. Returns, summary statistics and chart data are derived by code from upstream state/snapshot. The prompt must not ask the LLM to restate them. Raw bars are not sent to the LLM. |
| **Hard Rule 2** (code-appended disclaimer) | Extended: the disclaimer must also be present in `report_data` so the UI cannot omit it when rendering from structured data. |
| "`report_node` never calls an `integrations/` client" | Preserved. K-line fetching lives in a separate deterministic node before Report; Report reads stored snapshots via `data/queries.py`. |
| `REPORT_SYSTEM_PROMPT` "verbatim from ARCHITECTURE.md §5.5" | Update §5.5 first, then the constant. |

## 3. Data flow

```
Trader ──► kline_snapshot_node ──► report_node ──► API ──► UI
              │  (deterministic,      │  (one JSON LLM call;
              │   no LLM)             │   code builds table)
              ▼                       ▼
        integrations/kline.py    data/queries.py
        (Node bridge, stdin/     get_klines / get_basket_with_scores /
         stdout JSON)            save_report(report_md, report_data)
              │
              ▼
        run_klines table (snapshot per run + ticker)
```

- `kline_snapshot_node` lives in `app/agents/kline_snapshot.py` (deterministic,
  like the Modeling node). It never raises on per-ticker failure.
- Only **basket holdings** are fetched, not near-misses.
- Graph wiring and `AgentState`: insert the node between Trader and Report
  (**VERIFY** location of the LangGraph definition and checkpoint implications).

## 4. K-line snapshot

### 4.1 Constants (`app/integrations/kline.py`)

```python
KLINE_BARS = 126               # daily bars kept and shown (~6 months)
KLINE_FETCH_BARS = 140         # request slightly more to survive vendor gaps
KLINE_MIN_BARS_CHART = 20      # below this: status "insufficient", no chart
KLINE_MIN_BARS_RETURN = 120    # below this: no snapshot-based 6M return
KLINE_STALE_DAYS = 7           # last bar older than this (calendar days) => stale flag
KLINE_TIMEOUT_TOTAL_S = 60
KLINE_MAX_OUTPUT_BYTES = 5_000_000
SUSPECT_ADJUSTMENT_MOVE = 0.35 # |1-day close change| >= this => flag (D2)
```

126 bars with `first_close = bars[0].close` matches the existing
`momentum_6m = close[-1] / close[-126] - 1` definition in `factor_panel.py`.

### 4.2 Bridge protocol

Package: `tools/stock-sdk-kline/` with a **pinned** `stock-sdk` version and a
script `fetch_klines.mjs`. Python launches it with
`asyncio.create_subprocess_exec` (list arguments, **no shell**, minimal
environment), sends one JSON request on stdin, reads one JSON response from
stdout.

Request:

```json
{"version": 1, "symbols": ["AAPL", "MSFT"], "bars": 140, "adjust": "forward"}
```

Response:

```json
{
  "version": 1,
  "sdk_version": "x.y.z",
  "results": {
    "AAPL": {"status": "ok", "bars": [
      {"date": "2026-03-31", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 123456}
    ]},
    "ZZZ": {"status": "error", "code": "NO_DATA"}
  }
}
```

- Symbols are passed over stdin, never as command-line arguments. Python also
  validates each with `^[A-Z0-9]{1,6}([.\-][A-Z]{1,2})?$` and marks anything
  else `INVALID_SYMBOL` without sending it.
- One process handles all tickers, with bounded concurrency inside the script
  (suggest 4) and the SDK's retry/rate-limit policy enabled.
- Exit code 0 even when some symbols fail; non-zero or timeout means every
  ticker becomes `unavailable` with `BRIDGE_FAILED`. stderr is logged
  truncated.
- **VERIFY** against the SDK docs (https://stock-sdk.linkdiary.cn): the exact
  US K-line method and option names (`sdk.kline.us`), how to request N bars,
  whether forward-adjusted prices are available, and symbol forms for share
  classes (`BRK.B`, `BF.B`). Do not guess option names; record real sample
  output as test fixtures.

### 4.3 Normalization (Python, after the bridge)

For each ticker: drop bars with null/non-positive OHLC or with
`high < max(open, close)` or `low > min(open, close)`; sort ascending by date;
de-duplicate dates (keep last); keep the last `KLINE_BARS`.

Status values: `ok`, `insufficient`, `unavailable`.

Flags (stored, shown as UI chips):

- `stale`: last bar older than `KLINE_STALE_DAYS`.
- `suspect_adjustment`: any 1-day close change at or beyond
  `SUSPECT_ADJUSTMENT_MOVE` (possible unadjusted split; D2).
- `short_history`: fewer than `KLINE_BARS` bars but at least
  `KLINE_MIN_BARS_CHART`.

Error codes: SDK codes (`HTTP_ERROR`, `NETWORK_ERROR`, `TIMEOUT`, `ABORTED`,
`PARSE_ERROR`) passed through, plus `NO_DATA`, `INVALID_SYMBOL`, `DISABLED`,
`BRIDGE_FAILED`, `INSUFFICIENT_HISTORY`.

### 4.4 Settings and stub mode

- `kline_enabled` (default true), `kline_node_bin`, `kline_script_path`,
  `kline_timeout_s`; add to `app/config.py` and `.env.example`.
- When `settings.stub_agents` is true, generate deterministic seeded OHLC
  (same pattern as `_stub_price_history`) with no Node and no network.
- `kline_enabled = false` makes every ticker `unavailable` / `DISABLED`.

## 5. Derived metrics (code only)

**Per holding**

- `return_6m = bars[-1].close / bars[0].close - 1` when status is `ok` and
  `len(bars) >= KLINE_MIN_BARS_RETURN` and `bars[0].close > 0`;
  `return_6m_source = "kline_snapshot"`.
- Otherwise fall back to `momentum_6m` from `get_factor_panel_rows`
  (`return_6m_source = "factor_panel"`); otherwise `null`.
- The UI shows a footnote marker when the source is `factor_panel`.

**Summary**

| Field | Definition |
|---|---|
| `holdings_count` | Number of basket holdings |
| `weighted_return_6m` | `sum(w_i * r_i) / sum(w_i)` over holdings with non-null `return_6m` |
| `return_coverage` | `sum(w_i of holdings with return) / sum(w_i)`; if below 0.5 the UI shows "n/a" |
| `top3_weight` | Sum of the three largest weights |
| `allocation_by_sub_exposure` | Sum of weights grouped by `sub_exposure` (missing becomes "Other"), sorted descending |
| `data_as_of` | Earliest and latest `as_of` across snapshots |

`weighted_return_6m` is the **trailing return of today's weights**, a
hypothetical figure, not realized performance. Labeling must say so (§10).

## 6. Report generation

### 6.1 LLM call

`complete_json` with a Pydantic schema (same client method Modeling uses):

```python
class HoldingReason(BaseModel):
    ticker: str
    why_included: str            # 2-4 sentences

class ExcludedNote(BaseModel):
    ticker: str
    reason: str

class ReportNarrative(BaseModel):
    thesis: str                  # 2-3 sentences
    holdings: list[HoldingReason]
    excluded: list[ExcludedNote] # 2-3 near-miss names
    risk_summary: str            # describes provided risk_clusters only
```

Model and temperature unchanged (`REPORT_MODEL`, `REPORT_TEMPERATURE`).
Strings are plain text; code adds headings, tables and formatting.

### 6.2 Prompt changes (also update ARCHITECTURE.md §5.5)

- Remove: the "latest headline with source" and "1-year performance" lines
  from item 2, and item 5 (paragraph/heading format).
- Add: output must be the JSON object above; `why_included` must not restate
  the headline or return figure (they are displayed in separate columns);
  keep grounding in `thematic_relevance_rationale`, `composite_score`, top-2
  `factor_contributions`, catalysts, and any Modeling `caveats`.
- Context to the LLM: as today, plus per-holding `return_6m` (code-derived).
  **No bars.**

### 6.3 Validation and fallback

After the call, `validate_narrative(narrative, basket_tickers,
near_miss_tickers)`:

- Drop entries for tickers not in the basket / near-miss set (hallucinated).
- For any holding with a missing or empty `why_included`, use a deterministic
  fallback built only from upstream fields:
  `"{thematic_relevance_rationale} Composite score {score:.4f}."`
  (+ caveats if any).
- On invalid JSON or exception from the call: use fallbacks for every holding,
  a deterministic thesis (reuse the existing stub thesis text), no excluded
  notes beyond the stub pattern, and set `narrative_fallback = true` in
  `report_data`. Log a warning; do **not** fail the run.

### 6.4 Markdown assembly

Code builds `report_md`:

```
# {theme} - Rationale Report
## Theme Thesis
{thesis}
## Portfolio Holdings
| Stock | 6M Return | Recent News | 6M K-Line | Why Included |
|---|---|---|---|---|
| **AAPL** - Apple Inc. · 12.5% weight | +18.4% | [Headline](https://…) - Source | ![AAPL 6M K-line](/api/runs/{run_id}/klines/AAPL/mini.svg) | text… |
## Considered But Excluded
…
## Basket-Level Risks
{risk_summary or "No common basket-level risk cluster was identified across holdings."}

---
*disclaimer*
```

Cell rules (`_md_cell`): replace `|` with `\|`, collapse newlines to spaces,
strip control characters, escape `[` `]` in link text. Links must be
`http://` or `https://` only; otherwise render the headline as plain text.
Return format `f"{r * 100:+.1f}%"`, or `n/a`. Rows ordered by weight
descending, tie-break by rank. Missing news: `No recent news available.`
Missing chart: `Chart unavailable`.

**News selection (D5, VERIFY schema):** the newest item by `published_at` when
present, otherwise the first item in `analyst_report["news"]`.

`apply_disclaimer()` still wraps the final markdown.

## 7. Persistence

Additive migrations (no destructive changes):

**`run_klines`**

| Column | Notes |
|---|---|
| `run_id` | FK to runs, **`ON DELETE CASCADE`** |
| `ticker` | PK with `run_id` |
| `status` | `ok` / `insufficient` / `unavailable` |
| `source`, `sdk_version`, `adjust`, `period` | `stock-sdk`, pinned version, `forward`/`none`, `daily` |
| `as_of` | Date of last bar, nullable |
| `fetched_at` | Timestamp |
| `bars` | JSONB, nullable |
| `flags` | JSONB (`stale`, `suspect_adjustment`, `short_history`) |
| `error_code` | Nullable |

**`reports.report_data`**: JSONB, nullable. `save_report(run_id, report_md,
report_data)`. Legacy rows have `null` and render as before.

If Task 1's theme deletion is implemented, make sure `run_klines` is covered by
its cascade/cleanup (**VERIFY**).

### `report_data` (schema_version 1)

```json
{
  "schema_version": 1,
  "disclaimer": "…same text as DISCLAIMER…",
  "narrative_fallback": false,
  "summary": {
    "holdings_count": 9, "weighted_return_6m": 0.123, "return_coverage": 1.0,
    "top3_weight": 0.42,
    "allocation_by_sub_exposure": [{"name": "Semiconductors", "weight": 0.35}],
    "data_as_of": {"earliest": "2026-09-30", "latest": "2026-09-30"}
  },
  "thesis": "…",
  "holdings": [{
    "ticker": "AAPL", "company_name": "Apple Inc.", "weight": 0.125, "rank": 3,
    "sub_exposure": "…", "composite_score": 1.234,
    "return_6m": 0.184, "return_6m_source": "kline_snapshot",
    "news": {"headline": "…", "source": "…", "url": "https://…", "published_at": null},
    "kline": {"status": "ok", "as_of": "2026-09-30", "flags": [],
              "mini_url": "/api/runs/{run_id}/klines/AAPL/mini.svg"},
    "why_included": "…",
    "factor_contributions": {"thematic_z": 0.31, "growth_z": 0.12},
    "caveats": []
  }],
  "excluded": [{"ticker": "…", "company_name": "…", "reason": "…"}],
  "risk_summary": "…"
}
```

`factor_contributions` is passed through with whatever keys the theme's
persisted weights contain (6 or 8 keys if Task 2 ships); the UI must not assume
a fixed set.

## 8. API contract (additive; paths are proposals, align with existing routes)

| Endpoint | Purpose |
|---|---|
| Existing report endpoint | Add nullable `report_data` field; `report_md` unchanged in meaning |
| `GET /runs/{run_id}/klines/{ticker}` | JSON `{ticker, status, as_of, source, sdk_version, adjust, flags, bars[]}`; 404 if the ticker is not a holding of the run |
| `GET /runs/{run_id}/klines/{ticker}/mini.svg` | Server-rendered mini chart (§9); `Content-Type: image/svg+xml`; `Cache-Control: private` with a long max-age (snapshots are immutable) |
| `GET /runs/{run_id}/report/export?format=md\|csv` | Attachment. `md`: image URLs rewritten to absolute using `public_base_url`. `csv`: see §9 |

All are read-only and use the same session scoping as existing run endpoints.
PDF is produced client-side via print stylesheet (UI_DESIGN §10).

## 9. Mini chart (SVG) and CSV export

**Mini SVG** — `render_kline_svg(bars)` is a pure function with no I/O. Put it
in a small module next to the report code (for example `app/reports/`), and
**VERIFY** the placement against the layer rules with `pnpm check:structure`.
Requirements:

- Aggregate daily bars to **weekly candles** (open = first open, high = max,
  low = min, close = last close, ISO week) so ~26 candles remain legible at
  about 160 x 48 px. The modal shows daily bars.
- Transparent background, mid-tone up/down colors readable on light and dark,
  `<title>` with start and end close, `role="img"`.
- Contains only numbers computed from stored bars; no user-supplied text.

**CSV** — one row per holding: `ticker, company_name, weight, rank,
composite_score, return_6m, return_6m_source, news_headline, news_source,
news_url, why_included, caveats`. Quote all fields; neutralize leading
`= + - @` in text fields to prevent spreadsheet formula injection.

## 10. Security and compliance

- **Subprocess hardening:** no shell, argument list only, symbols over stdin,
  validated; output size cap; hard timeout; minimal environment; kill process
  group on timeout.
- **XSS:** URLs allowlisted to http/https; headline text escaped; SVG served
  as an image with `Content-Type: image/svg+xml` (never inlined from stored
  strings).
- **Unofficial source:** stock-sdk reads public third-party endpoints and
  quotes may be delayed. Review those providers' terms before client-facing
  use. Show "Source: stock-sdk (public market data), as of {date}" next to
  every chart.
- **Hypothetical return wording:** the summary figure must read
  "Trailing 6M return of current weights (hypothetical, not performance)".
  Get compliance review before shipping.
- **Licenses:** stock-sdk is ISC; the chart library has its own attribution
  requirements (D4). Add third-party notices.

## 11. Backward compatibility

- Reports created before this change have `report_data = null`; the UI keeps
  the existing markdown renderer for them.
- API changes are additive.
- Existing runs have no `run_klines` rows; the klines endpoints return 404 and
  the UI never requests them when `report_data` is null.
- Migrations only add a table and a nullable column.
- **Rollback:** revert the deploy; extra table/column are harmless.
  `KLINE_ENABLED=false` is the operational kill switch for the data source.

## 12. Acceptance criteria

- **A1.** A run completes and the report contains the five-column table with
  one row per holding, in weight order.
- **A2.** `report_md` for new runs contains no paragraph-style holdings and
  `_reformat_holdings_table` no longer exists.
- **A3.** Every holding row has non-null `return_6m` and an `ok` chart when
  fixtures are complete; otherwise `n/a` / `Chart unavailable` with the run
  still succeeding.
- **A4.** `return_6m` equals `last_close / first_close - 1` of the stored
  bars, and the table value equals `report_data` value.
- **A5.** The LLM prompt and context contain no bars and no instruction to
  produce a return or headline.
- **A6.** A hallucinated ticker in the LLM output never appears in the report;
  a missing ticker gets the deterministic fallback.
- **A7.** Invalid JSON from the LLM yields a complete report with
  `narrative_fallback = true`.
- **A8.** The disclaimer is present in `report_md` and `report_data.disclaimer`
  and rendered in the UI on both paths.
- **A9.** Cells containing `|`, newlines, or `javascript:` URLs are rendered
  safely.
- **A10.** Bridge failure (timeout, crash, bad JSON) never fails the run.
- **A11.** Legacy reports (`report_data = null`) still render.
- **A12.** Docs updated (§15) and the full check suite passes.

## 13. Open decisions (recommended default in bold)

1. **D1** FMP/yfinance fallback for K-lines: **none in v1**; follow-up would
   need OHLC added to `PriceHistory`.
2. **D2** Price adjustment: **forward-adjusted if the SDK supports it**;
   otherwise unadjusted plus the `suspect_adjustment` flag.
3. **D3** Candle colors: **green up / red down** as theme tokens (the SDK is
   China-oriented; confirm audience).
4. **D4** Chart library for the modal: **TradingView Lightweight Charts**
   (finance-native, small) vs Apache ECharts; check attribution terms.
5. **D5** News selection rule (§6.4).
6. **D6** Weight and rank shown inside the Stock cell (**yes**) rather than a
   sixth column.
7. **D7** Mini chart uses weekly candles (**yes**).
8. **D8** Node packaging: **same worker image** vs separate sidecar.
9. **D9** `public_base_url` setting for markdown export (**VERIFY** whether one
   exists).
10. **D10** Compliance wording for the hypothetical weighted return.

## 14. Files touched

| Area | Files |
|---|---|
| Node bridge | `tools/stock-sdk-kline/{package.json, fetch_klines.mjs}`, lockfile |
| Integration | `app/integrations/kline.py`, `app/config.py`, `.env.example` |
| Node | `app/agents/kline_snapshot.py`, graph wiring, `AgentState` |
| Data | `app/data/queries.py` (`save_klines`, `get_klines`, `save_report`), models, migration |
| Report | `app/agents/report.py` (context, schema, prompt, validate, assemble, delete `_reformat_holdings_table`, stub) |
| Rendering | SVG renderer module, export module |
| API | report response, klines JSON, mini SVG, export endpoints, schemas |
| Evaluation | `app/evaluation/groundedness.py` |
| Frontend | See `UI_DESIGN.md` |
| Infra | Dockerfile(s), CI (Node 18+, install pinned SDK) |
| Docs | `REPORT_SKILL.md`, `ARCHITECTURE.md` (§5.5, nodes, tables, decision log), `CONTEXT.md`, `CONVENTIONS.md`, README API table, third-party notices |

## 15. Documentation updates required

`REPORT_SKILL.md` Rules 1, 2, 7 and test fixtures; `ARCHITECTURE.md` §5.5
prompt, new node, new table, API contracts and a decision-log entry (Rule 7
reversal, unofficial data source, snapshot semantics); `CONTEXT.md` new terms
(K-line snapshot, weekly mini chart, hypothetical weighted return).
