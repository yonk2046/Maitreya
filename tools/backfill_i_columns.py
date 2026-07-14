"""tools/backfill_i_columns.py — P2-W6 I-only 歷史回填(裁定 D-7 選項 A)

把 2026-05-26 → 2026-07-09 的既有快照,以 **backfill 模式(obs_landing=False)**
重建為 1.9.0:只寫 4 個 I 欄(trust_net_buy / prop_net_buy / fii_sell_raw /
main_force_sell_raw)＋既有 raw 重組(weakening / temporal_enrich),**跳過全部
O 引擎**(obs_* / sync_streak / obs_market_*)。每日走 supersede(舊版 hash 留
history[]、current 指向新 1.9.0-I-only 版),1.8.1/1.4.0→1.9.0 epoch 轉移。

為何走 verify 的 replay 路徑(而非 live pipeline):
  回填的輸入一律來自 reports/_raw_archive/<date>/(WORM 封存),**絕不讀
  data/today.json**(現在裝著 live 資料)。本腳本重用 verify_all_replay 的
  `_replay_adapter`(對 archive 跑 adapter)＋ `_gather_lookback` /
  `_load_snap_objects`,再以 obs_landing=False 呼叫 ingest。生成與驗證共用同一
  條 adapter+lookback 程式路徑 → 回填後 verify_all_replay 對這些日子必然重算一致
  (D-7 硬條件:verify 已改為認得 obs_landing 旗標並走 backfill 模式)。

誠實跳過(覆蓋表 P1-worm-backfill-report.md):
  • rollup-only 日(provenance 只有 legacy_rollup、無 legacy_today_json)——
    結構性無 T86/賣方榜,I 欄不存在,跳過(範圍內僅 2026-05-27)。
  • fii_pending 日(t86 空)——trust/prop 誠實缺欄(None),賣方 raw 照回填,
    fii_pending=True(範圍內:05-28 / 05-29 / 06-03 / 06-25)。這些**不跳過**,
    照樣回填「有的 I 欄」。

冪等(裁定 D-7 附帶條件②):重跑不產生第二條 supersede。回填前先把「本次會產出的
  快照」normalize 對比磁碟現版的 replay-invariant hash;若已一致(該日已回填過)→
  no-op 跳過,不再 supersede。

紅線:
  • 2026-07-10 嚴禁回填(颱風假殭屍;範圍終點 = 07-09)。
  • 7/13、7/14 一個 byte 都不碰(超出範圍)。
  • WORM archive 既有檔案不改寫(archive_raw_inputs verify_only=True,只重算不複製)。

用法:
    python -m tools.backfill_i_columns --dry-run     # 只報告,不寫盤
    python -m tools.backfill_i_columns               # 實際回填 + supersede
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import yaml  # noqa: E402

from core.archive import archive_raw_inputs  # noqa: E402
from core.hashing import canonical_sha256, write_sidecar  # noqa: E402
from core.ingest import SCHEMA_VERSION, ingest  # noqa: E402
from core.replay_contract import normalize_for_replay_compare  # noqa: E402
from data.adapters.legacy import legacy_paths  # noqa: E402

# Reuse the verifier's proven replay helpers so generation == verification path.
from tools.run_pipeline import _update_index  # noqa: E402
from tools.verify_all_replay import (  # noqa: E402
    CONFIG_FILE,
    INDEX_FILE,
    RAW_ARCHIVE_DIR,
    REPORTS_DIR,
    _gather_lookback,
    _is_iso_date,
    _load_snap_objects,
    _replay_adapter,
)

# 回填範圍(含端點)。終點 = 2026-07-09(07-10 颱風假殭屍嚴禁回填,見紅線)。
BACKFILL_START = dt.date(2026, 5, 26)
BACKFILL_END = dt.date(2026, 7, 9)

# 硬保護:這些日期永不觸碰,即使邏輯錯誤把它們納入(defence-in-depth)。
FORBIDDEN_DATES = frozenset({"2026-07-10", "2026-07-13", "2026-07-14"})


def _in_range(date_iso: str) -> bool:
    try:
        d = dt.date.fromisoformat(date_iso)
    except ValueError:
        return False
    return BACKFILL_START <= d <= BACKFILL_END


def _is_rollup_only(on_disk_snap: dict) -> bool:
    """True when the snapshot's only raw source is legacy_rollup (no today.json).

    Rollup-only days structurally lack T86 / sell lists → the 4 I columns do not
    exist → honestly skip (C10). legacy_today_json presence is the discriminator.
    """
    prov = on_disk_snap.get("provenance", {}).get("sources", {})
    return "legacy_today_json" not in prov


def _build_backfill_snapshot(date_iso: str, on_disk_snap: dict, cfg: dict,
                             repo_root: pathlib.Path, index: dict) -> dict:
    """Re-ingest `date_iso` from its WORM archive in I-only backfill mode."""
    adapter_out = _replay_adapter(date_iso, on_disk_snap, repo_root)
    window = cfg.get("temporal", {}).get("lookback_window_days", 5)
    lookback = _gather_lookback(date_iso, window, index)
    prior_snap_objects = _load_snap_objects(lookback, REPORTS_DIR)

    snap = ingest(
        adapter_out, cfg, repo_root=str(repo_root),
        prior_snapshots=lookback, prior_snap_objects=prior_snap_objects,
        obs_landing=False,   # ← I-only: write I columns, skip ALL O engines
    )
    # Stamp provenance lineage (archived_sha256 / archived_copy_path) WITHOUT
    # touching archive bytes. verify_only=True re-hashes the existing WORM copy;
    # it never reads live data/ (red line: today.json is live 7/14 data).
    archive_raw_inputs(snap, repo_root, RAW_ARCHIVE_DIR, verify_only=True)
    return snap


def _already_backfilled(new_snap: dict, on_disk_snap: dict, current_hash: str) -> bool:
    """Idempotency gate: is the on-disk snapshot already this exact backfill?

    Normalize a copy of the freshly-built snapshot against the on-disk one
    (copies replay-excluded fields: generated_at / environment / schema_version /
    core_version / audit_log). If the resulting canonical hash equals the index's
    current_hash, the on-disk version is replay-identical to what we'd write →
    re-running would only churn generated_at → skip (no second supersede).

    First run: on-disk is a pre-1.9.0 epoch with different content → hashes differ
    → returns False → we write + supersede.
    """
    cmp = copy.deepcopy(new_snap)
    normalize_for_replay_compare(cmp, on_disk_snap)
    return canonical_sha256(cmp) == current_hash


def _classify(new_snap: dict) -> str:
    """backfilled_full (T86 present) vs backfilled_fii_pending (trust/prop None)."""
    return "backfilled_fii_pending" if new_snap.get("fii_pending") else "backfilled_full"


def process_one(date_iso: str, index: dict, cfg: dict, repo_root: pathlib.Path,
                dry_run: bool) -> dict:
    if date_iso in FORBIDDEN_DATES:
        return {"date": date_iso, "status": "forbidden_skip"}

    entry = index["snapshots"][date_iso]
    on_disk_snap = json.loads((REPORTS_DIR / entry["current"]).read_text(encoding="utf-8"))

    if _is_rollup_only(on_disk_snap):
        return {"date": date_iso, "status": "skip_rollup_only"}

    new_snap = _build_backfill_snapshot(date_iso, on_disk_snap, cfg, repo_root, index)

    if _already_backfilled(new_snap, on_disk_snap, entry["current_hash"]):
        return {"date": date_iso, "status": "already_backfilled",
                "kind": _classify(new_snap)}

    kind = _classify(new_snap)
    if dry_run:
        return {"date": date_iso, "status": "would_backfill", "kind": kind,
                "from_schema": on_disk_snap.get("schema_version")}

    out_path = REPORTS_DIR / f"{date_iso}.json"
    out_path.write_text(
        json.dumps(new_snap, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sha = write_sidecar(out_path, new_snap)
    _update_index(out_path, sha, new_snap)
    return {"date": date_iso, "status": "backfilled", "kind": kind,
            "from_schema": on_disk_snap.get("schema_version"), "hash": sha}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="P2-W6 I-only 回填(obs_landing=False, 冪等 supersede)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只報告會回填/跳過哪些日子,不寫盤、不動 index")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    repo_root = legacy_paths()["root"]
    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))

    dates = sorted(
        k for k in index["snapshots"].keys()
        if _is_iso_date(k) and _in_range(k)
    )
    mode = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"[backfill-i] {mode}  範圍 {BACKFILL_START}→{BACKFILL_END}  "
          f"候選 {len(dates)} 日  (current schema {SCHEMA_VERSION})", file=sys.stderr)

    tally: dict[str, int] = {}
    for d in dates:
        # Reload the index each iteration so _gather_lookback sees the priors we
        # just superseded (chronological cascade): a backfilled date's recorded
        # environment.lookback_snapshots must reference its priors' CURRENT
        # (freshly-backfilled) hashes, not the stale hashes from before this run.
        # _update_index persists to disk each write, so re-reading is the source
        # of truth. Keeps strict lookback continuity fresh within the chain.
        if not args.dry_run:
            index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        try:
            res = process_one(d, index, cfg, repo_root, args.dry_run)
        except Exception as e:
            res = {"date": d, "status": "error", "error": f"{type(e).__name__}: {e}"}
        st = res["status"]
        tally[st] = tally.get(st, 0) + 1
        kind = f"  ({res['kind']})" if res.get("kind") else ""
        frm = f"  from {res['from_schema']}" if res.get("from_schema") else ""
        icon = {
            "backfilled": "✅", "would_backfill": "→", "already_backfilled": "·",
            "skip_rollup_only": "⏭", "forbidden_skip": "🚫", "error": "❌",
        }.get(st, "?")
        line = f"  {icon} {d}  {st}{kind}{frm}"
        if res.get("error"):
            line += f"  {res['error']}"
        print(line, file=sys.stderr)

    print(f"\n[backfill-i] 完成:" +
          "  ".join(f"{k}={v}" for k, v in sorted(tally.items())), file=sys.stderr)
    return 1 if tally.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
