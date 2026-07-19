"""Walk every dated snapshot in reports/index.json and verify it still replays.

REPLAY-FROM-ARCHIVE: the verifier reads raw bytes from the immutable archive
at `reports/_raw_archive/<date>/<source_id>/` — NOT from live `data/`, which
is mutated by every upstream fetch. This is the whole reason the archive
exists; without it, daily upstream re-fetches would silently break the
replay legitimacy claim every time.

For each real ISO date in the index:
  1. Read the on-disk snapshot to discover which adapter it used and where
     its archived raw inputs live.
  2. Re-run that adapter against archived paths (paths_override / rollup_path
     pointing at the archive).
  3. Run ingest, then archive_raw_inputs(verify_only=True) — stamps the
     same archive metadata without touching the archive bytes.
  4. Normalize generated_at against the on-disk snapshot.
  5. Compare canonical_sha256 against index.current_hash.

A mismatch means real corruption: the snapshot bytes, the archive bytes,
the ingest logic, or the canonical hashing rule has drifted.

EPOCH-AWARE VERIFICATION (B1 fix, 2026-06-11):
Full replay re-runs ingest with HEAD code, so it can only legitimately
reproduce snapshots generated under the CURRENT schema version. Snapshots
from older schema epochs (e.g. 1.4.0 history after the 1.5.0 bump) would
mismatch by construction — that is schema evolution, not corruption.

  - schema_version == current  → FULL replay (adapter + ingest + hash compare)
  - schema_version != current  → LEGACY check: on-disk canonical hash must
    still equal index.current_hash (detects byte tampering / index drift,
    which is the only corruption class that applies to a frozen epoch).

AS-WAS CONFIG (C10/C11 fix, 2026-07-20):
Judgment thresholds/weights live in core/engine_params.py and, since 1.9.0,
are frozen into every snapshot's config_snapshot (the two-source {yaml,
engine_params} structure) and participate in the canonical hash. A forward-only
tweak to any live parameter (e.g. MC_TRANSITION_BREADTH_DELTA 0.25→0.10) must
NOT retroactively break historical replay. So full replay recomputes each date
with the config the SNAPSHOT RECORDED — its config_snapshot["yaml"] dict and
config_snapshot["engine_params"] values — never HEAD's live engine_params module
or the live config/scd.example.yaml file. Parameter changes are forward-only;
replay is as-was. See _resolve_replay_config / _params_as_recorded below.

Exit codes:
  0 — every date passes its applicable check
  1 — at least one date fails (replay mismatch or legacy hash drift)
"""
from __future__ import annotations

import contextlib
import importlib
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
sys.path.insert(0, str(_AI_STOCK))

import yaml  # noqa: E402

from core import engine_params  # noqa: E402
from core.archive import archive_raw_inputs  # noqa: E402
from core.hashing import canonical_bytes, canonical_sha256  # noqa: E402
from core.ingest import SCHEMA_VERSION, ingest  # noqa: E402
from core.replay_contract import normalize_for_replay_compare  # noqa: E402
from core.replay_ledger import (  # noqa: E402
    current_env_fingerprint,
    env_drift,
    latest_entry_for,
    load_ledger,
)
from data.adapters.legacy import adapt_legacy, legacy_paths  # noqa: E402
from data.adapters.rollup import adapt_rollup  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"
CONFIG_FILE = _AI_STOCK / "config" / "scd.example.yaml"
RAW_ARCHIVE_DIR = REPORTS_DIR / "_raw_archive"
REPLAY_LEDGER_FILE = REPORTS_DIR / "_replay_ledger.json"

