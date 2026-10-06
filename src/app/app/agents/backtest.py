"""Backtest agent: replay the deterministic pipeline on point-in-time data."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any
from unittest.mock import patch

from app.agents import modeling, screener, trader
from app.backtest import signals
from app.backtest.benchmarks import build_benchmarks
from app.backtest.calendar import build_schedule
from app.backtest.metrics import attribution, period_return, summary_metrics
from app.backtest.simulate import simulate
from app.backtest.types import Rebalance, RebalanceResult
from app.config import load_yaml
from app.data.queries import (
    get_basket_with_scores,
    get_candidates,
    get_factor_panel_rows,
    get_klines,
    get_run,
    get_theme,
    save_backtest_result,
    update_backtest_progress,
    update_backtest_status,
)
from app.integrations import factor_panel
from app.integrations.historical_data import HistoricalStore, make_store
from app.logging_conf import get_logger

logger = get_logger(__name__)

_PATCH_LOCK = threading.Lock()


def load_backtest_config() -> dict[str, Any]:
    """Read the sole backtest parameter source and return its snapshot."""
    return copy.deepcopy(load_yaml("backtest.yaml"))


def config_hash(config: dict[str, Any]) -> str:
    encoded = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class BacktestContext:
    run_id: str
    theme_config: dict[str, Any]
    sub_exposures: list[str]
    max_candidates: int
    min_candidates: int
    primary_benchmark: str
    money_flow_window: int
    money_flow_min_obs: int


@contextmanager
def as_of_context(
    store: HistoricalStore,
    as_of: date,
    reference_rows: list[dict[str, Any]],
) -> Iterator[None]:
    """Temporarily patch the live data fetchers to point-in-time views."""
    price_fn = store.make_price_fetcher(as_of)
    fund_fn = store.make_fundamentals_fetcher(as_of)
    with _PATCH_LOCK, patch.object(
        factor_panel, "fetch_price_history", price_fn
    ), patch.object(
        factor_panel, "fetch_fundamentals", fund_fn
    ), patch.object(
        screener, "search_sector", lambda _keyword: reference_rows
    ):
        yield


def build_ranked_entries(
    ranked: Any, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reproduce the dictionary ``modeling_node`` builds for the Trader."""
    candidate_map = {str(c["ticker"]): c for c in candidates}
    entries: list[dict[str, Any]] = []
    for _, row in ranked.iterrows():
        ticker = str(row["ticker"])
        candidate = candidate_map.get(ticker, {})
        entries.append(
            {
                "ticker": ticker,
                "company_name": candidate.get("company_name"),
                "gics_subindustry": candidate.get("gics_subindustry"),
                "sub_exposure": candidate.get("sub_exposure"),
                "sub_exposure_tags": candidate.get("sub_exposure_tags", []),
                "composite_score": (
                    float(row["composite_score"])
                    if row["composite_score"] is not None
                    and str(row["composite_score"]) != "nan"
                    else None
                ),
                "rank": int(row["rank"]),
                "market_cap": candidate.get("market_cap"),
                "avg_dollar_volume": candidate.get("avg_dollar_volume"),
                "thematic_relevance_score": 3,
                "sentiment": 0.0,
                "factor_contributions": {},
                "caveats": [],
            }
        )
    return entries


