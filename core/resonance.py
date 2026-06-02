"""
core/resonance.py — Institutional Resonance Engine

Observes whether multiple institutional participants are net-positive
on the same ticker across consecutive snapshots.

Outputs per ticker:
    resonance_level    0–3  (how many participants net positive)
    resonance_members  list of participant names
    resonance_streak   consecutive days with resonance_level >= 2
    resonance_label_zh Chinese label
    resonance_strength 0–100 composite score

Data inputs (from snapshot stocks):
    main_force_buy     主力淨買（張）      — reliably populated
    fii_net_buy        外資淨買（張）      — currently None in pipeline
    dealer_net_buy     投信淨買（張）      — currently None in pipeline

When a field is None it is excluded from participant count.
The module degrades gracefully: single participant → level 1, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Participant definitions ──────────────────────────────────────────────────

_PARTICIPANTS = [
    ("main_force",   "main_force_buy",  "主力"),
    ("foreign",      "fii_net_buy",     "外資"),   # from T86 t86["foreign"]
    ("invest_trust", "dealer_net_buy",  "投信"),   # from T86 t86["trust"] via dealer_net_buy
]

_LEVEL_LABELS = {
    0: "無共振",
    1: "單方買盤",
    2: "雙方共振",
    3: "三方共振",
}

_LEVEL_STARS = {
    0: "",
    1: "★",
    2: "★★",
    3: "★★★",
}


# ── Output dataclass ─────────────────────────────────────────────────────────

@dataclass
class ResonanceState:
    ticker:           str
    resonance_level:  int                  # 0 = none … 3 = triple
    resonance_members: list[str]           # e.g. ["main_force", "foreign"]
    resonance_streak: int                  # consecutive days level >= 2
    resonance_label_zh: str               # 無共振 / 單方買盤 / 雙方共振 / 三方共振
    resonance_strength: int               # 0–100
    # Per-participant status for display
    participant_status: dict[str, bool | None] = field(default_factory=dict)
    # e.g. {"main_force": True, "foreign": False, "invest_trust": None}

    @property
    def stars(self) -> str:
        return _LEVEL_STARS.get(self.resonance_level, "")

    def badge_html(self) -> str:
        """Compact HTML badge for golden card display."""
        if self.resonance_level == 0:
            return ""
        level_col = {1: "#6B8EAA", 2: "#7EB8D4", 3: "#D4A84B"}.get(
            self.resonance_level, "#6B8EAA"
        )
        stars     = self.stars
        label     = self.resonance_label_zh
        streak_s  = f"連續 {self.resonance_streak} 日" if self.resonance_streak >= 2 else ""

        # Member checkmarks
        member_parts = []
        for pid, _, zh in _PARTICIPANTS:
            status = self.participant_status.get(pid)
            if status is True:
                member_parts.append(f'<span style="color:#52B788;">{zh}✓</span>')
            elif status is False:
                member_parts.append(f'<span style="color:#3A4A5A;">{zh}✗</span>')
            else:
                member_parts.append(f'<span style="color:#4A5A6A;">{zh}—</span>')
        members_html = " ".join(member_parts)

        return (
            f'<div style="display:inline-flex;flex-direction:column;gap:2px;'
            f'padding:5px 9px;border-radius:7px;'
            f'background:{level_col}15;border:1px solid {level_col}40;'
            f'font-size:11px;margin-top:4px;">'
            f'<div style="color:{level_col};font-weight:700;">'
            f'{stars} {label}'
            + (f'&nbsp;&nbsp;<span style="color:#6B8EAA;font-size:10px;">{streak_s}</span>'
               if streak_s else "")
            + f'</div>'
            f'<div style="color:#8B949E;">{members_html}</div>'
            f'</div>'
        )


# ── Core computation ─────────────────────────────────────────────────────────

def _participant_sign(stock: dict[str, Any], field_name: str) -> bool | None:
    """Return True (positive), False (negative/zero), or None (missing data)."""
    v = stock.get(field_name)
    if v is None:
        return None
    return v > 0


def _resonance_for_stock(ticker: str, snapshots: list[dict]) -> ResonanceState:
    """Compute resonance state for one ticker across all snapshots."""
    if not snapshots:
        return ResonanceState(
            ticker=ticker, resonance_level=0, resonance_members=[],
            resonance_streak=0, resonance_label_zh="無共振",
            resonance_strength=0,
        )

    # Build per-day resonance levels (newest last)
    daily_levels: list[int] = []
    latest_status: dict[str, bool | None] = {}

    for snap in snapshots:
        stock = next(
            (s for s in snap.get("stocks", []) if s.get("ticker") == ticker),
            None,
        )
        if stock is None:
            daily_levels.append(0)
            continue

        members = []
        status  = {}
        for pid, fname, _ in _PARTICIPANTS:
            sign = _participant_sign(stock, fname)
            status[pid] = sign
            if sign is True:
                members.append(pid)

        level = len(members)
        daily_levels.append(level)
        latest_status = status

    # Current resonance (latest snapshot)
    cur_level   = daily_levels[-1] if daily_levels else 0
    cur_members = [
        pid for pid, _, _ in _PARTICIPANTS
        if latest_status.get(pid) is True
    ]

    # Streak: consecutive days (going back from latest) where level >= 2
    streak = 0
    for lv in reversed(daily_levels):
        if lv >= 2:
            streak += 1
        else:
            break

    # Resonance strength 0–100
    # Base: level × 25 (0/25/50/75)
    # Bonus: streak days (up to +25)
    strength = min(100, cur_level * 25 + min(streak * 5, 25))

    return ResonanceState(
        ticker=ticker,
        resonance_level=cur_level,
        resonance_members=cur_members,
        resonance_streak=streak,
        resonance_label_zh=_LEVEL_LABELS.get(cur_level, "未知"),
        resonance_strength=strength,
        participant_status=latest_status,
    )


# ── Public API ───────────────────────────────────────────────────────────────

def run_all(snapshots: list[dict]) -> dict[str, ResonanceState]:
    """
    Compute resonance state for every ticker that appears in the
    latest snapshot.

    Returns: dict mapping ticker → ResonanceState
    """
    if not snapshots:
        return {}

    latest_tickers = [
        s["ticker"]
        for s in snapshots[-1].get("stocks", [])
        if s.get("ticker")
    ]

    return {
        ticker: _resonance_for_stock(ticker, snapshots)
        for ticker in latest_tickers
    }


def run_one(ticker: str, snapshots: list[dict]) -> ResonanceState:
    """Compute resonance for a single ticker."""
    return _resonance_for_stock(ticker, snapshots)
