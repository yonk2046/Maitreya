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

Exit codes:
  0 — every date passes its applicable check
  1 — at least one date fails (replay mismatch or legacy hash drift)
"""
from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
sys.path.insert(0, str(_AI_STOCK))

import yaml  # noqa: E402

from core.archive import archive_raw_inputs  # noqa: E402
from core.hashing import canonical_sha256  # noqa: E402
from core.ingest import SCHEMA_VERSION, ingest  # noqa: E402
from data.adapters.legacy import adapt_legacy, legacy_paths  # noqa: E402
from data.adapters.rollup import adapt_rollup  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"
CONFIG_FILE = _AI_STOCK / "config" / "scd.example.yaml"
RAW_ARCHIVE_DIR = REPORTS_DIR / "_raw_archive"


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
        return adapt_legacy(date=d, paths_override=paths_override)
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


def main() -> int:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    window = cfg.get("temporal", {}).get("lookback_window_days", 5)
    repo_root = legacy_paths()["root"]
    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))

    dates = sorted(k for k in index["snapshots"].keys() if _is_iso_date(k))
    print(f"[verify-all] {len(dates)} dates to check (window={window})", file=sys.stderr)

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
                print(
                    f"  🔒 {d}  epoch {snap_schema} — disk hash matches index "
                    f"{h_disk[:20]}...",
                    file=sys.stderr,
                )
            else:
                failures.append(
                    f"{d}: LEGACY EPOCH HASH DRIFT disk={h_disk[:20]}... "
                    f"index={entry['current_hash'][:20]}..."
                )
                print(f"  ❌ {d}  legacy epoch hash drift!", file=sys.stderr)
            continue

        try:
            adapter_out = _replay_adapter(d, on_disk_snap, repo_root)
        except Exception as e:
            failures.append(f"{d}: adapter dispatch failed: {e}")
            print(f"  ❌ {d}  adapter dispatch failed: {e}", file=sys.stderr)
            continue

        lookback = _gather_lookback(d, window, index)
        prior_snap_objects = _load_snap_objects(lookback, REPORTS_DIR)
        snap = ingest(adapter_out, cfg, repo_root=str(repo_root),
                      prior_snapshots=lookback, prior_snap_objects=prior_snap_objects)
        # verify_only=True: do NOT copy from data/ (which has likely been
        # mutated by upstream fetches). Re-hash the existing archive copy and
        # stamp the same provenance/audit metadata as the original ingest.
        archive_raw_inputs(snap, repo_root, RAW_ARCHIVE_DIR, verify_only=True)

        # Normalize wall-clock fields
        snap["generated_at"] = on_disk_snap["generated_at"]
        # Normalize build-environment fingerprint + audit log. The `environment`
        # block records the BUILD machine (os, python, numpy, pandas, pyyaml,
        # jsonschema, etc.) and `audit_log` records build-time events. The primary
        # builder is the local macOS launchd job while this verifier runs on the
        # linux CI runner, so HEAD code on a different platform cannot reproduce
        # these — they are provenance metadata, not data integrity (stocks /
        # rankings / scoring / raw_sha256 are still compared). Copy on-disk in,
        # exactly like generated_at, so replay is platform-independent.
        for _meta in ("environment", "audit_log"):
            if _meta in on_disk_snap:
                snap[_meta] = on_disk_snap[_meta]
        # Normalize mtime-derived provenance metadata. fetched_at / report_date /
        # data_lag_days are computed from input-file mtimes (see legacy adapter).
        # shutil.copy2 preserves mtime within a run, so same-run replay matches —
        # but git checkout in a later CI job resets mtimes, so these fields cannot
        # be reproduced cross-run. They are environment timestamps, NOT input
        # integrity (that is covered by raw_sha256, which is still compared), so we
        # copy the on-disk values in before hashing, exactly like generated_at.
        _VOLATILE_PROV = ("fetched_at", "report_date", "data_lag_days")
        _disk_sources = on_disk_snap.get("provenance", {}).get("sources", {})
        for _sid, _src in snap.get("provenance", {}).get("sources", {}).items():
            if not isinstance(_src, dict):
                continue
            _disk_src = _disk_sources.get(_sid, {})
            if not isinstance(_disk_src, dict):
                continue
            for _f in _VOLATILE_PROV:
                if _f in _src and _f in _disk_src:
                    _src[_f] = _disk_src[_f]
        h_replay = canonical_sha256(snap)
        h_current = entry["current_hash"]

        if h_replay == h_current:
            passes += 1
            print(f"  ✅ {d}  {h_current[:20]}...", file=sys.stderr)
        else:
            failures.append(f"{d}: current={h_current[:20]}... replay={h_replay[:20]}...")
            print(f"  ❌ {d}  current={h_current[:20]}... replay={h_replay[:20]}...", file=sys.stderr)

    print(
        f"\n[verify-all] {passes} full-replay-clean + {legacy_passes} legacy-epoch-clean "
        f"of {len(dates)} dates; {len(failures)} failure(s) "
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
