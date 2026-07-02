"""SCD Engine — Distribution Intelligence Layer  (P3i, parallel to Golden Layer)
出貨意圖觀察層

Purpose
────────────────────────────────────────────────────────────────────────
Surfaces sell-side signals (賣超) that are already fetched into
data/today.json / data/branches/*.json (and preserved in
reports/_raw_archive/<date>/) but were never wired into the canonical
schema or any scoring module. (The audit finding that prompted this layer
was documented in the old PROJECT_STATUS.md "已知技術債", since merged into
ARCHITECTURE.md.)

Architectural contract — READ BEFORE EDITING
────────────────────────────────────────────────────────────────────────
  • This module NEVER touches core/ingest.py, data/adapters/legacy.py,
    or anything inside the canonical snapshot (the dict that gets
    canonical_sha256'd). It reads RAW sell-side data directly from the
    immutable archive (reports/_raw_archive/<date>/) — the same pattern
    core/intelligence_delta.py uses for its derived report — and persists
    its own output to reports/<date>.distribution.json.
  • Net effect: replay (verify_all_replay) is COMPLETELY UNAFFECTED.
    Adding/changing fields here can never change a canonical hash.
  • Golden Layer (core/golden.py) scoring is UNTOUCHED. This layer is
    purely observational/parallel — it does not feed into conviction
    scores, gates, or tiers. (User explicitly confirmed: "Golden 的邏輯
    保持不變，新增的賣超資料只影響 Distribution Layer、風險顯示與成本
    偏離資訊，不參與 Golden score 計算".)
  • Future note (see memory: scd-distribution-layer-plan): if this layer
    proves itself over time AND verify_all_replay's B1 bug is fixed, a
    *separate* future decision may fold sell-side fields into a new
    schema_version (e.g. 1.5.0) via a clean version cutover. That is an
    explicit, deliberate future migration — NOT something this module
    should creep toward by accumulating fields into the canonical side.

Pure observation. No trading signals. No buy/sell recommendations in the
financial-advice sense — "建議動作" is a descriptive label summarizing
what the chip-consistency + safety-margin combination looks like, not
investment advice.

────────────────────────────────────────────────────────────────────────
籌碼一致性 Chip Consistency Score   (-5 .. +5)
────────────────────────────────────────────────────────────────────────
  外資 + 主力皆強力買超 (前15名 或 買超>8,000張)   → +5  最高共振
  外資買超 + 主力中性                              → +3  外資主導
  主力買超 + 外資中性                              → +3  主力主導
  雙方皆買超但未達強力門檻                          → +3  一般共振 [assumption — see _score_consistency]
  外資賣超 或 主力賣超（非雙方）                    → -3  扣分
  外資 + 主力皆賣超                                → -5  強烈賣超
  其餘（雙方中性 / 訊號分歧）                       →  0  中性 / 分歧

顯示規則：強(綠) ≥ 4 ｜ 中(黃) 1~3 ｜ 弱(紅) ≤ 0

────────────────────────────────────────────────────────────────────────
安全邊際 Safety Margin = 現價 / 主力平均成本
────────────────────────────────────────────────────────────────────────
  ≤ 1.03x        綠   安全，可積極布局
  1.03x ~ 1.08x  黃   中等，小心 / 分批
  1.08x ~ 1.15x  橙   偏高，建議減碼
  > 1.15x        紅   高風險，強烈建議減碼或移除

────────────────────────────────────────────────────────────────────────
建議動作 Suggested Action  (display-only synthesis of the two signals above)
────────────────────────────────────────────────────────────────────────
  See _ACTION_MATRIX for the full lookup. High level:
    強籌碼 + 安全邊際寬鬆   → 優先佈局 / 核心持股佈局
    強籌碼 + 安全邊際偏緊   → 觀察（訊號好但價格已偏離成本，等拉回）
    中等籌碼                → 觀察
    弱籌碼  + 安全邊際寬鬆  → 觀察
    弱籌碼  + 安全邊際偏緊  → 減碼

自動過濾旗標（display-only — 不會更動 Golden 名單本身）：
    安全邊際 > 1.12x 且 籌碼一致性 = 弱 → flagged_for_removal = True
    （建議使用者自行從黃金名單移出，本層只標記不執行）

────────────────────────────────────────────────────────────────────────
Public API
────────────────────────────────────────────────────────────────────────
  run(date)        → DistributionResult  (in-memory, no file I/O)
  generate(date)   → DistributionResult  (computes + persists to
                                           reports/<date>.distribution.json)
  load_for_date(date) → DistributionResult | None
"""
from __future__ import annotations

