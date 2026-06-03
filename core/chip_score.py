"""
core/chip_score.py — 籌碼動能評分 Chip Momentum Score

Purpose: Information compression, not prediction.
All scoring logic lives here. Future changes require editing only this file.

Total: 40 points
  投量比        8 pts  — main_force_buy / market_volume ratio
  連續買超      10 pts  — consecutive accumulation streak
  籌碼集中度    8 pts  — top5 concentration (data pending)
  法人同向      8 pts  — how many of 3 institutions are net positive
  成本支撐      6 pts  — current price vs main force cost

Grade:
  32-40 → 強   #D4A84B gold
  24-31 → 中   #7EB8D4 blue
  <24   → 弱   #8B949E gray
"""
from __future__ import annotations
from dataclasses import dataclass

# ── Single source of truth for all scoring thresholds ────────────────────────
CHIP_SCORE_CONFIG: dict = {
    "vol_ratio": {
        "max": 8,
        "label": "投量比",
        "desc":  "主力買超 ÷ 市場成交量",
        # mfb / market_volume > 12% → 8, 6-12% → 4, <6% → 0
        "thresholds": [0.12, 0.06],
        "scores":     [8,    4,    0],
    },
    "streak": {
        "max": 10,
        "label": "連續買超",
        "desc":  "連續主力淨買超天數",
        # ≥7→10, 5-6→8, 3-4→6, 1-2→3, 0→0
        "thresholds": [7,  5,  3,  1],
        "scores":     [10, 8,  6,  3, 0],
    },
    "concentration": {
        "max": 8,
        "label": "籌碼集中度",
        "desc":  "大戶持股變化（TDCC）",
        # data pending — returns 0 when unavailable
        "thresholds": [],
        "scores":     [0],
    },
    "institutional": {
        "max": 8,
        "label": "法人同向",
        "desc":  "主力/外資/投信同向淨買家數",
        # 3→8, 2→5, 1→2, 0→0
        "thresholds": [3,  2,  1],
        "scores":     [8,  5,  2, 0],
    },
    "cost_support": {
        "max": 6,
        "label": "成本支撐",
        "desc":  "現價距主力成本距離（越近越好）",
        # price/cost ≤ 1.02 → 6, ≤ 1.05 → 3, > 1.05 → 0
        "thresholds": [1.02, 1.05],
        "scores":     [6,    3,    0],
    },
}

# Grade by percentage of available max (handles missing data gracefully)
# ≥80% → 強, ≥60% → 中, <60% → 弱
GRADE_PCT_MAP = [
    (0.80, "強", "#D4A84B"),
    (0.60, "中", "#7EB8D4"),
    (0.0,  "弱", "#8B949E"),
]


# ── Output dataclass ─────────────────────────────────────────────────────────

@dataclass
class ChipScore:
    total:         int           # 0–40
    max_total:     int = 40
    grade:         str = "—"
    grade_color:   str = "#6B8EAA"
    items: dict = None           # key → {"score": int, "max": int, "detail": str, "available": bool}

    def __post_init__(self):
        if self.items is None:
            self.items = {}
        pct = self.total / self.max_total if self.max_total > 0 else 0
        for threshold, grade, color in GRADE_PCT_MAP:
            if pct >= threshold:
                self.grade = grade
                self.grade_color = color
                break

    @property
    def pct(self) -> float:
        return self.total / self.max_total

    def bar_html(self, width: int = 100) -> str:
        """Render a compact progress bar HTML."""
        filled = round(self.pct * 10)
        empty  = 10 - filled
        bar    = "█" * filled + "░" * empty
        return (
            f'<span style="font-family:monospace;color:{self.grade_color};">{bar}</span>'
            f'&nbsp;<b style="color:{self.grade_color};">{self.total}/{self.max_total}</b>'
            f'&nbsp;<span style="color:{self.grade_color};">{self.grade}</span>'
        )


# ── Scoring helpers ──────────────────────────────────────────────────────────

def _threshold_score(value: float, thresholds: list, scores: list) -> int:
    """Return score based on descending threshold list."""
    for i, t in enumerate(thresholds):
        if value >= t:
            return scores[i]
    return scores[-1]


