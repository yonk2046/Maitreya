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

Exit codes:
  0 — every date passes
  1 — at least one date does not match its recorded current_hash
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
from core.ingest import ingest  # noqa: E402
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
    for d in dates:
        entry = index["snapshots"][d]
        on_disk_snap = json.loads((REPORTS_DIR / entry["current"]).read_text(encoding="utf-8"))

        try:
            adapter_out = _replay_adapter(d, on_disk_snap, repo_root)
        except Exception as e:
            failures.append(f"{d}: adapter dispatch failed: {e}")
            print(f"  ❌ {d}  adapter dispatch failed: {e}", file=sys.stderr)
            continue

        lookback = _gather_lookback(d, window, index)
        snap = ingest(adapter_out, cfg, repo_root=str(repo_root), prior_snapshots=lookback)
        # verify_only=True: do NOT copy from data/ (which has likely been
        # mutated by upstream fetches). Re-hash the existing archive copy and
        # stamp the same provenance/audit metadata as the original ingest.
        archive_raw_inputs(snap, repo_root, RAW_ARCHIVE_DIR, verify_only=True)

        # Normalize wall-clock fields
        snap["generated_at"] = on_disk_snap["generated_at"]
        h_replay = canonical_sha256(snap)
        h_current = entry["current_hash"]

        if h_replay == h_current:
            passes += 1
            print(f"  ✅ {d}  {h_current[:20]}...", file=sys.stderr)
        else:
            failures.append(f"{d}: current={h_current[:20]}... replay={h_replay[:20]}...")
            print(f"  ❌ {d}  current={h_current[:20]}... replay={h_replay[:20]}...", file=sys.stderr)

    print(
        f"\n[verify-all] {passes}/{len(dates)} dates replay-clean; "
        f"{len(failures)} mismatch(es)",
        file=sys.stderr,
    )
    if failures:
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