import json
import sys
import pathlib
from dataclasses import dataclass, field, asdict
from typing import Any

_HERE     = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.temporal._loader import load_snapshot, real_dates  # noqa: E402

_REPORTS      = _AI_STOCK / "reports"
_RAW_ARCHIVE  = _REPORTS / "_raw_archive"
_LIVE_TODAY   = _AI_STOCK / "data" / "today.json"
_LIVE_BRANCH  = _AI_STOCK / "data" / "branches"


# ── Tunable thresholds — single source of truth ──────────────────────────────

CONSISTENCY_CONFIG: dict = {
    "strong_rank_max":  15,      # 前 15 名視為強力訊號
    "strong_vol_min":   8000,    # 買/賣超 > 8,000 張視為強力訊號
    "scores": {
        "both_strong_buy":   (+5, "最高共振"),
        "both_buy":          (+3, "一般共振"),       # neither side hit the strength bar
        "foreign_lead":      (+3, "外資主導"),
        "main_lead":         (+3, "主力主導"),
        "either_sell":       (-3, "扣分"),
        "both_sell":         (-5, "強烈賣超"),
        "neutral":           ( 0, "中性 / 分歧"),
    },
}

GRADE_BANDS = [
    (4,  "強", "#52B788"),   # green
    (1,  "中", "#D4A84B"),   # yellow/gold
    (-99, "弱", "#E05C7A"),  # red — catches everything ≤ 0
]

SAFETY_MARGIN_BANDS = [
    # (upper_bound_exclusive, label, color, hint)
    (1.03, "綠", "#52B788", "安全，可積極布局"),
    (1.08, "黃", "#D4A84B", "中等，小心 / 分批"),
    (1.15, "橙", "#C47A5A", "偏高，建議減碼"),
    (float("inf"), "紅", "#E05C7A", "高風險，強烈建議減碼或移除"),
]

# Auto-filter (display-only) thresholds
AUTO_FILTER_MARGIN_MIN   = 1.12
AUTO_FILTER_CONSISTENCY  = "弱"

# ── Suggested action matrix (display-only synthesis) ─────────────────────────
# Keyed by (consistency_grade, safety_margin_label). Values: (action, detail)
_ACTION_MATRIX: dict[tuple[str, str], tuple[str, str]] = {
    ("強", "綠"): ("優先佈局",     "籌碼共振強，價格貼近主力成本，風險報酬比佳"),
    ("強", "黃"): ("核心持股佈局", "籌碼共振強，價格略高於成本但仍可接受，適合分批建立核心部位"),
    ("強", "橙"): ("觀察",         "籌碼仍強但價格已偏離成本，建議等拉回再進場"),
    ("強", "紅"): ("觀察",         "籌碼強但安全邊際過高，追價風險大，等回檔"),
    ("中", "綠"): ("觀察",         "籌碼中性偏多，價格便宜，可留意是否轉強"),
    ("中", "黃"): ("觀察",         "籌碼中性，價格尚可接受，持續觀察是否共振"),
    ("中", "橙"): ("觀察",         "籌碼中性、價格偏高，暫不建議加碼"),
    ("中", "紅"): ("觀察",         "籌碼中性、安全邊際過高，風險偏高"),
    ("弱", "綠"): ("觀察",         "雖然價格便宜，但籌碼開始轉弱，留意是否進一步轉空"),
    ("弱", "黃"): ("觀察",         "籌碼轉弱，價格仍可接受，但訊號不利，建議減少加碼"),
    ("弱", "橙"): ("減碼",         "籌碼轉弱、價格偏離成本，風險升高"),
    ("弱", "紅"): ("減碼",         "籌碼轉弱且安全邊際過高，雙重警訊，建議優先檢視"),
}


