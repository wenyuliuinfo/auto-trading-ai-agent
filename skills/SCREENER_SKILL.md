---
name: screener-agent-implementation
description: Use this skill whenever writing, modifying, reviewing, or debugging code in app/agents/screener.py, the search_sector/search_holdings tool functions, the assemble_candidate_universe orchestration function, the sub-exposure-to-ETF mapping config, or the reference universe loader. Covers where these tools are defined, which free data sources back each, the curated config they depend on, the LLM tool-schema registration needed to expose them as callable functions, and — critically — the actual strategy used to merge, dedupe, and cap raw tool hits into the final 50-100 ticker Candidate Universe. Do not use this skill for Analyst agent per-ticker research (see ANALYST_SKILL.md) or Modeling agent scoring (see MODELING_SKILL.md).
---

# Screener Agent — Canonical Implementation & Rules

`search_sector(keyword)` and `search_holdings(sub_exposure)` are **not
pre-existing tools** — nothing in this system provides them out of the
box. They are two Python functions this skill defines, exposed to the
LLM via function-calling, backed by free data sources plus one piece of
configuration that has to be hand-curated because no free API answers it
directly. A third function, `assemble_candidate_universe`, is what
actually turns the LLM's per-sub-exposure tool calls into the final
50-100 ticker Candidate Universe — see Step 3 below; this is the piece
that was previously undefined. `ARCHITECTURE.md` §5.1 has the prompt
contract; this file is the implementation this skill's coding agent
should load and follow.

## Where these functions live (per `CONVENTIONS.md` §2)

`search_sector`/`search_holdings` are I/O-bound (they call external
sources), so their fetch/parse logic lives in `integrations/`.
`assemble_candidate_universe` does no I/O of its own — it only merges,
scores, and caps data already fetched — so it stays in `agents/screener.py`
alongside the node function, per the same rule used for
`compute_factor_scores`/`combine_scores`/`rank` in `MODELING_SKILL.md`:

```
app/
├── integrations/
│   ├── reference_universe.py   # backs search_sector
│   └── etf_holdings.py         # backs search_holdings
├── agents/
│   └── screener.py             # tool wrappers + assemble_candidate_universe
│                                #   + the LLM call + prompt + screener_node
└── config/
    └── sub_exposure_etf_map.yaml   # the curated mapping (see below)
```

## Hard rules

1. **Neither `search_sector` nor `search_holdings` ever invents a ticker.**
   Both only return tickers that appear in a real reference source (an
   index constituent list or an actual ETF holdings file) — the
   Screener's system prompt already forbids inventing from memory
   (`ARCHITECTURE.md` §5.1); these functions are what makes that
   enforceable in code, not just in the prompt.
2. **Cache before fetching.** Both the reference universe and ETF holdings
   files change infrequently (daily at most) — cache with a TTL (24h is
   reasonable) rather than re-fetching on every Screener call. Since
   there's no scheduler (`ARCHITECTURE.md`, Decision: No Scheduler), this
   cache is populated lazily on first request per day, not by a
   background job.
3. **The sub-exposure → ETF mapping is a config file, not inferred at
   runtime.** See "Configuration" below — do not have the LLM guess ETF
   tickers for a sub-exposure at call time; unmapped sub-exposures return
   an explicit empty/partial result (which the Screener's prompt is
   already instructed to report honestly, per `ARCHITECTURE.md` §5.1:
   "if a sub-exposure returns fewer than 5 candidates, say so").
4. **Every returned ticker carries its source** (`"index:russell3000"` or
   `"etf_holdings:ICLN"`) so downstream dedup and the audit trail can
   trace where each candidate came from.
5. **ETF holdings are seed-only by design.** Live issuer CSV downloads are
   intentionally not attempted; `etf_holdings.py` reads
   `config/etf_holdings_seed.yaml` and returns one consistent
   `{ticker, weight}` shape.
6. **Capping to 100 is a deterministic function, never an LLM choice.**
   `assemble_candidate_universe` (Step 3) is plain code — the LLM decides
   *which sub-exposures and search terms* to use, but never which
   individual tickers survive the cap. This mirrors the determinism
   boundary already enforced for ranking in `MODELING_SKILL.md`.
