"""LangGraph StateGraph assembly (ARCHITECTURE.md §4.2).

The graph is a fixed DAG with two non-linear points: the Analyst fan-out
and the bounded Screener retry loop. Nodes communicate only through
``BasketState``; no direct agent-to-agent calls.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.analyst import analyst_node
from app.agents.modeling import modeling_node
from app.agents.report import report_node
from app.agents.screener import screener_node
from app.agents.trader import MIN_BASKET_SIZE, trader_node
from app.agents.validator import validator_node
from app.config import asyncpg_url_to_dsn, get_settings
from app.data.queries import get_run, get_theme, update_run_status
from app.integrations.langfuse_client import start_run_trace
from app.logging_conf import get_logger

logger = get_logger(__name__)


class BasketState(TypedDict):
    run_id: str
    theme: str
    theme_definition: str
    theme_config: dict[str, Any]
    candidates: list[dict[str, Any]]
    analyst_reports: Annotated[list[dict[str, Any]], operator.add]
    factor_panel: list[dict[str, Any]]
    ranked_list: list[dict[str, Any]]
    basket: list[dict[str, Any]]
    near_misses: list[dict[str, Any]]
    report_md: str
    retry_count: int
    warnings: list[str]


def fan_out_to_analysts(state: BasketState) -> list[Any]:
    """One Send per candidate; each branch is blind to the rest of the universe."""
    return [
        Send(
            "analyst_node",
            {
                "run_id": state["run_id"],
                "ticker": candidate["ticker"],
                "theme": state["theme"],
                "theme_definition": state["theme_definition"],
                "theme_config": state["theme_config"],
                "candidate": candidate,
            },
        )
        for candidate in state["candidates"]
    ]


def check_basket_complete(state: BasketState) -> str:
    """Bounded retry back to the Screener when the basket is under 5 names."""
    if len(state["basket"]) >= MIN_BASKET_SIZE or state.get("retry_count", 0) >= 2:
        return "report"
    return "screener_retry"


def build_graph(checkpointer: Any | None = None) -> Any:
    """Compile the pipeline graph with the given checkpointer (or none)."""
    graph = StateGraph(BasketState)
    graph.add_node("screener", screener_node)
    graph.add_node("analyst_node", analyst_node)
    graph.add_node("modeling", modeling_node)
    graph.add_node("validator", validator_node)
    graph.add_node("trader", trader_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "screener")
    graph.add_conditional_edges("screener", fan_out_to_analysts, ["analyst_node"])
    graph.add_edge("analyst_node", "modeling")
    graph.add_edge("modeling", "validator")
    graph.add_edge("validator", "trader")
    graph.add_conditional_edges(
        "trader",
        check_basket_complete,
        {"screener_retry": "screener", "report": "report"},
    )
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)


async def execute_run(run_id: str) -> None:
    """Run one pipeline end-to-end and keep the runs row in sync."""
    run = await get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    theme = await get_theme(str(run["theme_id"]))
    if theme is None:
        raise ValueError(f"theme {run['theme_id']} not found")

    await update_run_status(run_id, "running")
    trace = start_run_trace(run_id)
    try:
        initial_state: BasketState = {
            "run_id": run_id,
            "theme": str(theme["name"]),
            "theme_definition": str(theme["definition"]),
            "theme_config": theme["config"],
            "candidates": [],
            "analyst_reports": [],
            "factor_panel": [],
            "ranked_list": [],
            "basket": [],
            "near_misses": [],
            "report_md": "",
            "retry_count": 0,
            "warnings": [],
        }
        await _invoke_graph(initial_state, run_id)
        await update_run_status(run_id, "complete")
    except Exception as exc:
        logger.error("run_failed", run_id=run_id, error=str(exc))
        await update_run_status(run_id, "failed", error_detail=str(exc))
        raise
    finally:
        if trace is not None:
            try:
                trace.flush()
            except Exception:
                logger.warning("langfuse_flush_failed", run_id=run_id)


async def _invoke_graph(initial_state: BasketState, run_id: str) -> None:
    """Invoke the graph with AsyncPostgresSaver (MemorySaver dev fallback)."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning("postgres_checkpointer_unavailable_using_memory")
        from langgraph.checkpoint.memory import MemorySaver

        graph = build_graph(MemorySaver())
        await graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": run_id}}
        )
        return
    settings = get_settings()
    dsn = asyncpg_url_to_dsn(settings.effective_database_url)
    if not dsn.startswith("postgresql://"):
        from langgraph.checkpoint.memory import MemorySaver

        graph = build_graph(MemorySaver())
        await graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": run_id}}
        )
        return
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        await graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": run_id}}
        )
