---
name: trader-agent-implementation
description: Use this skill whenever writing, modifying, reviewing, or debugging code in app/agents/trader.py — hard screens, diversification caps, position sizing, or swap_reason generation. Covers the canonical construct_basket implementation and the rule that basket selection/sizing is deterministic code, never an LLM decision. Do not use this skill for Modeling agent ranking (see MODELING_SKILL.md) or Report agent synthesis (see REPORT_SKILL.md).
---

# Trader Agent — Canonical Implementation & Rules

This skill is the single source of truth for **how** the Trader agent
turns a `RankedList` into the final 8-10 name Basket. `ARCHITECTURE.md`
§4.1 and §5.4 explain the contract and the responsibility boundary; this
file is what a coding agent should load and follow *while writing the
actual code*.

**Scope reminder (per `CONTEXT.md`):** the Trader is **not re-analyzing
company merits** — the Modeling agent's rank is its primary input. Its
job is applying hard eligibility screens, diversification, and sizing
rules to that ranked list, and explaining (not deciding) any swap forced
by diversification.

## Where this logic lives (per `CONVENTIONS.md` §2)

`construct_basket` does no external I/O — it operates purely on the
`ranked_list` already in state — so it stays directly in
`agents/trader.py`, the same pattern as Modeling's Steps B/C/D:

```
app/
├── agents/
│   └── trader.py         # construct_basket (deterministic) + the narrow
│                          #   LLM call for swap_reason prose + trader_node
├── data/
│   └── queries.py         # save_basket() persists the result — trader.py
│                           #   calls this, never opens a DB session itself
```

`trader_node` reads `ranked_list` and `theme_config` from state; it never
calls an `integrations/` client directly.

## Hard rules

1. **Selection and sizing are deterministic code — never an LLM
   decision.** The only LLM-touched output field is `swap_reason` prose,
   generated from structured swap data the code already computed. If a
   change would let the LLM choose which tickers make the basket or how
   they're weighted, that violates `ARCHITECTURE.md` §4.1/§7's
   determinism boundary — the same boundary enforced for Modeling's
   ranking math.
2. **Hard screens are applied before ranking position is considered, not
   after.** A candidate failing `min_market_cap`, `min_avg_dollar_volume`,
   or carrying a Modeling `caveats` flag marked `"exclude"` is ineligible
   regardless of rank — screen first, then walk the ranked list, not the
   reverse.
3. **Diversification cap (`max_per_sub_industry`, default 3) is enforced
   by walking the ranked list top-down and skipping any candidate whose
   sub-exposure is already at cap** — never by a post-hoc filter that
   could silently drop a name without a recorded reason. Every skip must
   produce a structured record (ticker, rank, sub-exposure, cap) that
   `swap_reason` generation reads from — an unrecorded skip is a bug.
4. **Position sizing follows `theme_config["weighting_scheme"]`
   exactly** — `equal_weight` (default) or `score_weighted`. For
   `score_weighted`, floor/cap clipping (5%/20%) must be followed by a
   **renormalization pass** so weights still sum to 1.0 — clipping
   without renormalizing is a common bug that silently produces a basket
   that doesn't actually sum to 100%.
