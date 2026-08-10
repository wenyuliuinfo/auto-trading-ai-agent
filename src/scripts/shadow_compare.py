"""Shadow-mode factor-weight comparison (ARCHITECTURE.md §8.C).

Usage:
    python scripts/shadow_compare.py --run-id <run_id> --weights <new_weights.yaml>

Reruns only Modeling's pure functions against already-persisted data;
never calls an LLM or a vendor API.
"""

from __future__ import annotations

import argparse
from typing import Any

import yaml

from app.agents.modeling import (
    _build_scoring_frame,
    _panel_from_rows,
    combine_scores,
    compute_factor_scores,
    rank,
)
from app.data.queries import get_analyst_reports, get_factor_panel_rows, get_rankings


def shadow_compare(run_id: str, new_weights: dict[str, float]) -> dict[str, Any]:
    """Diff persisted rankings vs a proposed weight set (no I/O beyond reads)."""
    reports = get_analyst_reports(run_id)
    panel_rows = get_factor_panel_rows(run_id)
    panel = _panel_from_rows(panel_rows)
    scoring = _build_scoring_frame(panel, reports)
    factor_cols = [key.removesuffix("_z") for key in new_weights]
    scored = compute_factor_scores(scoring, factor_cols)
    scored["composite_score"] = combine_scores(scored, new_weights)
    new_ranked = rank(scored)
    new_by_ticker = {
        str(row["ticker"]): int(row["rank"]) for _, row in new_ranked.iterrows()
    }
    old_rankings = {r["ticker"]: r for r in get_rankings(run_id)}
    rank_deltas = {
        ticker: old_rankings[ticker]["rank"] - new_rank
        for ticker, new_rank in new_by_ticker.items()
        if ticker in old_rankings
    }
    entered = [t for t in new_by_ticker if t not in old_rankings]
    left = [t for t in old_rankings if t not in new_by_ticker]
    return {
        "run_id": run_id,
        "rank_deltas": rank_deltas,
        "entered": entered,
        "left": left,
        "top_10_new": [
            str(row["ticker"])
            for _, row in new_ranked.head(10).iterrows()
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--weights", required=True, help="path to proposed weights YAML")
    args = parser.parse_args()
    with open(args.weights, encoding="utf-8") as handle:
        weights = yaml.safe_load(handle)
    result = shadow_compare(args.run_id, weights)
    print(yaml.safe_dump(result, sort_keys=False))


if __name__ == "__main__":
    main()
