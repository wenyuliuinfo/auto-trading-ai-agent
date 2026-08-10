import { RankingRow } from "@/lib/api";

interface RankingsTableProps {
  rankings: RankingRow[];
}

export function RankingsTable({ rankings }: RankingsTableProps) {
  const top = rankings.slice(0, 20);
  return (
    <div className="panel table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Ticker</th>
            <th>Composite score</th>
            <th>Top contributions</th>
            <th>Caveats</th>
          </tr>
        </thead>
        <tbody>
          {top.map((row, index) => {
            const contributions = Object.entries(row.factor_contributions)
              .filter(([, value]) => value !== null && value !== undefined)
              .sort((a, b) => (b[1] as number) - (a[1] as number))
              .slice(0, 2)
              .map(([name, value]) => `${name}=${(value as number).toFixed(3)}`)
              .join(", ");
            return (
              <tr key={`${row.ticker}-${index}`}>
                <td className="mono">{row.rank ?? "—"}</td>
                <td className="ticker">{row.ticker}</td>
                <td>
                  <span className="score-pill">
                  {row.composite_score !== null && row.composite_score !== undefined
                    ? row.composite_score.toFixed(4)
                    : "—"}
                  </span>
                </td>
                <td className="mono muted">{contributions || "—"}</td>
                <td className="caveat-text">
                  {row.caveats.length > 0 ? row.caveats.join("; ") : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
