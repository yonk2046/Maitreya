"""Canonical contract enforcement — CI gate for replay legitimacy.

These tests guard the immutable historical record. They must pass for
every snapshot in `reports/` before any scoring logic is allowed to run
(see [[scd-priority-replay-first]] in the project memory).

Coverage:
  H7  test_every_snapshot_matches_canonical_schema
       Every reports/<date>.json validates against schema/canonical_schema.json.
  H8  test_every_sidecar_matches_canonical_hash
       Every reports/<date>.json.sha256 sidecar matches re-computed canonical_sha256.
  H9  test_index_internal_consistency
       index.json invariants: current_hash == disk canonical hash; supersedes chain
       is linked, acyclic, and matches history order.

Run:
    cd "Ai stock" && python -m pytest tests/test_contracts.py -v
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.hashing import canonical_sha256  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"
SCHEMA_FILE = _AI_STOCK / "schema" / "canonical_schema.json"
INDEX_FILE = REPORTS_DIR / "index.json"

_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _snapshot_files() -> list[pathlib.Path]:
    """All <date>.json snapshots in reports/, excluding index.json and proposals.

    `*.intelligence.json` sidecars are EXCLUDED: they are Distribution Layer
    outputs (a different schema family), not canonical snapshots, and must not
    be validated against the canonical schema or hash/index invariants.
    See test_intelligence_sidecars_are_valid_json for their (lighter) check.
    """
    out: list[pathlib.Path] = []
    for f in sorted(REPORTS_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        if f.name.startswith("score_breakdown"):
            continue
        if f.name.endswith(".intelligence.json"):
            continue
        out.append(f)
    return out


def _intelligence_sidecar_files() -> list[pathlib.Path]:
    """Distribution Layer sidecars (`*.intelligence.json`)."""
    return sorted(REPORTS_DIR.glob("*.intelligence.json"))


@pytest.fixture(scope="module")
def schema() -> dict:
    assert SCHEMA_FILE.is_file(), f"missing canonical schema: {SCHEMA_FILE}"
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index() -> dict:
    assert INDEX_FILE.is_file(), f"missing index: {INDEX_FILE}"
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# H7 — every snapshot validates against canonical schema
# ----------------------------------------------------------------------

def test_every_snapshot_matches_canonical_schema(schema):
    import jsonschema

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    files = _snapshot_files()
    assert files, "No snapshot files found in reports/; cannot validate contract"
    failures: list[str] = []
    for f in files:
        obj = json.loads(f.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path))
        if errors:
            paths = ["/".join(str(p) for p in e.absolute_path) or "<root>" for e in errors[:3]]
            msgs = [f"{p}: {e.message}" for p, e in zip(paths, errors[:3])]
            failures.append(f"{f.name}: {len(errors)} error(s) — {'; '.join(msgs)}")
    assert not failures, "Schema violations:\n  " + "\n  ".join(failures)


# ----------------------------------------------------------------------
# H7b — intelligence sidecars: lighter sanity check (different schema family)
# ----------------------------------------------------------------------

def test_intelligence_sidecars_are_valid_json():
    """Intelligence sidecars are NOT canonical snapshots — they only need to
    be parseable JSON objects keyed to a real snapshot date."""
    failures: list[str] = []
    for f in _intelligence_sidecar_files():
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            failures.append(f"{f.name}: invalid JSON — {e}")
            continue
        if not isinstance(obj, dict):
            failures.append(f"{f.name}: top-level is not an object")
            continue
        # Sidecar must sit next to its canonical snapshot
        base = f.name.replace(".intelligence.json", ".json")
        if not (REPORTS_DIR / base).is_file():
            failures.append(f"{f.name}: no matching canonical snapshot {base}")
    assert not failures, "Intelligence sidecar issues:\n  " + "\n  ".join(failures)


# ----------------------------------------------------------------------
# H8 — every .sha256 sidecar matches re-computed canonical hash
# ----------------------------------------------------------------------

def test_every_sidecar_matches_canonical_hash():
    files = _snapshot_files()
    failures: list[str] = []
    missing: list[str] = []
    for f in files:
        sidecar = f.with_name(f.name + ".sha256")
        if not sidecar.is_file():
            missing.append(f.name)
            continue
        # sidecar format: "<hash>  <filename>\n"
        recorded = sidecar.read_text(encoding="utf-8").strip().split()[0]
        if not _SHA256_RE.match(recorded):
            failures.append(f"{sidecar.name}: malformed hash '{recorded}'")
            continue
        actual = canonical_sha256(json.loads(f.read_text(encoding="utf-8")))
        if recorded != actual:
            failures.append(
                f"{f.name}: sidecar={recorded[:20]}... actual={actual[:20]}..."
            )
    assert not missing, f"Missing sidecars: {missing}"
    assert not failures, "Sidecar mismatches:\n  " + "\n  ".join(failures)


# ----------------------------------------------------------------------
# H9 — index.json internal consistency
# ----------------------------------------------------------------------

def test_index_schema_version(index):
    assert index.get("schema_version") == "1.4.0"
    assert "snapshots" in index and isinstance(index["snapshots"], dict)


def test_index_current_hash_matches_disk(index):
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            failures.append(f"{key}: current file {f.name} missing")
            continue
        actual = canonical_sha256(json.loads(f.read_text(encoding="utf-8")))
        if entry["current_hash"] != actual:
            failures.append(
                f"{key}: current_hash {entry['current_hash'][:20]}... "
                f"!= disk canonical {actual[:20]}..."
            )
    assert not failures, "Disk/index hash drift:\n  " + "\n  ".join(failures)


def test_index_history_tip_matches_current(index):
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        history = entry.get("history", [])
        assert history, f"{key}: empty history"
        if history[-1]["hash"] != entry["current_hash"]:
            failures.append(
                f"{key}: history[-1].hash != current_hash"
            )
    assert not failures, "\n  ".join(failures)


def test_index_supersedes_chain_linked(index):
    """For every history list:
       history[0].supersedes is None
       history[-1].superseded_by is None
       history[i].supersedes == history[i-1].hash  (i > 0)
       history[i].superseded_by == history[i+1].hash  (i < n-1)
    """
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        h = entry["history"]
        n = len(h)
        if h[0]["supersedes"] is not None:
            failures.append(f"{key}: history[0].supersedes != null")
        if h[-1]["superseded_by"] is not None:
            failures.append(f"{key}: history[-1].superseded_by != null")
        for i in range(1, n):
            if h[i]["supersedes"] != h[i - 1]["hash"]:
                failures.append(
                    f"{key}: history[{i}].supersedes != history[{i-1}].hash"
                )
        for i in range(n - 1):
            if h[i]["superseded_by"] != h[i + 1]["hash"]:
                failures.append(
                    f"{key}: history[{i}].superseded_by != history[{i+1}].hash"
                )
    assert not failures, "Chain integrity violations:\n  " + "\n  ".join(failures)


def test_index_supersedes_chain_acyclic(index):
    """No hash appears twice in a single history (would be a cycle)."""
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        hashes = [h["hash"] for h in entry["history"]]
        if len(hashes) != len(set(hashes)):
            dupes = [h for h in set(hashes) if hashes.count(h) > 1]
            failures.append(f"{key}: duplicate hash(es) in history: {dupes}")
    assert not failures, "\n  ".join(failures)


def test_index_history_entries_well_formed(index):
    required_keys = {"file", "hash", "created_at", "supersedes", "superseded_by"}
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        for i, h in enumerate(entry["history"]):
            missing = required_keys - set(h.keys())
            if missing:
                failures.append(f"{key}: history[{i}] missing keys {missing}")
            if not _SHA256_RE.match(h["hash"]):
                failures.append(f"{key}: history[{i}] malformed hash '{h['hash']}'")
            if not h["created_at"].endswith("Z"):
                failures.append(
                    f"{key}: history[{i}].created_at must end with 'Z' (UTC), got '{h['created_at']}'"
                )
    assert not failures, "\n  ".join(failures)


def test_index_covers_all_real_snapshots_on_disk(index):
    """Every <date>.json on disk (excluding *.example.json) must have an index entry."""
    indexed = set(index["snapshots"].keys())
    on_disk = set()
    for f in _snapshot_files():
        # Strip .json — keys include .example variants
        on_disk.add(f.stem)
    missing_from_index = on_disk - indexed
    assert not missing_from_index, (
        f"Files on disk not indexed: {sorted(missing_from_index)}"
    )


# ----------------------------------------------------------------------
# H14 — cross-date lookback continuity
# ----------------------------------------------------------------------

def _is_real_date_key(k: str) -> bool:
    """Skip *.example keys when checking date continuity."""
    try:
        import datetime as dt
        dt.date.fromisoformat(k)
        return True
    except ValueError:
        return False


def test_lookback_references_exist_in_index(index):
    """Every snapshot's environment.lookback_snapshots[date] must reference a date
    that has an index entry — referring to a date we never recorded is broken
    chain-of-custody.
    """
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        lookback = snap.get("environment", {}).get("lookback_snapshots", {})
        for lb_date in lookback.keys():
            if lb_date not in index["snapshots"]:
                failures.append(f"{key}: lookback references unindexed date '{lb_date}'")
    assert not failures, "Lookback references broken:\n  " + "\n  ".join(failures)


def test_lookback_hash_present_in_history(index):
    """Every snapshot's environment.lookback_snapshots[date] = hash must appear
    somewhere in index.snapshots[date].history. This is the LENIENT continuity
    check — the hash referenced may have been superseded since, but it must
    have *existed* in the history of that date (we never reference a hash that
    was never written).
    """
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        lookback = snap.get("environment", {}).get("lookback_snapshots", {})
        for lb_date, lb_hash in lookback.items():
            prior = index["snapshots"].get(lb_date)
            if prior is None:
                continue  # covered by the previous test
            ever_existed = any(h["hash"] == lb_hash for h in prior["history"])
            if not ever_existed:
                failures.append(
                    f"{key}: lookback[{lb_date}]={lb_hash[:20]}... "
                    f"never appeared in {lb_date}'s history"
                )
    assert not failures, "Phantom lookback hashes:\n  " + "\n  ".join(failures)


def test_lookback_hash_matches_current_strict(index):
    """STRICT continuity: every lookback hash equals the prior date's
    current_hash. Holds only when snapshots have been re-ingested in
    chronological order after their priors changed. Used as a stretch check —
    failures here are not corruption but mean the chain is not fully fresh.
    """
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        lookback = snap.get("environment", {}).get("lookback_snapshots", {})
        for lb_date, lb_hash in lookback.items():
            prior = index["snapshots"].get(lb_date)
            if prior is None:
                continue
            if lb_hash != prior["current_hash"]:
                failures.append(
                    f"{key}: lookback[{lb_date}]={lb_hash[:20]}... "
                    f"!= current {prior['current_hash'][:20]}..."
                )
    # This assertion is the strict desideratum. If it fails, run a chronological
    # cascade re-ingest to refresh the chain — that's intentional, not corruption.
    assert not failures, (
        "STRICT continuity broken (cascade re-ingest may resolve):\n  "
        + "\n  ".join(failures)
    )


# ----------------------------------------------------------------------
# H16 — archive integrity: archived_sha256 == re-hash of actual archive bytes
# ----------------------------------------------------------------------

def _hash_archive_dir_manifest(d):
    """Mirror core.archive._hash_dir_manifest. Inlined to avoid private import."""
    import hashlib
    lines = []
    for f in sorted(d.glob("*.json")):
        from core.hashing import file_sha256
        lines.append(f"{f.name} {file_sha256(f)}")
    manifest_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    return "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()


def test_archive_integrity_every_source(index):
    """For every dated snapshot, the on-disk snapshot's provenance.sources[*].archived_sha256
    must equal a fresh re-hash of the actual archive bytes. This catches:
      - Tampering with reports/_raw_archive/<date>/<src_id>/...
      - Drift between what the snapshot CLAIMS its archive is and what the
        archive actually contains right now.
      - Missing archive directories.

    File-mode sources: re-hash via file_sha256 of the file matching raw_file's basename.
    Dir-mode sources:  re-hash via the same dir-manifest algorithm used by core.archive.
    """
    from core.hashing import file_sha256
    import pathlib as _pl

    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        sources = snap.get("provenance", {}).get("sources", {})
        for src_id, src in sources.items():
            archived_rel = src.get("archived_copy_path")
            archived_sha = src.get("archived_sha256")
            if not archived_rel or not archived_sha:
                failures.append(f"{key}/{src_id}: missing archived_copy_path or archived_sha256")
                continue
            archive_dir = (REPORTS_DIR / archived_rel.rstrip("/")).resolve()
            if not archive_dir.is_dir():
                failures.append(f"{key}/{src_id}: archive dir missing: {archive_dir}")
                continue
            raw_file = src["raw_file"]
            is_dir_source = raw_file.endswith("/")
            if is_dir_source:
                actual_sha = _hash_archive_dir_manifest(archive_dir)
            else:
                basename = _pl.PurePosixPath(raw_file).name
                target = archive_dir / basename
                if not target.is_file():
                    failures.append(
                        f"{key}/{src_id}: archived file {basename} not in {archive_dir}"
                    )
                    continue
                actual_sha = file_sha256(target)
            if actual_sha != archived_sha:
                failures.append(
                    f"{key}/{src_id}: recorded={archived_sha[:20]}... actual={actual_sha[:20]}..."
                )
    assert not failures, "Archive integrity violations:\n  " + "\n  ".join(failures)


def test_archive_sha_equals_raw_sha(index):
    """The whole POINT of the archive: archived_sha256 must equal raw_sha256.
    The pipeline enforces this at ingest, but verify it stays true on every read.
    """
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        for src_id, src in snap.get("provenance", {}).get("sources", {}).items():
            raw_sha = src.get("raw_sha256")
            archived_sha = src.get("archived_sha256")
            if raw_sha != archived_sha:
                failures.append(
                    f"{key}/{src_id}: raw_sha256={raw_sha[:20]}... != archived={archived_sha[:20] if archived_sha else None}..."
                )
    assert not failures, "raw_sha vs archive_sha drift:\n  " + "\n  ".join(failures)


def test_lookback_window_size_respects_config(index):
    """environment.lookback_window_days must not exceed config.temporal.lookback_window_days."""
    import yaml
    cfg = yaml.safe_load(
        (_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8")
    )
    cfg_window = cfg.get("temporal", {}).get("lookback_window_days", 5)
    failures: list[str] = []
    for key, entry in index["snapshots"].items():
        if not _is_real_date_key(key):
            continue
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            continue
        snap = json.loads(f.read_text(encoding="utf-8"))
        lookback = snap.get("environment", {}).get("lookback_snapshots", {})
        if len(lookback) > cfg_window:
            failures.append(
                f"{key}: lookback has {len(lookback)} entries, config caps at {cfg_window}"
            )
    assert not failures, "\n  ".join(failures)
