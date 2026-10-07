"use client";

import {
  BarChart3,
  CalendarDays,
  Download,
  LineChart as LineChartIcon,
  Play,
  RefreshCw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  BacktestEquityPoint,
  BacktestMode,
  BacktestPayload,
} from "@/lib/api";

interface BacktestSectionProps {
  runId: string;
}

const STAGES = [
  "fetching_data",
  "building_universe",
  "scoring",
  "simulating",
  "finalizing",
];

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toFixed(0)}`;
}

function shortDate(value: string): string {
  return value.slice(0, 10);
}

function lineColor(index: number): string {
  return index === 0 ? "#7c86e8" : "#9ca3af";
}

function transformPoints(
  points: BacktestEquityPoint[],
  view: "$" | "%" | "Excess",
  initial: number,
  benchmarkPoints: BacktestEquityPoint[] | undefined,
  log: boolean,
): BacktestEquityPoint[] {
  const benchmarkByDate = new Map(
    (benchmarkPoints ?? []).map((point) => [point.date, point.value]),
  );
  return points.map((point) => {
    let value = point.value;
    if (view === "%") {
      value = (point.value / initial - 1) * 100;
    } else if (view === "Excess") {
      const benchmark = benchmarkByDate.get(point.date);
      value = benchmark === undefined ? 0 : point.value - benchmark;
    }
    if (log && value > 0) value = Math.log(value);
    return { date: point.date, value };
  });
}

function LineChart({
  series,
  initialCash,
  rebalanceDates,
}: {
  series: Array<{ name: string; points: BacktestEquityPoint[] }>;
  initialCash: number;
  rebalanceDates: string[];
}) {
  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length === 0) {
    return <div className="empty-state">No series data.</div>;
  }

  const width = 960;
  const height = 340;
  const pad = { left: 58, right: 18, top: 24, bottom: 44 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const values = allPoints.map((point) => point.value).filter((value) => Number.isFinite(value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const dates = Array.from(new Set(allPoints.map((point) => point.date))).sort();
  const x = (date: string) =>
    pad.left + (dates.indexOf(date) / Math.max(1, dates.length - 1)) * chartW;
  const y = (value: number) =>
    pad.top + chartH - ((value - min) / span) * chartH;

  const paths = series
    .map((item, seriesIndex) => {
      const points = item.points
        .filter((point) => Number.isFinite(point.value))
        .sort((a, b) => a.date.localeCompare(b.date));
      const d = points
        .map((point, index) =>
          `${index === 0 ? "M" : "L"}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)}`,
        )
        .join(" ");
      return { name: item.name, d, color: lineColor(seriesIndex) };
    })
    .filter((item) => item.d);

  return (
    <div className="backtest-chart" role="img" aria-label="Backtest equity curve">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
        {[0, 1, 2, 3, 4].map((tick) => {
          const value = min + (span * tick) / 4;
          const tickY = y(value);
          return (
            <g key={tick}>
              <line
                x1={pad.left}
                y1={tickY}
                x2={width - pad.right}
                y2={tickY}
                stroke="rgba(148,163,184,0.16)"
              />
              <text
                x={pad.left - 8}
                y={tickY + 4}
                fill="#8a8f98"
                fontSize="11"
                fontFamily="monospace"
                textAnchor="end"
              >
                {value.toFixed(1)}
              </text>
            </g>
          );
        })}
        {paths.map((path) => (
          <path
            key={path.name}
            d={path.d}
            fill="none"
            stroke={path.color}
            strokeWidth="2"
            strokeLinejoin="round"
          />
        ))}
        {rebalanceDates.map((date, index) => {
          const cx = x(date);
          return (
            <g key={`${date}-${index}`}>
              <line
                x1={cx}
                y1={pad.top}
                x2={cx}
                y2={height - pad.bottom}
                stroke="rgba(148,163,184,0.24)"
                strokeDasharray="3 4"
              />
              <circle cx={cx} cy={height - pad.bottom} r="4" fill="#7c86e8" />
            </g>
          );
        })}
        <text
          x={pad.left}
          y={height - 8}
          fill="#8a8f98"
          fontSize="11"
          fontFamily="monospace"
        >
          ${initialCash.toLocaleString("en-US")} start
        </text>
      </svg>
      <div className="chart-legend">
        {series.map((item, index) => (
          <span key={item.name} className="legend-item">
            <span
              className="legend-dot"
              style={{ backgroundColor: lineColor(index) }}
            />
            {item.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function SummaryCards({
  data,
  benchmark,
}: {
  data: BacktestPayload;
  benchmark: string;
}) {
  const strategy = data.summary?.strategy;
  const bench = data.summary?.benchmarks?.[benchmark];
  const cards = [
    { label: "Final value", value: formatMoney(strategy?.final_value), sub: `${benchmark} ${formatMoney(bench?.final_value)}` },
    { label: "Total return", value: formatPct(strategy?.total_return), sub: `${benchmark} ${formatPct(bench?.total_return)}` },
    { label: "Max drawdown", value: formatPct(strategy?.max_drawdown), sub: `${benchmark} ${formatPct(bench?.max_drawdown)}` },
    { label: "Sharpe", value: strategy?.sharpe == null ? "n/a" : strategy.sharpe.toFixed(2), sub: benchmark },
    {
      label: "Alpha / Beta",
      value:
        strategy?.alpha == null || strategy?.beta == null
          ? "n/a"
          : `${strategy.alpha.toFixed(2)} / ${strategy.beta.toFixed(2)}`,
      sub: "vs primary benchmark",
    },
    { label: "Quarterly win rate", value: strategy?.hit_rate == null ? "n/a" : `${Math.round(strategy.hit_rate * 100)}%`, sub: "periods beating benchmark" },
    { label: "Turnover", value: strategy?.turnover == null ? "n/a" : strategy.turnover.toFixed(2), sub: "annualized" },
    { label: "Costs paid", value: formatMoney(strategy?.costs_paid), sub: "10 bps per side" },
  ];
  return (
    <div className="backtest-cards">
      {cards.map((card) => (
        <div className="summary-card" key={card.label}>
          <div className="summary-label">{card.label}</div>
          <div className="backtest-card-value">{card.value}</div>
          <div className="backtest-card-sub">{card.sub}</div>
        </div>
      ))}
    </div>
  );
}

function FlagChips({ flags }: { flags: string[] }) {
  if (!flags?.length) return null;
  return (
    <div className="chip-row backtest-flags">
      {flags.map((flag) => (
        <span className="chip chip-warning" key={flag} title={flag.replaceAll("_", " ")}>
          {flag.replaceAll("_", " ")}
        </span>
      ))}
    </div>
  );
}

function RebalanceTimeline({ data }: { data: BacktestPayload }) {
  return (
    <section className="backtest-section">
      <div className="backtest-section-heading">
        <CalendarDays size={16} aria-hidden />
        Rebalance timeline
      </div>
      <div className="rebalance-list">
        {data.rebalances.map((item) => (
          <div className="rebalance-card" key={item.idx}>
            <div className="rebalance-head">
              <span className="mono">Rebalance {item.idx + 1}</span>
              <span className="muted small">
                Signal {shortDate(item.signal_date)} · Executed {shortDate(item.exec_date)} · Held to {shortDate(item.hold_end_date)}
              </span>
            </div>
            <div className="weights-row">
              {item.basket.map((holding) => (
                <div className="weight-segment" key={holding.ticker}>
                  <span className="weight-segment-fill" style={{ flexGrow: Math.max(0.05, holding.weight) }} />
                  <span className="weight-segment-label">
                    {holding.ticker} {((holding.weight ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
              {item.basket.length === 0 ? (
                <span className="muted small">Held cash</span>
              ) : null}
            </div>
            <div className="rebalance-footer">
              <span className={`return-pill ${(item.period_return ?? 0) >= 0 ? "return-up" : "return-down"}`}>
                {formatPct(item.period_return)}
              </span>
              {item.flags.length > 0 ? (
                <span className="muted small">{item.flags.map((flag) => flag.replaceAll("_", " ")).join(", ")}</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CurrentHoldings({ data }: { data: BacktestPayload }) {
  return (
    <section className="backtest-section">
      <div className="backtest-section-heading">
        <BarChart3 size={16} aria-hidden />
        Current holdings
      </div>
      <div className="table-wrap panel">
        <table className="table">
          <thead>
            <tr>
              <th>Stock</th>
              <th>6M return</th>
              <th>Price</th>
              <th>P/E</th>
              <th>Market cap</th>
              <th>Chart</th>
            </tr>
          </thead>
          <tbody>
            {data.current_holdings.map((holding) => (
              <tr key={holding.ticker}>
                <td>
                  <div className="ticker">{holding.ticker}</div>
                  <div className="company-name">{holding.company_name ?? "—"}</div>
                </td>
                <td>
                  <span className={`return-pill ${(holding.return_6m ?? 0) >= 0 ? "return-up" : "return-down"}`}>
                    {formatPct(holding.return_6m)}
                  </span>
                </td>
                <td className="mono">{formatMoney(holding.price)}</td>
                <td className="mono">
                  {holding.pe_ratio != null && holding.pe_ratio > 0
                    ? holding.pe_ratio.toFixed(1)
                    : "n/m"}
                </td>
                <td className="mono">{formatCompact(holding.market_cap)}</td>
                <td>
                  {holding.kline?.mini_url ? (
                    <a href={holding.kline.mini_url} target="_blank" rel="noopener noreferrer">
                      Mini chart
                    </a>
                  ) : (
                    "Chart unavailable"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="backtest-caption">
        Current basket from this run&apos;s pipeline. The backtest uses a deterministic version of the strategy.
      </div>
    </section>
  );
}

function ContributionBars({ data }: { data: BacktestPayload }) {
  const rows = [...(data.attribution ?? [])].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 15);
  const max = Math.max(...rows.map((row) => Math.abs(row.pnl)), 1);
  const costsTotal = data.costs_total ?? 0;
  return (
    <section className="backtest-section">
      <div className="backtest-section-heading">Contribution by stock</div>
      <div className="contribution-list">
        {rows.map((row) => (
          <div className="contribution-row" key={row.ticker}>
            <span className="contribution-ticker">{row.ticker}</span>
            <div className="contribution-track">
              <div
                className={row.pnl >= 0 ? "contribution-bar positive" : "contribution-bar negative"}
                style={{ width: `${(Math.abs(row.pnl) / max) * 100}%` }}
              />
            </div>
            <span className="mono">{formatMoney(row.pnl)}</span>
          </div>
        ))}
        <div className="contribution-row contribution-cost">
          <span className="contribution-ticker">Costs</span>
          <div className="contribution-track">
            <div className="contribution-bar negative" style={{ width: `${(Math.abs(costsTotal) / max) * 100}%` }} />
          </div>
          <span className="mono">-{formatMoney(Math.abs(costsTotal))}</span>
        </div>
      </div>
    </section>
  );
}

function TradeBlotter({ data }: { data: BacktestPayload }) {
  const [visible, setVisible] = useState(25);
  const trades = data.trades ?? [];
  return (
    <section className="backtest-section">
      <div className="backtest-section-heading">Trade blotter</div>
      <div className="table-wrap panel">
        <table className="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Ticker</th>
              <th>Side</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Value</th>
              <th>Cost</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, visible).map((trade) => (
              <tr key={trade.seq}>
                <td className="mono">{shortDate(trade.date)}</td>
                <td className="ticker">{trade.ticker}</td>
                <td className={trade.side === "BUY" ? "return-up" : "return-down"}>{trade.side}</td>
                <td className="mono">{trade.shares.toFixed(4)}</td>
                <td className="mono">{formatMoney(trade.price)}</td>
                <td className="mono">{formatMoney(trade.value)}</td>
                <td className="mono">{formatMoney(trade.cost)}</td>
                <td>{trade.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {trades.length > visible ? (
        <button className="btn backtest-more" onClick={() => setVisible((current) => current + 100)}>
          Show more
        </button>
      ) : null}
    </section>
  );
}

function ProgressState({ data }: { data: BacktestPayload }) {
  const currentIndex = STAGES.indexOf(data.progress?.stage ?? "fetching_data");
  const completed = data.progress?.completed ?? 0;
  const total = data.progress?.total ?? 0;
  return (
    <div className="backtest-progress">
      <div className="backtest-stepper">
        {STAGES.map((stage, index) => (
          <div key={stage} className={`stepper-step${index <= currentIndex ? " active" : ""}`}>
            <span className="stepper-dot" />
            <span>{stage.replaceAll("_", " ")}</span>
          </div>
        ))}
      </div>
      <div className="progress-wrap">
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
          />
        </div>
        <span className="progress-label">
          {completed} / {total}
        </span>
      </div>
      <div className="loading-text">You can leave this page; results will be here later.</div>
    </div>
  );
}

export function BacktestSection({ runId }: BacktestSectionProps) {
  const [mode, setMode] = useState<BacktestMode>("trailing");
  const [data, setData] = useState<BacktestPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [benchmark, setBenchmark] = useState("QQQ");
  const [view, setView] = useState<"$" | "%" | "Excess">("$");
  const [log, setLog] = useState(false);
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load() {
      try {
        const result = await api.getBacktest(runId, mode);
        if (cancelled) return;
        setData(result);
        setError(null);
        if (result.status === "queued" || result.status === "running") {
          timer = setTimeout(load, 3000);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Backtest load failed");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId, mode, refreshToken]);

  const benchmarkNames = useMemo(() => {
    if (!data?.series) return ["QQQ"];
    return Object.keys(data.series).filter((name) => name !== "strategy");
  }, [data]);

  async function runBacktest() {
    setStarting(true);
    setError(null);
    try {
      await api.startBacktest(runId, mode);
      setRefreshToken((current) => current + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest failed to start");
    } finally {
      setStarting(false);
    }
  }

  if (!data) {
    return (
      <div className="panel empty-state">
        <LineChartIcon size={22} className="empty-icon" aria-hidden />
        <span>{error ?? "Loading backtest..."}</span>
      </div>
    );
  }

  const status = data.status;
  const initialCash = data.initial_cash ?? 10000;
  const selectedBenchmark = benchmarkNames.includes(benchmark)
    ? benchmark
    : benchmarkNames[0] ?? "QQQ";
  const strategyPoints = data.series?.strategy ?? [];
  const benchmarkPoints = data.series?.[selectedBenchmark] ?? [];
  const strategyView = transformPoints(strategyPoints, view, initialCash, benchmarkPoints, log);
  const benchmarkView = transformPoints(benchmarkPoints, view, initialCash, benchmarkPoints, log);
  const chartSeries = [
    { name: "Strategy", points: strategyView },
    { name: selectedBenchmark, points: benchmarkView },
  ];
  const rebalanceDates = data.rebalances?.map((item) => item.exec_date) ?? [];
  const hasResults = status === "succeeded" || status === "partial";

  return (
    <div className="backtest-shell">
      <div className="backtest-toolbar">
        <div className="segmented backtest-mode-switch">
          {(["trailing", "full"] as BacktestMode[]).map((item) => (
            <button
              key={item}
              className={`segmented-btn${mode === item ? " segmented-btn-active" : ""}`}
              onClick={() => setMode(item)}
              aria-pressed={mode === item}
            >
              {item === "trailing" ? "Trailing" : "Full"}
            </button>
          ))}
        </div>
        <div className="backtest-toolbar-spacer" />
        {hasResults ? (
          <>
            <select
              className="field backtest-select"
              value={selectedBenchmark}
              onChange={(event) => setBenchmark(event.target.value)}
              aria-label="Benchmark"
            >
              {benchmarkNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <select
              className="field backtest-select"
              value={view}
              onChange={(event) => setView(event.target.value as "$" | "%" | "Excess")}
              aria-label="Chart view"
            >
              <option value="$">$</option>
              <option value="%">%</option>
              <option value="Excess">Excess</option>
            </select>
            {view === "$" ? (
              <label className="check-label backtest-check">
                <input
                  type="checkbox"
                  className="checkbox"
                  checked={log}
                  onChange={(event) => setLog(event.target.checked)}
                />
                Log
              </label>
            ) : null}
          </>
        ) : null}
      </div>

      <FlagChips flags={data.flags} />

      {status === "disabled" ? (
        <div className="panel empty-state">
          <span>Backtest is turned off for this environment.</span>
        </div>
      ) : null}

      {status === "not_run" ? (
        <div className="panel empty-state">
          <span>No backtest yet for this run.</span>
          <button className="btn btn-primary" onClick={() => void runBacktest()} disabled={starting}>
            <Play size={15} aria-hidden />
            {starting ? "Starting..." : "Run backtest"}
          </button>
        </div>
      ) : null}

      {status === "queued" || status === "running" ? (
        <div className="panel panel-pad">
          <div className="status-line">
            <span className={`badge badge-${status === "queued" ? "queued" : "running"}`}>{status}</span>
          </div>
          <ProgressState data={data} />
        </div>
      ) : null}

      {status === "failed" ? (
        <div className="panel panel-pad backtest-error">
          <div className="form-error">
            {data.error_code ?? "Backtest failed"}: {data.error_message ?? "Unknown error"}
          </div>
          <button className="btn" onClick={() => void runBacktest()}>
            <RefreshCw size={15} aria-hidden />
            Retry
          </button>
        </div>
      ) : null}

      {status === "partial" ? (
        <div className="backtest-partial-banner">
          Some rebalances failed or were empty. Review the timeline and flags below.
        </div>
      ) : null}

      {hasResults ? (
        <>
          <SummaryCards data={data} benchmark={selectedBenchmark} />
          <section className="backtest-section">
            <div className="backtest-section-heading">Equity curve</div>
            <LineChart series={chartSeries} initialCash={initialCash} rebalanceDates={rebalanceDates} />
          </section>
          <RebalanceTimeline data={data} />
          <CurrentHoldings data={data} />
          <ContributionBars data={data} />
          <TradeBlotter data={data} />
        </>
      ) : null}

      {methodologyOpen ? (
        <div className="methodology-panel">
          <div className="methodology-header">
            <span>Backtest methodology</span>
            <button className="icon-button" onClick={() => setMethodologyOpen(false)} aria-label="Close methodology">
              ×
            </button>
          </div>
          <p>
            Quarterly rebalances on the first trading day of January, April, July, and October.
            Signals use only data on or before the previous trading day. Thematic relevance is
            replaced by ETF breadth; sentiment is replaced by a 126-day money-flow ratio.
          </p>
          <p>{data.disclaimer}</p>
          <div className="backtest-export-row">
            <a className="btn" href={`/runs/${runId}/backtest/export?format=csv&part=equity&mode=${mode}`}>
              <Download size={14} aria-hidden />
              Equity CSV
            </a>
            <a className="btn" href={`/runs/${runId}/backtest/export?format=csv&part=trades&mode=${mode}`}>
              <Download size={14} aria-hidden />
              Trades CSV
            </a>
            <a className="btn" href={`/runs/${runId}/backtest/export?format=json&mode=${mode}`}>
              JSON
            </a>
          </div>
        </div>
      ) : null}

      <div className="backtest-disclaimer">{data.disclaimer}</div>
    </div>
  );
}
