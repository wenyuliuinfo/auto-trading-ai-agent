import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportView } from "../ReportView";

describe("ReportView", () => {
  it("renders headings, bullets, and the disclaimer", () => {
    const markdown = [
      "# Grid modernization - Rationale Report",
      "",
      "### 1. Theme Thesis",
      "A thesis paragraph.",
      "",
      "#### INCY - Incyte Corporation",
      "Why included: strong pipeline.",
      "",
      "## Basket",
      "- **NVDA** (12.5%) - composite_score 1.23",
      "- Latest news: **Earnings beat** ([Google News](https://example.com/nvda))",
      "",
      "---",
      "*This report is for research purposes only and does not constitute investment advice.*",
    ].join("\n");
    render(<ReportView markdown={markdown} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Grid modernization");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("1. Theme Thesis");
    expect(screen.getByRole("heading", { level: 4 })).toHaveTextContent("INCY - Incyte Corporation");
    expect(screen.getByText(/does not constitute investment advice/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Google News" })).toHaveAttribute(
      "href",
      "https://example.com/nvda",
    );
  });
});
