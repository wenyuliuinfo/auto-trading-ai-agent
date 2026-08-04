---
name: report-agent-implementation
description: Use this skill whenever writing, modifying, reviewing, or debugging code in app/agents/report.py — context assembly for the Report agent, the not-investment-advice disclaimer wrapper, risk aggregation across holdings, or anything related to how report_md is generated and grounded. Covers the canonical implementation and the hard rules that keep the Report strictly fact-bound to upstream state. Do not use this skill for Trader agent basket construction (see TRADER_SKILL.md) or Modeling agent scoring (see MODELING_SKILL.md).
---

# Report Agent — Canonical Implementation & Rules

This skill is the single source of truth for **how** the Report agent
assembles context and generates `report_md`. `ARCHITECTURE.md` §4.1 and
§5.5 explain the contract; this file is what a coding agent should load
and follow *while writing the actual code*.

**Scope reminder (per `CONTEXT.md`):** the Report agent is a **faithful
synthesis of the pipeline's own outputs, not a research report from
scratch.** It is the last agent in the pipeline and the only one whose
entire job is prose — but "prose" does not mean "unconstrained." Every
claim must trace to something another agent already produced.

## Where this logic lives (per `CONVENTIONS.md` §2)

Context assembly reads from `data/` (no new external I/O beyond the LLM
call itself), so it stays directly in `agents/report.py`:

```
app/
├── agents/
│   └── report.py         # assemble_report_context, group_shared_risks,
│                          #   apply_disclaimer, the LLM call, report_node
├── data/
│   └── queries.py         # get_basket_with_scores() (TRADER_SKILL.md),
│                           #   get_analyst_reports(), save_report()
```

`report_node` reads assembled state; it never calls an `integrations/`
data-vendor client directly, and it is not the same code path as
`app/evaluation/groundedness.py`'s `check_report_groundedness` — that
checker runs *after* a Report already exists, as an advisory pass, not
as part of generating it (`CONVENTIONS.md` §2.1).

## Hard rules

1. **Zero new facts, enforced structurally, not just by prompt
   instruction.** Every number, catalyst, risk, and rationale in
   `report_md` must originate from `analyst_reports`, `rankings`
   (including `composite_score`/`factor_contributions`), `basket`, or
   `near_misses` — never from the model's general knowledge. The prompt
   says this (`ARCHITECTURE.md` §5.5), but the actual backstop is
   `app/evaluation/groundedness.py`'s `check_report_groundedness`
   (`ARCHITECTURE.md` §8.B) — treat that checker's existence as the
   reason this rule is enforceable at all, not just aspirational.
2. **The "not investment advice" disclaimer is appended by code, never
   left to the model to remember.** `apply_disclaimer(report_md)` wraps
   every generated report before it is persisted or returned — if the
   LLM's own output happens to include disclaimer-like language, that's
   incidental, not relied upon. This is a compliance requirement
   (`ARCHITECTURE.md` §9, `CONTEXT.md`), not a style preference.
3. **`composite_score` must be present in the assembled context per
   holding, not just `factor_contributions`.** Use
   `get_basket_with_scores()` (defined in `TRADER_SKILL.md`, shared with
   the API layer) rather than reimplementing the basket/rankings join
   here — one join function, two callers.
4. **Risk aggregation is pre-clustered by code before the LLM writes
   about it.** Don't trust the model alone to notice that 4 of 9
   holdings share a regulatory risk across separately-written
   `AnalystReport.risks` lists — `group_shared_risks()` does a
   deterministic pass first (see below) and hands the LLM pre-grouped
   clusters, so "risk shared across ≥2 holdings" is a code-verified fact
   the prose describes, not a pattern the model might or might not spot.
5. **One LLM call per report, not an iterative/agentic loop.** The Report
   agent is a single generation call over fully-assembled context — it
   does not call tools, does not re-query data mid-generation, and does
   not loop for self-critique. Keeping this a single bounded call keeps
   cost and latency predictable for the last step in the pipeline.
6. **Sentence-structure variety is a testable quality bar, not just a
   prompt request.** The prompt instructs varied per-holding phrasing
   (`ARCHITECTURE.md` §5.5); back this with a lightweight structural
   check in tests (see Test fixtures) rather than trusting the model
   unverified — repetitive "X is included because Y" templates across
   every holding is a real failure mode for this kind of generation task.
7. **Model/temperature are fixed and centralized**, matching the
   low-volume/high-stakes tier: `REPORT_MODEL = "deepseek-v4-pro"`
   (`ARCHITECTURE.md` §6), `REPORT_TEMPERATURE = 0.5` — higher than
   Analyst's 0.1 since prose variety is desirable here, but still
   constrained by Hard Rule 1's grounding requirement.

## Reference implementation

### Context assembly

