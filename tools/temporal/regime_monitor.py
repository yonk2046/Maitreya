"""Market-wide descriptive observations per snapshot and across the window.

DESCRIPTIVE ONLY. No regime LABELS. No "bullish/bearish" claims. No
predictions. The output is a set of measurements about each snapshot and
how those measurements moved between snapshots — what someone can look at
and decide for themselves.

Per-snapshot observations:
  universe_size
  positive_count / negative_count / flat_count / unknown_count (from change_pct)
  breadth_positive  = positive_count / known_count
  breadth_negative  = negative_count / known_count
  median_change_pct
  mean_change_pct
  top5_branch_coverage = stocks with non-empty top5_branches / universe_size
  main_force_buy_known = stocks with main_force_buy not None / universe_size

Window deltas:
  universe_size_delta
  new_entrants_count
  leavers_count
  breadth_positive_delta
  carry_rate = continuing_tickers / max(prev_universe, 1)

CLI:
    python -m tools.temporal.regime_monitor
    python -m tools.temporal.regime_monitor --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass

from tools.temporal._loader import load_snapshot, real_dates


@dataclass
class SnapshotObservation:
    date: str
    universe_size: int
    positive_count: int
    negative_count: int
    flat_count: int
    unknown_count: int
    breadth_positive: float | None
    breadth_negative: float | None
    median_change_pct: float | None
    mean_change_pct: float | None
    top5_branch_coverage: float
    main_force_buy_known: float


@dataclass
class WindowDelta:
    date: str
    prior_date: str
    universe_size_delta: int
    new_entrants_count: int
    leavers_count: int
    carry_rate: float
    breadth_positive_delta: float | None


def _observe(date_key: str) -> SnapshotObservation:
    snap = load_snapshot(date_key)
    stocks = snap.get("stocks", [])
    n = len(stocks)
    pos = neg = flat = unk = 0
    chgs: list[float] = []
    top5_covered = 0
    mfb_known = 0
    for s in stocks:
        cp = s.get("change_pct")
        if cp is None:
            unk += 1
        elif cp > 0:
            pos += 1; chgs.append(float(cp))
        elif cp < 0:
            neg += 1; chgs.append(float(cp))
        else:
            flat += 1; chgs.append(float(cp))
        if s.get("top5_branches"):
            top5_covered += 1
        if s.get("main_force_buy") is not None:
            mfb_known += 1
    known = pos + neg + flat
    return SnapshotObservation(
        date=date_key,
        universe_size=n,
        positive_count=pos,
        negative_count=neg,
        flat_count=flat,
        unknown_count=unk,
        breadth_positive=(pos / known) if known else None,
        breadth_negative=(neg / known) if known else None,
        median_change_pct=(statistics.median(chgs) if chgs else None),
        mean_change_pct=(sum(chgs) / len(chgs) if chgs else None),
        top5_branch_coverage=(top5_covered / n) if n else 0.0,
        main_force_buy_known=(mfb_known / n) if n else 0.0,
    )


def observe_all() -> list[SnapshotObservation]:
    return [_observe(d) for d in real_dates()]


def deltas() -> list[WindowDelta]:
    dates = real_dates()
    if len(dates) < 2:
        return []
    obs = [_observe(d) for d in dates]
    out: list[WindowDelta] = []
    for i in range(1, len(dates)):
        prev = obs[i - 1]
        cur = obs[i]
        # universe set delta
        prev_u = {s["ticker"] for s in load_snapshot(dates[i - 1]).get("stocks", [])}
        cur_u = {s["ticker"] for s in load_snapshot(dates[i]).get("stocks", [])}
        new = cur_u - prev_u
        lost = prev_u - cur_u
        carry = len(prev_u & cur_u) / max(len(prev_u), 1)
        bd = None
        if prev.breadth_positive is not None and cur.breadth_positive is not None:
            bd = round(cur.breadth_positive - prev.breadth_positive, 4)
        out.append(WindowDelta(
            date=cur.date,
            prior_date=prev.date,
            universe_size_delta=cur.universe_size - prev.universe_size,
            new_entrants_count=len(new),
            leavers_count=len(lost),
            carry_rate=round(carry, 4),
            breadth_positive_delta=bd,
        ))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_float(v: float | None, digits: int = 3) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _print_observations(rows: list[SnapshotObservation]) -> None:
    if not rows:
        print("(no observations)")
        return
    print("# Per-snapshot observations")
    headers = ["date", "univ", "pos", "neg", "flat", "unk", "bdPos", "bdNeg",
               "medChg%", "meanChg%", "top5cov", "mfbKnown"]
    widths = [11, 4, 4, 4, 4, 4, 6, 6, 8, 8, 7, 8]
    print("  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        vals = [
            r.date, r.universe_size, r.positive_count, r.negative_count,
            r.flat_count, r.unknown_count,
            _fmt_float(r.breadth_positive), _fmt_float(r.breadth_negative),
            _fmt_float(r.median_change_pct, 2), _fmt_float(r.mean_change_pct, 2),
            f"{r.top5_branch_coverage:.2f}", f"{r.main_force_buy_known:.2f}",
        ]
        print("  ".join(f"{str(v):<{w}}" for v, w in zip(vals, widths)))


def _print_deltas(rows: list[WindowDelta]) -> None:
    if not rows:
        print("(no deltas)")
        return
    print("\n# Day-over-day deltas")
    headers = ["date", "prior", "univΔ", "new", "lost", "carry", "bdPosΔ"]
    widths = [11, 11, 6, 4, 4, 6, 8]
    print("  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        vals = [r.date, r.prior_date, r.universe_size_delta, r.new_entrants_count,
                r.leavers_count, f"{r.carry_rate:.3f}",
                _fmt_float(r.breadth_positive_delta, 3)]
        print("  ".join(f"{str(v):<{w}}" for v, w in zip(vals, widths)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Market-wide descriptive observations.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    obs = observe_all()
    ds = deltas()
    if args.json:
        json.dump(
            {"observations": [asdict(o) for o in obs],
             "deltas":       [asdict(d) for d in ds]},
            sys.stdout, indent=2, ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        _print_observations(obs)
        _print_deltas(ds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
