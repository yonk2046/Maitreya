"""tools/run_backtest.py — CLI to run a paper-trading strategy over history.

Loads the committed dated snapshots, runs the deterministic engine, writes
reports/backtest/<strategy>_<start>_<end>.json (+ .sha256), prints a summary.

Usage:
    python -m tools.run_backtest                 # Strategy B over all snapshots
    python -m tools.run_backtest --strategy momentum_continuation
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.hashing import canonical_sha256          # noqa: E402
from core.paper_trading import run_backtest          # noqa: E402
from core.strategies import ALL_STRATEGIES, STRATEGY_B  # noqa: E402

REPORTS = _AI_STOCK / "reports"
OUT_DIR = REPORTS / "backtest"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _load_snapshots() -> list[dict]:
    files = [f for f in glob.glob(str(REPORTS / "*.json")) if _ISO.match(os.path.basename(f))]
    snaps = []
    for f in sorted(files):
        try:
            snaps.append(json.loads(pathlib.Path(f).read_text(encoding="utf-8")))
        except Exception:
            pass
    return snaps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maitreya paper-trading backtest")
    ap.add_argument("--strategy", default=STRATEGY_B.name, choices=list(ALL_STRATEGIES))
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    strategy = ALL_STRATEGIES[args.strategy]
    snaps = _load_snapshots()
    result = run_backtest(snaps, strategy)

    s = result.summary
    print(f"[backtest] {strategy.name} ({strategy.zh}) | {result.date_range[0]}→{result.date_range[1]}",
          file=sys.stderr)
    print(f"[backtest] trades={s.get('trades')} win_rate={s.get('win_rate')} "
          f"avg_return={s.get('avg_return')} median={s.get('median_return')} "
          f"max_dd={s.get('max_drawdown')} avg_hold={s.get('avg_holding_days')}d", file=sys.stderr)
    if s.get("exit_reasons"):
        print(f"[backtest] exit_reasons={s['exit_reasons']}", file=sys.stderr)

    if not args.no_write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        lo, hi = result.date_range
        out = OUT_DIR / f"{strategy.name}_{lo}_{hi}.json"
        payload = result.as_dict()
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        sha = canonical_sha256(payload)
        (out.with_suffix(".json.sha256")).write_text(sha + "\n", encoding="utf-8")
        print(f"[backtest] wrote {out.relative_to(_AI_STOCK)}  {sha[:24]}…", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