7. **The per-sub-exposure floor is enforced before the market-cap fill.**
   Do not cap by market cap alone — a single broad sector ETF (e.g. a
   sub-exposure resolving to `XLK`, hundreds of holdings) would otherwise
   crowd out every narrower sub-exposure's candidates. See Step 3's
   floor-then-fill strategy.

## Which data sources back each function

| Function | Data source | What it returns |
|---|---|---|
| `search_sector(keyword)` | A cached reference universe: Russell 3000 or S&P 1500 constituents with GICS sub-industry tags, sourced from Wikipedia or stockanalysis.com | Tickers whose GICS sub-industry (or, optionally, Pinecone-embedded business description — see note below) matches the keyword |
| `search_holdings(sub_exposure)` | The curated `sub_exposure_etf_map.yaml` config resolves sub-exposure → a short list of ETF tickers; `etf_holdings.py` reads the bundled `etf_holdings_seed.yaml` | Seed constituents of the mapped ETF(s) |

**Optional semantic supplement:** if the Pinecone semantic-candidate-
discovery feature (`ARCHITECTURE.md` §2.2) is implemented, `search_sector`
can additionally run a kNN query of the embedded keyword against embedded
company business descriptions, merging those hits in — but the
GICS/keyword match above must work standalone first; treat Pinecone as
additive, not a dependency this function requires to function at all.

## Configuration this skill requires (beyond the functions themselves)

1. **`config/sub_exposure_etf_map.yaml` — hand-curated, the one piece with
   no free-API shortcut.** No data source maps "smart meters" to ETF
   tickers automatically; someone has to decide which real thematic/
   sector ETFs represent each sub-exposure your themes will use, and
   maintain this file as new themes are added. See the full seed file
   generated alongside this skill (70 sub-exposures, sourced from current
   GICS Select Sector SPDRs and major thematic ETF families as of the
   dates below).

   Treat an unmapped sub-exposure as a known gap (Hard Rule 3), not a bug
   to silently paper over with an LLM guess.

2. **Reference universe source + refresh cadence.** Decide once: pull the
   Russell 3000/S&P 1500 list from Wikipedia or stockanalysis.com (both
   free), and set the cache TTL (Hard Rule 2). This needs an owner to
   confirm the source stays parseable — these are HTML scrapes/CSV
   pulls from public pages, not a stable versioned API, so a periodic
   manual check that the parser still works is worth budgeting for.

3. **ETF holdings seed file.** `config/etf_holdings_seed.yaml` is the
   single source of ETF constituents. Maintain it by hand as ETFs change;
   live issuer CSV fetching is intentionally not implemented.

4. **LLM tool-calling schema, registered separately from the Python
   function.** The LLM needs a JSON schema describing each tool's
   name/parameters/description to call it at all — this is not generated
   automatically from the Python signature; keep it explicitly in sync:
   ```python
   SCREENER_TOOLS = [
       {
           "name": "search_sector",
           "description": "Find tickers whose GICS sub-industry matches a keyword",
           "input_schema": {
               "type": "object",
               "properties": {"keyword": {"type": "string"}},
               "required": ["keyword"],
           },
       },
       {
           "name": "search_holdings",
           "description": "Find constituent tickers of ETFs mapped to a sub-exposure",
           "input_schema": {
               "type": "object",
               "properties": {"sub_exposure": {"type": "string"}},
               "required": ["sub_exposure"],
           },
       },
   ]
   ```
   If you rename a Python parameter or add one, update this schema in the
   same commit — a mismatch here causes silent tool-call failures, not a
   type error. Note `assemble_candidate_universe` (Step 3) is **not**
   exposed to the LLM as a tool at all — it runs automatically after the
   LLM's tool calls complete, not by LLM choice (Hard Rule 6).

## Step 1/2 — `search_sector` / `search_holdings` reference implementation

