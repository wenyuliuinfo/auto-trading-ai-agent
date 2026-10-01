# Task 2 — Implementation Plan

Companion to `SPEC.md`, `TEST_PLAN.md`, `UI_DESIGN.md`. Each step is one
reviewable commit (or small PR). Steps 2–3 and 9 can run in parallel once
Step 0 is done; Step 9 can start against mock data after Step 7 defines the
API fixtures.

## Step 0 — Verification spikes (no production code)

Resolve every **VERIFY** in `SPEC.md` and record answers there.

1. **stock-sdk**: confirm the US K-line method, how to request N bars, whether
   adjusted prices exist, symbol forms for `BRK.B` / `BF.B`, and error codes.
   Save real sample output for 3–5 tickers as test fixtures (scrub nothing;
   it is public market data).
2. **Analyst output**: does `news[]` include `published_at`? Is the list
   ordered newest-first?
3. **Graph**: where is the LangGraph defined, how does `AgentState` carry data,
   and does adding a node affect checkpoints?
4. **Database**: reports table shape, migration tool (Alembic), and whether
   `save_report` has other callers.
5. **LLM client**: behavior of `complete_json` on invalid JSON (raises? retries?).
6. **API**: current report endpoint, session scoping, `public_base_url` setting.
7. **Progress**: does an endpoint already expose per-stage run status for the
   stepper? If not, decide the minimal addition.
8. **Layer rules**: where the SVG renderer may live (`pnpm check:structure`).
9. **Licenses**: chart library attribution terms; stock-sdk ISC notice.
10. **Task 1 cascade**: whether theme deletion covers `run_klines`.

Exit: `SPEC.md` status changes from DRAFT; open decisions D1–D10 settled.

## Step 1 — Baseline

With the stub fixture basket, save the current `report_md` as a snapshot.
The "considered but excluded" and "basket-level risks" sections must stay
equivalent in content after the refactor (the thesis and holdings sections
will change by design).

## Step 2 — Node bridge (`tools/stock-sdk-kline/`)

1. `package.json` with the pinned `stock-sdk` version; add to the pnpm
   workspace and lockfile.
2. `fetch_klines.mjs`: read the stdin request, fetch with bounded concurrency
   and the SDK's retry policy, normalize dates to ISO and numbers to floats,
   write the response JSON, per-symbol errors with codes, never crash on one
   bad symbol.
3. Script-level tests using a mocked SDK (no network).

## Step 3 — Python integration (`app/integrations/kline.py`)

1. Constants and symbol validation.
2. `fetch_klines(tickers) -> dict[str, KlineSnapshot]` using
   `asyncio.create_subprocess_exec`: timeout, output cap, process-group kill,
   truncated stderr logging.
3. Normalization, flags (`stale`, `suspect_adjustment`, `short_history`).
4. Stub mode (seeded OHLC) and `kline_enabled` switch.
5. Settings in `app/config.py` and `.env.example`.
6. Unit tests (TEST_PLAN §1–§2).

## Step 4 — Persistence

1. Alembic migration: `run_klines` table (FK with `ON DELETE CASCADE`) and
   nullable `reports.report_data`.
2. `app/data/queries.py`: `save_klines`, `get_klines`; extend
   `save_report(run_id, report_md, report_data=None)` keeping the old call
   signature working.
3. Tests (TEST_PLAN §8). Confirm Task 1 delete flow covers the new table.

## Step 5 — Graph node

1. `app/agents/kline_snapshot.py`: read basket tickers, call
   `fetch_klines`, `save_klines`; never raise on per-ticker failures.
2. Wire it between Trader and Report; update `AgentState` if needed.
3. Make sure the run still completes if the node is disabled or fails
   entirely.

## Step 6 — Report agent refactor (`app/agents/report.py`)

1. Add pure helpers: `compute_return_6m`, `compute_summary`, `_md_cell`,
   `_safe_url`, `select_latest_news`, `build_holdings_rows`.
