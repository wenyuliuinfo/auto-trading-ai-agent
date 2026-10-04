"""Report agent: fact-bound rationale synthesis with code-enforced disclaimer."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

from app.data.queries import (
    get_analyst_reports,
    get_basket_with_scores,
    get_candidates,
    get_factor_panel_rows,
    get_klines,
    get_rankings,
    save_report,
)
from app.integrations.kline import KLINE_MIN_BARS_CHART, KLINE_MIN_BARS_RETURN
from app.logging_conf import get_logger

logger = get_logger(__name__)

REPORT_MODEL = "deepseek-v4-pro"
REPORT_TEMPERATURE = 0.5


THEME_EXPLANATION_PROMPT = """You are an investment-thesis writer. Given a theme name and
definition, explain what the theme is, why it matters as an investment
theme, and the broad structural drivers, demand tailwinds, and risks that
define it. Write 2-3 clear sentences. Do not mention specific tickers or
portfolio weights, and do not give investment advice."""

RISK_SUMMARY_PROMPT = """You are a portfolio risk writer. Given a list of shared
risk themes, write exactly one concise sentence describing the primary
basket-level risk. Do not invent risks and do not mention specific tickers
unless a risk was explicitly shared by those tickers."""

REPORT_SYSTEM_PROMPT = """You are an Investment Rationale Writer. You will receive the full audit
trail: theme definition, Analyst reports, Modeling Agent factor
breakdowns (including composite_score), and the Trader Agent's final
basket with weights.

Write a client-ready rationale document with:
1. A 2-3 sentence theme thesis.
2. Per-holding rationale (2-4 sentences each): why it's in the basket,
   grounded specifically in its thematic_relevance_rationale, composite_score
   and top-2 factor_contributions, and any near-term catalyst — not
   generic boilerplate. For each holding include: the company name,
   a concise "why included" summary, the latest news headline with its
   source, and the 1-year performance figure. Do not repeat the same
   sentence structure for every name.
3. A short "considered but excluded" section referencing 2-3 near-miss
   names and why they didn't make the cut (this builds credibility).
4. A risk section: describe the pre-clustered risk_clusters you were
   given (each already verified to be shared by ≥2 holdings) as
   basket-level risks, not per-stock footnotes — do not attempt to find
   additional overlaps yourself beyond what's provided.
5. Format per-holding entries as paragraphs, never a table. Under
   "Portfolio Holdings", give each holding a heading like
   `### Ticker - Company Name`, followed by `**Why included:** ...`,
   `**Latest News:** ...`, and `**1-Year Return:** ...` lines.

Ground every claim in the upstream agent outputs — do not introduce new
facts. If the Modeling Agent flagged a caveat on a held position, surface
it here rather than omitting it. This is not a research report from
scratch; it is a faithful synthesis of the pipeline's own outputs."""

DISCLAIMER = (
    "\n\n---\n*This report is for research purposes only and does not "
    "constitute investment advice. It is not a recommendation to buy or "
    "sell any security.*"
)

DISCLAIMER_TEXT = (
    "This report is for research purposes only and does not constitute "
    "investment advice. It is not a recommendation to buy or sell any security."
)


def apply_disclaimer(report_md: str) -> str:
    """Unconditionally append the compliance disclaimer (Hard Rule 2)."""
    return report_md.rstrip() + DISCLAIMER


def _stub_theme_explanation(theme: str, theme_definition: str) -> str:
    return (
        f"{theme} is an investment theme selected for its structural "
        f"exposure to a specific demand or infrastructure cycle. "
        f"{theme_definition}"
    ).strip()


def _stub_risk_summary(clusters: list[dict[str, Any]]) -> str:
    return _risk_summary_text(clusters)


async def _generate_theme_explanation(
    theme: str, theme_definition: str
) -> str:
    from app.integrations.deepseek_client import DeepSeekClient

    client = DeepSeekClient()
    result = await client.complete_text(
        model=REPORT_MODEL,
        temperature=0.4,
        system=THEME_EXPLANATION_PROMPT,
        input_data={"theme": theme, "definition": theme_definition},
    )
    return result.strip()


