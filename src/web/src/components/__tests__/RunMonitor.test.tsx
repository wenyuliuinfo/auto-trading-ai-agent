import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunMonitor } from "../RunMonitor";

describe("RunMonitor", () => {
  beforeEach(() => {
    cleanup();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("shows completed basket, rankings, and report", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const body = url.endsWith("/basket")
        ? [{ ticker: "NVDA", weight: 0.5, rank: 1, sub_exposure: "ai_chips", swap_reason: null, composite_score: 2.5, factor_contributions: {} }]
        : url.endsWith("/rankings")
          ? [{ ticker: "NVDA", composite_score: 2.5, rank: 1, factor_contributions: {}, caveats: [] }]
          : url.endsWith("/report")
            ? { run_id: "run1", report_md: "# Report\n\nresearch only", disclaimer: "x" }
            : { run_id: "run1", theme_id: "t1", status: "complete", requested_at: "now", retry_count: 0, error_detail: null, progress: { analyzed: 1, total: 1 } };
      return Promise.resolve({ ok: true, json: async () => body });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RunMonitor
        runId="run1"
        initialStatus={{
          run_id: "run1",
          theme_id: "t1",
          status: "running",
          requested_at: "now",
          retry_count: 0,
          error_detail: null,
          progress: { analyzed: 0, total: 1 },
        }}
      />,
    );

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("2.5000")).toBeInTheDocument();
    expect(screen.getByText("complete")).toBeInTheDocument();
  });

  it("shows empty basket state and still renders rankings and report", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const body = url.endsWith("/basket")
        ? []
        : url.endsWith("/rankings")
          ? [{ ticker: "NVDA", composite_score: 2.5, rank: 1, factor_contributions: {}, caveats: [] }]
          : url.endsWith("/report")
            ? { run_id: "run1", report_md: "# Report\n\nresearch only", disclaimer: "x" }
            : { run_id: "run1", theme_id: "t1", status: "complete", requested_at: "now", retry_count: 0, error_detail: null, progress: { analyzed: 1, total: 1 } };
      return Promise.resolve({ ok: true, json: async () => body });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RunMonitor
        runId="run1"
        initialStatus={{
          run_id: "run1",
          theme_id: "t1",
          status: "complete",
          requested_at: "now",
          retry_count: 0,
          error_detail: null,
          progress: { analyzed: 1, total: 1 },
        }}
      />,
    );

    expect(await screen.findByText("No basket was generated for this run.")).toBeInTheDocument();
    expect(screen.queryByText("Loading results...")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /rankings/i }));
    expect(await screen.findByText("NVDA")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /report/i }));
    expect(await screen.findByText(/research only/)).toBeInTheDocument();
  });
});
