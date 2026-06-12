"""P2 — action grouping tests (行動分組: core business logic, UI renders only)."""
from __future__ import annotations

import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import golden  # noqa: E402


def _entry(**kw):
    base = dict(
        ticker="9999", name="測試", tier="prime", tier_zh="頂級黃金",
        tier_en="Prime", tier_color="#F4C842", conviction=0.7,
        funnel_layer="confirmation", sm_state="confirmed", sm_state_zh="成熟確認",
        sm_state_color="#7EB8D4", transition_risk="low", transition_risk_zh="低風險",
        transition_risk_color="#52B788", streak=5, net_cumulative=10000,
        velocity_3d=100.0, acceleration=10.0, sponsorship_score=0.7,
        sector="financials", is_tier_a=False,
        current_price=100.0, cost_conservative=98.0,
    )
    base.update(kw)
    return golden.GoldenEntry(**base)


def test_executable_within_premium():
    # 100 ≤ 98 × 1.05 = 102.9 → executable
    assert golden.action_group(_entry()) == golden.ACTION_EXECUTABLE


def test_wait_pullback_when_extended():
    e = _entry(current_price=110.0, cost_conservative=98.0)  # 110 > 102.9
    assert golden.action_group(e) == golden.ACTION_WAIT_PULLBACK


def test_weakening_on_red_severity():
    assert golden.action_group(_entry(), weakening_severity="red") == golden.ACTION_WEAKENING


def test_weakening_on_orange_severity():
    assert golden.action_group(_entry(), weakening_severity="orange") == golden.ACTION_WEAKENING


def test_yellow_severity_does_not_force_weakening():
    assert golden.action_group(_entry(), weakening_severity="yellow") == golden.ACTION_EXECUTABLE


def test_weakening_on_distributing_state():
    e = _entry(sm_state="distributing")
    assert golden.action_group(e) == golden.ACTION_WEAKENING


def test_decelerating_stays_price_based():
    e = _entry(sm_state="decelerating")
    assert golden.action_group(e) == golden.ACTION_EXECUTABLE


def test_data_pending_on_skeleton_cap():
    e = _entry(tier_caps=["CAP_skeleton_data"])
    assert golden.action_group(e) == golden.ACTION_DATA_PENDING


def test_data_pending_when_no_anchor():
    e = _entry(cost_conservative=None, main_force_cost=None)
    assert golden.action_group(e) == golden.ACTION_DATA_PENDING
    e2 = _entry(current_price=None)
    assert golden.action_group(e2) == golden.ACTION_DATA_PENDING


def test_anchor_falls_back_to_main_force_cost():
    e = _entry(cost_conservative=None, main_force_cost=99.0)
    assert golden.action_group(e) == golden.ACTION_EXECUTABLE


def test_weakening_priority_over_skeleton():
    e = _entry(tier_caps=["CAP_skeleton_data"])
    assert golden.action_group(e, weakening_severity="red") == golden.ACTION_WEAKENING


def test_action_meta_covers_all_groups():
    assert set(golden.ACTION_ORDER) == set(golden.ACTION_META.keys())
