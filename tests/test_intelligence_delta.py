"""Tests for core/intelligence_delta.py — market-breadth story line (bug fix).

Root cause (verified 2026-07-23): `_build_market_story()` (and the shared
breadth-streak logic in `_diff_market_structure()`) used to read
`snap["market_regime"]["breadth"]`. `market_regime` is a deprecated stub field
that never carried a `breadth` key, so `.get("breadth", 0)` silently returned 0
every single day, baking a fake "市場廣度 0%" line into intelligence.json.

The real SoT is `obs_market_breadth.breadth` (core/market_family.py #41),
which is honestly `None` on data-gap days (old snapshots, fetch failures) —
never coerced to 0.

Covers:
  - real value present  → correct "市場廣度 XX%" line, using obs_market_breadth
  - obs_market_breadth missing/None → the breadth line is skipped entirely
    (not printed as "0%")
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import intelligence_delta as idelta
from core import confidence as _conf


def _make_temp(level: str = "stable", value: float = 0.40) -> _conf.MarketRiskTemperature:
    return _conf.MarketRiskTemperature(
        date="2026-07-22",
        snapshot_count=1,
        temperature=value,
        temperature_level=level,
        temperature_zh="穩定",
        temperature_color="#888888",
        elevated_risk_ratio=0.1,
        distributing_ratio=0.1,
        breadth_signal=0.5,
        total_tracked=100,
        confirmed_count=10,
        strengthening_count=5,
        distributing_count=2,
        high_confidence_low_risk=3,
    )


def test_market_story_uses_real_obs_market_breadth_value():
    """2026-07-22 真值 0.4912 → 故事行印 49% (絕不是 0%)。"""
    snaps_today = [
        {"obs_market_breadth": {"breadth": 0.4912, "advancers": 431, "decliners": 447, "total": 878}},
    ]
    story = idelta._build_market_story(
        all_events=[], today_temp=_make_temp(), today_golden_n=5,
        snaps_today=snaps_today,
    )
    breadth_lines = [s for s in story if "市場廣度" in s]
    assert breadth_lines == ["市場廣度 49%"]


def test_market_story_skips_breadth_line_when_obs_market_breadth_missing():
    """欄位缺(舊快照)或值為 None(抓取失敗)→ 完全不印該行,不可印「市場廣度 0%」。"""
    for snaps_today in (
        [{}],                                               # key entirely absent
        [{"obs_market_breadth": None}],                      # whole field None
        [{"obs_market_breadth": {"breadth": None, "reason": "fetch_failed"}}],  # honest null
    ):
        story = idelta._build_market_story(
            all_events=[], today_temp=_make_temp(), today_golden_n=5,
            snaps_today=snaps_today,
        )
        breadth_lines = [s for s in story if "市場廣度" in s]
        assert breadth_lines == [], f"expected no breadth line for {snaps_today!r}, got {breadth_lines!r}"


def test_market_story_no_snapshots_skips_breadth_line():
    story = idelta._build_market_story(
        all_events=[], today_temp=_make_temp(), today_golden_n=5,
        snaps_today=[],
    )
    assert [s for s in story if "市場廣度" in s] == []


def test_snap_breadth_helper_reads_obs_market_breadth():
    assert idelta._snap_breadth({"obs_market_breadth": {"breadth": 0.7}}) == 0.7
    assert idelta._snap_breadth({"obs_market_breadth": {"breadth": None}}) is None
    assert idelta._snap_breadth({"obs_market_breadth": None}) is None
    assert idelta._snap_breadth({}) is None
    # market_regime stub must never be consulted anymore
    assert idelta._snap_breadth({"market_regime": {"breadth": 0.9}}) is None


def test_diff_market_structure_breadth_streak_ignores_data_gap_days():
    """streak 計算走 obs_market_breadth；缺料日視為不達標(中斷連續),不誤植 0。"""
    snaps_today = [
        {"obs_market_breadth": {"breadth": 0.75}},
        {"obs_market_breadth": {"breadth": 0.80}},
        {"obs_market_breadth": {"breadth": None, "reason": "fetch_failed"}},
    ]
    events = idelta._diff_market_structure(
        snaps_today=snaps_today,
        snaps_yesterday=None,
        today_temp=_make_temp(),
        yest_temp=None,
        today_golden_n=5,
        yest_golden_n=None,
    )
    breadth_events = [e for e in events if e.event_type == idelta.EVT_BREADTH_MILESTONE]
    # latest day is a data gap → streak breaks immediately at 0, no milestone event
    assert breadth_events == []
