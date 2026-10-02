"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { api, KlineBar, ReportHolding } from "@/lib/api";

interface KlineModalProps {
  holding: ReportHolding;
  runId: string;
  onClose: () => void;
}

function renderFullSvg(bars: KlineBar[]): string {
  if (bars.length === 0) return "";
  const width = 760;
  const height = 320;
  const pad = { left: 62, right: 18, top: 26, bottom: 64 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const volumeH = 54;
  const candleH = chartH - volumeH - 18;
  const lows = bars.map((bar) => bar.low);
  const highs = bars.map((bar) => bar.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const span = max - min || 1;
  const maxVolume = Math.max(...bars.map((bar) => bar.volume || 0), 1);
  const step = chartW / bars.length;
  const candleW = Math.max(1, step * 0.62);

  const y = (value: number) =>
    pad.top + candleH - ((value - min) / span) * candleH;
  const volumeY = (volume: number) =>
    pad.top + candleH + 22 + volumeH - (volume / maxVolume) * volumeH;

  const parts: string[] = [];

  Array.from({ length: 5 }, (_, index) => {
    const value = min + ((max - min) * index) / 4;
    const tickY = y(value);
    parts.push(
      `<line x1="${pad.left}" y1="${tickY}" x2="${width - pad.right}" y2="${tickY}" stroke="rgba(148,163,184,0.18)" stroke-width="1"/>`,
      `<text x="${pad.left - 8}" y="${tickY + 3}" fill="#9ca3af" font-size="10" font-family="monospace" text-anchor="end">${value.toFixed(1)}</text>`,
    );
  });

  const xTickCount = 5;
  for (let index = 0; index < xTickCount; index += 1) {
    const dataIndex = Math.round((bars.length - 1) * (index / (xTickCount - 1)));
    const bar = bars[dataIndex];
    const x = pad.left + dataIndex * step + step / 2;
    parts.push(
      `<line x1="${x}" y1="${pad.top}" x2="${x}" y2="${pad.top + candleH}" stroke="rgba(148,163,184,0.12)" stroke-width="1"/>`,
      `<text x="${x}" y="${height - pad.bottom + 22}" fill="#9ca3af" font-size="10" font-family="monospace" text-anchor="middle">${bar.date.slice(5)}</text>`,
    );
  }

  bars.forEach((bar, index) => {
    const x = pad.left + index * step + step / 2;
    const up = bar.close >= bar.open;
    const color = up ? "#22c55e" : "#ef4444";
    const cx = x;
    parts.push(
      `<line x1="${cx}" y1="${y(bar.high)}" x2="${cx}" y2="${y(bar.low)}" stroke="${color}" stroke-width="1"/>`,
    );
    const top = Math.min(y(bar.open), y(bar.close));
    const bodyH = Math.max(1, Math.abs(y(bar.open) - y(bar.close)));
    parts.push(
      `<rect x="${cx - candleW / 2}" y="${top}" width="${candleW}" height="${bodyH}" fill="${color}"/>`,
    );
    parts.push(
      `<rect x="${cx - candleW / 2}" y="${volumeY(bar.volume)}" width="${candleW}" height="${volumeH - (volumeY(bar.volume) - (pad.top + candleH + 22))}" fill="rgba(94,106,210,0.55)"/>`,
    );
  });

  const last = bars[bars.length - 1];
  const first = bars[0];
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="760" height="320" viewBox="0 0 ${width} ${height}" role="img">` +
    `<title>${last.date} open ${last.open}, high ${last.high}, low ${last.low}, close ${last.close}</title>` +
    `<text x="${pad.left}" y="${pad.top - 8}" fill="#9ca3af" font-size="11" font-family="monospace">${first.date} → ${last.date}</text>` +
    `<text x="${width - pad.right}" y="${height - pad.bottom + 40}" fill="#9ca3af" font-size="10" font-family="monospace" text-anchor="end">Volume</text>` +
    parts.join("") +
    "</svg>"
  );
}

export function KlineModal({ holding, runId, onClose }: KlineModalProps) {
  const [bars, setBars] = useState<KlineBar[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getKline(runId, holding.ticker)
      .then((result) => {
        if (!cancelled) setBars(result.bars);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load chart");
      });
    return () => {
      cancelled = true;
    };
  }, [runId, holding.ticker]);

  useEffect(() => {
    dialogRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="kline-modal-title"
        tabIndex={-1}
      >
        <div className="modal-header">
          <div>
            <div className="ticker">{holding.ticker}</div>
            <div className="company-name">{holding.company_name}</div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close chart">
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className="modal-body">
          {error ? (
            <div className="form-error" role="alert">{error}</div>
          ) : bars === null ? (
            <div className="loading-text">Loading chart...</div>
          ) : bars.length === 0 ? (
            <div className="muted">Chart unavailable</div>
          ) : (
            <div
              className="kline-full-svg"
              dangerouslySetInnerHTML={{ __html: renderFullSvg(bars) }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
