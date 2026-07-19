"""As-was engine_params replay tests (C10/C11).

A forward-only tweak to a judgment parameter in core/engine_params.py (the real
incident: MC_TRANSITION_BREADTH_DELTA 0.25→0.10) must NOT retroactively break the
full replay of historical snapshots. tools/verify_all_replay.py recomputes each
date with the config the snapshot RECORDED (config_snapshot.engine_params), never
HEAD's live module. These tests lock that behaviour AND the from-import trap.

Run:
    cd "Ai stock" && python -m pytest tests/test_replay_as_was_params.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
import yaml

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import engine_params  # noqa: E402
from core import distribution  # noqa: E402
from core.ingest import SCHEMA_VERSION  # noqa: E402
from data.adapters.legacy import legacy_paths  # noqa: E402
from tools import verify_all_replay as v  # noqa: E402


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(v.CONFIG_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return json.loads(v.INDEX_FILE.read_text(encoding="utf-8"))


def _pick_full_replay_date(index: dict) -> tuple[str, dict, dict]:
    """Return (date, index_entry, on_disk_snapshot) for a full-replay date whose
    recorded MC_TRANSITION_BREADTH_DELTA diverges from HEAD's live value — the
    strongest as-was case (recorded ≠ live). Falls back to any full-replay date.
    """
    live = getattr(engine_params, "MC_TRANSITION_BREADTH_DELTA")
    fallback = None
    for d in sorted(index["snapshots"].keys()):
        if not v._is_iso_date(d):
            continue
        entry = index["snapshots"][d]
        snap = json.loads((v.REPORTS_DIR / entry["current"]).read_text(encoding="utf-8"))
        if snap.get("schema_version") != SCHEMA_VERSION:
            continue
        fallback = fallback or (d, entry, snap)
        recorded = snap.get("config_snapshot", {}).get("engine_params", {})
        if recorded.get("MC_TRANSITION_BREADTH_DELTA") != live:
            return d, entry, snap
    if fallback is None:
        pytest.skip("no full-replay (current-schema) snapshot in index")
    return fallback


def test_full_replay_uses_recorded_params_not_live(cfg, index, monkeypatch):
    """With the live parameter set to a divergent junk value, a real snapshot must
    still replay clean — because full_replay_hash recomputes with the RECORDED
    value from the snapshot's config_snapshot, not the live module."""
    d, entry, snap = _pick_full_replay_date(index)
    repo_root = legacy_paths()["root"]
    window = cfg.get("temporal", {}).get("lookback_window_days", 5)

    junk = 0.999  # differs from both 0.25 and 0.10; guarantees live ≠ recorded
    monkeypatch.setattr(engine_params, "MC_TRANSITION_BREADTH_DELTA", junk)

    h_replay = v.full_replay_hash(d, snap, cfg, repo_root, index, window)
    assert h_replay == entry["current_hash"], (
        f"{d} did not replay clean with live param patched to junk; "
        f"replay must use the snapshot-recorded value, not the live module"
    )

    # The patch must be fully restored: after the call the live value is back to
    # OUR junk (the value at context entry), never leaking the recorded value.
    assert getattr(engine_params, "MC_TRANSITION_BREADTH_DELTA") == junk


def test_params_as_recorded_reaches_from_import_site(monkeypatch):
    """The from-import trap: DIST_AUTO_FILTER_MARGIN_MIN is copied into
    distribution.AUTO_FILTER_MARGIN_MIN at import time. Patching only the
    engine_params attribute would miss it. _params_as_recorded must rebind BOTH
    the engine_params attr and the from-import alias, then restore both."""
    orig = getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN")
    wrong = orig + 0.5  # simulate a live value that diverges from the record

    # Live (HEAD) now holds `wrong` at both binding sites.
    monkeypatch.setattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN", wrong)
    monkeypatch.setattr(distribution, "AUTO_FILTER_MARGIN_MIN", wrong)

    recorded = {"DIST_AUTO_FILTER_MARGIN_MIN": orig}  # the snapshot recorded `orig`
    with v._params_as_recorded(recorded):
        assert getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN") == orig
        # The whole point: the from-import site is patched too, not just the module.
        assert distribution.AUTO_FILTER_MARGIN_MIN == orig

    # Both sites restored to the live (entry) value, not left at `orig`.
    assert getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN") == wrong
    assert distribution.AUTO_FILTER_MARGIN_MIN == wrong


def test_params_as_recorded_noop_when_matching(monkeypatch):
    """A recorded value that canonically equals live must NOT be patched, and a
    None record is a clean no-op (pre-1.9.0 defensive fallback)."""
    orig = getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN")
    with v._params_as_recorded({"DIST_AUTO_FILTER_MARGIN_MIN": orig}):
        assert getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN") == orig
    with v._params_as_recorded(None):
        pass
    assert getattr(engine_params, "DIST_AUTO_FILTER_MARGIN_MIN") == orig