```python
# integrations/reference_universe.py

import pandas as pd

_CACHE: dict[str, tuple[pd.DataFrame, float]] = {}
CACHE_TTL_SECONDS = 24 * 60 * 60

def get_reference_universe() -> pd.DataFrame:
    """Returns cached (ticker, company_name, gics_subindustry, market_cap)
    for the Russell 3000 / S&P 1500. Refetches only if cache is stale or
    empty — no scheduler; this is a lazy, on-demand cache (Hard Rule 2)."""
    import time
    now = time.time()
    if "universe" in _CACHE:
        df, fetched_at = _CACHE["universe"]
        if now - fetched_at < CACHE_TTL_SECONDS:
            return df
    df = fetch_and_parse_index_constituents()  # Wikipedia / stockanalysis.com
    _CACHE["universe"] = (df, now)
    return df


def search_sector(keyword: str) -> list[dict]:
    universe = get_reference_universe()
    matches = universe[universe["gics_subindustry"].str.contains(keyword, case=False, na=False)]
    return [
        {**row, "source": "index:russell3000"}
        for row in matches.to_dict("records")
    ]
```

```python
# integrations/etf_holdings.py

import yaml
import pandas as pd

with open("config/sub_exposure_etf_map.yaml") as f:
    SUB_EXPOSURE_ETF_MAP: dict[str, list[str]] = yaml.safe_load(f)

with open("config/etf_holdings_seed.yaml") as f:
    ETF_HOLDINGS_SEED: dict[str, list[str]] = yaml.safe_load(f)

def fetch_etf_holdings(etf_ticker: str) -> pd.DataFrame:
    """Seed-only holdings; live issuer CSV downloads are not attempted."""
    tickers = ETF_HOLDINGS_SEED.get(etf_ticker) or ETF_HOLDINGS_SEED["_fallback"]
    return pd.DataFrame([{"ticker": ticker} for ticker in tickers])


def search_holdings(sub_exposure: str) -> list[dict]:
    etfs = SUB_EXPOSURE_ETF_MAP.get(sub_exposure, [])
    if not etfs:
        return []   # Hard Rule 3 — explicit gap, not an LLM guess
    results = []
    for etf in etfs:
        holdings = fetch_etf_holdings(etf)
        results.extend(
            {"ticker": r["ticker"], "weight": r.get("weight"), "source": f"etf_holdings:{etf}"}
            for r in holdings.to_dict("records")
        )
    return results
```

## Step 3 — Assemble & Cap the Candidate Universe (the previously-missing piece)

**This is the function that actually decides which 50-100 tickers make it
into the Candidate Universe.** Neither `search_sector` nor
`search_holdings` does this alone — each only returns raw hits for one
sub-exposure at a time, and a theme decomposes into 3-6 sub-exposures
(`ARCHITECTURE.md` §5.1), so their combined raw output is frequently
either well under 50 (narrow themes) or well over 100 (a sub-exposure
that resolves to a broad sector ETF like `XLK`). `assemble_candidate_universe`
is what merges, dedupes, and caps that raw output — called once, after
`screener_node`'s LLM call finishes making its `search_sector`/
`search_holdings` tool calls, never by the LLM itself (Hard Rule 6).

**Strategy — floor-then-fill by market cap:**
1. **Merge + dedupe** every sub-exposure's hits by ticker, tracking every
   sub-exposure a ticker matched (a ticker hit by two sub-exposures is
   kept once, tagged with both).
2. **Coverage check**: any sub-exposure with fewer than 5 raw hits is
   recorded as a warning — this is what feeds the prompt's "if a
   sub-exposure returns fewer than 5 candidates, say so explicitly"
   requirement (`ARCHITECTURE.md` §5.1).
3. **If under 50 total**: return as-is with a warning. Do not pad the
   list to hit 50 — this is exactly the gap the bounded retry loop
   (`ARCHITECTURE.md` §10, capped at 2) exists to handle by widening
   search terms, not something this function should paper over.
4. **If over 100 total**: cap using a *floor-then-fill* strategy, not a
   single global sort — this is the part that keeps the universe
   thematically balanced instead of one broad ETF drowning out
   everything else:
   - **Floor**: guarantee each sub-exposure a minimum number of slots
     (`max(3, 100 // (2 × number_of_sub_exposures))`), taking its
     highest-market-cap candidates first.
   - **Fill**: spend remaining slots across the whole remaining pool,
     sorted by market cap descending — market cap is used here purely as
     an investability/liquidity proxy, not a thematic-relevance
     judgment (that judgment already happened via which sub-exposure/ETF
     surfaced the ticker in the first place).