5. **`composite_score` is never duplicated into the `baskets` table.**
   It already lives in the `rankings` table, keyed by `(run_id, ticker)`
   (`ARCHITECTURE.md` §2.1) — `save_basket()` persists only `ticker`,
   `weight`, `rank`, `sub_exposure`, `swap_reason`. The
   `/runs/{run_id}/basket` API response's required `composite_score`
   field (`ARCHITECTURE.md` §3) is produced by **joining** `baskets` with
   `rankings` at read time via a shared query function (see "Composite
   score resolution" below) — not by adding a redundant column that could
   drift out of sync with the value Modeling actually computed.
6. **The basket target is 8-10 positions; fewer than 8 is not this
   function's problem to solve.** `construct_basket` returns whatever it
   could legitimately build under the screens/diversification rules —
   the bounded retry loop back to the Screener (`ARCHITECTURE.md` §4.2's
   `check_basket_complete`) is what handles a too-small result. Do not
   add retry or pool-widening logic inside `trader.py` itself.
7. **`near_misses` (the next ~5 eligible names after the cutoff) is
   always returned alongside the basket**, even when the basket came in
   under 8 — the Report agent's "considered but excluded" section
   (`REPORT_SKILL.md`) depends on this being present regardless of
   whether the retry loop later fires.

## Composite score resolution (closes the schema gap)

`baskets` has no `composite_score` column by design (Hard Rule 5).
Both the API layer and the Report agent need basket rows *with* their
score attached, so this join is a single shared function, not
reimplemented twice:

```python
# data/queries.py

def get_basket_with_scores(run_id: str) -> list[dict]:
    """Joins baskets with rankings on (run_id, ticker) to attach
    composite_score and factor_contributions. Single source of truth for
    both the /runs/{run_id}/basket API response (api-engineer) and the
    Report agent's context assembly (REPORT_SKILL.md) — do not
    reimplement this join in either place."""
    basket_rows = get_basket_rows(run_id)          # ticker, weight, rank, sub_exposure, swap_reason
    ranking_rows = {r["ticker"]: r for r in get_rankings(run_id)}  # keyed by ticker
    return [
        {**b, "composite_score": ranking_rows[b["ticker"]]["composite_score"],
              "factor_contributions": ranking_rows[b["ticker"]]["factor_contributions"]}
        for b in basket_rows
    ]
```

## Reference implementation

```python
# agents/trader.py

from collections import defaultdict

TARGET_BASKET_SIZE = 10
MIN_BASKET_SIZE = 8
NEAR_MISS_COUNT = 5

def construct_basket(
    ranked_list: list[dict], theme_config: dict
) -> tuple[list[dict], list[dict], list[dict]]:
    """Deterministic basket construction (Hard Rule 1). Returns
    (basket, near_misses, swap_events) — swap_events is structured data
    for the LLM to turn into swap_reason prose, not prose itself."""
    screens = theme_config["screens"]
    min_cap = screens.get("min_market_cap", 300_000_000)
    min_adv = screens.get("min_avg_dollar_volume", 5_000_000)
    max_per_sub = screens.get("max_per_sub_industry", 3)

    # Hard Rule 2 — screen before considering rank position at all
    eligible = [
        c for c in ranked_list
        if c.get("market_cap", 0) >= min_cap
        and c.get("avg_dollar_volume", 0) >= min_adv
        and "exclude" not in (c.get("caveats") or [])
    ]

    basket: list[dict] = []
    sub_exposure_counts: dict[str, int] = defaultdict(int)
    swap_events: list[dict] = []
    most_recent_skip: dict | None = None

    for candidate in eligible:
        if len(basket) >= TARGET_BASKET_SIZE:
            break
        sub_exp = candidate["sub_exposure"]
        if sub_exposure_counts[sub_exp] >= max_per_sub:
            # Hard Rule 3 — every skip is a structured record, not a silent drop
            most_recent_skip = {
                "skipped_ticker": candidate["ticker"],
                "skipped_rank": candidate["rank"],
                "sub_exposure": sub_exp,
                "cap": max_per_sub,
            }
            continue
        basket.append(candidate)
        sub_exposure_counts[sub_exp] += 1
        if most_recent_skip is not None:
            # this candidate was included ahead of a skipped, better-ranked one
            swap_events.append({**most_recent_skip, "included_ticker": candidate["ticker"],
                                 "included_rank": candidate["rank"]})
            most_recent_skip = None

    _apply_position_sizing(basket, theme_config.get("weighting_scheme", "equal_weight"))

    near_misses = eligible[len(basket):len(basket) + NEAR_MISS_COUNT]
    return basket, near_misses, swap_events


def _apply_position_sizing(basket: list[dict], weighting_scheme: str) -> None:
    if not basket:
        return
    if weighting_scheme == "equal_weight":
        w = 1.0 / len(basket)
        for c in basket:
            c["weight"] = w
        return

    # score_weighted — Hard Rule 4: floor/cap THEN renormalize
    total_score = sum(c["composite_score"] for c in basket)
    raw_weights = {c["ticker"]: c["composite_score"] / total_score for c in basket}
    clipped = {t: min(max(w, 0.05), 0.20) for t, w in raw_weights.items()}
    clipped_total = sum(clipped.values())
    for c in basket:
        c["weight"] = clipped[c["ticker"]] / clipped_total  # renormalized to sum to 1.0
```

## `agents/trader.py` — node function

```python
from app.data.queries import save_basket

TRADER_MODEL = "deepseek-v4-pro"   # low-volume, high-stakes tier — ARCHITECTURE.md §6
TRADER_TEMPERATURE = 0.2            # only used for swap_reason prose generation

async def trader_node(state: dict) -> dict:
    basket, near_misses, swap_events = construct_basket(
        state["ranked_list"], state["theme_config"]
    )

    if swap_events:
        # Single narrow LLM call: turns structured swap_events into prose,
        # one sentence per event — never decides the swap itself (Hard Rule 1)
        swap_reasons = await deepseek_client.complete(
            model=TRADER_MODEL,
            temperature=TRADER_TEMPERATURE,
            system=TRADER_SWAP_REASON_PROMPT,
            input_data={"swap_events": swap_events},
        )
        for ticker, reason in swap_reasons.items():
            next(c for c in basket if c["ticker"] == ticker)["swap_reason"] = reason

    await save_basket(state["run_id"], basket)   # ticker/weight/rank/sub_exposure/swap_reason only
    return {"basket": basket, "near_misses": near_misses}
```

## Test fixtures to include (per `CONVENTIONS.md` §5)

- All candidates fail hard screens — `construct_basket` returns an empty
  basket, not an error; the retry loop (Hard Rule 6) is what handles this
  upstream.
- A ranked list where one sub-exposure dominates the top 10 ranks —
  verify the diversification cap actually skips excess candidates from
  that sub-exposure and fills from further down the list, and that each
  skip produces a `swap_events` entry.
- `score_weighted` sizing where multiple candidates clip at the 20% cap —
  verify the renormalization pass (Hard Rule 4) still sums weights to
  1.0, not just individually-clipped values that no longer sum to 100%.
- Fewer than 8 eligible candidates after screening — verify
  `construct_basket` returns the partial basket and correct `near_misses`
  without raising, and does not attempt its own retry.
- `get_basket_with_scores` — verify the join correctly attaches
  `composite_score`/`factor_contributions` from `rankings` and doesn't
  silently drop a basket row if a matching ranking row is somehow
  missing (should raise loudly, not join to `None`).
