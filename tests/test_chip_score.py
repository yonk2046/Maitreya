"""Contract tests for core/chip_score.py (T5 — pure scoring helpers).

Locks the public contract of the chip momentum score: threshold mapping,
volume labels, the available-only denominator, and grade banding. These are
pure functions (no I/O), so the tests are deterministic and fast.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import chip_score  # noqa: E402
from core.chip_score import ChipScore, _threshold_score, compute, volume_label  # noqa: E402


# ── _threshold_score ──────────────────────────────────────────────────────────

def test_threshold_score_picks_first_met_descending():
    # streak config: thresholds [7,5,3,1] → scores [10,8,6,3,0]
    thresholds = [7, 5, 3, 1]
    scores = [10, 8, 6, 3, 0]
    assert _threshold_score(8, thresholds, scores) == 10
    assert _threshold_score(7, thresholds, scores) == 10   # boundary inclusive
    assert _threshold_score(6, thresholds, scores) == 8
    assert _threshold_score(5, thresholds, scores) == 8    # boundary inclusive
    assert _threshold_score(4, thresholds, scores) == 6
    assert _threshold_score(3, thresholds, scores) == 6
    assert _threshold_score(2, thresholds, scores) == 3
    assert _threshold_score(1, thresholds, scores) == 3
    assert _threshold_score(0, thresholds, scores) == 0    # below all → last


# ── volume_label ──────────────────────────────────────────────────────────────

def test_volume_label_none_is_placeholder():
    label, color = volume_label(None)
    assert label == "—"
    assert color.startswith("#")


def test_volume_label_boundaries():
    assert volume_label(3.0)[0] == "異常爆量"
    assert volume_label(2.5)[0] == "健康放量"
    assert volume_label(2.0)[0] == "健康放量"   # boundary inclusive
    assert volume_label(1.5)[0] == "溫和放量"   # boundary inclusive
    assert volume_label(1.2)[0] == "正常"
    assert volume_label(0.8)[0] == "正常"        # boundary inclusive
    assert volume_label(0.5)[0] == "縮量整理"


# ── compute(): available-only denominator ──────────────────────────────────────

def test_compute_streak_only_denominator():
    # Everything missing except streak → denominator is just streak.max (10).
    cs = compute(
        streak=7, sponsorship=0.0, fii_sync_count=None,
        main_force_buy=None, market_volume=None,
        main_force_cost=None, current_price=None,
    )
    assert cs.items["streak"]["available"] is True
    assert cs.items["vol_ratio"]["available"] is False
    assert cs.items["institutional"]["available"] is False
    assert cs.items["cost_support"]["available"] is False
    assert cs.max_total == 10            # only the available item counts
    assert cs.total == 10                # streak >= 7 → 10
    assert cs.grade == "強"              # pct == 1.0


def test_compute_full_available_set():
    cs = compute(
        streak=7, sponsorship=0.0, fii_sync_count=3,
        main_force_buy=200, market_volume=1000,   # ratio 0.2 ≥ 0.12 → 8
        main_force_cost=100.0, current_price=101.0,  # ratio 1.01 ≤ 1.02 → 6
    )
    # vol_ratio(8) + streak(10) + institutional(8) + cost_support(6) = 32
    # concentration stays unavailable (top5 None) so it is NOT in denominator.
    assert cs.total == 32
    assert cs.max_total == 32
    assert cs.grade == "強"


def test_compute_concentration_available_lowers_pct():
    # Providing top5_concentration makes the item available (max 8, score 0),
    # so it expands the denominator and drags the grade down.
    cs = compute(
        streak=7, sponsorship=0.0, fii_sync_count=None,
        main_force_buy=None, market_volume=None,
        main_force_cost=None, current_price=None,
        top5_concentration=0.5,
    )
    assert cs.items["concentration"]["available"] is True
    assert cs.max_total == 18         # streak(10) + concentration(8)
    assert cs.total == 10             # concentration contributes 0
    assert cs.grade == "弱"           # 10/18 ≈ 0.556 < 0.60


# ── ChipScore grade banding (post_init) ─────────────────────────────────────────

def test_chipscore_grade_bands():
    assert ChipScore(total=32, max_total=40).grade == "強"   # 0.80 inclusive
    assert ChipScore(total=24, max_total=40).grade == "中"   # 0.60 inclusive
    assert ChipScore(total=23, max_total=40).grade == "弱"   # < 0.60
    assert ChipScore(total=0,  max_total=40).grade == "弱"


def test_chipscore_bar_html_contains_total():
    cs = ChipScore(total=30, max_total=40)
    html = cs.bar_html()
    assert "30/40" in html
    assert isinstance(html, str)


def test_chip_score_config_shape():
    # Sum of all item maxes is the canonical 40-point scale.
    cfg = chip_score.CHIP_SCORE_CONFIG
    assert sum(c["max"] for c in cfg.values()) == 40