def _score_once(
    ctx: BacktestContext,
    store: HistoricalStore,
    rebalance: Rebalance,
    max_candidates: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    list[dict[str, Any]],
    dict[str, Any],
]:
    hits = store.etf_universe(ctx.sub_exposures, rebalance.signal_date)
    with as_of_context(
        store, rebalance.signal_date, store.reference_rows(rebalance.signal_date)
    ):
        candidates, warnings = screener.assemble_candidate_universe(
            hits, max_candidates=max_candidates
        )
        tickers = sorted(str(c["ticker"]) for c in candidates)
        panel = factor_panel.get_factor_panel(tickers)

    reports = [
        {"ticker": ticker, "thematic_relevance_score": 3, "sentiment_label": "neutral"}
        for ticker in tickers
    ]
    frame = modeling._build_scoring_frame(panel, reports)
    frame["thematic"] = signals.etf_breadth(
        tickers, store.etf_membership(rebalance.signal_date)
    )
    frame["sentiment"] = signals.money_flow_ratio(
        store.ohlcv(tickers, rebalance.signal_date),
        window=ctx.money_flow_window,
        min_obs=ctx.money_flow_min_obs,
    )

    weights = ctx.theme_config["factor_weights"]
    factor_cols = [str(key).removesuffix("_z") for key in weights]
    missing_columns = [col for col in factor_cols if col not in frame.columns]
    if missing_columns:
        raise KeyError(f"missing factor columns for weights: {missing_columns}")

    scored = modeling.compute_factor_scores(frame, factor_cols)
    scored["composite_score"] = modeling.combine_scores(scored, weights)
    ranked = modeling.rank(scored)
    entries = build_ranked_entries(ranked, candidates)
    basket, near_misses, _swaps = trader.construct_basket(
        copy.deepcopy(entries), ctx.theme_config
    )
    inputs_summary = {
        "candidate_count": len(candidates),
        "eligible_count": len(entries),
        "etf_snapshots": {
            sub_exposure: len(store.etf_universe([sub_exposure], rebalance.signal_date).get(sub_exposure, []))
            for sub_exposure in ctx.sub_exposures
        },
        "top_tickers": [
            {"ticker": str(row["ticker"]), "rank": int(row["rank"])}
            for row in basket[:5]
        ],
    }
    return basket, near_misses, warnings, list(candidates), inputs_summary


def _score_rebalance(
    ctx: BacktestContext, store: HistoricalStore, rebalance: Rebalance
) -> RebalanceResult:
    warnings: list[str] = []
    try:
        basket, near_misses, score_warnings, candidates, inputs_summary = _score_once(
            ctx, store, rebalance, ctx.max_candidates
        )
        warnings.extend(score_warnings)
    except Exception as exc:
        logger.warning(
            "backtest_rebalance_failed",
            run_id=ctx.run_id,
            idx=rebalance.idx,
            error=str(exc),
        )
        return RebalanceResult(
            idx=rebalance.idx,
            signal_date=rebalance.signal_date,
            exec_date=rebalance.exec_date,
            hold_end_date=rebalance.hold_end_date,
            basket=[],
            warnings=[str(exc)],
            flags=["rebalance_failed"],
            inputs_summary={"candidate_count": 0, "eligible_count": 0},
            in_progress=rebalance.in_progress,
        )

    flags = ["llm_factors_replaced"]
    if len(candidates) < ctx.min_candidates:
        flags.append("insufficient_universe")
        basket = []
    if not basket:
        flags.append("no_basket")
    elif len(basket) < trader.MIN_BASKET_SIZE:
        flags.append("partial_basket")

    return RebalanceResult(
        idx=rebalance.idx,
        signal_date=rebalance.signal_date,
        exec_date=rebalance.exec_date,
        hold_end_date=rebalance.hold_end_date,
        basket=basket,
        warnings=warnings,
        flags=flags,
        near_misses=near_misses,
        inputs_summary=inputs_summary,
        in_progress=rebalance.in_progress,
    )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