# ── Output dataclasses ────────────────────────────────────────────────────────

@dataclass
class DistributionEntry:
    ticker:   str
    name:     str

    # Raw side-status (for transparency / debugging)
    foreign_status:   str            # "buy" | "sell" | "neutral"
    foreign_detail:   str
    main_status:      str            # "buy" | "sell" | "neutral"
    main_detail:      str

    # 籌碼一致性
    consistency_score: int           # -5 .. +5
    consistency_grade: str           # 強 / 中 / 弱
    consistency_color: str
    consistency_reason: str

    # 安全邊際
    current_price:     float | None
    main_force_cost:   float | None
    safety_margin:     float | None  # current_price / main_force_cost, None if unavailable
    safety_label:      str           # 綠 / 黃 / 橙 / 紅 / —
    safety_color:      str
    safety_hint:       str

    # 建議動作 (display-only synthesis — not financial advice)
    suggested_action:  str
    suggested_detail:  str

    # Display-only auto-filter flag (does NOT modify the Golden list itself)
    flagged_for_removal: bool = False
    flag_reason:         str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DistributionResult:
    date:           str
    universe_count: int
    entries:        list[DistributionEntry] = field(default_factory=list)

    @property
    def flagged(self) -> list[DistributionEntry]:
        return [e for e in self.entries if e.flagged_for_removal]

    @property
    def strong_sell_signal(self) -> list[DistributionEntry]:
        """Both foreign + main force in net-sell — the sharpest distribution signal."""
        return [e for e in self.entries if e.consistency_score <= -5]

    def as_dict(self) -> dict[str, Any]:
        return {
            "date":           self.date,
            "universe_count": self.universe_count,
            "counts": {
                "total":             len(self.entries),
                "flagged_for_removal": len(self.flagged),
                "strong_sell_signal":  len(self.strong_sell_signal),
            },
            "entries": [e.as_dict() for e in self.entries],
        }


# ── Raw sell-side data loading ────────────────────────────────────────────────
# Mirrors data/adapters/legacy.py's read pattern, but DOES NOT go through the
# adapter — we read raw bytes directly and never touch raw_inputs_per_ticker.

def _archived_today_json(date: str) -> pathlib.Path | None:
    d = _RAW_ARCHIVE / date / "legacy_today_json"
    if d.is_dir():
        files = sorted(d.glob("*.json"))
        if files:
            return files[0]
    return None


def _archived_branches_dir(date: str) -> pathlib.Path | None:
    d = _RAW_ARCHIVE / date / "legacy_branches"
    return d if d.is_dir() else None


