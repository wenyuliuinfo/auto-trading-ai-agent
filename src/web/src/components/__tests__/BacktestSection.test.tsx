import { cleanup, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BacktestSection } from "../BacktestSection";

describe("BacktestSection", () => {
  beforeEach(() => {
    cleanup();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("shows the not-run state with a run button", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        run_id: "run1",
        mode: "trailing",
        status: "not_run",
        progress: { stage: "queued", completed: 0, total: 0 },
        summary: { strategy: {}, benchmarks: {} },
        series: {},
        rebalances: [],
        attribution: [],
        trades: [],
        current_holdings: [],
        flags: [],
        disclaimer: "Hypothetical backtest, not performance.",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BacktestSection runId="run1" />);

    expect(await screen.findByText("No backtest yet for this run.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run backtest/i })).toBeInTheDocument();
  });
});