async def build_current_holdings(run_id: str) -> list[dict[str, Any]]:
    """Assemble the live basket + factor panel + K-line snapshot view."""
    basket = await get_basket_with_scores(run_id)
    candidates = {row["ticker"]: row for row in await get_candidates(run_id)}
    klines = {row["ticker"]: row for row in await get_klines(run_id)}
    factor_rows: dict[str, dict[str, float | None]] = {}
    for row in await get_factor_panel_rows(run_id):
        factor_rows.setdefault(row["ticker"], {})[row["factor_name"]] = row["raw_value"]

    holdings: list[dict[str, Any]] = []
    for holding in basket:
        ticker = holding["ticker"]
        candidate = candidates.get(ticker, {})
        factor = factor_rows.get(ticker, {})
        kline = klines.get(ticker)
        holdings.append(
            {
                "ticker": ticker,
                "company_name": candidate.get("company_name"),
                "weight": holding.get("weight"),
                "rank": holding.get("rank"),
                "return_6m": factor.get("momentum_6m"),
                "price": kline["bars"][-1]["close"] if kline and kline.get("bars") else None,
                "pe_ratio": factor.get("pe_ratio"),
                "market_cap": factor.get("market_cap"),
                "kline": {
                    "status": kline["status"] if kline else "unavailable",
                    "mini_url": (
                        f"/api/runs/{run_id}/klines/{ticker}/mini.svg"
                        if kline and kline["status"] == "ok"
                        else None
                    ),
                },
            }
        )
    return holdings


def _rebalance_payload(
    result: RebalanceResult,
    strategy_points: list[Any],
    benchmark_points: list[Any],
    rebalance: Rebalance,
) -> dict[str, Any]:
    return {
        "idx": result.idx,
        "signal_date": _iso(result.signal_date),
        "exec_date": _iso(result.exec_date),
        "hold_end_date": _iso(result.hold_end_date),
        "candidate_count": result.inputs_summary.get("candidate_count", 0),
        "eligible_count": result.inputs_summary.get("eligible_count", 0),
        "basket": result.basket,
        "flags": result.flags,
        "period_return": period_return(rebalance, strategy_points),
        "benchmark_returns": {
            "primary": period_return(rebalance, benchmark_points)
            if benchmark_points
            else None
        },
        "inputs_summary": result.inputs_summary,
    }


