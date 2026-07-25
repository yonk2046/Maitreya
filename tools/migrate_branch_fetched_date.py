"""一次性遷移:把 `fetched_date` 補蓋進 data/branches/ 的舊分點檔。

## 為什麼需要

修正案 C-2 給每檔分點資料加了新鮮度守門(`data/adapters/legacy.py:_branch_stale`),
判定基準有兩條:

  1. 檔案內容的 `fetched_date` — **live 與 replay 共用**,可重現;
  2. 沒有 `fetched_date` 時回退看檔案 mtime — **只在 live 生效**。replay 不看 mtime
     (mtime 是可變的複製metadata,封存檔會保留舊 mtime,用它會改寫 as-was 歷史)。

第 2 條對「守門上線前就存在的舊快照」是正確的:它們當初就是在沒有守門的情況下建的,
replay 不該回頭把它們判成棄權。但它對**守門上線後新建的快照**是致命的——
live 讀 mtime 判 stale 而棄權,replay 讀不到 mtime 於是照用資料,兩邊必然分歧:

    2026-07-24 快照(C-2 落地後第一個新建快照)→ verify_all_replay 直接紅。
    live: 17 檔判 stale 棄權(top5_branches=[]、主力成本待補)
    replay: 全部照用 → canonical hash 不同

## 修法

不動引擎(舊快照的 replay 行為必須維持原樣),改成消滅「沒有 fetched_date」這個狀態:
把每個未蓋章的活檔補上 `fetched_date` = 該檔 mtime 的**本地**日期——也就是 live 現在
就在用的同一個訊號,所以 live 的判定結果一個字都不會變;差別只在這個判定依據從
「檔案系統 metadata」變成「檔案內容」,於是 replay 也看得到、判得出一樣的結果。

封存檔(reports/_raw_archive/)一律不動 → 舊快照的 replay 完全不受影響。

冪等:已有 fetched_date 的檔跳過。寫入後還原原 mtime(那是這筆蓋章的證據來源)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

_AI_STOCK = pathlib.Path(__file__).resolve().parent.parent
BRANCHES_DIR = _AI_STOCK / "data" / "branches"
SOURCE_TAG = "mtime-migration"


def migrate(branches_dir: pathlib.Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Stamp fetched_date on every branch file missing it. Returns (stamped, skipped)."""
    stamped = skipped = 0
    for f in sorted(branches_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ⚠ {f.name}: unreadable ({e}) — skipped", file=sys.stderr)
            skipped += 1
            continue
        if not isinstance(data, dict) or data.get("fetched_date"):
            skipped += 1
            continue

        st = f.stat()
        # LOCAL date — same basis as _branch_stale's mtime fallback and as
        # fetch_sinotrade's datetime.date.today(). UTC would roll an
        # evening-fetched file back a day and falsely age it.
        data["fetched_date"] = dt.date.fromtimestamp(st.st_mtime).isoformat()
        data["fetched_date_source"] = SOURCE_TAG
        if not dry_run:
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.utime(f, (st.st_atime, st.st_mtime))   # keep the evidence intact
        stamped += 1
    return stamped, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--branches-dir", default=str(BRANCHES_DIR))
    args = ap.parse_args(argv)

    d = pathlib.Path(args.branches_dir)
    if not d.is_dir():
        print(f"[migrate] {d} not a directory", file=sys.stderr)
        return 1
    stamped, skipped = migrate(d, dry_run=args.dry_run)
    verb = "would stamp" if args.dry_run else "stamped"
    print(f"[migrate] {verb} {stamped}, already-stamped/skipped {skipped} "
          f"({stamped + skipped} files in {d})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