# Sentinel date that precedes every TDCC weekly cache file. Passed as tdcc_asof
# to force the legacy adapter to resolve NO weekly file (load_for_date returns
# {}), so replay reproduces a snapshot that recorded NO tdcc_weekly source
# exactly — instead of re-resolving a later weekly file (as-of target_date) that
# was never part of that snapshot's provenance. This matters for the P2-W6
# I-only backfill: pre-TDCC-integration dates (schema ≤1.4.0) become 1.9.0
# snapshots with no tdcc source, and their full-replay must not silently add one.
_TDCC_REPRODUCE_NONE = "1970-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# AS-WAS engine_params patching (C10/C11). See module docstring §AS-WAS CONFIG.
# ─────────────────────────────────────────────────────────────────────────────
#
# THE FROM-IMPORT TRAP (the easiest thing to get wrong here):
# Patching `engine_params.<KEY>` only reaches consumers that read the parameter
# through the *module* at call time, i.e. `from core import engine_params as _cfg`
# then `_cfg.<KEY>` — that covers market_context / golden / state_machine /
# market_family, and ingest itself (via engine_params.as_config_dict(), which is
# what regenerates config_snapshot and therefore config_hash). But three modules
# copy the *value* into their own namespace at import time via
# `from core.engine_params import <KEY> [as <ALIAS>]`; rebinding the engine_params
# attribute does NOT reach those bindings. This registry lists every such
# from-import site (verified by grepping `from core.engine_params import` and the
# `from core.watchlists import TIER_A` re-export chain across core/). Only sites
# whose parameter actually diverges from the recorded value get patched, and every
# patch is restored (try/finally), so the module stays pristine after each date.
#
# key in engine_params -> [(module_dotted_path, attribute_name_at_that_site), ...]
_FROM_IMPORT_SITES: dict[str, list[tuple[str, str]]] = {
    # core/watchlists.py re-exports TIER_A; state_machine/funnel/market_state
    # bind the SAME dict object via `from core.watchlists import TIER_A`
    # (narrative_engine imports it inside functions → re-fetched from watchlists,
    # so patching watchlists reaches it too). TIER_A_CODES is a derived frozenset,
    # handled specially below.
    "TIER_A": [
        ("core.watchlists", "TIER_A"),
        ("core.state_machine", "TIER_A"),
        ("core.funnel", "TIER_A"),
        ("core.market_state", "TIER_A"),
    ],
    # core/chip_score.py: `from core.engine_params import CHIP_SCORE_CONFIG, GRADE_PCT_MAP`
    "CHIP_SCORE_CONFIG": [("core.chip_score", "CHIP_SCORE_CONFIG")],
    "GRADE_PCT_MAP":     [("core.chip_score", "GRADE_PCT_MAP")],
    # core/distribution.py: `from core.engine_params import DIST_* as <ALIAS>`
    "DIST_CONSISTENCY_CONFIG":      [("core.distribution", "CONSISTENCY_CONFIG")],
    "DIST_GRADE_BANDS":             [("core.distribution", "GRADE_BANDS")],
    "DIST_SAFETY_MARGIN_BANDS":     [("core.distribution", "SAFETY_MARGIN_BANDS")],
    "DIST_AUTO_FILTER_MARGIN_MIN":  [("core.distribution", "AUTO_FILTER_MARGIN_MIN")],
    "DIST_AUTO_FILTER_CONSISTENCY": [("core.distribution", "AUTO_FILTER_CONSISTENCY")],
}


def _canon_equal(a: object, b: object) -> bool:
    """Compare two parameter values canonically.

    config_snapshot is stored as JSON, so recorded values come back with tuples
    decoded to lists; the live engine_params still holds tuples. Comparing
    canonical bytes (the same serialization that feeds the snapshot hash) treats
    tuple-vs-list and key ordering as equal, so only genuine semantic divergences
    (e.g. 0.25 vs 0.10) count as a difference worth patching.
    """
    return canonical_bytes(a) == canonical_bytes(b)


