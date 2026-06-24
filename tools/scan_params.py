"""tools/scan_params.py — parameter sweep over the backtest engine.

Answers the spec's calibration questions (§3) by running the deterministic
engine across a range of one StrategyConfig parameter and tabulating the result.
Default: Strategy B `entry_streak_min` ∈ {3,4,5} — spec Q2 (連買3 初段 vs 連買5 末段).

Usage:
    python -m tools.scan_params                                  # B entry_streak_min 3,4,5
    python -m tools.scan_params --strategy momentum_continuation --param trailing_stop_pct --values 0.05,0.08,0.12
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.hashing import canonical_sha256          # noqa: E402
from core.paper_trading import run_backtest          # noqa: E402
from core.strategies import ALL_STRATEGIES, STRATEGY_B  # noqa: E402
from tools.run_backtest import _load_snapshots, OUT_DIR  # noqa: E402


def scan(snapshots, strategy, param: str, values: list) -> dict:
    rows = []
    for v in values:
        cfg = dataclasses.replace(strategy, **{param: v})
        res = run_backtest(snapshots, cfg)
        s = res.summary
        rows.append({"value": v, **{k: s.get(k) for k in
                    ("trades", "win_rate", "avg_return", "median_return",
                     "sharpe_per_trade", "avg_holding_days", "max_drawdown")}})
    return {
        "strategy": strategy.name,
        "param": param,
        "date_range": [snapshots[0].get("date", ""), snapshots[-1].get("date", "")] if snapshots else ["", ""],
        "rows": rows,
    }


def _coerce(raw: str):
    try:
        return int(raw) if "." not in raw else float(raw)
    except ValueError:
        return raw


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest parameter sweep")
    ap.add_argument("--strategy", default=STRATEGY_B.name, choices=list(ALL_STRATEGIES))
    ap.add_argument("--param", default="entry_streak_min")
    ap.add_argument("--values", default="3,4,5")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    values = [_coerce(x.strip()) for x in args.values.split(",")]
    strategy = ALL_STRATEGIES[args.strategy]
    snaps = _load_snapshots()
    out = scan(snaps, strategy, args.param, values)

    print(f"[scan] {strategy.name} · {args.param} · {out['date_range'][0]}→{out['date_range'][1]}", file=sys.stderr)
    print(f"  {'value':>8} | {'trades':>6} | {'win':>6} | {'avg_ret':>8} | {'median':>8} | {'maxDD':>7} | {'hold':>5}", file=sys.stderr)
    for r in out["rows"]:
        def f(x, pct=False):
            if x is None:
                return "—"
            return f"{x:.1%}" if pct else (f"{x}")
        print(f"  {str(r['value']):>8} | {f(r['trades']):>6} | {f(r['win_rate'],1):>6} | "
              f"{f(r['avg_return'],1):>8} | {f(r['median_return'],1):>8} | "
              f"{f(r['max_drawdown'],1):>7} | {f(r['avg_holding_days']):>5}", file=sys.stderr)

    if not args.no_write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"scan_{strategy.name}_{args.param}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        (path.with_suffix(".json.sha256")).write_text(canonical_sha256(out) + "\n", encoding="utf-8")
        print(f"[scan] wrote {path.relative_to(_AI_STOCK)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
