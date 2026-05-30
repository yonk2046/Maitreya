"""Pure, deterministic temporal metric primitives.

These functions take simple Python sequences and return scalar/dict
summaries. No I/O. No file access. No external state. Identical inputs
always produce identical outputs.

Conventions:
  - `values: list[float | int | None]`   numeric series (Nones allowed)
  - `presences: list[bool]`              True if observation existed on day i
  - `states: list[Any]`                  hashable per-day states (or None)

Empty inputs return safe defaults (None / 0 / 0.0 / empty list).
"""
from __future__ import annotations

from typing import Any, Hashable


# ---------------------------------------------------------------------------
# Differences
# ---------------------------------------------------------------------------

def velocity(values: list[float | int | None]) -> float | None:
    """First difference between the LAST two observed values.

    Skips trailing Nones to find the most recent real pair. Returns None if
    fewer than two real values are available.
    """
    real = [v for v in values if v is not None]
    if len(real) < 2:
        return None
    return float(real[-1]) - float(real[-2])


def acceleration(values: list[float | int | None]) -> float | None:
    """Second difference between the LAST three observed values."""
    real = [v for v in values if v is not None]
    if len(real) < 3:
        return None
    return (float(real[-1]) - float(real[-2])) - (float(real[-2]) - float(real[-3]))


def mean(values: list[float | int | None]) -> float | None:
    real = [float(v) for v in values if v is not None]
    if not real:
        return None
    return sum(real) / len(real)


def stdev(values: list[float | int | None]) -> float | None:
    """Population standard deviation. None if <2 real values."""
    real = [float(v) for v in values if v is not None]
    n = len(real)
    if n < 2:
        return None
    m = sum(real) / n
    return (sum((v - m) ** 2 for v in real) / n) ** 0.5


# ---------------------------------------------------------------------------
# Run-length analysis over presence/state sequences
# ---------------------------------------------------------------------------

def runs(values: list[Hashable]) -> list[tuple[Hashable, int]]:
    """Return [(value, length), ...] of contiguous runs. Pure RLE."""
    if not values:
        return []
    out: list[tuple[Hashable, int]] = []
    cur = values[0]
    n = 1
    for v in values[1:]:
        if v == cur:
            n += 1
        else:
            out.append((cur, n))
            cur = v
            n = 1
    out.append((cur, n))
    return out


def persistence(presences: list[bool]) -> dict[str, Any]:
    """Run-length analysis on a boolean presence sequence.

    Returns:
      total_days, present_days, absent_days,
      longest_present_run, longest_absent_run,
      current_run_value, current_run_length,
      run_count_present, run_count_absent,
      first_present_index, last_present_index
    """
    n = len(presences)
    if n == 0:
        return {
            "total_days": 0, "present_days": 0, "absent_days": 0,
            "longest_present_run": 0, "longest_absent_run": 0,
            "current_run_value": None, "current_run_length": 0,
            "run_count_present": 0, "run_count_absent": 0,
            "first_present_index": None, "last_present_index": None,
        }
    rs = runs(presences)
    longest_present = max((ln for v, ln in rs if v), default=0)
    longest_absent = max((ln for v, ln in rs if not v), default=0)
    cur_val, cur_len = rs[-1]
    runs_present = sum(1 for v, _ in rs if v)
    runs_absent = sum(1 for v, _ in rs if not v)
    first_present = next((i for i, v in enumerate(presences) if v), None)
    last_present = next((n - 1 - i for i, v in enumerate(reversed(presences)) if v), None)
    return {
        "total_days":          n,
        "present_days":        sum(1 for v in presences if v),
        "absent_days":         sum(1 for v in presences if not v),
        "longest_present_run": longest_present,
        "longest_absent_run":  longest_absent,
        "current_run_value":   cur_val,
        "current_run_length":  cur_len,
        "run_count_present":   runs_present,
        "run_count_absent":    runs_absent,
        "first_present_index": first_present,
        "last_present_index":  last_present,
    }


# ---------------------------------------------------------------------------
# State-change metrics
# ---------------------------------------------------------------------------

def transition_frequency(states: list[Any]) -> int:
    """Number of times the state value changes between consecutive elements.

    None-to-something or something-to-None counts as a transition.
    """
    if len(states) < 2:
        return 0
    return sum(1 for a, b in zip(states, states[1:]) if a != b)


def state_volatility(states: list[Any]) -> float:
    """Transitions normalized to [0, 1]: transitions / max_possible_transitions.

    `max_possible_transitions` = max(len(states) - 1, 1) to avoid div-by-zero.
    A sequence that flips every step → 1.0; constant sequence → 0.0.
    """
    if len(states) < 2:
        return 0.0
    return transition_frequency(states) / float(len(states) - 1)


def transitions(states: list[Any], dates: list[str] | None = None) -> list[dict[str, Any]]:
    """List of {index, date?, from, to} for every transition."""
    out: list[dict[str, Any]] = []
    for i, (a, b) in enumerate(zip(states, states[1:]), start=1):
        if a != b:
            row: dict[str, Any] = {"index": i, "from": a, "to": b}
            if dates is not None and i < len(dates):
                row["date"] = dates[i]
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# Coverage / continuity / stability
# ---------------------------------------------------------------------------

def continuity_score(presences: list[bool]) -> float:
    """Fraction of days the observation was present. 1.0 = present every day."""
    if not presences:
        return 0.0
    return sum(1 for v in presences if v) / float(len(presences))


def streak_stability(presences: list[bool]) -> float:
    """How concentrated the presences are into a single contiguous run.

    Formula: 1 - (number_of_present_runs - 1) / max(number_of_present_runs, 1)
    Equivalently: 1/number_of_present_runs if any presences else 1.0.

    1.0 → one contiguous run (or zero presence — neutral).
    0.5 → two separate runs.
    0.33 → three runs. Etc.
    """
    pres_run_count = sum(1 for v, _ in runs(presences) if v)
    if pres_run_count == 0:
        return 1.0   # vacuously stable (no presence to be unstable about)
    return 1.0 / pres_run_count


def current_streak(presences: list[bool]) -> int:
    """Consecutive True values at the tail of the sequence."""
    n = 0
    for v in reversed(presences):
        if v:
            n += 1
        else:
            break
    return n


def max_streak(presences: list[bool]) -> int:
    return max((ln for v, ln in runs(presences) if v), default=0)
