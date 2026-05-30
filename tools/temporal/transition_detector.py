"""State-transition detection across consecutive snapshots.

Three classes of transitions are observable at P3a:

  TIER transition         — `tier` value changes between snapshots.
                            At P3a this is empty (every record is IGNORE);
                            wired for P3b.
  PRESENCE transition     — ticker appears (ENTER), disappears (LEAVE),
                            or reappears after an absence (REAPPEAR).
  CHANGE_PCT_SIGN flip    — change_pct sign flips (e.g., - → +).
                            Useful proxy for short-term reversals.

OBSERVATIONAL ONLY. No directional claims, no recommendation labels.

CLI:
    python -m tools.temporal.transition_detector
    python -m tools.temporal.transition_detector --kind tier
    python -m tools.temporal.transition_detector --ticker 2330 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

from tools.temporal._loader import load_snapshot, real_dates


@dataclass
class Transition:
    date: str          # the date the transition was OBSERVED (i.e., snapshot N where state differs from N-1)
    prior_date: str    # snapshot N-1
    ticker: str
    kind: str          # "TIER" | "PRESENCE" | "CHANGE_PCT_SIGN"
    from_state: str | None
    to_state: str | None
    notes: str = ""


def _sign(x: float | int | None) -> str | None:
    if x is None:
        return None
    if x > 0:
        return "+"
    if x < 0:
        return "-"
    return "0"


def detect(
    kinds: tuple[str, ...] = ("TIER", "PRESENCE", "CHANGE_PCT_SIGN"),
    ticker_filter: str | None = None,
) -> list[Transition]:
    dates = real_dates()
    if len(dates) < 2:
        return []
    transitions: list[Transition] = []

    prev_snap = load_snapshot(dates[0])
    prev_by_t: dict[str, dict] = {s["ticker"]: s for s in prev_snap.get("stocks", [])}

    for i in range(1, len(dates)):
        d = dates[i]
        pd_ = dates[i - 1]
        snap = load_snapshot(d)
        cur_by_t = {s["ticker"]: s for s in snap.get("stocks", [])}

        all_t = set(prev_by_t.keys()) | set(cur_by_t.keys())
        if ticker_filter:
            all_t = {t for t in all_t if t == ticker_filter}

        for t in sorted(all_t):
            prev_rec = prev_by_t.get(t)
            cur_rec = cur_by_t.get(t)

            # PRESENCE
            if "PRESENCE" in kinds:
                if prev_rec is None and cur_rec is not None:
                    # was it ever seen before this point?
                    transitions.append(Transition(
                        date=d, prior_date=pd_, ticker=t,
                        kind="PRESENCE", from_state="absent", to_state="present",
                        notes="ENTER",
                    ))
                elif prev_rec is not None and cur_rec is None:
                    transitions.append(Transition(
                        date=d, prior_date=pd_, ticker=t,
                        kind="PRESENCE", from_state="present", to_state="absent",
                        notes="LEAVE",
                    ))

            # TIER (P3a: always IGNORE → IGNORE, so nothing emitted unless
            # one side is absent, but we treat absent as "no tier change")
            if "TIER" in kinds and prev_rec is not None and cur_rec is not None:
                pt = prev_rec.get("tier")
                ct = cur_rec.get("tier")
                if pt != ct:
                    transitions.append(Transition(
                        date=d, prior_date=pd_, ticker=t,
                        kind="TIER", from_state=pt, to_state=ct,
                        notes="",
                    ))

            # CHANGE_PCT_SIGN
            if "CHANGE_PCT_SIGN" in kinds and prev_rec is not None and cur_rec is not None:
                ps = _sign(prev_rec.get("change_pct"))
                cs = _sign(cur_rec.get("change_pct"))
                if ps is not None and cs is not None and ps != cs:
                    transitions.append(Transition(
                        date=d, prior_date=pd_, ticker=t,
                        kind="CHANGE_PCT_SIGN", from_state=ps, to_state=cs,
                        notes="",
                    ))

        prev_by_t = cur_by_t

    return transitions


def reappearance_events(min_absence: int = 1) -> list[Transition]:
    """Specialization of PRESENCE that distinguishes ENTER vs. REAPPEAR.

    A REAPPEAR is a present-after-absent transition where the ticker was
    seen at any earlier date. ENTER means first appearance ever.
    """
    dates = real_dates()
    seen_before: set[str] = set()
    absent_count: dict[str, int] = {}   # consecutive absent count per ticker
    out: list[Transition] = []
    prev_present: dict[str, bool] = {}

    for i, d in enumerate(dates):
        snap = load_snapshot(d)
        cur_universe = {s["ticker"] for s in snap.get("stocks", [])}
        for t in sorted(cur_universe | seen_before):
            present_now = t in cur_universe
            present_prev = prev_present.get(t, False)
            if present_now and not present_prev:
                if t in seen_before:
                    # Reappearance — check min_absence threshold
                    if absent_count.get(t, 0) >= min_absence:
                        out.append(Transition(
                            date=d,
                            prior_date=dates[i - 1] if i > 0 else d,
                            ticker=t, kind="PRESENCE",
                            from_state="absent", to_state="present",
                            notes=f"REAPPEAR_after_{absent_count.get(t, 0)}d",
                        ))
                else:
                    out.append(Transition(
                        date=d,
                        prior_date=dates[i - 1] if i > 0 else d,
                        ticker=t, kind="PRESENCE",
                        from_state="absent", to_state="present",
                        notes="ENTER",
                    ))
            if present_now:
                absent_count[t] = 0
                seen_before.add(t)
            else:
                if t in seen_before:
                    absent_count[t] = absent_count.get(t, 0) + 1
            prev_present[t] = present_now
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(rows: list[Transition]) -> None:
    if not rows:
        print("(no transitions)")
        return
    headers = ["date", "prior", "ticker", "kind", "from", "to", "notes"]
    widths  = [11, 11, 8, 17, 8, 8, 24]
    print("  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        vals = [r.date, r.prior_date, r.ticker, r.kind,
                str(r.from_state), str(r.to_state), r.notes]
        print("  ".join(f"{str(v):<{w}}" for v, w in zip(vals, widths)))
    print(f"\n{len(rows)} transition(s)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect state transitions across snapshots.")
    ap.add_argument(
        "--kind", action="append",
        choices=["TIER", "PRESENCE", "CHANGE_PCT_SIGN"],
        help="restrict to one kind (repeat to include multiple)",
    )
    ap.add_argument("--ticker", help="filter to one ticker")
    ap.add_argument("--reappearances", action="store_true",
                    help="emit ENTER vs REAPPEAR events instead of raw PRESENCE")
    ap.add_argument("--min-absence", type=int, default=1,
                    help="(with --reappearances) min consecutive absent days for REAPPEAR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.reappearances:
        rows = reappearance_events(min_absence=args.min_absence)
        if args.ticker:
            rows = [r for r in rows if r.ticker == args.ticker]
    else:
        kinds = tuple(args.kind) if args.kind else ("TIER", "PRESENCE", "CHANGE_PCT_SIGN")
        rows = detect(kinds=kinds, ticker_filter=args.ticker)

    if args.json:
        json.dump([asdict(r) for r in rows], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