async def _generate_risk_summary(clusters: list[dict[str, Any]]) -> str:
    from app.integrations.deepseek_client import DeepSeekClient

    client = DeepSeekClient()
    result = await client.complete_text(
        model=REPORT_MODEL,
        temperature=0.3,
        system=RISK_SUMMARY_PROMPT,
        input_data={"risk_clusters": clusters},
    )
    return result.strip()


def _split_table_row(line: str) -> list[str]:
    """Split one markdown table row into trimmed cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _strip_inline_markdown(text: str) -> str:
    """Remove simple bold/italic markers from a table cell."""
    return text.strip().removeprefix("**").removesuffix("**").removeprefix("*").removesuffix("*")


def _column_index(header: list[str], names: tuple[str, ...]) -> int | None:
    for index, cell in enumerate(header):
        normalized = cell.lower().replace("\u2011", "-")
        if any(name in normalized for name in names):
            return index
    return None


def _reformat_holdings_table(report_md: str) -> str:
    """Replace a holdings markdown table with per-stock paragraphs.

    The LLM sometimes emits a table for Portfolio Holdings; this converts
    it deterministically so the UI always renders paragraph-style entries.
    """
    lines = report_md.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("|") or index + 1 >= len(lines):
            output.append(line)
            index += 1
            continue
        header = _split_table_row(line)
        separator = lines[index + 1]
        if not separator.lstrip().startswith("|") or not set(separator) <= set("|-: "):
            output.append(line)
            index += 1
            continue
        ticker_idx = _column_index(header, ("ticker",))
        company_idx = _column_index(header, ("company",))
        why_idx = _column_index(header, ("why included", "why"))
        news_idx = _column_index(header, ("news",))
        return_idx = _column_index(header, ("1-year", "1 year", "return"))
        if ticker_idx is None or why_idx is None:
            output.append(line)
            index += 1
            continue
        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            row = _split_table_row(lines[index])
            required_width = max(
                column
                for column in (ticker_idx, why_idx)
                if column is not None
            )
            if len(row) <= required_width:
                output.append(lines[index])
                index += 1
                continue
            ticker = _strip_inline_markdown(row[ticker_idx]) or "Unknown"
            company = (
                _strip_inline_markdown(row[company_idx])
                if company_idx is not None and company_idx < len(row)
                else ""
            )
            heading = f"**{ticker} - {company}**" if company else f"**{ticker}**"
            output.append(heading)
            output.append(f"- Why included: {row[why_idx]}")
            if news_idx is not None and news_idx < len(row):
                output.append(f"- Latest news: {row[news_idx]}")
            if return_idx is not None and return_idx < len(row):
                output.append(f"- 1-Year Return: {row[return_idx]}")
            output.append("")
            index += 1
    return "\n".join(output).rstrip() + "\n"


def _normalize_risk_text(risk: str) -> str:
    """Lowercase + strip punctuation; conservative matching (REPORT_SKILL.md)."""
    return risk.lower().strip().rstrip(".")


def group_shared_risks(
    analyst_reports: dict[str, dict[str, Any]], tickers: list[str]
) -> list[dict[str, Any]]:
    """Pre-cluster risks shared by >=2 holdings (Hard Rule 4)."""
    risk_to_tickers: dict[str, list[str]] = defaultdict(list)
    for ticker in tickers:
        report = analyst_reports.get(ticker)
        if not report:
            continue
        for risk in report.get("risks", []):
            risk_to_tickers[_normalize_risk_text(str(risk))].append(ticker)
    return [
        {"risk_theme": risk, "tickers": tickers_sharing_it}
        for risk, tickers_sharing_it in risk_to_tickers.items()
        if len(tickers_sharing_it) >= 2
    ]


async def assemble_report_context(
    run_id: str,
    theme: str,
    near_misses: list[dict[str, Any]],
    theme_definition: str = "",
) -> dict[str, Any]:
    """Gather everything report_node hands to the LLM (Hard Rule 1)."""
    basket = await get_basket_with_scores(run_id)
    analyst_reports = {r["ticker"]: r for r in await get_analyst_reports(run_id)}
    ranking_caveats = {
        r["ticker"]: r.get("caveats", []) for r in await get_rankings(run_id)
    }
    candidates = {c["ticker"]: c for c in await get_candidates(run_id)}
    factor_rows = await get_factor_panel_rows(run_id)
    return_1y = {
        row["ticker"]: row["raw_value"]
        for row in factor_rows
        if row["factor_name"] == "return_1y"
    }
    momentum_6m = {
        row["ticker"]: row["raw_value"]
        for row in factor_rows
        if row["factor_name"] == "momentum_6m"
    }
    klines = {row["ticker"]: row for row in await get_klines(run_id)}
    risk_clusters = group_shared_risks(
        analyst_reports, tickers=[b["ticker"] for b in basket]
    )
    return {
        "theme": theme,
        "theme_definition": theme_definition,
        "basket": [
            {
                **b,
                "company_name": candidates.get(b["ticker"], {}).get("company_name"),
                "analyst_report": analyst_reports.get(b["ticker"]),
                "caveats": ranking_caveats.get(b["ticker"], []),
                "return_1y": return_1y.get(b["ticker"]),
            }
            for b in basket
        ],
        "near_misses": [
            {
                **n,
                "company_name": candidates.get(n["ticker"], {}).get("company_name"),
                "analyst_report": analyst_reports.get(n["ticker"]),
            }
            for n in near_misses
        ],
        "risk_clusters": risk_clusters,
        "klines": klines,
        "momentum_6m": momentum_6m,
    }


def _top_contributions(factor_contributions: dict[str, Any]) -> list[str]:
    finite = [
        (str(name), float(value))
        for name, value in factor_contributions.items()
        if value is not None
    ]
    finite.sort(key=lambda item: item[1], reverse=True)
    return [f"{name}={value:.3f}" for name, value in finite[:2]]


def _safe_url(url: Any) -> str | None:
    value = str(url or "")
    return value if value.startswith(("http://", "https://")) else None


def _select_latest_news(news: Any) -> dict[str, Any]:
    items = news if isinstance(news, list) else []
    if not items:
        return {}
    def sort_key(item: dict[str, Any]) -> tuple[bool, str]:
        value = str(item.get("published_at") or "")
        return (bool(value), value)
    selected = sorted(items, key=sort_key, reverse=True)[0]
    url = _safe_url(selected.get("url"))
    return {
        "headline": str(selected.get("headline") or ""),
        "source": str(selected.get("source") or ""),
        "url": url,
        "published_at": selected.get("published_at"),
    }


def compute_return_6m(bars: list[dict[str, Any]]) -> float | None:
    if len(bars) < KLINE_MIN_BARS_RETURN:
        return None
    first = bars[0].get("close")
    last = bars[-1].get("close")
    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    try:
        first_close = as_float(first)
        last_close = as_float(last)
    except Exception:
        return None
    if first_close is None or last_close is None or first_close <= 0:
        return None
    return last_close / first_close - 1


def _fallback_reason(holding: dict[str, Any]) -> str:
    analyst = holding.get("analyst_report") or {}
    score = holding.get("composite_score")
    score_text = f"{score:.4f}" if score is not None else "n/a"
    parts = [
        str(analyst.get("thematic_relevance_rationale") or "").strip(),
        f"Composite score {score_text}.",
        ", ".join(_top_contributions(holding.get("factor_contributions", {}))),
    ]
    caveats = holding.get("caveats") or []
    if caveats:
        parts.append("Modeling caveat: " + "; ".join(str(c) for c in caveats))
    return " ".join(part for part in parts if part)


def _build_report_data(context: dict[str, Any], run_id: str) -> dict[str, Any]:
    basket = list(context.get("basket", []))
    basket.sort(key=lambda h: (-float(h.get("weight", 0) or 0), int(h.get("rank") or 0)))
    holdings: list[dict[str, Any]] = []
    for holding in basket:
        ticker = str(holding["ticker"])
        kline = context.get("klines", {}).get(ticker, {})
        bars = kline.get("bars") or []
        return_6m = compute_return_6m(bars)
        source: str | None = (
            "kline_snapshot" if return_6m is not None else "factor_panel"
        )
        if return_6m is None:
            momentum = context.get("momentum_6m", {}).get(ticker)
            return_6m = float(momentum) if momentum is not None else None
            source = "factor_panel" if return_6m is not None else None
        kline_status = kline.get("status", "unavailable")
        mini_url = (
            f"/runs/{run_id}/klines/{ticker}/mini.svg"
            if kline_status == "ok" and len(bars) >= KLINE_MIN_BARS_CHART
            else None
        )
        holdings.append(
            {
                "ticker": ticker,
                "company_name": holding.get("company_name") or ticker,
                "weight": float(holding.get("weight") or 0),
                "rank": holding.get("rank"),
                "sub_exposure": holding.get("sub_exposure"),
                "composite_score": holding.get("composite_score"),
                "return_6m": return_6m,
                "return_6m_source": source,
                "news": _select_latest_news(
                    (holding.get("analyst_report") or {}).get("news")
                ),
                "kline": {
                    "status": kline_status,
                    "as_of": kline.get("as_of"),
                    "flags": kline.get("flags") or [],
                    "mini_url": mini_url,
                    "error_code": kline.get("error_code"),
                },
                "why_included": _fallback_reason(holding),
                "factor_contributions": holding.get("factor_contributions") or {},
                "caveats": holding.get("caveats") or [],
            }
        )

    total_weight = sum(h["weight"] for h in holdings)
    weighted_numerator = sum(
        h["weight"] * h["return_6m"]
        for h in holdings
        if h["return_6m"] is not None
    )
    covered_weight = sum(
        h["weight"] for h in holdings if h["return_6m"] is not None
    )
    allocation: dict[str, float] = {}
    for h in holdings:
        name = str(h.get("sub_exposure") or "Other")
        allocation[name] = allocation.get(name, 0.0) + h["weight"]
    allocation_rows = sorted(
        [{"name": k, "weight": v} for k, v in allocation.items()],
        key=lambda row: cast(float, row["weight"]),
        reverse=True,
    )
    as_ofs = [k["as_of"] for k in [h["kline"] for h in holdings] if k.get("as_of")]
    return {
        "schema_version": 1,
        "theme_name": context.get("theme"),
        "disclaimer": DISCLAIMER_TEXT,
        "narrative_fallback": True,
        "summary": {
            "holdings_count": len(holdings),
            "weighted_return_6m": (
                weighted_numerator / covered_weight if covered_weight else None
            ),
            "return_coverage": (
                covered_weight / total_weight if total_weight else 0.0
            ),
            "top3_weight": sum(sorted((h["weight"] for h in holdings), reverse=True)[:3]),
            "allocation_by_sub_exposure": allocation_rows,
            "data_as_of": {
                "earliest": min(as_ofs) if as_ofs else None,
                "latest": max(as_ofs) if as_ofs else None,
            },
        },
        "thesis": context.get("theme_explanation")
        or (
            "This basket aggregates high-ranked candidates whose business "
            "exposure, growth, and momentum align with the theme."
        ),
        "holdings": holdings,
        "excluded": [
            {
                "ticker": str(n.get("ticker")),
                "company_name": n.get("company_name") or str(n.get("ticker")),
                "reason": (
                    (n.get("analyst_report") or {}).get("thematic_relevance_rationale")
                    or ""
                ),
            }
            for n in context.get("near_misses", [])[:3]
        ],
        "risk_summary": context.get("risk_summary")
        or _risk_summary_text(context.get("risk_clusters", [])),
    }


def _risk_summary_text(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "No common basket-level risk cluster was identified across holdings."
    return "; ".join(
        f"{cluster['risk_theme']} (shared by {', '.join(cluster['tickers'])})"
        for cluster in clusters
    )


def _stub_report(context: dict[str, Any]) -> str:
    """Deterministic markdown report for offline/stub runs."""
    lines: list[str] = []
    theme = str(context.get("theme", "Thematic basket"))
    lines.append(f"# {theme} - Rationale Report")
    lines.append("")
    thesis = (
        "This basket aggregates high-ranked candidates whose business "
        "exposure, growth, and momentum align with the theme. Holdings were "
        "selected deterministically from the ranked universe under "
        "diversification and liquidity constraints."
    )
    lines.append(f"## Theme Thesis\n\n{thesis}")
    lines.append("## Basket")
    for holding in context.get("basket", []):
        ticker = holding["ticker"]
        company_name = holding.get("company_name") or ticker
        analyst = holding.get("analyst_report") or {}
        score = holding.get("composite_score")
        score_text = f"{score:.4f}" if score is not None else "n/a"
        rationale = analyst.get("thematic_relevance_rationale", "")
        catalysts = analyst.get("catalysts", [])
        catalyst_text = f" Catalyst: {catalysts[0]}." if catalysts else ""
        caveat_text = (
            f" Modeling caveat: {', '.join(holding.get('caveats', []))}."
            if holding.get("caveats")
            else ""
        )
        news_items = analyst.get("news", [])
        news_text = "No recent news available."
        if news_items:
            latest = news_items[0]
            news_text = (
                f"**{latest.get('headline', '')}** ({latest.get('source', '')}) - "
                f"{latest.get('url', '')}"
            )
        return_1y = holding.get("return_1y")
        return_text = (
            f"{return_1y * 100:+.1f}%" if return_1y is not None else "n/a"
        )
        why_text = (
            f"Why included: {rationale} Composite score {score_text}, "
            f"top contributions {', '.join(_top_contributions(holding.get('factor_contributions', {})))}."
            f"{catalyst_text}{caveat_text}"
        )
        lines.append(
            f"**{ticker} - {company_name}** ({holding.get('weight', 0) * 100:.1f}%)"
        )
        lines.append(f"- {why_text}")
        lines.append(f"- Latest news: {news_text}")
        lines.append(f"- 1-year performance: {return_text}")
    lines.append("")
    lines.append("## Considered But Excluded")
    for near_miss in context.get("near_misses", [])[:3]:
        analyst = near_miss.get("analyst_report") or {}
        rationale = analyst.get("thematic_relevance_rationale", "")
        company_name = near_miss.get("company_name") or near_miss["ticker"]
        lines.append(
            f"- {near_miss['ticker']} ({company_name}) ranked below the basket "
            f"cutoff; {rationale}"
        )
    if not context.get("near_misses"):
        lines.append("- No near-miss names were available for this run.")
    lines.append("")
    lines.append("## Basket-Level Risks")
    clusters = context.get("risk_clusters", [])
    if clusters:
        for cluster in clusters:
            lines.append(
                f"- {cluster['risk_theme']} (shared by "
                f"{', '.join(cluster['tickers'])})."
            )
    else:
        lines.append(
            "No common basket-level risk cluster was identified across holdings."
        )
    return "\n".join(lines)


async def report_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesize the report, apply the disclaimer, and persist it."""
    from app.integrations.deepseek_client import DeepSeekClient, stubbing_enabled

    context = await assemble_report_context(
        str(state["run_id"]),
        str(state.get("theme", "")),
        state.get("near_misses", []),
        str(state.get("theme_definition", "")),
    )
    theme_name = str(state.get("theme", ""))
    theme_definition = str(state.get("theme_definition", ""))
    if stubbing_enabled():
        context["theme_explanation"] = _stub_theme_explanation(
            theme_name, theme_definition
        )
        context["risk_summary"] = _stub_risk_summary(
            context.get("risk_clusters", [])
        )
    else:
        try:
            context["theme_explanation"] = await _generate_theme_explanation(
                theme_name, theme_definition
            )
        except Exception as exc:
            logger.warning("theme_explanation_llm_failed", error=str(exc))
            context["theme_explanation"] = _stub_theme_explanation(
                theme_name, theme_definition
            )
        try:
            context["risk_summary"] = await _generate_risk_summary(
                context.get("risk_clusters", [])
            )
        except Exception as exc:
            logger.warning("risk_summary_llm_failed", error=str(exc))
            context["risk_summary"] = _stub_risk_summary(
                context.get("risk_clusters", [])
            )
    if stubbing_enabled():
        raw_report = _stub_report(context)
    else:
        client = DeepSeekClient()
        # Raw K-line bars are storage/render data only. Keep them out of the
        # LLM payload: they add no grounding and can make the request so large
        # that the provider drops the connection.
        llm_context = {
            key: value
            for key, value in context.items()
            if key not in {"klines", "momentum_6m"}
        }
        raw_report = await client.complete_text(
            model=REPORT_MODEL,
            temperature=REPORT_TEMPERATURE,
            system=REPORT_SYSTEM_PROMPT,
            input_data=llm_context,
        )
    report_md = apply_disclaimer(_reformat_holdings_table(raw_report))
    report_data = _build_report_data(context, str(state["run_id"]))
    await save_report(str(state["run_id"]), report_md, report_data)
    return {"report_md": report_md}
