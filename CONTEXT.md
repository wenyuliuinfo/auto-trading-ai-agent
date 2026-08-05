# CONTEXT.md
## Ubiquitous Language / Domain Glossary

This file defines the shared vocabulary for this system. Every term here
should be used consistently across code, prompts, documentation, and
conversation — if a coding agent finds itself using a synonym not listed
here for a defined concept, it should use the term below instead, or add
a new entry rather than introduce ambiguity.


---

## People / Roles

**End User** — The person interacting with the system through the Next.js
UI: defines or selects a Theme, triggers a Run, and reviews the resulting
Basket and Report. Never interacts with agents directly — only through the
UI/API surface.

**Reviewer** — An End User (or a designated role) performing the manual
review gate before a Basket/Report is treated as client-facing output (see
ARCHITECTURE.md §8, Evaluation Plan). Not a separate account type unless
the product later requires role-based access control.

**Operator** — The person(s) responsible for running and maintaining the
system itself: managing Secrets, monitoring Langfuse/Prometheus/Grafana,
responding to Failure Modes. Distinct from the End User, who never needs
operational visibility into the system's internals.

---

## The Pipeline (top-level concepts)

**Theme** — A user-defined investment idea (e.g. "grid modernization")
consisting of a name, a written definition, and a config (sub-exposures,
factor weights, screening thresholds). Persisted once, reusable across
many Runs.

**Run** — A single, on-demand execution of the full pipeline for one
Theme, from Screener through Report. Identified by a `run_id`. Never
triggered on a schedule (see ARCHITECTURE.md, Decision: No Scheduler) —
only by an explicit End User request.

**Candidate Universe** — The bounded set of tickers (typically 50-150)
produced by the Screener for a given Run. Not the full market — a
theme-scoped subset.

**Sub-exposure** — A decomposition of a Theme into a narrower thread (e.g.
"transmission equipment," "grid software" under "grid modernization").
Used by the Screener to structure candidate search and by the Trader to
enforce diversification.

**Basket** — The final output set of 8-10 tickers with assigned weights,
constructed by the Trader from the Ranked List under diversification and
liquidity constraints. This is the system's primary deliverable alongside
the Report.

**Report** (or **Rationale Report**) — The markdown document produced by
the Report agent explaining why each Basket holding was selected, which
near-misses were excluded and why, and aggregated basket-level risks.
Always carries the "not investment advice" disclaimer.

**Near-miss** — A candidate that ranked just below the cutoff for basket
inclusion (ranks 11-15 by convention), retained so the Report can
reference "considered but excluded" names for credibility.

**Swap** — An instance where the Trader skips a higher-ranked name in
favor of a lower-ranked one to satisfy a diversification constraint,
logged with an explicit `swap_reason`.

---

## Agents (each a bounded, single-responsibility role in the pipeline)

**Screener (Agent)** — Converts a Theme into a Candidate Universe. Does
not rank or judge; only generates and bounds the candidate list.

**Analyst (Agent)** — Produces one Analyst Report per ticker in the
Candidate Universe (run in parallel, one invocation per candidate). Does
not rank across tickers — operates on a single ticker at a time, blind to
the rest of the universe.

**Modeling (Agent)** — Converts Analyst Reports plus a Factor Panel into
a Ranked List via deterministic scoring code. The LLM's role here is
narrow: converting qualitative signals to numeric inputs and writing
`caveats`. The ranking itself is never an LLM judgment call (see
ARCHITECTURE.md, Decision: Deterministic Ranking).

**Validator (Agent, optional)** — Runs an adversarial bull/bear check on
the top ~12 entries of the Ranked List before basket construction. Can
demote or flag entries; never introduces new candidates or re-runs the
Modeling math.

**Trader (Agent)** — Constructs the Basket from the Ranked List under
hard constraints (liquidity floor, market cap floor, sector
diversification, position sizing). Selection and sizing are deterministic
code; the LLM's role is narrow: writing `swap_reason` prose.

**Report (Agent)** — Synthesizes the full Run's state into the Rationale
Report. Strictly fact-bound to upstream agent outputs — never introduces
information not already present in the Run.

---

## Data / Scoring Concepts

**Ticker** — A single tradable security (equity or ETF) identified by its
market symbol. The atomic unit the pipeline operates on.

