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
};
