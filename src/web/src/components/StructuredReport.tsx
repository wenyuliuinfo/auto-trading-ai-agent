"use client";

import { useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Download } from "lucide-react";

import {
  ReportData,
  ReportHolding,
} from "@/lib/api";
import { KlineModal } from "./KlineModal";

function formatReturn(value: number | null): string {
  return value === null || value === undefined ? "n/a" : `${value * 100 >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function ReturnPill({ holding }: { holding: ReportHolding }) {
  const value = holding.return_6m;
  if (value === null || value === undefined) {
    return <span className="return-pill return-neutral">n/a</span>;
  }
  const positive = value >= 0;
  return (
    <span className={`return-pill ${positive ? "return-up" : "return-down"}`}>
      {positive ? <ArrowUp size={13} aria-hidden /> : <ArrowDown size={13} aria-hidden />}
      {formatReturn(value)}
      {holding.return_6m_source === "factor_panel" ? <sup>†</sup> : null}
    </span>
  );
}

function NewsCell({ holding }: { holding: ReportHolding }) {
  const news = holding.news;
  if (!news?.headline) {
    return <span className="muted">No recent news available.</span>;
  }
  const safeUrl =
    news.url?.startsWith("http://") || news.url?.startsWith("https://")
      ? news.url
      : null;
  const source = [news.source, news.published_at].filter(Boolean).join(" · ");
  return (
    <div className="news-cell">
      {safeUrl ? (
        <a href={safeUrl} target="_blank" rel="noopener noreferrer">
          {news.headline}
        </a>
      ) : (
        <span>{news.headline}</span>
      )}
      {source ? <span className="muted news-source">{source}</span> : null}
    </div>
  );
}

function KlineMini({
  holding,
  onOpen,
}: {
  holding: ReportHolding;
  onOpen: () => void;
}) {
  const kline = holding.kline;
  const miniUrl = kline.mini_url?.replace(/^\/api\/runs\//, "/runs/") ?? null;
  if (kline.status !== "ok" || !miniUrl) {
    return (
      <span className="muted" title={kline.error_code ?? undefined}>
        Chart unavailable
      </span>
    );
  }
  return (
    <div className="kline-mini">
      <button
        className="kline-open"
        onMouseEnter={onOpen}
        onFocus={onOpen}
        onClick={onOpen}
        aria-label={`Open ${holding.ticker} chart`}
      >
        <img
          src={miniUrl}
          alt={`${holding.ticker} 6-month candlestick chart`}
          width={160}
          height={48}
        />
      </button>
      {kline.flags.includes("stale") ? <span className="chip chip-warning">Stale</span> : null}
      {kline.flags.includes("suspect_adjustment") ? (
        <span className="chip chip-warning">Check price adjustment</span>
      ) : null}
      {kline.flags.includes("short_history") ? <span className="chip">Short history</span> : null}
    </div>
  );
}

function downloadMarkdown(markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "report.md";
  anchor.click();
  URL.revokeObjectURL(url);
}

export function StructuredReport({
  data,
  markdown,
  runId,
}: {
  data: ReportData;
  markdown: string;
  runId: string;
}) {
  const [activeTicker, setActiveTicker] = useState<string | null>(null);
  const { summary } = data;
  const weightedReturn =
    summary.weighted_return_6m !== null && summary.return_coverage >= 0.5
      ? formatReturn(summary.weighted_return_6m)
      : "n/a";
  const allocation = summary.allocation_by_sub_exposure;
  const allocationTotal = allocation.reduce((sum, row) => sum + row.weight, 0);

  return (
    <div className="structured-report">
      <h1 className="report-page-title">{data.theme_name}</h1>
      <div className="report-toolbar">
        <button className="btn" onClick={() => downloadMarkdown(markdown)}>
          <Download size={15} aria-hidden />
          Markdown
        </button>
        <button className="btn" onClick={() => window.print()}>
          <Download size={15} aria-hidden />
          PDF
        </button>
      </div>
      <div className="report-summary-grid">
        <div className="summary-card">
          <span className="summary-label">Holdings</span>
          <strong>{summary.holdings_count}</strong>
        </div>
        <div className="summary-card">
          <span className="summary-label">Trailing 6M (hypothetical)</span>
          <strong>{weightedReturn}</strong>
          <span className="muted small">coverage {(summary.return_coverage * 100).toFixed(0)}%</span>
        </div>
        <div className="summary-card">
          <span className="summary-label">Top-3 weight</span>
          <strong>{(summary.top3_weight * 100).toFixed(0)}%</strong>
        </div>
        <div className="summary-card">
          <span className="summary-label">Data as of</span>
          <strong>{summary.data_as_of.latest ?? "n/a"}</strong>
        </div>
      </div>

      {allocation.length > 0 ? (
        <div className="allocation-row">
          <span className="summary-label">Allocation</span>
          <div className="allocation-bar">
            {allocation.slice(0, 6).map((row) => (
              <span
                key={row.name}
                className="allocation-segment"
                style={{ width: `${allocationTotal ? (row.weight / allocationTotal) * 100 : 0}%` }}
                title={`${row.name} ${(row.weight * 100).toFixed(0)}%`}
              />
            ))}
          </div>
          <span className="muted small">
            {allocation.slice(0, 6).map((row) => `${row.name} ${(row.weight * 100).toFixed(0)}%`).join(" · ")}
          </span>
        </div>
      ) : null}

      <section className="report-thesis-panel">
        <h2 className="report-section-title">Theme thesis</h2>
        <p className="thesis-body">{data.thesis}</p>
        <p className="muted small">
          This theme is scored across thematic relevance, quality, valuation,
          momentum, sentiment, liquidity, and volatility before the basket is
          constructed under diversification and liquidity constraints.
        </p>
      </section>

      <h2 className="report-section-title">Portfolio Holdings</h2>
      <div className="holdings-table-wrap">
        <table className="holdings-table">
          <thead>
            <tr>
              <th>Stock</th>
              <th>6M Return</th>
              <th>Recent News</th>
              <th>6M K-Line</th>
              <th>Why Included</th>
            </tr>
          </thead>
          <tbody>
            {data.holdings.map((holding) => (
              <tr key={holding.ticker}>
                <td>
                  <div className="ticker">{holding.ticker}</div>
                  <div className="company-name">{holding.company_name}</div>
                  <div className="muted small">
                    {(holding.weight * 100).toFixed(1)}% weight · #{holding.rank ?? "—"}
                  </div>
                  {holding.caveats.length > 0 ? (
                    <span className="caveat-badge">
                      <AlertTriangle size={12} aria-hidden />
                      {holding.caveats.length}
                    </span>
                  ) : null}
                </td>
                <td><ReturnPill holding={holding} /></td>
                <td><NewsCell holding={holding} /></td>
                <td>
                  <KlineMini holding={holding} onOpen={() => setActiveTicker(holding.ticker)} />
                </td>
                <td className="why-cell">{holding.why_included}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="report-section-title">Considered But Excluded</h2>
      {data.excluded.length > 0 ? (
        <ul>
          {data.excluded.map((row) => (
            <li key={row.ticker}>
              <strong>{row.ticker}</strong>
              {row.company_name ? ` (${row.company_name})` : ""} — {row.reason}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No near-miss names were available for this run.</p>
      )}

      <h2 className="report-section-title">Basket-Level Risks</h2>
      <p>{data.risk_summary}</p>

      <div className="report-disclaimer">{data.disclaimer}</div>
      {activeTicker ? (
        <KlineModal
          key={activeTicker}
          holding={
            data.holdings.find((holding) => holding.ticker === activeTicker) ??
            data.holdings[0]
          }
          runId={runId}
          onClose={() => setActiveTicker(null)}
        />
      ) : null}
    </div>
  );
}