5. **Enrich with market cap before capping**, if not already present on a
   hit (ETF holdings CSVs often lack it; reference-universe hits usually
   have it) — a lightweight batch quote call, not the full
   `get_factor_panel` from `MODELING_SKILL.md`, which is a separate,
   heavier pull reserved for the actual Candidate Universe survivors.

```python
# agents/screener.py

MIN_CANDIDATES = 50
MAX_CANDIDATES = 100

def assemble_candidate_universe(
    sub_exposure_hits: dict[str, list[dict]],  # sub_exposure -> raw hits from search_sector/search_holdings
) -> tuple[list[dict], list[str]]:
    """Merges, dedupes, and caps raw tool-call hits into the final
    Candidate Universe. Deterministic — never an LLM choice (Hard Rule 6).
    Returns (candidates, warnings)."""
    warnings: list[str] = []

    # 1. Merge + dedupe, tracking every sub-exposure each ticker matched
    merged: dict[str, dict] = {}
    for sub_exposure, hits in sub_exposure_hits.items():
        if len(hits) < 5:
            warnings.append(f"sub_exposure '{sub_exposure}' returned only {len(hits)} candidates")
        for hit in hits:
            ticker = hit["ticker"]
            if ticker not in merged:
                merged[ticker] = {**hit, "sub_exposure_tags": set()}
            merged[ticker]["sub_exposure_tags"].add(sub_exposure)

    # 2. Enrich missing market_cap (lightweight batch quote, not get_factor_panel)
    candidates = enrich_with_market_cap(list(merged.values()))

    # 3. Under minimum — return as-is; ARCHITECTURE.md §10 retry loop handles widening
    if len(candidates) < MIN_CANDIDATES:
        warnings.append(f"universe below target minimum: {len(candidates)} < {MIN_CANDIDATES}")
        return candidates, warnings

    if len(candidates) <= MAX_CANDIDATES:
        return candidates, warnings

    # 4. Over maximum — floor-then-fill cap (Hard Rule 7)
    n_sub_exposures = len(sub_exposure_hits)
    per_sub_exposure_floor = max(3, MAX_CANDIDATES // (2 * n_sub_exposures))

    selected: dict[str, dict] = {}
    for sub_exposure in sub_exposure_hits:
        pool = sorted(
            (c for c in candidates if sub_exposure in c["sub_exposure_tags"]),
            key=lambda c: c.get("market_cap") or 0,
            reverse=True,
        )
        for c in pool[:per_sub_exposure_floor]:
            selected[c["ticker"]] = c

    remaining_slots = MAX_CANDIDATES - len(selected)
    remaining_pool = sorted(
        (c for c in candidates if c["ticker"] not in selected),
        key=lambda c: c.get("market_cap") or 0,
        reverse=True,
    )
    for c in remaining_pool[:remaining_slots]:
        selected[c["ticker"]] = c

    warnings.append(f"universe capped: {len(candidates)} raw hits -> {len(selected)} candidates")
    return list(selected.values()), warnings
```

`screener_node` calls this once, after the LLM's tool-calling loop
completes, and writes both `candidates` and `warnings` into the Run's
state — `warnings` surface in the Screener's own output text per the
prompt's "say so explicitly" instruction, they are not silently dropped.

## Test fixtures to include (per `CONVENTIONS.md` §5)

- Keyword with zero GICS matches — `search_sector` returns an empty list,
  not an error, so the Screener's prompt-level "say so explicitly" logic
  can act on it.
- Sub-exposure not present in `sub_exposure_etf_map.yaml` — `search_holdings`
  returns `[]`; verify no fallback guess is attempted.
- Missing/unparseable seed entry — verify `_fallback` is used and the run
  continues.
- Cache hit vs. miss for `get_reference_universe` — verify TTL expiry
  actually triggers a refetch, and a fresh cache does not.
- `assemble_candidate_universe` with < 50 total raw hits — verify it
  returns as-is with a warning, does not pad.
- `assemble_candidate_universe` with one sub-exposure contributing 400
  hits (broad ETF) and others contributing 10 each — verify the
  floor-then-fill strategy still gives every sub-exposure its floor
  before the broad one fills the remainder.
- `assemble_candidate_universe` with missing `market_cap` on some hits —
  verify `enrich_with_market_cap` is called and capping doesn't crash or
  silently drop tickers with unknown market cap (treat as lowest
  priority for the fill step, not excluded outright).
