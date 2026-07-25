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


# ─────────────────────────────────────────────────────────────────────────────
# REPLAY DETERMINISM — the patch window must not poison a lazily-imported site
# ─────────────────────────────────────────────────────────────────────────────
# Incident (2026-07-24, P0): `python3 tools/verify_all_replay.py` reported a hash
# mismatch for 2026-07-24 while `run_pipeline --check-replay` passed. Root cause: the
# patcher used to call importlib.import_module() *after* rebinding engine_params, so a
# site module not yet in sys.modules (all of chip_score / distribution / state_machine /
# funnel — ingest imports obs_landing lazily) executed its own
# `from core.engine_params import <KEY>` against the PATCHED value. Its module-level
# binding was born holding the recorded value, `_set` saved that as `old`, and the
# `finally` made it permanent — the live parameter was gone for every later date in the
# same process, and `_canon_equal` (which only reads the correctly-restored
# engine_params) waved those dates through unpatched.
#
# WHY SUBPROCESSES ARE MANDATORY HERE: importing core.chip_score before the patch runs
# is the *cure*. Any in-process test would be cured by its own imports (and by
# tests/test_chip_score.py during a full run) and would pass even with the bug present
# — exactly why the existing from-import tests above never caught this. Every assertion
# below therefore runs in a cold interpreter that imports nothing from core/ up front.

_COLD_PROBE_PREAMBLE = f"""
import copy, json, sys
sys.path.insert(0, {str(_AI_STOCK)!r})
import tools.verify_all_replay as v
from core import engine_params as ep
_cold = [m for m in ("core.chip_score", "core.distribution", "core.state_machine",
                     "core.funnel", "core.market_state") if m in sys.modules]
assert not _cold, "probe invalidated: site modules pre-imported: %s" % _cold
"""


def _run_cold(body: str, *args: str) -> dict:
    """Execute `body` in a cold interpreter and return its JSON stdout."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", _COLD_PROBE_PREAMBLE + body, *args],
        cwd=str(_AI_STOCK), capture_output=True, text=True, timeout=900,
    )
    assert proc.returncode == 0, (
        f"cold probe crashed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


_SITE_BINDING_PROBE = """
def divergent(x):
    if isinstance(x, dict):
        d = copy.deepcopy(x); d["__divergence_probe__"] = 1; return d
    if isinstance(x, bool):
        return not x
    if isinstance(x, (int, float)):
        return x + 1
    if isinstance(x, (list, tuple)):
        return list(x) + ["__divergence_probe__"]
    return x

bad = []
for key, sites in v._FROM_IMPORT_SITES.items():
    live = getattr(ep, key)
    # Patch with a value guaranteed to canonically diverge → the patch path runs.
    with v._params_as_recorded({key: divergent(live)}):
        pass
    # After restore every site must be bound to the SAME object engine_params holds.
    for mod_name, attr in sites:
        mod = sys.modules.get(mod_name)
        if mod is None or not hasattr(mod, attr):
            continue
        site_val = getattr(mod, attr)
        if site_val is not getattr(ep, key):
            bad.append({
                "key": key, "site": mod_name + "." + attr,
                "site_canonically_equals_live":
                    v._canon_equal(site_val, getattr(ep, key)),
                "site_repr": repr(site_val)[:160],
            })
