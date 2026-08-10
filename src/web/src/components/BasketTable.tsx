import { AlertTriangle } from "lucide-react";

import { BasketHolding } from "@/lib/api";

interface BasketTableProps {
  holdings: BasketHolding[];
}

export function BasketTable({ holdings }: BasketTableProps) {
  return (
    <div className="panel table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Ticker</th>
            <th>Weight</th>
            <th>Composite score</th>
            <th>Sub-exposure</th>
            <th>Swap reason</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((holding, index) => (
            <tr key={`${holding.ticker}-${index}`}>
              <td className="mono">{holding.rank ?? "—"}</td>
              <td className="ticker">{holding.ticker}</td>
              <td className="mono">{(holding.weight * 100).toFixed(2)}%</td>
              <td>
                <span className="score-pill">
                {holding.composite_score !== null && holding.composite_score !== undefined
                  ? holding.composite_score.toFixed(4)
                  : "—"}
                </span>
              </td>
              <td>{holding.sub_exposure ?? "—"}</td>
              <td>
                {holding.swap_reason ? (
                  <span className="swap-reason">
                    <AlertTriangle size={13} aria-hidden />
                    {holding.swap_reason}
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