**Factor** — A single measurable dimension used to evaluate a ticker
(e.g. `thematic_relevance`, `growth`, `valuation`, `momentum`,
`sentiment`, `quality`). Each factor has a raw value and, after
normalization, a Z-score.

**Factor Panel** — The full set of raw and normalized Factor values for
every ticker in a Run's Candidate Universe, as of a given date.

**Z-score** — A Factor's raw value standardized against the cross-
sectional mean and standard deviation of the Candidate Universe (not the
broader market), making Factors with different units/scales comparable.
See ARCHITECTURE.md §4 and the Modeling Agent's `compute_factor_scores`.

**Composite Score** — A single per-ticker number combining all weighted
Z-scores (or, under the Borda method, summed cross-Factor ranks). The
basis for the Ranked List's ordering.

**Ranked List** — The full Candidate Universe ordered by Composite Score,
produced by the Modeling Agent, including each ticker's rank and Factor
Contributions (for auditability).

**Factor Contribution** — The individual weighted-Z-score (or rank)
component each Factor contributed to a ticker's Composite Score — kept
alongside the score so the Report agent (and any human reviewer) can
trace *why* a ticker ranked where it did.

**Caveat** — A flag attached by the Modeling Agent to a ranking result
that looks anomalous (e.g. a thinly-traded name ranking #1 on momentum
alone) — a signal for the Trader/Reviewer, never a silent re-ordering.

---

## Infrastructure / Orchestration Concepts

**Node** — A single function/step in the LangGraph pipeline (e.g.
`screener_node`, `analyst_node`). Corresponds to one Agent's execution,
or a piece of deterministic logic.

**Edge** — A transition between Nodes in the graph; may be a fixed
sequential edge or a conditional edge (as in the bounded retry loop or
the fan-out `Send` dispatch).

**Fan-out** — The dynamic dispatch of the Analyst Node once per Candidate
(via LangGraph's `Send`), running in parallel rather than sequentially.

**Fan-in** — The point where parallel Analyst Node branches merge back
into shared Run state via the `analyst_reports` reducer, before the
Modeling Node runs. Requires the `Annotated[List[dict], operator.add]`
reducer to function correctly — see ARCHITECTURE.md §4.

**State** — The shared `BasketState` object threaded through the graph;
the only channel through which Nodes communicate (no direct
agent-to-agent API calls within a single Run).

**Checkpoint** — A persisted snapshot of a Run's State at a point in the
graph, stored via `PostgresSaver`, enabling resume after a crash without
restarting from the Screener.

**Retry (bounded)** — The capped (max 2) loop back to the Screener when
the Trader can't fill the Basket to 8 names after constraints — distinct
from a Scheduler, which this system does not have.

---

## Third-Party / External Concepts

**LLM Provider** — DeepSeek, the one model backend used across
Agents, selected per-step by cost/stakes (see ARCHITECTURE.md §6).

**Data Vendor** — Any external source of fundamentals, price, or news
data (FMP, Finnhub, SEC EDGAR, yfinance, Stooq, GDELT, StockTwits,
ETF issuer sites). Distinct from an LLM Provider.

**Free tier** — The rate-capped, no-cost access level used for all Data
Vendors in this system's current design — a hard constraint that makes DB
caching load-bearing rather than optional.

**Trace / Span** — A single recorded unit of execution (a Span) and its
full nested call tree (a Trace) captured by Langfuse for a Run — covers
prompts, completions, token usage, and cost per Agent call.

**Metric** — A numeric time-series data point (e.g. API latency, queue
depth) captured by Prometheus and visualized in Grafana — distinct from a
Trace; metrics describe system health, traces describe what an Agent
actually did and said.

---

## Compliance Concepts

**Disclaimer** — The mandatory "not investment advice, for research
purposes only" notice attached to every Report.

**Audit Trail** — The immutable, append-only chain of `Run` →
`AnalystReport` → `Ranking` → `Basket` → `Report` rows in Postgres, tying
every claim in a Report back to the exact evidence that produced it.

**Not Investment Advice** — The system's standing legal/compliance
posture: outputs are research artifacts for human review, never
autonomous trading decisions or a substitute for professional financial
advice.
