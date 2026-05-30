"""Per-ticker persistence analysis across the snapshot archive.

OBSERVATIONAL ONLY. Outputs descriptive temporal properties — no scoring,
no labels, no alpha claims. The columns named `*_proxy` make explicit that
their P3a values stand in for fields that will be measured directly once
P3b scoring activates.

CLI:
    python -m tools.temporal.streak_analyzer
    python -m tools.temporal.streak_analyzer --json
    python -m tools.temporal.streak_analyzer --min-appearances 5
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

from tools.temporal import temporal_metrics as tm
from tools.temporal._loader import (
    load_snapshot,
    real_dates,
    universe_for_date,
)


@dataclass
class StreakRow:
    ticker: str
    appearances: int
    coverage_pct: float          # 0-100
    current_streak: int
    max_streak: int
    streak_stability: float      # 0-1, 1 = one contiguous run
    longest_absent_run: int
    run_count_present: int
    first_seen: str | None
    last_seen: str | None
    # P3a observable proxies (currently main_force_buy is the only signed proxy)
    main_force_buy_persistence: int   # consecutive present days with main_force_buy not None at the tail
    rank_volatility_proxy: float      # 0-1, state_volatility over change_pct sign sequence


def _ticker_observations_packed(
    tickers: list[str],
    dates: list[str],
) -> dict[str, dict[str, dict]]:
    """{ticker: {date: rec}} loaded once per snapshot — O(D+T·D) not O(T·D)."""
    out: dict[str, dict[str, dict]] = {t: {} for t in tickers}
    for d in dates:
        snap = load_snapshot(d)
        for s in snap.get("stocks", []):
            t = s.get("ticker")
            if t in out:
                out[t][d] = s
    return out


def analyze(min_appearances: int = 1) -> list[StreakRow]:
    dates = real_dates()
    if not dates:
        return []
    # union of tickers ever seen
    seen: set[str] = set()
    for d in dates:
        seen.update(universe_for_date(d))
    tickers = sorted(seen)
    packed = _ticker_observations_packed(tickers, dates)

    rows: list[StreakRow] = []
    for t in tickers:
        per_date = packed[t]
        presences = [d in per_date for d in dates]
        if sum(presences) < min_appearances:
            continue

        first_idx = next((i for i, v in enumerate(presences) if v), None)
        last_idx = next((len(dates) - 1 - i for i, v in enumerate(reversed(presences)) if v), None)

        # P3a proxies
        mfb_tail = 0
        for d in reversed(dates):
            rec = per_date.get(d)
            if rec is not None and rec.get("main_force_buy") is not None:
                mfb_tail += 1
            else:
                break

        # rank_volatility proxy: sign of change_pct day-over-day (positive/negative/None)
        chg_signs: list[str | None] = []
        for d in dates:
            rec = per_date.get(d)
            if rec is None:
                chg_signs.append(None)
                continue
            cp = rec.get("change_pct")
            if cp is None:
                chg_signs.append(None)
            elif cp > 0:
                chg_signs.append("+")
            elif cp < 0:
                chg_signs.append("-")
            else:
                chg_signs.append("0")

        rows.append(StreakRow(
            ticker=t,
            appearances=sum(presences),
            coverage_pct=round(100.0 * sum(presences) / len(dates), 2),
            current_streak=tm.current_streak(presences),
            max_streak=tm.max_streak(presences),
            streak_stability=round(tm.streak_stability(presences), 4),
            longest_absent_run=tm.persistence(presences)["longest_absent_run"],
            run_count_present=tm.persistence(presences)["run_count_present"],
            first_seen=dates[first_idx] if first_idx is not None else None,
            last_seen=dates[last_idx]  if last_idx  is not None else None,
            main_force_buy_persistence=mfb_tail,
            rank_volatility_proxy=round(tm.state_volatility(chg_signs), 4),
        ))
    rows.sort(key=lambda r: (-r.appearances, -r.current_streak, r.ticker))
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(rows: list[StreakRow]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = [
        "ticker", "app", "cov%", "cur", "max", "stab", "lonAbs",
        "runs", "first_seen", "last_seen", "mfb_tail", "rank_volP",
    ]
    widths = [8, 4, 6, 4, 4, 6, 6, 5, 11, 11, 9, 9]
    fmt_h = "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    print(fmt_h)
    print("-" * len(fmt_h))
    for r in rows:
        vals = [
            r.ticker,
            r.appearances,
            f"{r.coverage_pct:.1f}",
            r.current_streak,
            r.max_streak,
            f"{r.streak_stability:.3f}",
            r.longest_absent_run,
            r.run_count_present,
            r.first_seen or "",
            r.last_seen or "",
            r.main_force_buy_persistence,
            f"{r.rank_volatility_proxy:.3f}",
        ]
        print("  ".join(f"{str(v):<{w}}" for v, w in zip(vals, widths)))
    print(f"\n{len(rows)} ticker(s)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-appearances", type=int, default=1,
                    help="filter out tickers with fewer than this many appearances")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON to stdout instead of table")
    args = ap.parse_args(argv)
    rows = analyze(min_appearances=args.min_appearances)
    if args.json:
        json.dump([asdict(r) for r in rows], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