cap_key = "impossible_ratio_cap"
cs = sys.modules.get("core.chip_score")
print(json.dumps({
    "poisoned_sites": bad,
    "cap_in_engine_params": ep.CHIP_SCORE_CONFIG["vol_ratio"].get(cap_key, "MISSING"),
    "cap_seen_by_chip_score": (cs.CHIP_SCORE_CONFIG["vol_ratio"].get(cap_key, "MISSING")
                               if cs is not None else "module-not-imported"),
}))
"""


def test_patch_window_never_poisons_a_lazily_imported_site():
    """DETERMINISM P0: patching a parameter must leave every from-import site bound
    to the LIVE object, even when the site module's first import is triggered by the
    patcher itself. Runs cold — see the note above."""
    res = _run_cold(_SITE_BINDING_PROBE)
    assert res["poisoned_sites"] == [], (
        "from-import site(s) left bound to the RECORDED value after restore — "
        "the patch window poisoned a lazily-imported module: "
        f"{json.dumps(res['poisoned_sites'], ensure_ascii=False, indent=2)}"
    )
    # The concrete 2026-07-24 symptom: core/chip_score.py's C-2 vol_ratio guard
    # silently vanished for the rest of the process.
    assert res["cap_seen_by_chip_score"] == res["cap_in_engine_params"], (
        "chip_score sees a different vol_ratio.impossible_ratio_cap than "
        f"engine_params: {res!r}"
    )


_ORDER_PROBE = """
import yaml
from core.ingest import SCHEMA_VERSION
from data.adapters.legacy import legacy_paths

cfg = yaml.safe_load(v.CONFIG_FILE.read_text(encoding="utf-8"))
window = cfg.get("temporal", {}).get("lookback_window_days", 5)
index = json.loads(v.INDEX_FILE.read_text(encoding="utf-8"))
repo_root = legacy_paths()["root"]

out = {}
for d in sys.argv[1:]:
    snap = json.loads((v.REPORTS_DIR / index["snapshots"][d]["current"]).read_text(
        encoding="utf-8"))
    try:
        out[d] = v.full_replay_hash(d, snap, cfg, repo_root, index, window)
    except Exception as e:                      # a poisoner that errors still patched
        out[d] = "ERROR: %s" % e
print(json.dumps(out))
"""


def _current_schema_dates(index: dict) -> list[str]:
    out = []
    for d in sorted(k for k in index["snapshots"] if v._is_iso_date(k)):
        snap = json.loads((v.REPORTS_DIR / index["snapshots"][d]["current"]).read_text(
            encoding="utf-8"))
        if snap.get("schema_version") == SCHEMA_VERSION:
            out.append((d, snap))
    return out


def test_replay_hash_is_independent_of_previously_replayed_dates(index):
    """DETERMINISM P0 (end-to-end): a date's full-replay hash must be identical
    whether it is replayed alone or after other dates in the SAME process.

    Target = newest current-schema date whose recorded CHIP_SCORE_CONFIG canonically
    EQUALS live (so `_canon_equal` skips it → it relies on the live bindings being
    pristine, i.e. the exact victim class). Poisoner = an earlier date whose recorded
    value diverges (so the patch path — and formerly the poisoning — runs)."""
    dates = _current_schema_dates(index)
    if len(dates) < 2:
        pytest.skip("need ≥2 current-schema snapshots to test replay order independence")

    live_chip = getattr(engine_params, "CHIP_SCORE_CONFIG")

    def recorded_chip(snap):
        return snap.get("config_snapshot", {}).get("engine_params", {}).get(
            "CHIP_SCORE_CONFIG")

    equal_dates = [d for d, s in dates
                   if recorded_chip(s) is not None
                   and v._canon_equal(recorded_chip(s), live_chip)]
    diverging = [d for d, s in dates
                 if recorded_chip(s) is not None
                 and not v._canon_equal(recorded_chip(s), live_chip)]

    target = equal_dates[-1] if equal_dates else dates[-1][0]
    poisoners = [d for d in (diverging or [d for d, _ in dates]) if d != target][:1]
    if not poisoners:
        pytest.skip("no second snapshot available to replay before the target")

    alone = _run_cold(_ORDER_PROBE, target)
    after = _run_cold(_ORDER_PROBE, *poisoners, target)

    expected = index["snapshots"][target]["current_hash"]
    assert alone[target] == expected, (
        f"{target} does not replay clean even in isolation "
        f"(alone={alone[target]} expected={expected}) — not an ordering bug"
    )
    assert after[target] == alone[target], (
        f"replay of {target} is ORDER-DEPENDENT: alone={alone[target]} "
        f"but after replaying {poisoners}={after[target]} "
        f"(expected {expected}) — cross-date module state leaked"
    )