2. Add `ReportNarrative` schema, new prompt (update ARCHITECTURE.md §5.5
   first), `validate_narrative`, deterministic fallbacks.
3. Replace `complete_text` with `complete_json`; build `report_md` and
   `report_data`; keep `apply_disclaimer`.
4. Delete `_reformat_holdings_table`, `_split_table_row`,
   `_strip_inline_markdown`, `_column_index` and their tests.
5. Update `assemble_report_context` (klines, `return_6m`, drop `return_1y`)
   and `_stub_report`.
6. Re-run the Step 1 baseline for the unchanged sections.

## Step 7 — Rendering and API

1. `render_kline_svg` (weekly aggregation) and CSV/markdown export helpers.
2. Endpoints: report with `report_data`, klines JSON, mini SVG, export.
3. Pydantic response models and OpenAPI; write API fixtures for the frontend.

## Step 8 — Groundedness checker

Update `app/evaluation/groundedness.py` so derived values (`return_6m`, weights,
composite score) and table-formatted rows are recognized as grounded, and
remove assumptions about paragraph-style holdings. Keep it advisory.

## Step 9 — Frontend (see `UI_DESIGN.md`)

1. Design tokens and theme switch.
2. `ReportSummaryHeader`, `HoldingsTable` (sorting, sticky header, expand),
   `ReturnPill`, `KlineMini`, `KlineModal`, `FactorBars`, `CaveatChip`.
3. Responsive card layout below 768 px.
4. `ExportMenu` (Markdown, CSV, PDF via print) and print stylesheet.
5. `PipelineStepper` (depends on Step 0.7).
6. Legacy fallback (`report_data == null` renders the existing markdown view).
7. Component tests with mock `report_data`.

## Step 10 — Infrastructure

Dockerfile(s) and CI: Node 18+, install pinned `stock-sdk` for the worker
image; cache the pnpm store; add the Node bridge tests to CI.

## Step 11 — Documentation

`REPORT_SKILL.md` (Rules 1, 2, 7, fixtures), `ARCHITECTURE.md` (§5.5 prompt,
new node, tables, API, decision log), `CONTEXT.md`, `CONVENTIONS.md`, README
API table, third-party notices.

## Step 12 — Verification

Run `pnpm lint`, `pnpm lint:api`, `pnpm test:api`, `pnpm --dir src/web test`,
`pnpm check:structure`, `pnpm build`, then the manual checks in TEST_PLAN §12
and the opt-in live smoke test (TEST_PLAN §13).

## Step 13 — Rollout

1. Deploy to staging with `KLINE_ENABLED=true`; run 5 themes across sectors
   (include a share-class ticker and a recent IPO).
2. Review: table rendering on desktop and mobile, print preview, CSV and
   Markdown exports, dark/light themes, chart accuracy against a charting
   site for 3 tickers.
3. Obtain compliance sign-off on the weighted-return wording (D10).
4. Production deploy; watch the per-run fraction of `ok` snapshots and bridge
   error codes for a week.

## Rollback

Revert the deploy. The new table and nullable column are harmless. For a
data-source outage without a redeploy, set `KLINE_ENABLED=false`: reports
still generate, charts show "Chart unavailable", and returns fall back to
`momentum_6m`.

## Risks

| Risk | Mitigation |
|---|---|
| Unofficial endpoints change or block | Pinned version, kill switch, graceful degradation, monitoring |
| SDK option names differ from assumptions | Step 0 spike, real fixtures |
| LLM returns bad JSON | Validation and deterministic fallbacks (A6, A7) |
| Table cell injection or broken markdown | `_md_cell`, URL allowlist, tests |
| Unadjusted split distorts chart and return | D2, `suspect_adjustment` chip |
| UI omits the disclaimer when using structured data | `report_data.disclaimer`, A8, component test |
| Node missing in the worker image | Step 10, startup self-check logs |
| Legacy reports break | `report_data == null` path, A11 |
