-- ============================================================
-- init.sql — thematic-basket-system domain schema
-- Run once on a fresh Postgres instance (postgres:15-alpine)
-- ============================================================

-- gen_random_uuid() is native in Postgres 13+, but pgcrypto
-- ensures compatibility if ever downgraded.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------
-- 1. themes
-- ------------------------------------------------------------
CREATE TABLE themes (
    theme_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    config          JSONB NOT NULL,        -- sub-exposures, factor weights, screens
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_themes_created_at ON themes(created_at);

-- ------------------------------------------------------------
-- 2. runs
-- ------------------------------------------------------------
CREATE TABLE runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id        UUID REFERENCES themes(theme_id) ON DELETE CASCADE,
    requested_at    TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL,          -- queued | running | complete | failed
    retry_count     INT DEFAULT 0,
    error_detail    TEXT
);

CREATE INDEX idx_runs_theme_id     ON runs(theme_id);
CREATE INDEX idx_runs_status       ON runs(status);
CREATE INDEX idx_runs_requested_at ON runs(requested_at);

-- ------------------------------------------------------------
-- 3. candidates
-- ------------------------------------------------------------
CREATE TABLE candidates (
    candidate_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker           TEXT NOT NULL,
    company_name     TEXT,
    gics_subindustry TEXT,
    sub_exposure_tag TEXT,
    market_cap       NUMERIC,
    avg_dollar_volume NUMERIC,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_candidates_run_id   ON candidates(run_id);
CREATE INDEX idx_candidates_ticker     ON candidates(ticker);

-- ------------------------------------------------------------
-- 4. analyst_reports
-- ------------------------------------------------------------
CREATE TABLE analyst_reports (
    report_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                       UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker                       TEXT NOT NULL,
    thematic_relevance_score     NUMERIC,
    thematic_relevance_rationale TEXT,
    revenue_pct_theme_estimate   NUMERIC,
    catalysts                    JSONB,
    risks                        JSONB,
    sentiment_label              TEXT,
    sentiment_evidence           JSONB,
    sources                      JSONB,
    news                         JSONB,        -- latest news items surfaced in the Report
    fetched_at                   TIMESTAMPTZ DEFAULT now(),   -- used for same-day cache lookups
    UNIQUE (ticker, run_id)
);

CREATE INDEX idx_analyst_reports_run_id    ON analyst_reports(run_id);
CREATE INDEX idx_analyst_reports_ticker    ON analyst_reports(ticker);
CREATE INDEX idx_analyst_reports_fetched_at ON analyst_reports(fetched_at);
CREATE INDEX idx_analyst_reports_ticker_fetched ON analyst_reports(ticker, fetched_at);

-- Cache lookup: reuse a report if one exists for `ticker` with
-- fetched_at > now() - interval '1 day', regardless of run_id, before
-- calling the Analyst LLM/tools again.

-- ------------------------------------------------------------
-- 5. factor_panel
-- ------------------------------------------------------------
CREATE TABLE factor_panel (
    factor_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    as_of_date      DATE NOT NULL,
    factor_name     TEXT NOT NULL,       -- 'pe_ratio', 'roe', 'momentum_6m', ...
    raw_value       NUMERIC,
    z_score         NUMERIC
);

CREATE INDEX idx_factor_panel_run_id      ON factor_panel(run_id);
CREATE INDEX idx_factor_panel_ticker      ON factor_panel(ticker);
CREATE INDEX idx_factor_panel_as_of_date  ON factor_panel(as_of_date);
CREATE INDEX idx_factor_panel_factor_name ON factor_panel(factor_name);
CREATE INDEX idx_factor_panel_ticker_asof ON factor_panel(ticker, as_of_date);
CREATE INDEX idx_factor_panel_asof_factor ON factor_panel(as_of_date, factor_name);

-- ------------------------------------------------------------
-- 6. rankings
-- ------------------------------------------------------------
CREATE TABLE rankings (
    ranking_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker               TEXT NOT NULL,
    composite_score      NUMERIC,
    rank                 INT,
    factor_contributions JSONB,
    caveats              JSONB
);

CREATE INDEX idx_rankings_run_id  ON rankings(run_id);
CREATE INDEX idx_rankings_ticker  ON rankings(ticker);
CREATE INDEX idx_rankings_rank    ON rankings(rank);

-- ------------------------------------------------------------
-- 7. baskets
-- ------------------------------------------------------------
CREATE TABLE baskets (
    basket_row_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    weight          NUMERIC NOT NULL,
    rank            INT,
    sub_exposure    TEXT,
    swap_reason     TEXT
);

CREATE INDEX idx_baskets_run_id ON baskets(run_id);
CREATE INDEX idx_baskets_ticker ON baskets(ticker);

-- ------------------------------------------------------------
-- 8. reports
-- ------------------------------------------------------------
CREATE TABLE reports (
    report_doc_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id) ON DELETE CASCADE UNIQUE,
    report_md       TEXT NOT NULL,
    report_data     JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_reports_run_id     ON reports(run_id);
CREATE INDEX idx_reports_created_at ON reports(created_at);

-- ------------------------------------------------------------
-- 9b. run_klines — immutable per-run K-line snapshots
-- ------------------------------------------------------------
CREATE TABLE run_klines (
    run_id          UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    status          TEXT NOT NULL,
    source          TEXT NOT NULL,
    sdk_version     TEXT,
    adjust          TEXT NOT NULL,
    period          TEXT NOT NULL DEFAULT 'daily',
    as_of           DATE,
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    bars            JSONB,
    flags           JSONB,
    error_code      TEXT,
    PRIMARY KEY (run_id, ticker)
);

CREATE INDEX idx_run_klines_run_id ON run_klines(run_id);

-- ------------------------------------------------------------
-- 9. basket_performance
-- ------------------------------------------------------------
CREATE TABLE basket_performance (
    perf_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    as_of_date       DATE NOT NULL,
    realized_return  NUMERIC,
    benchmark_return NUMERIC,
    alpha            NUMERIC
);

CREATE INDEX idx_basket_perf_run_id     ON basket_performance(run_id);
CREATE INDEX idx_basket_perf_as_of_date ON basket_performance(as_of_date);

-- ------------------------------------------------------------
-- 10. backtest results and child artifacts
-- ------------------------------------------------------------
CREATE TABLE backtest_runs (
    backtest_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    mode                 TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'queued',
    progress             JSONB,
    data_source          TEXT,
    config_hash          TEXT,
    config_json          JSONB,
    methodology_version  INT,
    code_version         TEXT,
    data_version         TEXT,
    period_start         DATE,
    period_end           DATE,
    initial_cash         NUMERIC,
    costs_total          NUMERIC,
    summary              JSONB,
    attribution          JSONB,
    flags                JSONB,
    error_code           TEXT,
    error_message        TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    started_at           TIMESTAMPTZ,
    finished_at          TIMESTAMPTZ
);

CREATE INDEX idx_backtest_runs_run_id     ON backtest_runs(run_id);
CREATE INDEX idx_backtest_runs_mode       ON backtest_runs(mode);
CREATE INDEX idx_backtest_runs_created_at ON backtest_runs(created_at);

CREATE TABLE backtest_rebalances (
    backtest_rebalance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id           UUID REFERENCES backtest_runs(backtest_id) ON DELETE CASCADE,
    idx                   INT NOT NULL,
    signal_date           DATE NOT NULL,
    exec_date             DATE NOT NULL,
    hold_end_date         DATE NOT NULL,
    candidate_count       INT,
    eligible_count        INT,
    basket                JSONB,
    flags                 JSONB,
    period_return         NUMERIC,
    benchmark_returns     JSONB,
    inputs_summary        JSONB
);

CREATE INDEX idx_backtest_rebalances_backtest_id ON backtest_rebalances(backtest_id);
CREATE INDEX idx_backtest_rebalances_idx        ON backtest_rebalances(idx);

CREATE TABLE backtest_equity (
    backtest_equity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id        UUID REFERENCES backtest_runs(backtest_id) ON DELETE CASCADE,
    series_name        TEXT NOT NULL,
    points             JSONB NOT NULL
);

CREATE INDEX idx_backtest_equity_backtest_id ON backtest_equity(backtest_id);

CREATE TABLE backtest_trades (
    backtest_trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id       UUID REFERENCES backtest_runs(backtest_id) ON DELETE CASCADE,
    seq               INT NOT NULL,
    date              DATE NOT NULL,
    ticker            TEXT NOT NULL,
    side              TEXT NOT NULL,
    shares            NUMERIC NOT NULL,
    price             NUMERIC NOT NULL,
    value             NUMERIC NOT NULL,
    cost              NUMERIC NOT NULL,
    reason            TEXT NOT NULL
);

CREATE INDEX idx_backtest_trades_backtest_id ON backtest_trades(backtest_id);
CREATE INDEX idx_backtest_trades_seq        ON backtest_trades(seq);