async def _execute_backtest_impl(backtest_id: str, run_id: str, mode: str) -> None:
    """Run the full backtest loop and persist an immutable result."""
    cfg = load_backtest_config()
    mode_cfg = cfg.get("modes", {}).get(mode, {})
    if not bool(mode_cfg.get("enabled", False)):
        raise RuntimeError(f"backtest mode '{mode}' is disabled")

    run = await get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    theme = await get_theme(str(run["theme_id"]))
    if theme is None:
        raise ValueError(f"theme {run['theme_id']} not found")

    await update_backtest_progress(
        backtest_id, {"stage": "fetching_data", "completed": 0, "total": 0}, "running"
    )
    theme_config = theme["config"]
    store = make_store(cfg, theme_config)
    provenance = store.provenance()
    schedule = build_schedule(
        mode, cfg, run["requested_at"].date(), store.trading_days()
    )
    await store.prefetch(
        theme_config,
        schedule,
        lambda stage, completed, total: None,
    )

    ctx = BacktestContext(
        run_id=run_id,
        theme_config=theme_config,
        sub_exposures=list(theme_config.get("sub_exposures", [])),
        max_candidates=int(cfg.get("universe", {}).get("max_candidates_hard_limit", 400)),
        min_candidates=int(cfg.get("universe", {}).get("min_candidates_for_rebalance", 20)),
        primary_benchmark=str(cfg.get("benchmarks", {}).get("primary", "QQQ")),
        money_flow_window=int(
            cfg.get("signals", {}).get("sentiment", {}).get(
                "window_trading_days", 126
            )
        ),
        money_flow_min_obs=int(
            cfg.get("signals", {}).get("sentiment", {}).get(
                "money_flow_min_obs", 100
            )
        ),
    )

    await update_backtest_progress(
        backtest_id,
        {"stage": "building_universe", "completed": 0, "total": len(schedule)},
    )
    results = []
    for completed, rebalance in enumerate(schedule, start=1):
        await update_backtest_progress(
            backtest_id,
            {"stage": "scoring", "completed": completed, "total": len(schedule)},
        )
        results.append(
            await asyncio.to_thread(_score_rebalance, ctx, store, rebalance)
        )

    await update_backtest_progress(
        backtest_id,
        {"stage": "simulating", "completed": len(schedule), "total": len(schedule)},
    )
    targets = {
        result.exec_date: {
            str(holding["ticker"]): float(holding["weight"])
            for holding in result.basket
        }
        for result in results
    }
    sim = simulate(schedule, targets, store.total_return_prices(), cfg)
    configured_benchmarks = cfg.get("benchmarks", {}).get("enabled", [])
    # Only real fund tickers have an FMP price series. The equal-weight
    # baselines are strategy-derived and are not implemented by the current
    # store, so requesting prices for their names wastes an FMP call.
    real_benchmark_tickers = {"QQQ", "SPY"}
    benchmark_prices = {
        name: store.benchmark_prices(name)
        for name in configured_benchmarks
        if name in real_benchmark_tickers
    }
    date_axis = [point.date for point in sim.equity]
    benchmarks = build_benchmarks(benchmark_prices, date_axis, cfg)
    primary_points = benchmarks.get(ctx.primary_benchmark, [])
    summary = summary_metrics(
        sim.equity,
        benchmarks,
        schedule,
        sim,
        cfg,
        ctx.primary_benchmark,
    )

    flags = list(cfg.get("flags", {}).get("always_include", []))
    flags.extend(str(flag) for flag in provenance.get("flags", []))
    if len(schedule) < int(cfg.get("metrics", {}).get("short_window_min_rebalances", 8)):
        flags.append("short_window")
    flags = sorted(set(flags))
    if sim.missing_prices:
        flags.append("missing_prices")
    if sim.delisted_holdings:
        flags.append("delisted_holding")
    if provenance.get("data_source") == "stub":
        flags.append("synthetic_data")

    candidate_names = {
        str(row["ticker"]): str(row.get("company_name") or "")
        for row in await get_candidates(run_id)
    }
    attribution_rows = attribution(
        sim.trades,
        sim.final_positions,
        sim.final_prices,
        float(cfg.get("capital", {}).get("initial_cash", 10000)),
        candidate_names,
    )

    rebalance_payloads = [
        _rebalance_payload(result, sim.equity, primary_points, schedule[result.idx])
        for result in results
    ]
    status = "succeeded"
    failed_rebalances = [row for row in rebalance_payloads if "rebalance_failed" in row["flags"]]
    empty_rebalances = [row for row in rebalance_payloads if not row["basket"]]
    if len(failed_rebalances) == len(rebalance_payloads) and rebalance_payloads:
        status = "failed"
    elif failed_rebalances or empty_rebalances or not rebalance_payloads:
        status = "partial"

    await update_backtest_progress(
        backtest_id,
        {"stage": "finalizing", "completed": len(schedule), "total": len(schedule)},
        status,
    )
    await save_backtest_result(
        backtest_id,
        status=status,
        data_source=str(provenance.get("data_source", "stub")),
        code_version=os.getenv("GIT_COMMIT_SHA", "dev"),
        data_version=str(provenance.get("data_version", "dev")),
        period_start=schedule[0].exec_date if schedule else None,
        period_end=schedule[-1].hold_end_date if schedule else None,
        initial_cash=float(cfg.get("capital", {}).get("initial_cash", 10000)),
        costs_total=sim.costs_total,
        summary=summary,
        attribution=attribution_rows,
        flags=flags,
        progress={"stage": "finalizing", "completed": len(schedule), "total": len(schedule)},
        rebalances=rebalance_payloads,
        series={
            "strategy": sim.equity,
            **{name: points for name, points in benchmarks.items()},
        },
        trades=sim.trades,
    )


async def execute_backtest(backtest_id: str, run_id: str, mode: str) -> None:
    """Run one backtest, isolating failures from the parent run."""
    try:
        await _execute_backtest_impl(backtest_id, run_id, mode)
    except Exception as exc:
        logger.error(
            "backtest_job_failed",
            backtest_id=backtest_id,
            run_id=run_id,
            error=str(exc),
        )
        await update_backtest_status(
            backtest_id,
            "failed",
            error_code="BACKTEST_FAILED",
            error_message=str(exc),
        )
        raise
