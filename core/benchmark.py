"""core/benchmark.py — TAIEX benchmark lookups for backtest alpha/beta split.

Wave A3 (2026-07-23), fable 裁定 R4. Pure functions only (no I/O, no network)
— mirrors core/paper_trading.py's "engine stays pure; CLI wrapper does I/O"
discipline. Callers (tools/run_backtest.py) load data/taiex_history.json and
pass the resulting dict in; this module never touches the filesystem.

`as_of_close` does a NEAREST-PRIOR-DATE lookup rather than requiring an exact
key match: TAIEX has no close on non-trading days, and a couple of committed
snapshot dates in reports/*.json (e.g. 2026-05-17, a Sunday — a pre-existing
backfill artifact, not something this module can or should fix) don't line up
with a real trading day. Falling back to the latest available close before
the requested date is the standard "index doesn't move on days it's closed"
convention and keeps every trade's benchmark lookup defined.
"""
from __future__ import annotations

import bisect
from typing import Any


def as_of_close(history: dict[str, dict[str, Any]], date: str) -> float | None:
    """Return the TAIEX close on `date`, or the nearest PRIOR trading date's
    close if `date` itself has no entry. None if history is empty or every
    entry is after `date`."""
    if not history:
        return None
    if date in history:
        return history[date].get("close")
    dates = sorted(history)
    i = bisect.bisect_left(dates, date)
    if i == 0:
        return None   # every known date is after `date` — no prior anchor
    return history[dates[i - 1]].get("close")


def period_return_pct(history: dict[str, dict[str, Any]], start_date: str, end_date: str) -> float | None:
    """Buy-and-hold TAIEX return over [start_date, end_date], as a fraction
    (0.0224 == +2.24%). None if either endpoint can't be resolved."""
    c0 = as_of_close(history, start_date)
    c1 = as_of_close(history, end_date)
    if c0 is None or c1 is None or c0 == 0:
        return None
    return (c1 - c0) / c0