```python
# agents/report.py

from collections import defaultdict
from app.data.queries import get_basket_with_scores, get_analyst_reports

def assemble_report_context(run_id: str, theme: str, near_misses: list[dict]) -> dict:
    """Single place that gathers everything report_node hands to the LLM.
    No field here should require the model to infer or recall anything
    not present in this dict (Hard Rule 1)."""
    basket = get_basket_with_scores(run_id)          # ticker, weight, rank, sub_exposure,
                                                        #   swap_reason, composite_score,
                                                        #   factor_contributions (Hard Rule 3)
    analyst_reports = {r["ticker"]: r for r in get_analyst_reports(run_id)}
    risk_clusters = group_shared_risks(analyst_reports, tickers=[b["ticker"] for b in basket])

    return {
        "theme": theme,
        "basket": [{**b, "analyst_report": analyst_reports.get(b["ticker"])} for b in basket],
        "near_misses": [{**n, "analyst_report": analyst_reports.get(n["ticker"])} for n in near_misses],
        "risk_clusters": risk_clusters,   # pre-aggregated, Hard Rule 4
    }


def group_shared_risks(analyst_reports: dict[str, dict], tickers: list[str]) -> list[dict]:
    """Deterministic pre-clustering of risks across basket holdings, so
    the LLM describes an already-verified pattern instead of having to
    notice one itself. A simple normalized-text match is enough here —
    this doesn't need to be sophisticated, just reliable."""
    risk_to_tickers: dict[str, list[str]] = defaultdict(list)
    for ticker in tickers:
        report = analyst_reports.get(ticker)
        if not report:
            continue
        for risk in report.get("risks", []):
            normalized = _normalize_risk_text(risk)
            risk_to_tickers[normalized].append(ticker)

    return [
        {"risk_theme": risk, "tickers": tickers_sharing_it}
        for risk, tickers_sharing_it in risk_to_tickers.items()
        if len(tickers_sharing_it) >= 2   # "shared" per ARCHITECTURE.md §5.5 point 4
    ]


def _normalize_risk_text(risk: str) -> str:
    """Lowercase + strip punctuation is intentionally crude — false
    negatives (missing a real overlap due to differing phrasing) are
    safer than false positives (claiming two unrelated risks are the
    same) for a compliance-adjacent document. Revisit only if this
    proves too conservative in practice."""
    return risk.lower().strip().rstrip(".")
```

### Disclaimer enforcement

```python
DISCLAIMER = (
    "\n\n---\n*This report is for research purposes only and does not "
    "constitute investment advice. It is not a recommendation to buy or "
    "sell any security.*"
)

def apply_disclaimer(report_md: str) -> str:
    """Called unconditionally on every generated report, before
    persistence or return (Hard Rule 2) — never assume the model
    included equivalent language on its own."""
    return report_md.rstrip() + DISCLAIMER
```

### `agents/report.py` — node function

```python
from app.data.queries import save_report

REPORT_MODEL = "deepseek-v4-pro"
REPORT_TEMPERATURE = 0.5

async def report_node(state: dict) -> dict:
    context = assemble_report_context(
        state["run_id"], state["theme"], state["near_misses"]
    )

    raw_report_md = await deepseek_client.complete(
        model=REPORT_MODEL,
        temperature=REPORT_TEMPERATURE,
        system=REPORT_SYSTEM_PROMPT,   # ARCHITECTURE.md §5.5, verbatim
        input_data=context,
    )

    report_md = apply_disclaimer(raw_report_md)   # Hard Rule 2 — always, not conditionally
    await save_report(state["run_id"], report_md)
    return {"report_md": report_md}
```

## Test fixtures to include (per `CONVENTIONS.md` §5)

- `group_shared_risks` with no overlapping risks across holdings —
  returns an empty list; verify `report_node`'s prompt handles an empty
  `risk_clusters` gracefully (e.g. states no common basket-level risk was
  identified, rather than fabricating one to fill the section).
- `group_shared_risks` with a risk shared by exactly 2 holdings — the
  minimum "shared" threshold from `ARCHITECTURE.md` §5.5; verify it's
  included, and a risk held by only 1 ticker is not.
- `apply_disclaimer` — verify it's appended even when the raw model
  output already contains disclaimer-like text (no dedup logic needed;
  redundancy here is safe, omission is not).
- Basket row with a Modeling `caveats` entry — verify
  `assemble_report_context` surfaces it into the LLM's input rather than
  it being silently dropped between `rankings` and the Report's context
  (`ARCHITECTURE.md` §5.5: "if the Modeling Agent flagged a caveat... surface it").
- Structural variety check: generate reports for 3+ different fixture
  baskets, assert no two consecutive per-holding paragraphs open with an
  identical sentence template (a cheap regex/first-N-words comparison is
  sufficient — this is a smoke test, not a rigorous linguistic check).
- `near_misses` list shorter than the usual 5 (e.g. only 2 available) —
  verify the "considered but excluded" section still generates
  sensibly rather than assuming a fixed count.
