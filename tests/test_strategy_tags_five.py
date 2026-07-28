"""Tests for the五支策略 strategy_tags sidecar (Yonki 2026-07-28 任務 A).

_write_strategy_tags() used to hardcode {"A": STRATEGY_A, "B": STRATEGY_B} —
v2/v3 never produced badges. This locks the fix in:

  (1) sidecar["strategies"] covers all five keys (A/B/A2/B2/A3), each mapped
      to the single source of truth core.strategies.ALL_STRATEGIES.
  (2) existing "A"/"B" semantics are byte-identical to before (viewer/older
      sidecars depend on them — governance redline).
  (3) exactly chip_anchored_v3 (key "A3") carries research=true (4.3:研究待審,
      非上線); the other four are research=false.
  (4) the key map can never silently drop a strategy: if ALL_STRATEGIES grows
      a 6th entry without updating _STRATEGY_TAG_KEYS, the pipeline must
      abstain from writing the sidecar rather than emit an incomplete one
      (best proven by covering the current map to guard against regressing
      that assertion).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.strategies import ALL_STRATEGIES  # noqa: E402
from tools import run_pipeline  # noqa: E402

_EXPECTED_KEY_TO_NAME = {
    "A": "chip_anchored_swing",
    "B": "momentum_continuation",
    "A2": "chip_anchored_v2",
    "B2": "momentum_v2",
    "A3": "chip_anchored_v3",
}


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    """Mirrors tests/test_run_pipeline.py's fixture — redirect every write
    target so this test can never touch the real (read-only) reports/."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(run_pipeline, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(run_pipeline, "STRATEGY_TAGS_DIR", reports_dir / "strategy_tags")
    return reports_dir


def _write_min_snapshot(reports_dir: pathlib.Path, date: str) -> None:
    (reports_dir / f"{date}.json").write_text(
        json.dumps({"date": date, "stocks": []}), encoding="utf-8")


def test_key_map_covers_exactly_all_strategies():
    """_STRATEGY_TAG_KEYS is the single source for the sidecar's key layout —
    it must map onto ALL_STRATEGIES with no gaps and no extras."""
    assert set(run_pipeline._STRATEGY_TAG_KEYS) == set(_EXPECTED_KEY_TO_NAME)
    assert run_pipeline._STRATEGY_TAG_KEYS == _EXPECTED_KEY_TO_NAME
    assert set(run_pipeline._STRATEGY_TAG_KEYS.values()) == set(ALL_STRATEGIES)


def test_write_strategy_tags_covers_all_five_strategies(tmp_reports):
    date = "2026-07-27"
    _write_min_snapshot(tmp_reports, date)

    run_pipeline._write_strategy_tags(date)

    out_path = tmp_reports / "strategy_tags" / f"{date}.json"
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    strategies = payload["strategies"]
    assert set(strategies) == set(_EXPECTED_KEY_TO_NAME)
    for k, name in _EXPECTED_KEY_TO_NAME.items():
        cfg = ALL_STRATEGIES[name]
        assert strategies[k]["name"] == name
        assert strategies[k]["zh"] == cfg.zh
        assert strategies[k]["kind"] == cfg.kind


def test_a_and_b_semantics_unchanged():
    """"A"/"B" keys must keep mapping to the exact same strategies as before
    this change (viewer badges + older on-disk sidecars depend on this)."""
    assert run_pipeline._STRATEGY_TAG_KEYS["A"] == "chip_anchored_swing"
    assert run_pipeline._STRATEGY_TAG_KEYS["B"] == "momentum_continuation"


def test_only_v3_is_flagged_research(tmp_reports):
    """4.3(core/strategies.py STRATEGY_A_V3 docstring):研究待審,非上線 — only
    chip_anchored_v3 ("A3") should carry research=true."""
    date = "2026-07-27"
    _write_min_snapshot(tmp_reports, date)

    run_pipeline._write_strategy_tags(date)

    payload = json.loads((tmp_reports / "strategy_tags" / f"{date}.json").read_text(encoding="utf-8"))
    strategies = payload["strategies"]
    assert strategies["A3"]["research"] is True
    for k in ("A", "B", "A2", "B2"):
        assert strategies[k]["research"] is False, f"{k} should not be flagged research"


def test_sidecar_generation_never_raises_on_key_map_drift(tmp_reports, monkeypatch):
    """If _STRATEGY_TAG_KEYS ever drifts out of sync with ALL_STRATEGIES, the
    guard assertion inside _write_strategy_tags must be swallowed by the
    outer try/except (display sidecar must never block the pipeline) —
    proven here by deliberately breaking the map."""
    date = "2026-07-27"
    _write_min_snapshot(tmp_reports, date)
    monkeypatch.setattr(run_pipeline, "_STRATEGY_TAG_KEYS", {"A": "chip_anchored_swing"})

    run_pipeline._write_strategy_tags(date)  # must not raise

    out_path = tmp_reports / "strategy_tags" / f"{date}.json"
    assert not out_path.exists(), "drifted key map should abstain, not emit a partial sidecar"
