"""Temporal Observation Toolkit — replay-safety + correctness.

Two test classes:

  ReplaySafety
    Fingerprints every byte under reports/ before and after running every
    toolkit entry point. Any mutation is a bug.

  Correctness
    Unit tests on the metric primitives with hand-built inputs, plus a few
    sanity checks against the real archive (e.g., streak sums match
    universe sums).

Run:
    cd "Ai stock" && python -m pytest tests/test_temporal_toolkit.py -v
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools.temporal import (  # noqa: E402
    persistence_ranker,
    regime_monitor,
    streak_analyzer,
    temporal_metrics as tm,
    transition_detector,
)
from tools.temporal import _loader  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"


# ---------------------------------------------------------------------------
# Replay-safety fixture
# ---------------------------------------------------------------------------

def _fingerprint_tree(root: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            out[str(f.relative_to(root))] = h.hexdigest()
    return out


@pytest.fixture
def reports_fingerprint() -> dict[str, str]:
    return _fingerprint_tree(REPORTS_DIR)


# ---------------------------------------------------------------------------
# Replay safety
# ---------------------------------------------------------------------------

def test_loader_is_read_only(reports_fingerprint):
    _loader.load_index()
    for d in _loader.real_dates():
        _loader.load_snapshot(d)
        _loader.universe_for_date(d)
        _loader.stocks_for_date(d)
        _loader.audit_events_for_date(d)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_streak_analyzer_is_read_only(reports_fingerprint):
    rows = streak_analyzer.analyze()
    assert isinstance(rows, list)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_transition_detector_is_read_only(reports_fingerprint):
    transition_detector.detect()
    transition_detector.detect(kinds=("TIER",))
    transition_detector.detect(kinds=("PRESENCE",))
    transition_detector.detect(kinds=("CHANGE_PCT_SIGN",))
    transition_detector.reappearance_events()
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_persistence_ranker_is_read_only(reports_fingerprint):
    for m in ("coverage", "stability", "tail_run", "composite"):
        persistence_ranker.rank(m)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_regime_monitor_is_read_only(reports_fingerprint):
    regime_monitor.observe_all()
    regime_monitor.deltas()
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


# ---------------------------------------------------------------------------
# temporal_metrics primitive correctness
# ---------------------------------------------------------------------------

def test_velocity_basic():
    assert tm.velocity([1.0, 2.0]) == 1.0
    assert tm.velocity([1.0, 2.0, 5.0]) == 3.0
    assert tm.velocity([1.0]) is None
    assert tm.velocity([]) is None
    assert tm.velocity([None, 1.0, 3.0]) == 2.0   # Nones skipped


def test_acceleration_basic():
    assert tm.acceleration([1.0, 2.0, 4.0]) == 1.0    # (4-2) - (2-1)
    assert tm.acceleration([1.0, 2.0]) is None
    assert tm.acceleration([None, 1.0, 2.0, 4.0]) == 1.0


def test_persistence_runlengths():
    p = tm.persistence([True, True, False, True, True, True, False])
    assert p["total_days"] == 7
    assert p["present_days"] == 5
    assert p["absent_days"] == 2
    assert p["longest_present_run"] == 3
    assert p["longest_absent_run"] == 1
    assert p["current_run_value"] is False
    assert p["current_run_length"] == 1
    assert p["run_count_present"] == 2
    assert p["run_count_absent"] == 2


def test_persistence_empty():
    p = tm.persistence([])
    assert p["total_days"] == 0
    assert p["longest_present_run"] == 0


def test_transition_frequency():
    assert tm.transition_frequency(["a", "a", "b", "b", "a"]) == 2
    assert tm.transition_frequency(["a", "a", "a"]) == 0
    assert tm.transition_frequency([]) == 0
    assert tm.transition_frequency(["a"]) == 0
    assert tm.transition_frequency([None, "a", "b", None]) == 3


def test_state_volatility_bounds():
    assert tm.state_volatility([]) == 0.0
    assert tm.state_volatility(["a"]) == 0.0
    assert tm.state_volatility(["a", "a"]) == 0.0
    assert tm.state_volatility(["a", "b"]) == 1.0
    assert tm.state_volatility(["a", "b", "a", "b"]) == 1.0  # max flip
    assert 0.0 <= tm.state_volatility(["a", "b", "b", "a", "a"]) <= 1.0


def test_continuity_score():
    assert tm.continuity_score([]) == 0.0
    assert tm.continuity_score([True, True, True]) == 1.0
    assert tm.continuity_score([False, False, False]) == 0.0
    assert tm.continuity_score([True, False, True, False]) == 0.5


def test_streak_stability():
    assert tm.streak_stability([True, True, True]) == 1.0       # one run
    assert tm.streak_stability([True, False, True]) == 0.5      # two present runs
    assert tm.streak_stability([True, False, True, False, True]) == 1.0 / 3
    assert tm.streak_stability([False, False, False]) == 1.0    # vacuous


def test_current_and_max_streak():
    assert tm.current_streak([True, True, True]) == 3
    assert tm.current_streak([True, False, True]) == 1
    assert tm.current_streak([True, False, False]) == 0
    assert tm.max_streak([True, True, False, True]) == 2
    assert tm.max_streak([]) == 0


# ---------------------------------------------------------------------------
# Sanity checks against the real archive
# ---------------------------------------------------------------------------

def test_streak_sums_match_universe_sums():
    dates = _loader.real_dates()
    if not dates:
        pytest.skip("no snapshots")
    total_universe = sum(len(_loader.universe_for_date(d)) for d in dates)
    rows = streak_analyzer.analyze()
    total_app = sum(r.appearances for r in rows)
    assert total_app == total_universe


def test_persistence_ranker_modes_all_return_same_tickers():
    base = {r.ticker for r in persistence_ranker.rank("coverage")}
    for m in ("stability", "tail_run", "composite"):
        assert {r.ticker for r in persistence_ranker.rank(m)} == base


def test_regime_observations_count_consistent_with_universe():
    obs = regime_monitor.observe_all()
    dates = _loader.real_dates()
    assert len(obs) == len(dates)
    for o, d in zip(obs, dates):
        assert o.universe_size == len(_loader.universe_for_date(d))
        # positive + negative + flat + unknown == universe_size
        assert (o.positive_count + o.negative_count
                + o.flat_count + o.unknown_count) == o.universe_size


def test_regime_deltas_one_less_than_observations():
    dates = _loader.real_dates()
    if len(dates) < 2:
        pytest.skip("need >= 2 snapshots")
    assert len(regime_monitor.deltas()) == len(dates) - 1


def test_transition_detector_at_p3a_has_no_tier_changes():
    """All tiers are IGNORE at P3a; TIER transitions must be empty."""
    tier_changes = transition_detector.detect(kinds=("TIER",))
    assert tier_changes == [], (
        f"Unexpected tier transitions at P3a: {len(tier_changes)}"
    )


def test_reappearance_event_distinguishes_enter_from_reappear():
    events = transition_detector.reappearance_events()
    for e in events:
        assert e.notes in {"ENTER"} or e.notes.startswith("REAPPEAR_after_")
        assert e.from_state == "absent"
        assert e.to_state == "present"