@contextlib.contextmanager
def _params_as_recorded(recorded: dict | None):
    """Temporarily patch core.engine_params to the values a snapshot RECORDED.

    `recorded` is on_disk_snap["config_snapshot"]["engine_params"] (or None for a
    pre-1.9.0 shape → no-op, replay proceeds with the live values, matching legacy
    behaviour). Semantics:

      • Only keys present in `recorded` are considered. A parameter HEAD added
        since the snapshot (live-only) keeps its current value and cannot be on
        this snapshot's recompute path anyway.
      • A recorded key HEAD no longer defines is skipped (nothing to bind).
      • A key whose recorded value canonically equals the live value is skipped
        (no divergence → no patch needed).
      • A divergent key is rebound on engine_params AND on every from-import site
        registered for it (the trap). All originals are restored on exit.
    """
    if not recorded:
        yield
        return

    saved: list[tuple[object, str, bool, object]] = []

    def _set(obj: object, attr: str, value: object) -> None:
        saved.append((obj, attr, hasattr(obj, attr), getattr(obj, attr, None)))
        setattr(obj, attr, value)

    try:
        for key, value in recorded.items():
            if not hasattr(engine_params, key):
                continue  # recorded a param HEAD no longer defines
            if _canon_equal(getattr(engine_params, key), value):
                continue  # no divergence → nothing to patch
            _set(engine_params, key, value)
            for mod_name, attr in _FROM_IMPORT_SITES.get(key, ()):
                mod = importlib.import_module(mod_name)
                if hasattr(mod, attr):
                    _set(mod, attr, value)
            if key == "TIER_A":
                # watchlists.TIER_A_CODES is a frozenset snapshot of TIER_A.keys()
                # taken at import; rebuild it so tier membership checks match as-was.
                wl = importlib.import_module("core.watchlists")
                if hasattr(wl, "TIER_A_CODES"):
                    _set(wl, "TIER_A_CODES", frozenset(value.keys()))
        yield
    finally:
        for obj, attr, had, old in reversed(saved):
            if had:
                setattr(obj, attr, old)
            else:
                delattr(obj, attr)


def _resolve_replay_config(
    on_disk_snap: dict, cfg_fallback: dict
) -> tuple[dict, dict | None]:
    """Return (yaml_cfg, recorded_engine_params) for as-was replay.

    1.9.0+ snapshots carry config_snapshot={yaml, engine_params}; use both so
    replay recomputes with the config the snapshot froze, not HEAD's live files.
    Defensive fallback for any snapshot lacking the two-source shape (theoretically
    none in the current index): use the live config and no param patch, preserving
    the prior behaviour for that legacy shape.
    """
    cs = on_disk_snap.get("config_snapshot")
    if isinstance(cs, dict) and "yaml" in cs:
        return cs["yaml"], cs.get("engine_params")
    return cfg_fallback, None


def _attestation_note(ledger: dict, cur_env: dict, date: str, current_hash: str) -> str:
    """SOFT ledger cross-check (P2-W5, L2.5). Returns a human-readable suffix.

    - Ledger entry present for (date, current tip hash) → "attested" marker.
    - Entry's environment fingerprint differs from now → drift warning (R10).
    - NO ledger entry → empty string. A missing entry is NEVER a failure
      (fable D-5 iron rule: replay pass/fail never depends on the ledger).
    """
    entry = latest_entry_for(ledger, date, current_hash)
    if entry is None:
        return ""
    note = "  📜 attested"
    if not entry.get("check_replay_passed", False):
        note += " (recorded FAIL)"
    drift = env_drift(entry, cur_env)
    if drift:
        parts = ", ".join(f"{k} {a}→{c}" for k, (a, c) in sorted(drift.items()))
        note += f"  ⚠️ 環境已漂移 [{parts}]"
    return note


def _archived_dir_for(src: dict) -> pathlib.Path:
    """Resolve provenance.sources[*].archived_copy_path to an absolute dir."""
    rel = src["archived_copy_path"].rstrip("/")
    return (REPORTS_DIR / rel).resolve()


def _archived_file_for(src: dict) -> pathlib.Path:
    """For file-mode sources: pick the specific archived file matching the
    on-disk snapshot's raw_file. The archive may legitimately contain
    multiple files for the same source over time (e.g., when upstream rolls
    rollup filenames between ingests), so we use the snapshot's recorded
    raw_file basename to pick the right one.
    """
    archive_dir = _archived_dir_for(src)
    basename = pathlib.PurePosixPath(src["raw_file"]).name
    candidate = archive_dir / basename
    if not candidate.is_file():
        raise RuntimeError(
            f"verify_all_replay: archived file {candidate.name} not found in {archive_dir}. "
            f"raw_file={src['raw_file']}"
        )
    return candidate


def _load_snap_objects(lookback: dict[str, str], reports_dir: pathlib.Path) -> list[dict]:
    """Load actual prior-snapshot content for the lookback dates (oldest first).

    Mirrors tools.run_pipeline._load_snap_objects so that the FULL replay feeds
    ingest() the SAME prior_snap_objects the live pipeline used. Without this,
    weakening_profile() receives [] on replay and emits empty weakening fields,
    which diverge from the live snapshot and break full replay for schema >=1.6.0.
    Silently skips dates whose file is missing or unreadable.
    """
    result: list[dict] = []
    for date in sorted(lookback.keys()):
        path = reports_dir / f"{date}.json"
        if path.is_file():
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return result


