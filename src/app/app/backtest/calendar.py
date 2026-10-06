"""Rebalance schedule construction for the backtest engine."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.backtest.types import Rebalance


def _first_trading_day_on_or_after(
    target: date, trading_days: list[date]
) -> date | None:
    """Return the first trading day at or after ``target``."""
    for day in trading_days:
        if day >= target:
            return day
    return None


def _last_trading_day_on_or_before(
    target: date, trading_days: list[date]
) -> date | None:
    """Return the last trading day at or before ``target``."""
    result: date | None = None
    for day in trading_days:
        if day > target:
            break
        result = day
    return result


def _previous_trading_day(day: date, trading_days: list[date]) -> date | None:
    previous: date | None = None
    for candidate in trading_days:
        if candidate >= day:
            break
        previous = candidate
    return previous


def _month_candidates(
    months: list[int], start_year: int, end_year: int, trading_days: list[date]
) -> list[date]:
    """Rebalance execution dates for the requested year range."""
    candidates: list[date] = []
    seen: set[date] = set()
    for year in range(start_year, end_year + 1):
        for month in months:
            exec_date = _first_trading_day_on_or_after(
                date(year, month, 1), trading_days
            )
            if exec_date is not None and exec_date not in seen:
                seen.add(exec_date)
                candidates.append(exec_date)
    return candidates


def _build_from_dates(
    exec_dates: list[date],
    trading_days: list[date],
    period_end: date,
    in_progress_end: date | None = None,
) -> list[Rebalance]:
    """Attach signal and hold-end dates to execution dates."""
    rebalances: list[Rebalance] = []
    for idx, exec_date in enumerate(exec_dates):
        signal_date = _previous_trading_day(exec_date, trading_days)
        if signal_date is None:
            raise ValueError(f"no signal date before {exec_date.isoformat()}")
        if idx + 1 < len(exec_dates):
            hold_end = exec_dates[idx + 1]
            in_progress = False
        elif in_progress_end is not None and exec_date < in_progress_end:
            hold_end = in_progress_end
            in_progress = True
        else:
            hold_end = period_end
            in_progress = False
        rebalances.append(
            Rebalance(
                idx=idx,
                signal_date=signal_date,
                exec_date=exec_date,
                hold_end_date=hold_end,
                in_progress=in_progress,
            )
        )
    return rebalances


def build_schedule(
    mode: str,
    cfg: dict[str, Any],
    run_date: date,
    trading_days: list[date],
) -> list[Rebalance]:
    """Build the rebalance schedule for ``trailing`` or ``full`` mode.

    ``trading_days`` must be sorted ascending. Rebalance dates are the first
    trading day on or after the first of each configured month.
    """
    days = sorted({day for day in trading_days if isinstance(day, date)})
    if not days:
        return []

    schedule_cfg = cfg.get("schedule", {})
    months = [int(month) for month in schedule_cfg.get("rebalance_months", [1, 4, 7, 10])]
    mode_cfg = cfg.get("modes", {}).get(mode, {})

    if mode == "full":
        start = date.fromisoformat(str(mode_cfg.get("start", "2021-01-01")))
        end = date.fromisoformat(str(mode_cfg.get("end", "2025-12-31")))
        exec_dates = _month_candidates(months, start.year, end.year, days)
        exec_dates = [day for day in exec_dates if start <= day <= end]
        if exec_dates:
            truncated_end = _last_trading_day_on_or_before(end, days)
            if truncated_end is None:
                truncated_end = end
            return _build_from_dates(exec_dates, days, truncated_end)
        return []

    if mode == "trailing":
        completed_periods = int(mode_cfg.get("completed_periods", 4))
        include_in_progress = bool(mode_cfg.get("include_in_progress_period", True))
        min_partial_days = int(mode_cfg.get("min_partial_hold_days", 10))
        # Cover enough history that four completed periods are available around
        # the run date. The last period is intentionally included and then
        # classified below.
        exec_dates = _month_candidates(months, run_date.year - 2, run_date.year, days)
        exec_dates = [day for day in exec_dates if day <= run_date]

        completed: list[date] = []
        in_progress_exec: date | None = None
        for index, exec_date in enumerate(exec_dates):
            next_exec = exec_dates[index + 1] if index + 1 < len(exec_dates) else None
            if next_exec is not None and next_exec <= run_date:
                completed.append(exec_date)
            elif exec_date <= run_date:
                in_progress_exec = exec_date

        selected = completed[-completed_periods:] if completed else []
        if include_in_progress and in_progress_exec is not None:
            end_date = _last_trading_day_on_or_before(run_date, days) or run_date
            elapsed = sum(
                1 for day in days if in_progress_exec < day <= end_date
            )
            if elapsed >= min_partial_days and in_progress_exec not in selected:
                selected = [*selected, in_progress_exec]

        if not selected:
            return []
        end_date = _last_trading_day_on_or_before(run_date, days) or run_date
        in_progress_end = run_date if include_in_progress else None
        return _build_from_dates(selected, days, end_date, in_progress_end)

    raise ValueError(f"unsupported backtest mode: {mode}")
