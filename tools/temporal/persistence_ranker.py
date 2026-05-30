"""Rank tickers by temporal persistence instead of static score.

This is NOT a scoring engine. It's a way to ask the archive
"which tickers have been most temporally stable so far?" and get a
deterministic ranking back. No alpha claim. No prediction. Useful for
observing whether persistence correlates with anything once P3b activates.

Rank modes:
  coverage      — sort by appearances / total_days (descending)
  stability     — sort by streak_stability descending (single contiguous run beats many fragments)
  tail_run      — sort by current_streak descending (currently-active runs first)
  composite     — z-score sum across coverage + stability + 1/(transition_freq+1)
                  (descriptive only — NO claim about future performance)

CLI:
    python -m tools.temporal.persistence_ranker
    python -m tools.temporal.persistence_ranker --mode tail_run
    python -m tools.temporal.persistence_ranker --mode composite --top 20 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

from tools.temporal import temporal_metrics as tm
from tools.temporal._loader import load_snapshot, real_dates, universe_for_date


@dataclass
class PersistenceRow:
    ticker: str
    coverage: float           # fraction in [0, 1]
    streak_stability: float
    current_streak: int
    max_streak: int
    transition_frequency: int   # change_pct sign flips
    composite_z: float          # only set when mode=composite; else 0
    appearances: int
    first_seen: str | None
    last_seen: str | None


_VALID_MODES = ("coverage", "stability", "tail_run", "composite")


def _build_rows() -> list[PersistenceRow]:
    dates = real_dates()
    if not dates:
        return []
    universes = [set(universe_for_date(d)) for d in dates]
    seen: set[str] = set().union(*universes) if universes else set()

    # Per-ticker presence + change_pct sign sequence
    sign_seqs: dict[str, list[str | None]] = {t: [] for t in seen}
    for d in dates:
        snap = load_snapshot(d)
        per_t = {s["ticker"]: s for s in snap.get("stocks", [])}
        for t in seen:
            rec = per_t.get(t)
            if rec is None:
                sign_seqs[t].append(None)
                continue
            cp = rec.get("change_pct")
            if cp is None:
                sign_seqs[t].append(None)
            elif cp > 0:
                sign_seqs[t].append("+")
            elif cp < 0:
                sign_seqs[t].append("-")
            else:
                sign_seqs[t].append("0")

    rows: list[PersistenceRow] = []
    for t in sorted(seen):
        presences = [t in u for u in universes]
        first_idx = next((i for i, v in enumerate(presences) if v), None)
        last_idx = next((len(dates) - 1 - i for i, v in enumerate(reversed(presences)) if v), None)
        rows.append(PersistenceRow(
            ticker=t,
            coverage=tm.continuity_score(presences),
            streak_stability=tm.streak_stability(presences),
            current_streak=tm.current_streak(presences),
            max_streak=tm.max_streak(presences),
            transition_frequency=tm.transition_frequency(sign_seqs[t]),
            composite_z=0.0,
            appearances=sum(presences),
            first_seen=dates[first_idx] if first_idx is not None else None,
            last_seen=dates[last_idx] if last_idx is not None else None,
        ))
    return rows


def _zscore_inplace(rows: list[PersistenceRow], attr: str, invert: bool = False) -> dict[str, float]:
    vals = [getattr(r, attr) for r in rows]
    n = len(vals)
    if n == 0:
        return {}
    m = sum(vals) / n
    s = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    if s == 0:
        return {r.ticker: 0.0 for r in rows}
    out = {}
    for r in rows:
        z = (getattr(r, attr) - m) / s
        if invert:
            z = -z
        out[r.ticker] = z
    return out


def rank(mode: str = "coverage") -> list[PersistenceRow]:
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    rows = _build_rows()
    if not rows:
        return []

    if mode == "coverage":
        rows.sort(key=lambda r: (-r.coverage, -r.streak_stability, r.ticker))
    elif mode == "stability":
        rows.sort(key=lambda r: (-r.streak_stability, -r.coverage, r.ticker))
    elif mode == "tail_run":
        rows.sort(key=lambda r: (-r.current_streak, -r.coverage, r.ticker))
    elif mode == "composite":
        # z-scores on coverage, stability, and inverted transition_freq.
        # Sum then re-sort.
        zc = _zscore_inplace(rows, "coverage")
        zs = _zscore_inplace(rows, "streak_stability")
        zt = _zscore_inplace(rows, "transition_frequency", invert=True)
        for r in rows:
            r.composite_z = round(zc[r.ticker] + zs[r.ticker] + zt[r.ticker], 4)
        rows.sort(key=lambda r: (-r.composite_z, r.ticker))
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(rows: list[PersistenceRow], mode: str) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = ["rank", "ticker", "cov", "stab", "cur", "max", "txf", "compZ", "first", "last"]
    widths  = [4,     8,        6,    6,     4,    4,    4,    7,      11,     11]
    print(f"# mode={mode}")
    print("  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for i, r in enumerate(rows, start=1):
        vals = [
            i, r.ticker,
            f"{r.coverage:.3f}",
            f"{r.streak_stability:.3f}",
            r.current_streak, r.max_streak,
            r.transition_frequency,
            f"{r.composite_z:.3f}" if mode == "composite" else "—",
            r.first_seen or "",
            r.last_seen or "",
        ]
        print("  ".join(f"{str(v):<{w}}" for v, w in zip(vals, widths)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rank tickers by temporal persistence.")
    ap.add_argument("--mode", default="coverage", choices=_VALID_MODES)
    ap.add_argument("--top", type=int, default=None, help="show top N rows")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = rank(args.mode)
    if args.top is not None:
        rows = rows[: args.top]
    if args.json:
        json.dump([asdict(r) for r in rows], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_table(rows, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
