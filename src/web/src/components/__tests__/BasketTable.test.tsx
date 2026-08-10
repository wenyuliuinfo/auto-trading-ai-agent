import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BasketHolding } from "@/lib/api";
import { BasketTable } from "../BasketTable";

const holdings: BasketHolding[] = [
  {
    ticker: "NVDA",
    weight: 0.125,
    rank: 1,
    sub_exposure: "ai_chips",
    swap_reason: null,
    composite_score: 1.2345,
    factor_contributions: { thematic_z: 0.8 },
  },
  {
    ticker: "GEV",
    weight: 0.1,
    rank: 2,
    sub_exposure: "grid",
    swap_reason: "AAA skipped at cap",
    composite_score: 0.9876,
    factor_contributions: { growth_z: 0.4 },
  },
];

describe("BasketTable", () => {
  afterEach(() => cleanup());

  it("renders composite_score directly for every holding", () => {
    render(<BasketTable holdings={holdings} />);
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("1.2345")).toBeInTheDocument();
    expect(screen.getByText("GEV")).toBeInTheDocument();
    expect(screen.getByText("0.9876")).toBeInTheDocument();
  });

  it("shows swap reason text when present", () => {
    render(<BasketTable holdings={holdings} />);
    expect(screen.getAllByText(/skipped at cap/).length).toBeGreaterThan(0);
  });

  it("renders duplicate tickers without duplicate-key warnings", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const duplicateHoldings = [
      ...holdings,
      { ...holdings[0], rank: 3, weight: 0.05, composite_score: 0.5 },
    ];

    render(<BasketTable holdings={duplicateHoldings} />);

    expect(screen.getAllByText("NVDA", { selector: "td.ticker" })).toHaveLength(2);
    expect(errorSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("same key"),
      expect.anything(),
      expect.anything(),
    );
    errorSpy.mockRestore();
  });
});