def _replay_adapter(d: str, on_disk_snap: dict, repo_root: pathlib.Path) -> dict:
    """Dispatch on provenance to run the right adapter against the archive."""
    prov = on_disk_snap.get("provenance", {}).get("sources", {})
    if "legacy_rollup" in prov:
        archived_rollup = _archived_file_for(prov["legacy_rollup"])
        return adapt_rollup(d, rollup_path=archived_rollup)
    if "legacy_today_json" in prov:
        today_file = _archived_file_for(prov["legacy_today_json"])
        branches_dir = _archived_dir_for(prov["legacy_branches"])
        paths_override = {
            "root":         repo_root,
            "today_json":   today_file,
            "branches_dir": branches_dir,
            "snapshots":    repo_root / "data" / "snapshots",  # unused by legacy adapter
        }
        # Reproduce the snapshot's RECORDED tdcc source exactly:
        #   - Snapshot recorded a tdcc_weekly source → pin to its report_date so
        #     replay reads the same weekly file (live data/tdcc retains prior
        #     weeks; capping stops drift to a NEWER file not in this archive,
        #     which would crash archive verification). (fix 2026-06-22)
        #   - Snapshot recorded NO tdcc source (pre-integration epoch, incl. the
        #     P2-W6 I-only backfill) → force NO weekly file via a pre-epoch
        #     sentinel, so replay does NOT re-resolve tdcc as-of target_date and
        #     add a source the snapshot never had. (D-7 as-was sources)
        tdcc_prov = prov.get("tdcc_weekly")
        tdcc_asof = tdcc_prov["report_date"] if tdcc_prov else _TDCC_REPRODUCE_NONE
        return adapt_legacy(date=d, paths_override=paths_override, tdcc_asof=tdcc_asof)
    raise RuntimeError(
        f"verify_all_replay: snapshot {d} has unrecognized provenance "
        f"sources {sorted(prov.keys())}; cannot determine which adapter to replay."
    )


def _is_iso_date(s: str) -> bool:
    import datetime as dt
    try:
        dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _gather_lookback(target_date: str, window: int, index: dict) -> dict[str, str]:
    import datetime as dt
    tgt = dt.date.fromisoformat(target_date)
    out: dict[str, str] = {}
    for key, entry in index["snapshots"].items():
        try:
            d = dt.date.fromisoformat(key)
        except ValueError:
            continue
        if d >= tgt:
            continue
        days_ago = (tgt - d).days
        if 0 < days_ago <= window:
            out[key] = entry["current_hash"]
    return out


def full_replay_hash(
    d: str,
    on_disk_snap: dict,
    cfg_fallback: dict,
    repo_root: pathlib.Path,
    index: dict,
    window: int,
) -> str:
    """Recompute a full-replay snapshot as-was and return its canonical hash.

    Extracted from main() so the regression test can drive the exact replay path.
    Uses the snapshot's RECORDED config (yaml + engine_params) — never HEAD's live
    engine_params module or the live config file (C10/C11). The engine_params
    patch wraps ingest() because that single call both runs the O-layer engines
    AND regenerates config_snapshot/config_hash via engine_params.as_config_dict();
    both must see the recorded values. The patch is fully restored on return.
    """
    yaml_cfg, recorded_params = _resolve_replay_config(on_disk_snap, cfg_fallback)
    adapter_out = _replay_adapter(d, on_disk_snap, repo_root)
    lookback = _gather_lookback(d, window, index)
    prior_snap_objects = _load_snap_objects(lookback, REPORTS_DIR)
    snap_obs_landing = bool(on_disk_snap.get("obs_landing", True))
    with _params_as_recorded(recorded_params):
        snap = ingest(adapter_out, yaml_cfg, repo_root=str(repo_root),
                      prior_snapshots=lookback, prior_snap_objects=prior_snap_objects,
                      obs_landing=snap_obs_landing)
    # archive_raw_inputs stamps provenance metadata only (no engine_params use),
    # so it runs after the patch is restored.
    archive_raw_inputs(snap, repo_root, RAW_ARCHIVE_DIR, verify_only=True)
    # Normalize the replay-excluded fields before comparing. The set of
    # fields that do NOT participate in replay — wall-clock (generated_at),
    # build-environment fingerprint (environment), build-time events
    # (audit_log), version stamps (schema_version, core_version), and the
    # mtime-derived volatile provenance sub-fields (fetched_at / report_date /
    # data_lag_days) — is DERIVED from schema/field_registry.yaml (replay
    # level = excluded-M), NOT hardcoded here. This is the single SoT shared
    # with run_pipeline.py, replacing the two drifting strip lists (RC-5).
    # provenance's lineage integrity fields (raw_sha256 / archived_sha256 /
    # archived_copy_path) deliberately stay in the compared hash so archive
    # drift is still caught. See core/replay_contract.py.
    normalize_for_replay_compare(snap, on_disk_snap)
    return canonical_sha256(snap)


