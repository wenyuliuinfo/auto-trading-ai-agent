"use client";

import { FileText, Gauge, ListOrdered } from "lucide-react";
import { useEffect, useState } from "react";

import {
  api,
  BasketHolding,
  RankingRow,
  ReportResponse,
  RunStatus,
} from "@/lib/api";
import { BasketTable } from "./BasketTable";
import { RankingsTable } from "./RankingsTable";
import { ReportView } from "./ReportView";

type Tab = "basket" | "rankings" | "report";

interface RunMonitorProps {
  runId: string;
  initialStatus: RunStatus;
}

export function RunMonitor({ runId, initialStatus }: RunMonitorProps) {
  const [status, setStatus] = useState<RunStatus>(initialStatus);
  const [basket, setBasket] = useState<BasketHolding[] | null>(null);
  const [rankings, setRankings] = useState<RankingRow[] | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [tab, setTab] = useState<Tab>("basket");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      try {
        const current = await api.getRun(runId);
        if (cancelled) return;
        setStatus(current);
        if (current.status === "complete") {
          const [basketResult, rankingResult, reportResult] = await Promise.allSettled([
            api.getBasket(runId),
            api.getRankings(runId),
            api.getReport(runId),
          ]);
          if (cancelled) return;
          let firstError: string | null = null;
          if (basketResult.status === "fulfilled") {
            setBasket(basketResult.value);
          } else if (
            basketResult.reason instanceof Error &&
            basketResult.reason.message.includes("API 404")
          ) {
            setBasket([]);
          } else {
            firstError = basketResult.reason instanceof Error ? basketResult.reason.message : "Basket load failed";
          }
          if (rankingResult.status === "fulfilled") {
            setRankings(rankingResult.value);
          } else if (!firstError) {
            firstError = rankingResult.reason instanceof Error ? rankingResult.reason.message : "Rankings load failed";
          }
          if (reportResult.status === "fulfilled") {
            setReport(reportResult.value);
          } else if (!firstError) {
            firstError = reportResult.reason instanceof Error ? reportResult.reason.message : "Report load failed";
          }
          setError(firstError);
          return;
        }
        if (current.status === "failed") {
          setError(current.error_detail ?? "Run failed");
          return;
        }
        timer = setTimeout(refresh, 2000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Status check failed");
      }
    }

    void refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  const analyzed = status.progress?.analyzed ?? 0;
  const total = status.progress?.total ?? 0;
  const pct = total > 0 ? Math.round((analyzed / total) * 100) : 0;

  return (
    <div>
      <div className="panel status-card">
        <div className="status-line">
          <span className={`badge badge-${status.status}`}>{status.status}</span>
          <span className="run-meta">{runId.slice(0, 8)}</span>
          <span className="run-count">{analyzed} / {total} analyzed</span>
        </div>
        <div className="progress-wrap">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="progress-label">{pct}%</span>
        </div>
        {error ? (
          <div className="form-error" style={{ marginTop: "0.75rem" }}>
            {error}
          </div>
        ) : null}
      </div>

      <div className="segmented">
        <button
          className={`segmented-btn${tab === "basket" ? " segmented-btn-active" : ""}`}
          onClick={() => setTab("basket")}
        >
          <Gauge size={15} aria-hidden />
          Basket
        </button>
        <button
          className={`segmented-btn${tab === "rankings" ? " segmented-btn-active" : ""}`}
          onClick={() => setTab("rankings")}
        >
          <ListOrdered size={15} aria-hidden />
          Rankings
        </button>
        <button
          className={`segmented-btn${tab === "report" ? " segmented-btn-active" : ""}`}
          onClick={() => setTab("report")}
        >
          <FileText size={15} aria-hidden />
          Report
        </button>
      </div>

      {tab === "basket" && basket && basket.length > 0 ? (
        <BasketTable holdings={basket} />
      ) : null}
      {tab === "basket" && basket && basket.length === 0 ? (
        <div className="panel empty-state">
          No basket was generated for this run.
        </div>
      ) : null}
      {tab === "rankings" && rankings ? <RankingsTable rankings={rankings} /> : null}
      {tab === "report" && report ? <ReportView markdown={report.report_md} /> : null}
      {status.status === "complete" && !basket && !error ? (
        <div className="loading-text">Loading results...</div>
      ) : null}
    </div>
  );
}
