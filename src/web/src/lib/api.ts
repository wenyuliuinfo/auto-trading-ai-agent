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
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listThemes: () => request<Theme[]>("/themes"),
  getTheme: (themeId: string) => request<Theme>(`/themes/${themeId}`),
  createTheme: (payload: ThemeCreateRequest) =>
    request<Theme>("/themes", { method: "POST", body: JSON.stringify(payload) }),
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
};
