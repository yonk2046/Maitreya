"""tools/backfill_range.py — 歷史快照重建沙盒(SANDBOX,絕不污染主檔)

目的:用 TWSE 歷史 API(T86 三大法人 + STOCK_DAY_ALL 開盤 + TDCC 週資料)
回推某段日期的「重建版」快照,寫入 data/backfill/snapshots/<date>.json,
供 `python -m tools.run_backtest --source=backfill` 跑歷史回測。

⚠ 已知限制(寫死備忘):
    1. Fubon 分點(主力排名 ZGK_F)無歷史 API → mainForceBuy 退化為 T86 自營商代理
       → A 策略(籌碼錨定)結果失真。建議只看 B 策略(動能延續)的回測。
    2. 重建快照 schema 與 main 一致(便於 backtest 引擎共用),但加上
       `_provenance: "historical_reconstruction"` 標記,viewer/replay 可辨識。
    3. 永遠不寫入 data/snapshots/、reports/<date>.json、reports/_raw_archive/。
       永遠不更新 reports/index.json。
    4. 不參與 verify_all_replay 鏈(獨立沙盒)。

用法:
    python -m tools.backfill_range --from 2026-04-01 --to 2026-05-25
    python -m tools.backfill_range --from 2026-04-01 --to 2026-05-25 --force  # 覆寫已存在
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
_PROJECT_ROOT = _AI_STOCK.parent  # SCD engine/
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

# 沙盒輸出位置(獨立於 main archive)
BACKFILL_ROOT = _AI_STOCK / "data" / "backfill"
BACKFILL_HISTORY = BACKFILL_ROOT / "history"     # fetch_history 的原始輸出(JSON)
BACKFILL_SNAPS = BACKFILL_ROOT / "snapshots"      # 重建後的快照
BACKFILL_STAGING = BACKFILL_ROOT / "staging"      # 每日 adapter 工作區


def _trading_days(start: str, end: str) -> list[str]:
    """ISO 日期區間內所有平日(週一~五),不含週末和假日(後者由 T86 fetch 自然回傳空)。"""
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    if a > b:
        a, b = b, a
    out = []
    cur = a
    while cur <= b:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    return out


def _build_staging(date_iso: str, history_data: dict) -> pathlib.Path:
    """把 history/<date>.json 重新包裝成 staging/<date>/today.json + 空 branches/。"""
    stage = BACKFILL_STAGING / date_iso
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "data").mkdir(exist_ok=True)
    (stage / "data" / "branches").mkdir(exist_ok=True)  # 空目錄(無 Fubon 歷史)
    (stage / "data" / "today.json").write_text(
        json.dumps(history_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stage


def _load_prior_backfill_snaps(date_iso: str, window: int = 30) -> list[dict]:
    """從 BACKFILL_SNAPS 撈該日期之前 window 天的快照(供 weakening_profile)。"""
    if not BACKFILL_SNAPS.is_dir():
        return []
    target = dt.date.fromisoformat(date_iso)
    out = []
    for f in sorted(BACKFILL_SNAPS.glob("*.json")):
        try:
            d = dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d >= target:
            continue
        if (target - d).days > window:
            continue
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def _build_one(date_iso: str, force: bool = False) -> dict:
    """單日:fetch_history → adapt → ingest → 寫入 backfill/snapshots/<date>.json。"""
    from tools import fetch_history
    from data.adapters.legacy import adapt_legacy
    from core.ingest import ingest
    import yaml

    out_path = BACKFILL_SNAPS / f"{date_iso}.json"
    if out_path.is_file() and not force:
        return {"date": date_iso, "status": "skip_exists", "path": str(out_path)}

    # --- Step 1: fetch T86 + TDCC 歷史(寫到 BACKFILL_HISTORY,不污染 data/history)---
    # 借用 fetch_history 邏輯,但把輸出重定向。最簡作法:讓 fetch_history 跑完寫到
    # data/history/<date>.json,然後我們搬到 BACKFILL_HISTORY。
    main_history = _AI_STOCK / "data" / "history" / f"{date_iso}.json"
    backfill_hist = BACKFILL_HISTORY / f"{date_iso}.json"
    BACKFILL_HISTORY.mkdir(parents=True, exist_ok=True)

    if not backfill_hist.is_file():
        try:
            fetch_history.run(date_iso)
        except Exception as e:
            return {"date": date_iso, "status": "fetch_failed", "error": str(e)}
        if not main_history.is_file():
            return {"date": date_iso, "status": "no_history_data"}
        # 搬到沙盒位置(主檔 data/history/ 由 fetch_history 創建,
        # 它本身就是「歷史補抓」目錄,不算主要產線。但仍搬走以避免後續被 main pipeline 誤用)
        backfill_hist.write_text(main_history.read_text(encoding="utf-8"), encoding="utf-8")

    history_data = json.loads(backfill_hist.read_text(encoding="utf-8"))

    # --- Step 2: 包成 staging,跑 legacy adapter ---
    stage = _build_staging(date_iso, history_data)
    paths_override = {
        "root":         stage,
        "today_json":   stage / "data" / "today.json",
        "branches_dir": stage / "data" / "branches",
        "snapshots":    stage / "data" / "snapshots",   # 不會被寫到,只是 paths 契約
    }
    adapter_out = adapt_legacy(date_iso, paths_override=paths_override)

    # --- Step 3: ingest + 接 prior 快照(供 weakening 連續性)---
    config = yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    prior_snaps = _load_prior_backfill_snaps(date_iso)
    prior_idx = {s.get("report_date") or s.get("date"): s.get("sha256", "sha256:" + "0" * 64)
                 for s in prior_snaps if (s.get("report_date") or s.get("date"))}

    snapshot = ingest(
        adapter_out,
        config,
        repo_root=_AI_STOCK,
        prior_snapshots=prior_idx,
        prior_snap_objects=prior_snaps,
    )

    # --- Step 4: 標記為 backfill provenance(供 viewer/replay 辨識)---
    snapshot["_provenance"] = "historical_reconstruction"
    snapshot["_backfill_note"] = (
        "Fubon 分點主力無歷史 → mainForceBuy 退化為 T86 自營商代理。"
        "建議只看 B 策略(動能延續)。不參與 verify_all_replay。"
    )

    BACKFILL_SNAPS.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"date": date_iso, "status": "ok", "path": str(out_path.relative_to(_AI_STOCK))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="重建歷史快照沙盒(獨立於 main archive,僅供 backtest 使用)",
    )
    ap.add_argument("--from", dest="date_from", required=True, help="起始日 YYYY-MM-DD")
    ap.add_argument("--to",   dest="date_to",   required=True, help="結束日 YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的 backfill snapshot")
    args = ap.parse_args(argv)

    days = _trading_days(args.date_from, args.date_to)
    print(f"[backfill] 計畫重建 {len(days)} 個交易日:{days[0]} → {days[-1]}", file=sys.stderr)
    print(f"[backfill] 沙盒輸出:{BACKFILL_SNAPS.relative_to(_AI_STOCK)}/", file=sys.stderr)
    print(f"[backfill] ⚠ 已知限制:mainForceBuy 為 T86 自營商代理(無 Fubon 歷史),"
          f"建議只看 B 策略回測。", file=sys.stderr)

    ok_n, skip_n, fail_n = 0, 0, 0
    for d in days:
        res = _build_one(d, force=args.force)
        status = res["status"]
        if status == "ok":
            ok_n += 1
            print(f"  ✓ {d}  {res.get('path','')}", file=sys.stderr)
        elif status.startswith("skip"):
            skip_n += 1
            print(f"  · {d}  (已存在,跳過)", file=sys.stderr)
        else:
            fail_n += 1
            print(f"  ✗ {d}  {status}  {res.get('error','')}", file=sys.stderr)

    print(f"\n[backfill] 完成。新建 {ok_n} 個,跳過 {skip_n} 個,失敗 {fail_n} 個。",
          file=sys.stderr)
    print(f"[backfill] 跑回測:python -m tools.run_backtest --source=backfill "
          f"--strategy momentum_continuation", file=sys.stderr)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
