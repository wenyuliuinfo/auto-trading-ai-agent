function resolveApiBase(): string {
  // Server components need an absolute internal URL; browser code uses
  // same-origin requests that Next.js rewrites to FastAPI (see next.config.ts).
  if (typeof window === "undefined") {
    return (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
  }
  return "";
}

export const API_BASE = resolveApiBase();

export interface ThemeConfig {
  sub_exposures: string[];
  factor_weights: Record<string, number>;
  screens: Record<string, number>;
  weighting_scheme: "equal_weight" | "score_weighted";
  validator_enabled: boolean;
}

export interface Theme {
  theme_id: string;
  name: string;
  definition: string;
  config: ThemeConfig;
  created_at: string;
}

export interface RunStatus {
  run_id: string;
  theme_id: string;
  status: "queued" | "running" | "complete" | "failed";
  requested_at: string;
  retry_count: number;
  error_detail: string | null;
  progress: { analyzed: number; total: number } | null;
}

export interface BasketHolding {
  ticker: string;
  weight: number;
  rank: number | null;
  sub_exposure: string | null;
  swap_reason: string | null;
  composite_score: number | null;
  factor_contributions: Record<string, number | null>;
}

export interface RankingRow {
  ticker: string;
  composite_score: number | null;
  rank: number | null;
  factor_contributions: Record<string, number | null>;
  caveats: string[];
}

export interface ReportResponse {
  run_id: string;
  report_md: string;
  disclaimer: string;
  report_data: ReportData | null;
}

export interface ReportNews {
  headline: string;
  source: string;
  url: string | null;
  published_at: string | null;
}

export interface ReportKline {
  status: "ok" | "insufficient" | "unavailable";
  as_of: string | null;
  flags: string[];
  mini_url: string | null;
  error_code: string | null;
}

export interface ReportHolding {
  ticker: string;
  company_name: string;
  weight: number;
  rank: number | null;
  sub_exposure: string | null;
  composite_score: number | null;
  return_6m: number | null;
  return_6m_source: "kline_snapshot" | "factor_panel" | null;
  news: ReportNews;
  kline: ReportKline;
  why_included: string;
  factor_contributions: Record<string, number | null>;
  caveats: string[];
}

export interface ReportSummary {
  holdings_count: number;
  weighted_return_6m: number | null;
  return_coverage: number;
  top3_weight: number;
  allocation_by_sub_exposure: { name: string; weight: number }[];
  data_as_of: { earliest: string | null; latest: string | null };
}

export interface ReportData {
  schema_version: number;
  theme_name: string;
  disclaimer: string;
  narrative_fallback: boolean;
  summary: ReportSummary;
  thesis: string;
  holdings: ReportHolding[];
  excluded: { ticker: string; company_name: string; reason: string }[];
  risk_summary: string;
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KlineResponse {
  ticker: string;
  status: "ok" | "insufficient" | "unavailable";
  source: string;
  sdk_version: string | null;
  adjust: string;
  as_of: string | null;
  flags: string[];
  error_code: string | null;
  bars: KlineBar[];
}

export type BacktestMode = "trailing" | "full";
export type BacktestStatus =
  | "not_run"
  | "disabled"
  | "queued"
  | "running"
  | "succeeded"
  | "partial"
  | "failed";

export interface BacktestEquityPoint {
  date: string;
  value: number;
}

export interface BacktestMetric {
  total_return: number | null;
  final_value: number | null;
  cagr?: number | null;
  volatility: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  max_drawdown_peak_date?: string | null;
  max_drawdown_trough_date?: string | null;
  alpha?: number | null;
  beta?: number | null;
  turnover?: number | null;
  costs_paid?: number | null;
  tracking_error?: number | null;
  information_ratio?: number | null;
  hit_rate?: number | null;
}

export interface BacktestRebalance {
  idx: number;
  signal_date: string;
  exec_date: string;
  hold_end_date: string;
  candidate_count: number | null;
  eligible_count: number | null;
  basket: Array<{
    ticker: string;
    weight: number;
    rank?: number | null;
    sub_exposure?: string | null;
    composite_score?: number | null;
  }>;
  flags: string[];
  period_return: number | null;
  benchmark_returns: Record<string, number | null>;
  inputs_summary: Record<string, unknown>;
}

export interface BacktestTrade {
  seq: number;
  date: string;
  ticker: string;
  side: "BUY" | "SELL";
  shares: number;
  price: number;
  value: number;
  cost: number;
  reason: string;
}

export interface BacktestCurrentHolding {
  ticker: string;
  company_name: string | null;
  weight: number | null;
  rank: number | null;
  return_6m: number | null;
  price: number | null;
  pe_ratio: number | null;
  market_cap: number | null;
  kline: {
    status: "ok" | "insufficient" | "unavailable";
    mini_url: string | null;
  };
}

export interface BacktestPayload {
  backtest_id?: string;
  run_id: string;
  mode: BacktestMode;
  status: BacktestStatus;
  progress: { stage: string; completed: number; total: number };
  data_source?: "fmp" | "stub" | "mixed" | null;
  methodology_version?: number | null;
  config_hash?: string | null;
  code_version?: string | null;
  data_version?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  initial_cash?: number | null;
  costs_total?: number | null;
  summary: {
    strategy: BacktestMetric;
    benchmarks: Record<string, BacktestMetric>;
  };
  series: Record<string, BacktestEquityPoint[]>;
  rebalances: BacktestRebalance[];
  attribution: Array<{
    ticker: string;
    company_name: string | null;
    pnl: number;
    contribution_pct: number;
    periods_held: number;
  }>;
  trades: BacktestTrade[];
  current_holdings: BacktestCurrentHolding[];
  flags: string[];
  disclaimer: string;
  error_code?: string | null;
  error_message?: string | null;
}

export interface ThemeCreateRequest {
  name: string;
  definition: string;
  sub_exposures: string[];
  weighting_scheme?: "equal_weight" | "score_weighted";
  validator_enabled?: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (response.status === 204) {
    return undefined as T;
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listThemes: () => request<Theme[]>("/themes"),
  listSubExposures: () => request<string[]>("/themes/sub-exposures"),
  getTheme: (themeId: string) => request<Theme>(`/themes/${themeId}`),
  createTheme: (payload: ThemeCreateRequest) =>
    request<Theme>("/themes", { method: "POST", body: JSON.stringify(payload) }),
  deleteTheme: (themeId: string) =>
    request<void>(`/themes/${themeId}`, { method: "DELETE" }),
  triggerRun: (themeId: string) =>
    request<{ run_id: string; status: "queued" }>(
      `/themes/${themeId}/runs`,
      { method: "POST" },
    ),
  getRun: (runId: string) => request<RunStatus>(`/runs/${runId}`),
  getBasket: (runId: string) =>
    request<BasketHolding[]>(`/runs/${runId}/basket`),
  getRankings: (runId: string) =>
    request<RankingRow[]>(`/runs/${runId}/rankings`),
  getReport: (runId: string) => request<ReportResponse>(`/runs/${runId}/report`),
  getKline: (runId: string, ticker: string) =>
    request<KlineResponse>(`/runs/${runId}/klines/${ticker}`),
  getBacktest: (runId: string, mode: BacktestMode = "trailing") =>
    request<BacktestPayload>(`/runs/${runId}/backtest?mode=${mode}`),
  startBacktest: (runId: string, mode: BacktestMode) =>
    request<{ backtest_id: string; run_id: string; mode: BacktestMode; status: "queued" }>(
      `/runs/${runId}/backtest`,
      { method: "POST", body: JSON.stringify({ mode }) },
    ),
  getBacktestTrades: (
    runId: string,
    mode: BacktestMode = "trailing",
    limit = 25,
    offset = 0,
  ) =>
    request<{ items: BacktestTrade[]; total: number; limit: number; offset: number }>(
      `/runs/${runId}/backtest/trades?mode=${mode}&limit=${limit}&offset=${offset}`,
    ),
};
