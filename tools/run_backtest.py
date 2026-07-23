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

from core.benchmark import period_return_pct        # noqa: E402
from core.hashing import canonical_sha256          # noqa: E402
from core.paper_trading import run_backtest          # noqa: E402
from core.strategies import ALL_STRATEGIES, STRATEGY_B  # noqa: E402

REPORTS = _AI_STOCK / "reports"
OUT_DIR = REPORTS / "backtest"
TAIEX_HISTORY_FILE = _AI_STOCK / "data" / "taiex_history.json"
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


def _load_backfill_snapshots() -> list[dict]:
    """讀 data/backfill/snapshots/ 下的歷史重建快照(實驗用,不污染主檔)。"""
    backfill_dir = _AI_STOCK / "data" / "backfill" / "snapshots"
    if not backfill_dir.is_dir():
        return []
    files = [f for f in glob.glob(str(backfill_dir / "*.json"))
             if _ISO.match(os.path.basename(f))]
    snaps = []
    for f in sorted(files):
        try:
            snaps.append(json.loads(pathlib.Path(f).read_text(encoding="utf-8")))
        except Exception:
            pass
    return snaps


def _load_taiex_history() -> dict[str, dict]:
    """{date: {close, change, change_pct, source}} from data/taiex_history.json.

    Missing/corrupt file → {} (benchmark/alpha fields stay None; the backtest
    itself never depends on this — R4 is additive, not a hard requirement).
    """
    if not TAIEX_HISTORY_FILE.is_file():
        return {}
    try:
        return json.loads(TAIEX_HISTORY_FILE.read_text(encoding="utf-8")).get("dates", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _enrich_with_benchmark(payload: dict, taiex_history: dict[str, dict]) -> None:
    """R4 (2.3): 每筆交易記同期大盤報酬與超額報酬 + 整體 alpha 統計.

    Mutates `payload` in place (post-processing on the already-serialized
    result dict — core/paper_trading.py stays a pure function untouched by
    this; core/benchmark.py holds the actual lookup/return-calc logic).
    """
    excess: list[float] = []
    for t in payload["trades"]:
        bret = period_return_pct(taiex_history, t["entry_date"], t["exit_date"])
        if bret is None:
            t["benchmark_return_pct"] = None
            t["excess_return_pct"] = None
            continue
        bret = round(bret, 4)
        ex = round(t["return_pct"] - bret, 4)
        t["benchmark_return_pct"] = bret
        t["excess_return_pct"] = ex
        excess.append(ex)

    lo, hi = payload["date_range"]
    period_bench = period_return_pct(taiex_history, lo, hi) if lo and hi else None
    alpha = {
        "trades_with_benchmark": len(excess),
        "trades_total": len(payload["trades"]),
        "avg_excess_return": round(sum(excess) / len(excess), 4) if excess else None,
        "period_buy_hold_return": round(period_bench, 4) if period_bench is not None else None,
        "note": ("avg_excess_return = 策略平均報酬 − 同期(進場↔出場)大盤買入持有報酬"
                 "(逐筆);period_buy_hold_return = 整段回測期間(date_range)大盤買入持有"
                 "報酬,供對照——回答「策略總報酬是 alpha 還是 beta」看兩者相對大小。"),
    }
    payload.setdefault("summary", {})["alpha"] = alpha


def _regime_index(snaps: list[dict]) -> dict[str, dict]:
    """{date: 落地體制值} — 只收「至少有一個 obs_market_* 落地」的日期(R5:讀落地,
    不重算)。內部 pulse 僅 2026-07-08 起才有這些欄,故多數歷史日缺 → 不入索引,
    對應交易記 None(歸入「未標記」體制組)。"""
    idx: dict[str, dict] = {}
    for s in snaps:
        d = s.get("date")
        if not d:
            continue
        breadth = s.get("obs_market_breadth")
        regime = s.get("obs_market_regime")
        temp = s.get("obs_market_temperature")
        if not (breadth or regime or temp):
            continue
        idx[d] = {
            "breadth": (breadth or {}).get("breadth"),
            "regime": (regime or {}).get("regime_label_en"),
            "regime_zh": (regime or {}).get("regime_label_zh"),
            "temperature_level": (temp or {}).get("temperature_level"),
        }
    return idx


def _enrich_with_regime(payload: dict, snaps: list[dict]) -> None:
    """2.4 體制標記(裁定 R5:讀落地不重算)。

    為每筆交易記進場當日(entry_date)的落地 obs_market_breadth/regime/temperature
    值(t["regime"]),並輸出分體制績效表(summary["by_regime"])。純後處理:
    core/paper_trading.py 維持純函數,體制值來自已落地的快照,不在此重算。
    """
    idx = _regime_index(snaps)
    buckets: dict[str, list[float]] = {}
    for t in payload["trades"]:
        info = idx.get(t["entry_date"])
        t["regime"] = info                      # None 或落地體制 dict
        label = (info or {}).get("regime") or "unlabeled"
        buckets.setdefault(label, []).append(t.get("return_pct") or 0.0)

    by_regime: dict[str, dict] = {}
    for label in sorted(buckets):
        rets = buckets[label]
        n = len(rets)
        wins = sum(1 for r in rets if r > 0)
        by_regime[label] = {
            "trades": n,
            "win_rate": round(wins / n, 4) if n else None,
            "avg_return": round(sum(rets) / n, 4) if n else None,
        }
    payload.setdefault("summary", {})["by_regime"] = {
        "note": ("進場當日落地體制(obs_market_regime.regime_label_en)分組毛平均報酬;"
                 "unlabeled = 該進場日快照無 obs_market_*(內部 pulse 僅 7/08 起)。"
                 "R5:讀落地值,不重算。"),
        "groups": by_regime,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maitreya paper-trading backtest")
    ap.add_argument("--strategy", default=STRATEGY_B.name, choices=list(ALL_STRATEGIES))
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--latest-only", action="store_true",
                    help="只寫 <strategy>_latest.json(供 viewer 讀取);不留歷史檔。")
    ap.add_argument("--source", default="main",
                    help="快照來源:main(預設,讀 reports/*.json)或 backfill"
                         "(讀 data/backfill/snapshots/*.json,僅做歷史回測用)。")
    args = ap.parse_args(argv)

    strategy = ALL_STRATEGIES[args.strategy]
    if args.source == "backfill":
        snaps = _load_backfill_snapshots()
    else:
        snaps = _load_snapshots()
    if not snaps:
        print(f"[backtest] no snapshots found for source={args.source}", file=sys.stderr)
        return 1
    result = run_backtest(snaps, strategy)

    s = result.summary
    print(f"[backtest] {strategy.name} ({strategy.zh}) | {result.date_range[0]}→{result.date_range[1]}",
          file=sys.stderr)
    print(f"[backtest] trades={s.get('trades')} win_rate={s.get('win_rate')} "
          f"avg_return={s.get('avg_return')} median={s.get('median_return')} "
          f"max_dd={s.get('max_drawdown')} avg_hold={s.get('avg_holding_days')}d", file=sys.stderr)
    if s.get("exit_reasons"):
        print(f"[backtest] exit_reasons={s['exit_reasons']}", file=sys.stderr)

    payload = result.as_dict()
    # provenance 標記(viewer 顯示用)
    payload["_source"] = args.source
    _enrich_with_benchmark(payload, _load_taiex_history())
    a = payload["summary"]["alpha"]
    print(f"[backtest] alpha vs TAIEX: avg_excess_return={a['avg_excess_return']} "
          f"(n={a['trades_with_benchmark']}/{a['trades_total']}) "
          f"period_buy_hold={a['period_buy_hold_return']}", file=sys.stderr)

    _enrich_with_regime(payload, snaps)   # 2.4 體制標記(R5:讀落地不重算)
    rg = payload["summary"]["by_regime"]["groups"]
    print(f"[backtest] by_regime: " + " | ".join(
        f"{k}:{v['trades']}筆 avg={v['avg_return']}" for k, v in rg.items()), file=sys.stderr)

    rz = payload["summary"].get("realized", {})
    uz = payload["summary"].get("unrealized", {})
    print(f"[backtest] realized(3.4): n={rz.get('trades')} avg={rz.get('avg_return')} "
          f"net={rz.get('net',{}).get('avg_return')} | unrealized: n={uz.get('trades')} "
          f"avg={uz.get('avg_return')} | independent_tickers={payload['summary'].get('independent_tickers')}",
          file=sys.stderr)

    if not args.no_write:
        out_dir = OUT_DIR if args.source == "main" else OUT_DIR / "backfill"
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.latest_only:
            out = out_dir / f"{strategy.name}_latest.json"
        else:
            lo, hi = result.date_range
            out = out_dir / f"{strategy.name}_{lo}_{hi}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        sha = canonical_sha256(payload)
        (out.with_suffix(".json.sha256")).write_text(sha + "\n", encoding="utf-8")
        print(f"[backtest] wrote {out.relative_to(_AI_STOCK)}  {sha[:24]}…", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