def main() -> int:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    window = cfg.get("temporal", {}).get("lookback_window_days", 5)
    repo_root = legacy_paths()["root"]
    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))

    dates = sorted(k for k in index["snapshots"].keys() if _is_iso_date(k))
    print(f"[verify-all] {len(dates)} dates to check (window={window})", file=sys.stderr)

    # SOFT attestation cross-check inputs (P2-W5). Read-only; never gates.
    ledger = load_ledger(REPLAY_LEDGER_FILE)
    cur_env = current_env_fingerprint()
    attested_count = 0

    failures: list[str] = []
    passes = 0
    legacy_passes = 0
    for d in dates:
        entry = index["snapshots"][d]
        on_disk_snap = json.loads((REPORTS_DIR / entry["current"]).read_text(encoding="utf-8"))

        snap_schema = on_disk_snap.get("schema_version")
        if snap_schema != SCHEMA_VERSION:
            # Frozen epoch: HEAD code cannot legitimately reproduce this
            # snapshot. Verify the bytes haven't drifted from the index.
            h_disk = canonical_sha256(on_disk_snap)
            if h_disk == entry["current_hash"]:
                legacy_passes += 1
                note = _attestation_note(ledger, cur_env, d, entry["current_hash"])
                if note:
                    attested_count += 1
                print(
                    f"  🔒 {d}  epoch {snap_schema} — disk hash matches index "
                    f"{h_disk[:20]}...{note}",
                    file=sys.stderr,
                )
            else:
                failures.append(
                    f"{d}: LEGACY EPOCH HASH DRIFT disk={h_disk[:20]}... "
                    f"index={entry['current_hash'][:20]}..."
                )
                print(f"  ❌ {d}  legacy epoch hash drift!", file=sys.stderr)
            continue

        # D-7 HARD CONDITION: the obs_landing flag and the as-was config (yaml +
        # engine_params) are read from the on-disk snapshot inside full_replay_hash
        # so the verifier reproduces the SAME ingest mode and the SAME judgment
        # parameters the snapshot recorded — see full_replay_hash / _params_as_recorded.
        try:
            h_replay = full_replay_hash(d, on_disk_snap, cfg, repo_root, index, window)
        except Exception as e:
            failures.append(f"{d}: replay failed: {e}")
            print(f"  ❌ {d}  replay failed: {e}", file=sys.stderr)
            continue
        h_current = entry["current_hash"]

        if h_replay == h_current:
            passes += 1
            note = _attestation_note(ledger, cur_env, d, h_current)
            if note:
                attested_count += 1
            print(f"  ✅ {d}  {h_current[:20]}...{note}", file=sys.stderr)
        else:
            failures.append(f"{d}: current={h_current[:20]}... replay={h_replay[:20]}...")
            print(f"  ❌ {d}  current={h_current[:20]}... replay={h_replay[:20]}...", file=sys.stderr)

    print(
        f"\n[verify-all] {passes} full-replay-clean + {legacy_passes} legacy-epoch-clean "
        f"of {len(dates)} dates; {len(failures)} failure(s); "
        f"{attested_count} ledger-attested (soft) "
        f"(current schema {SCHEMA_VERSION})",
        file=sys.stderr,
    )
    if failures:
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