def _load_raw_sell_data(date: str) -> dict[str, Any]:
    """Load sell-side raw data for `date`.

    Resolution order:
      1. reports/_raw_archive/<date>/  — immutable, authoritative for any
         date that has completed the daily pipeline (preferred — matches
         exactly what the canonical snapshot for that date was built from).
      2. data/today.json + data/branches/  — live fallback, used only when
         no archive exists yet for `date` (e.g. ad-hoc same-day run before
         the pipeline has archived raw bytes).

    Returns:
        {
          "sell_list":        [...],   # 外資賣超 (Fubon ZGK_D topSell)
          "main_force_sell":  [...],   # 主力賣超 (Fubon ZGK_F topSell)
          "buy_list":         [...],   # 外資買超 (for strength comparison)
          "main_force_buy":   [...],   # 主力買超 (for strength comparison)
          "branches_by_ticker": {ticker: {...}},
          "source": "archive" | "live" | "missing",
        }
    """
    today_path = _archived_today_json(date)
    branches_dir = _archived_branches_dir(date)
    source = "archive"

    if today_path is None:
        # Fall back to live data — only sane for the most recent date.
        if _LIVE_TODAY.is_file():
            today_path = _LIVE_TODAY
            branches_dir = _LIVE_BRANCH if _LIVE_BRANCH.is_dir() else None
            source = "live"
        else:
            return {
                "sell_list": [], "main_force_sell": [],
                "buy_list": [], "main_force_buy": [],
                "branches_by_ticker": {}, "source": "missing",
            }

    try:
        today = json.loads(today_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        today = {}

    branches_by_ticker: dict[str, dict] = {}
    if branches_dir is not None:
        for f in sorted(branches_dir.glob("*.json")):
            try:
                branches_by_ticker[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

    return {
        "sell_list":          today.get("sellList", []) or [],
        "main_force_sell":    today.get("mainForceSell", []) or [],
        "buy_list":           today.get("buyList", []) or [],
        "main_force_buy":     today.get("mainForceBuy", []) or [],
        "branches_by_ticker": branches_by_ticker,
        "source":             source,
    }


# ── Side-status classification ────────────────────────────────────────────────

def _row_for(ticker: str, rows: list[dict]) -> dict | None:
    for r in rows:
        if str(r.get("code", "")).strip() == ticker:
            return r
    return None


def _is_strong_row(row: dict, vol_key: str) -> bool:
    """A ranking row counts as 'strong' if it's top-15 or moves > 8,000 lots."""
    cfg = CONSISTENCY_CONFIG
    rank = row.get("rank")
    vol  = row.get(vol_key)
    if rank is not None and rank <= cfg["strong_rank_max"]:
        return True
    if vol is not None and abs(vol) > cfg["strong_vol_min"]:
        return True
    return False


def _side_status(
    ticker: str,
    buy_rows: list[dict],
    sell_rows: list[dict],
    buy_vol_key: str = "buyVol",
    sell_vol_key: str = "sellVol",
    label: str = "",
) -> tuple[str, bool, str]:
    """Classify one side (外資 or 主力) for one ticker.

    Returns (status, is_strong, detail) where status ∈ {"buy","sell","neutral"}.
    """
    buy_row  = _row_for(ticker, buy_rows)
    sell_row = _row_for(ticker, sell_rows)

    if buy_row is not None:
        strong = _is_strong_row(buy_row, buy_vol_key)
        rank = buy_row.get("rank")
        vol  = buy_row.get(buy_vol_key)
        tag  = "（強）" if strong else ""
        return ("buy", strong,
                f"{label}買超{tag} 第{rank}名" + (f"，{vol:,}張" if vol is not None else ""))

    if sell_row is not None:
        rank = sell_row.get("rank")
        vol  = sell_row.get(sell_vol_key)
        return ("sell", False,
                f"{label}賣超 第{rank}名" + (f"，{vol:,}張" if vol is not None else ""))

    return ("neutral", False, f"{label}中性（未上榜）")


# ── 籌碼一致性 scoring ─────────────────────────────────────────────────────────

def _score_consistency(
    foreign_status: str, foreign_strong: bool,
    main_status: str,    main_strong: bool,
) -> tuple[int, str]:
    """Return (score, reason_label) per the decision tree in the module docstring.

    NOTE on assumption: the user's spec gives +5 for "both sides strong-buy"
    and +3 for "one side buy, other neutral", but does not specify the case
    "both sides buy but neither meets the strength bar". This implementation
    treats that case as +3 ("一般共振") — a deliberate, documented choice;
    tune CONSISTENCY_CONFIG["scores"] if you'd rather treat it differently.
    """
    cfg = CONSISTENCY_CONFIG["scores"]
    both_buy  = (foreign_status == "buy"  and main_status == "buy")
    both_sell = (foreign_status == "sell" and main_status == "sell")
    either_sell = (foreign_status == "sell" or main_status == "sell")

    if both_sell:
        return cfg["both_sell"]
    if either_sell:
        return cfg["either_sell"]
    if both_buy:
        if foreign_strong and main_strong:
            return cfg["both_strong_buy"]
        return cfg["both_buy"]
    if foreign_status == "buy" and main_status == "neutral":
        return cfg["foreign_lead"]
    if main_status == "buy" and foreign_status == "neutral":
        return cfg["main_lead"]
    return cfg["neutral"]


def _consistency_grade(score: int) -> tuple[str, str]:
    for floor, grade, color in GRADE_BANDS:
        if score >= floor:
            return grade, color
    return "弱", "#E05C7A"


# ── 安全邊際 ───────────────────────────────────────────────────────────────────

def _safety_margin(current_price: float | None, main_force_cost: float | None
                    ) -> tuple[float | None, str, str, str]:
    if not current_price or not main_force_cost or main_force_cost <= 0:
        return None, "—", "#6B8EAA", "主力成本資料待補"
    ratio = current_price / main_force_cost
    for upper, label, color, hint in SAFETY_MARGIN_BANDS:
        if ratio < upper:
            return round(ratio, 4), label, color, hint
    last = SAFETY_MARGIN_BANDS[-1]
    return round(ratio, 4), last[1], last[2], last[3]


# ── 建議動作 + 自動過濾旗標 ────────────────────────────────────────────────────

def _suggest_action(consistency_grade: str, safety_label: str) -> tuple[str, str]:
    if safety_label == "—":
        # No safety-margin data — fall back to chip-consistency only.
        fallback = {
            "強": ("觀察", "籌碼共振強，但缺主力成本資料，無法評估安全邊際"),
            "中": ("觀察", "籌碼中性，缺成本資料，持續觀察"),
            "弱": ("觀察", "籌碼轉弱，缺成本資料，建議留意後續變化"),
        }
        return fallback.get(consistency_grade, ("觀察", "資料不足，持續觀察"))
    return _ACTION_MATRIX.get((consistency_grade, safety_label), ("觀察", "—"))


def _should_flag(consistency_grade: str, safety_margin: float | None) -> tuple[bool, str | None]:
    if (consistency_grade == AUTO_FILTER_CONSISTENCY
            and safety_margin is not None
            and safety_margin > AUTO_FILTER_MARGIN_MIN):
        return True, (
            f"籌碼一致性「{AUTO_FILTER_CONSISTENCY}」且安全邊際 "
            f"{safety_margin:.3f}x > {AUTO_FILTER_MARGIN_MIN}x — 建議自黃金名單移出"
        )
    return False, None


# ── Main computation ──────────────────────────────────────────────────────────

def run(date: str | None = None) -> DistributionResult:
    """Compute the Distribution Intelligence layer for `date` (default: latest).

    Pure in-memory computation — does not write any file. Use generate() to
    persist to reports/<date>.distribution.json.
    """
    if date is None:
        dates = real_dates()
        if not dates:
            return DistributionResult(date="unknown", universe_count=0)
        date = dates[-1]

    snap = load_snapshot(date)
    stock_map = {s["ticker"]: s for s in snap.get("stocks", [])}

    raw = _load_raw_sell_data(date)
    buy_list  = raw["buy_list"]
    sell_list = raw["sell_list"]
    mfb       = raw["main_force_buy"]
    mfs       = raw["main_force_sell"]

    # Universe = union of everything that appears in any of the four rankings
    # plus whatever the canonical snapshot already tracks (so cost/price are
    # available wherever possible).
    universe: set[str] = set(stock_map.keys())
    for rows in (buy_list, sell_list, mfb, mfs):
        universe.update(str(r.get("code", "")).strip() for r in rows if r.get("code"))
    universe.discard("")

    entries: list[DistributionEntry] = []
    for ticker in sorted(universe):
        stock = stock_map.get(ticker, {})
        name  = stock.get("name") or _name_from_rows(ticker, (buy_list, sell_list, mfb, mfs))

        f_status, f_strong, f_detail = _side_status(
            ticker, buy_list, sell_list, "buyVol", "sellVol", "外資")
        m_status, m_strong, m_detail = _side_status(
            ticker, mfb, mfs, "buyVol", "sellVol", "主力")

        score = _score_consistency(f_status, f_strong, m_status, m_strong)
        c_score, c_reason = score
        c_grade, c_color = _consistency_grade(c_score)

        current_price   = stock.get("current_price")
        main_force_cost = stock.get("main_force_cost")
        margin, s_label, s_color, s_hint = _safety_margin(current_price, main_force_cost)

        action, action_detail = _suggest_action(c_grade, s_label)
        flagged, flag_reason = _should_flag(c_grade, margin)

        entries.append(DistributionEntry(
            ticker=ticker, name=name,
            foreign_status=f_status, foreign_detail=f_detail,
            main_status=m_status, main_detail=m_detail,
            consistency_score=c_score, consistency_grade=c_grade,
            consistency_color=c_color, consistency_reason=c_reason,
            current_price=current_price, main_force_cost=main_force_cost,
            safety_margin=margin, safety_label=s_label,
            safety_color=s_color, safety_hint=s_hint,
            suggested_action=action, suggested_detail=action_detail,
            flagged_for_removal=flagged, flag_reason=flag_reason,
        ))

    # Sort: strongest distribution signal first (most negative consistency,
    # then highest safety margin) — surfaces the riskiest names at the top.
    entries.sort(key=lambda e: (e.consistency_score, -(e.safety_margin or 0)))

    return DistributionResult(date=date, universe_count=len(universe), entries=entries)


def _name_from_rows(ticker: str, row_groups: tuple[list[dict], ...]) -> str:
    for rows in row_groups:
        row = _row_for(ticker, rows)
        if row and row.get("name"):
            return str(row["name"])
    return ""


# ── Persistence (mirrors core/intelligence_delta.py) ──────────────────────────

def generate(date: str | None = None, force: bool = False) -> DistributionResult:
    """Compute and persist to reports/<date>.distribution.json.

    This file lives entirely OUTSIDE the canonical snapshot / hash boundary —
    see the module docstring's "Architectural contract" section.
    """
    result = run(date)
    out_path = _REPORTS / f"{result.date}.distribution.json"
    if out_path.exists() and not force:
        return load_for_date(result.date) or result

    out_path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def load_for_date(date: str) -> DistributionResult | None:
    path = _REPORTS / f"{date}.distribution.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [DistributionEntry(**e) for e in data.get("entries", [])]
    return DistributionResult(date=data["date"], universe_count=data["universe_count"], entries=entries)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Distribution Intelligence Layer — 出貨意圖觀察層")
    ap.add_argument("--date", help="target date YYYY-MM-DD (default: latest)")
    ap.add_argument("--save", action="store_true", help="persist to reports/<date>.distribution.json")
    ap.add_argument("--force", action="store_true", help="overwrite existing report")
    ap.add_argument("--json", action="store_true", help="print full JSON")
    args = ap.parse_args(argv)

    result = generate(args.date, force=args.force) if args.save else run(args.date)

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\n📉 Distribution Intelligence Layer — {result.date}")
    print(f"   觀察範圍：{result.universe_count} 檔（外資/主力買賣超榜聯集 ∪ canonical universe）")
    print(f"   強烈賣超共振：{len(result.strong_sell_signal)} 檔　｜　建議移出旗標：{len(result.flagged)} 檔\n")

    header = f"{'代號':<6}{'名稱':<10}{'籌碼一致性':<14}{'安全邊際':<14}{'建議動作':<10}{'備註'}"
    print(header)
    print("─" * len(header) * 2)
    for e in result.entries[:40]:
        margin_str = f"{e.safety_margin:.3f}x ({e.safety_label})" if e.safety_margin is not None else "—"
        flag = "  ⚠移出" if e.flagged_for_removal else ""
        print(f"{e.ticker:<6}{e.name:<10}"
              f"{e.consistency_score:+d} {e.consistency_grade:<8}"
              f"{margin_str:<14}{e.suggested_action:<10}{e.foreign_detail} / {e.main_detail}{flag}")

    if len(result.entries) > 40:
        print(f"\n   …其餘 {len(result.entries) - 40} 檔省略，使用 --json 查看完整輸出")
    print(f"\n   已儲存 → reports/{result.date}.distribution.json" if args.save else
          "\n   （未儲存，加上 --save 寫入 reports/<date>.distribution.json）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
