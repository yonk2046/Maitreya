"""WORM backfill coverage report — how deep Phase 2 can backfill trust/prop/sell data.

Context (migration Phase 1 第 3+4 線, see docs/architecture_research/CROSS-SESSION-NOTES.md
#1 and #38, and docs/ARCHITECTURE_BLUEPRINT.md §7 Phase 1):
  - dealer_net_buy is misnamed (actually 投信/trust); the real 自營商/prop value has
    always been computed by the adapter but silently dropped by ingest.
  - Sell-side raw (sellList/mainForceSell) is the only sell evidence source but has
    never entered canonical.
  - Both are recoverable from history ONLY where the immutable WORM archive
    (reports/_raw_archive/<date>/) still holds a raw today.json with T86 data —
    the legacy_rollup-only dates (early backfill, no today.json shape) structurally
    never had T86 (自營商) or sellList/mainForceSell at all.

This script walks every archived date and reports, PER SOURCE SHAPE:
  - Whether a raw today.json is archived at all (legacy_today_json source).
  - T86 presence and prop-field (自營商) coverage — how many of that day's T86
    tickers have a non-null "prop" value.
  - sellList / mainForceSell row counts (the raw evidence rows a future
    obs_dist_consistency landing could recover for that date).

Read-only: never writes under data/ or reports/_raw_archive/. Writes only the
markdown report to the path given by --out (default docs/migration/P1-worm-backfill-report.md).

Usage:
    python3 -m tools.worm_backfill_coverage
    python3 -m tools.worm_backfill_coverage --out /tmp/report.md
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

REPORTS_DIR = _AI_STOCK / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"
RAW_ARCHIVE_DIR = REPORTS_DIR / "_raw_archive"
DEFAULT_OUT = _AI_STOCK / "docs" / "migration" / "P1-worm-backfill-report.md"


def _real_dates() -> list[str]:
    """Every real ISO date in index.json (excludes '*.example' keys)."""
    idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    out = []
    for key in idx.get("snapshots", {}):
        try:
            import datetime as dt
            dt.date.fromisoformat(key)
        except ValueError:
            continue
        out.append(key)
    return sorted(out)


def _inspect_date(date: str) -> dict:
    """Return coverage facts for one archived date. Never raises — missing
    data is recorded as absent, not an error (that's the point of the report).
    """
    date_dir = RAW_ARCHIVE_DIR / date
    sources = sorted(p.name for p in date_dir.iterdir()) if date_dir.is_dir() else []

    row: dict = {
        "date": date,
        "sources": sources,
        "has_today_json": "legacy_today_json" in sources,
        "t86_ticker_count": 0,
        "prop_present_count": 0,
        "trust_present_count": 0,
        "sell_list_count": 0,
        "main_force_sell_count": 0,
        "note": "",
    }

    if not row["has_today_json"]:
        row["note"] = "legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data"
        return row

    today_path = date_dir / "legacy_today_json" / "today.json"
    if not today_path.is_file():
        row["note"] = "legacy_today_json dir present but today.json missing (archive corruption?)"
        return row

    try:
        today = json.loads(today_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        row["note"] = f"today.json unreadable: {type(e).__name__}"
        return row

    t86 = today.get("t86") or {}
    row["t86_ticker_count"] = len(t86)
    row["prop_present_count"] = sum(1 for v in t86.values() if isinstance(v, dict) and v.get("prop") is not None)
    row["trust_present_count"] = sum(1 for v in t86.values() if isinstance(v, dict) and v.get("trust") is not None)

    sell_list = today.get("sellList") or []
    mfs = today.get("mainForceSell") or []
    row["sell_list_count"] = len(sell_list)
    row["main_force_sell_count"] = len(mfs)

    t86_date = str(today.get("t86Date") or "").strip()
    target_compact = date.replace("-", "")
    if t86 and t86_date and t86_date != target_compact:
        row["note"] = f"t86Date={t86_date} != {target_compact} (stale — same rule adapter uses to drop it)"
    elif not t86:
        row["note"] = "t86 empty in archived today.json (fii_pending day)"
    elif not sell_list and not mfs:
        row["note"] = "sellList/mainForceSell both empty in archived today.json"

    return row


def build_rows() -> list[dict]:
    return [_inspect_date(d) for d in _real_dates()]


def render_markdown(rows: list[dict]) -> str:
    total = len(rows)
    dates = [r["date"] for r in rows]
    date_range = f"{dates[0]} ~ {dates[-1]}" if dates else "(none)"

    with_today_json = [r for r in rows if r["has_today_json"]]
    # prop coverage % = (dates where >=1 ticker has non-null prop) / total dates
    # AND the finer-grained per-ticker fraction, both reported (task asks
    # for "prop 值...覆蓋率各多少" — date-level tells "can we backfill this
    # day at all", ticker-level tells "how complete is that day's backfill").
    prop_date_hits = sum(1 for r in rows if r["prop_present_count"] > 0)
    sell_date_hits = sum(1 for r in rows if r["sell_list_count"] > 0 or r["main_force_sell_count"] > 0)

    total_t86_tickers = sum(r["t86_ticker_count"] for r in rows)
    total_prop_present = sum(r["prop_present_count"] for r in rows)
    total_trust_present = sum(r["trust_present_count"] for r in rows)

    prop_date_pct = 100.0 * prop_date_hits / total if total else 0.0
    sell_date_pct = 100.0 * sell_date_hits / total if total else 0.0
    prop_ticker_pct = 100.0 * total_prop_present / total_t86_tickers if total_t86_tickers else 0.0

    gaps = [r for r in rows if r["prop_present_count"] == 0 or (r["sell_list_count"] == 0 and r["main_force_sell_count"] == 0)]

    lines: list[str] = []
    lines.append("# Phase 1 WORM 回填覆蓋率報告")
    lines.append("")
    lines.append(
        "> 產生方式：`python3 -m tools.worm_backfill_coverage`（唯讀，掃 "
        "`reports/_raw_archive/<date>/` 全部歷史存檔 today.json）。"
    )
    lines.append(
        "> 目的：量化 Phase 2（1.9.0）能把 trust_net_buy／prop_net_buy／賣方 raw "
        "回填到多深——WORM 存檔缺的資料，backfill 無論如何都補不回來（誠實面對缺口，C10）。"
    )
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- **日期範圍**：{date_range}（{total} 個已存檔日期）")
    lines.append(
        f"- **prop（自營商）覆蓋率**：{prop_date_hits}/{total} 天（{prop_date_pct:.1f}%）"
        f"至少 1 檔有值；逐檔覆蓋 {total_prop_present}/{total_t86_tickers}"
        f"（{prop_ticker_pct:.1f}%，僅計有 today.json 存檔的天）"
    )
    lines.append(
        f"- **sellList／mainForceSell（賣方榜）覆蓋率**：{sell_date_hits}/{total} 天（{sell_date_pct:.1f}%）"
        " 至少一份非空榜"
    )
    lines.append(
        f"- **today.json 存檔本身**：{len(with_today_json)}/{total} 天有 legacy_today_json 存檔"
        f"（其餘 {total - len(with_today_json)} 天只有 legacy_rollup——結構性不含 T86/賣方榜，"
        "backfill 無解，非缺陷）"
    )
    lines.append(f"- **有缺口的天數**：{len(gaps)}/{total}（見下方缺口清單）")
    lines.append("")
    lines.append("## 逐日明細")
    lines.append("")
    lines.append("| 日期 | today.json 存檔 | T86 檔數 | prop 有值 | trust 有值 | sellList 列數 | mainForceSell 列數 | 備註 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['date']} | {'✅' if r['has_today_json'] else '❌ rollup-only'} "
            f"| {r['t86_ticker_count']} | {r['prop_present_count']} | {r['trust_present_count']} "
            f"| {r['sell_list_count']} | {r['main_force_sell_count']} | {r['note']} |"
        )
    lines.append("")
    lines.append("## 缺口清單（prop 或賣方榜任一缺）")
    lines.append("")
    if gaps:
        lines.append("| 日期 | 缺什麼 | 原因 |")
        lines.append("|---|---|---|")
        for r in gaps:
            missing = []
            if r["prop_present_count"] == 0:
                missing.append("prop")
            if r["sell_list_count"] == 0 and r["main_force_sell_count"] == 0:
                missing.append("賣方榜")
            lines.append(f"| {r['date']} | {'+'.join(missing)} | {r['note'] or '（見逐日明細）'} |")
    else:
        lines.append("（無缺口）")
    lines.append("")
    lines.append("## Phase 2 回填深度結論")
    lines.append("")
    lines.append(
        f"- 可回填 prop_net_buy 的最早日期：**{next((r['date'] for r in rows if r['prop_present_count'] > 0), '(無)')}**"
        f"（{prop_date_hits} 天可回填，早於此的 rollup-only 天結構性無 T86，Phase 2 backfill 誠實放棄，不偽稱可回溯 — C10）"
    )
    lines.append(
        f"- 可回填賣方 raw 的最早日期：**{next((r['date'] for r in rows if r['sell_list_count'] > 0 or r['main_force_sell_count'] > 0), '(無)')}**"
        f"（{sell_date_hits} 天可回填）"
    )
    lines.append(
        "- rollup-only 天（" + ", ".join(r["date"] for r in rows if not r["has_today_json"]) + "）"
        "：無 today.json 存檔，trust/prop/賣方 raw 三者皆結構性不存在，Phase 2 backfill 範圍上限即此清單。"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = build_rows()
    md = render_markdown(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"[worm-backfill-coverage] wrote {args.out} ({len(rows)} dates)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