# ── Main compute function ────────────────────────────────────────────────────

def compute(
    streak: int,
    sponsorship: float,              # kept for future use
    fii_sync_count: int | None,
    main_force_buy: int | None,
    market_volume: int | None,       # total market trading volume (張)
    main_force_cost: float | None,
    current_price: float | None,
    top5_concentration: float | None = None,  # 0.0–1.0, None = unavailable
) -> ChipScore:
    """Compute chip momentum score from available fields."""
    cfg    = CHIP_SCORE_CONFIG
    items  = {}
    total  = 0

    # 1. 投量比
    c = cfg["vol_ratio"]
    if main_force_buy is not None and market_volume and market_volume > 0:
        ratio = abs(main_force_buy) / market_volume
        s     = _threshold_score(ratio, c["thresholds"], c["scores"])
        items["vol_ratio"] = {
            "score": s, "max": c["max"],
            "detail": f"主力買超 / 成交量 = {ratio:.1%}",
            "available": True,
        }
    else:
        items["vol_ratio"] = {
            "score": 0, "max": c["max"],
            "detail": "市場成交量資料待補",
            "available": False,
        }
    total += items["vol_ratio"]["score"]

    # 2. 連續買超
    c = cfg["streak"]
    s = _threshold_score(streak, c["thresholds"], c["scores"])
    items["streak"] = {
        "score": s, "max": c["max"],
        "detail": f"連買 {streak} 日",
        "available": True,
    }
    total += s

    # 3. 籌碼集中度
    c = cfg["concentration"]
    if top5_concentration is not None:
        # placeholder — TDCC data not yet wired
        items["concentration"] = {
            "score": 0, "max": c["max"],
            "detail": f"集中度 {top5_concentration:.1%}",
            "available": True,
        }
    else:
        items["concentration"] = {
            "score": 0, "max": c["max"],
            "detail": "TDCC 資料待補",
            "available": False,
        }
    # no total addition — data unavailable

    # 4. 法人同向
    c = cfg["institutional"]
    if fii_sync_count is not None:
        s = _threshold_score(fii_sync_count, c["thresholds"], c["scores"])
        items["institutional"] = {
            "score": s, "max": c["max"],
            "detail": f"{fii_sync_count}/3 方淨買",
            "available": True,
        }
        total += s
    else:
        items["institutional"] = {
            "score": 0, "max": c["max"],
            "detail": "資料待補",
            "available": False,
        }

    # 5. 成本支撐
    c = cfg["cost_support"]
    if main_force_cost and main_force_cost > 0 and current_price and current_price > 0:
        ratio = current_price / main_force_cost
        s     = _threshold_score(1 / ratio if ratio > 0 else 0,
                                  [1/t for t in c["thresholds"]], c["scores"])
        # Simpler: score by price/cost
        if ratio <= 1.02:
            s = c["scores"][0]
        elif ratio <= 1.05:
            s = c["scores"][1]
        else:
            s = c["scores"][2]
        dist = (current_price - main_force_cost) / main_force_cost * 100
        items["cost_support"] = {
            "score": s, "max": c["max"],
            "detail": f"現價距成本 {dist:+.1f}%",
            "available": True,
        }
        total += s
    else:
        items["cost_support"] = {
            "score": 0, "max": c["max"],
            "detail": "主力成本資料待補",
            "available": False,
        }

    # Denominator: only count available items
    available_max = sum(
        v["max"] for v in items.values() if v["available"]
    )

    return ChipScore(total=total, max_total=available_max or 40, items=items)


# ── Volume intelligence ──────────────────────────────────────────────────────

def volume_label(ratio: float | None) -> tuple[str, str]:
    """Return (label_zh, color) for a volume ratio."""
    if ratio is None:
        return "—", "#6B8EAA"
    if ratio >= 3.0:
        return "異常爆量", "#E05C7A"
    if ratio >= 2.0:
        return "健康放量", "#52B788"
    if ratio >= 1.5:
        return "溫和放量", "#7EB8D4"
    if ratio >= 0.8:
        return "正常", "#6B8EAA"
    return "縮量整理", "#D4A84B"
