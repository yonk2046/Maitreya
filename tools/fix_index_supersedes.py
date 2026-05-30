"""One-off: link the supersedes chain in reports/index.json.

Pre-state (before this script ran on 2026-05-26):
  Every snapshot's history[] was appended on each re-run during P3a
  shake-out, but `supersedes` / `superseded_by` were left null on every
  entry. The audit trail is technically present (timestamps + hashes)
  but the chain isn't linked, which makes provenance queries weaker.

What this does:
  For each snapshot entry in index.json:
    - Walk history[] in order (the file is append-only by construction).
    - For each entry h[i] (i > 0), set h[i].supersedes = h[i-1].hash.
    - For each entry h[i] (i < len-1), set h[i].superseded_by = h[i+1].hash.
    - Last entry's superseded_by stays null (it IS the current).
    - First entry's supersedes stays null (no prior).
  Then verify:
    - Last entry's hash == current_hash. If not, fail loudly.
    - Last entry's `file` exists on disk and re-hashing it == current_hash.

Idempotent: running twice produces no change.
"""
from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
sys.path.insert(0, str(_AI_STOCK))

from core.hashing import canonical_sha256  # noqa: E402


def _canonical_hash_of_file(path: pathlib.Path) -> str:
    """Re-hash an on-disk snapshot using the canonical rule.

    The on-disk file is pretty-printed (indent=2) — file_sha256 would NOT
    match the index hash. We must re-parse to JSON and recompute the
    canonical hash (NFC + sort_keys + minified UTF-8).
    """
    return canonical_sha256(json.loads(path.read_text(encoding="utf-8")))

INDEX_FILE = _AI_STOCK / "reports" / "index.json"
REPORTS_DIR = _AI_STOCK / "reports"


def fix_chain(history: list[dict]) -> tuple[list[dict], int]:
    """Return (new_history, changes_count)."""
    n = len(history)
    changes = 0
    new_history = []
    for i, h in enumerate(history):
        prev_hash = history[i - 1]["hash"] if i > 0 else None
        next_hash = history[i + 1]["hash"] if i < n - 1 else None
        new_entry = dict(h)
        if new_entry.get("supersedes") != prev_hash:
            new_entry["supersedes"] = prev_hash
            changes += 1
        if new_entry.get("superseded_by") != next_hash:
            new_entry["superseded_by"] = next_hash
            changes += 1
        new_history.append(new_entry)
    return new_history, changes


def main() -> int:
    if not INDEX_FILE.is_file():
        print(f"[fix-index] no index at {INDEX_FILE}", file=sys.stderr)
        return 1
    idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    snapshots = idx.get("snapshots", {})
    total_changes = 0
    problems: list[str] = []

    for key, entry in snapshots.items():
        history = entry.get("history", [])
        if not history:
            problems.append(f"{key}: empty history")
            continue
        new_history, changes = fix_chain(history)
        entry["history"] = new_history
        total_changes += changes

        # Verify last entry hash matches current_hash
        last = new_history[-1]
        if last["hash"] != entry.get("current_hash"):
            problems.append(
                f"{key}: last history hash {last['hash']} != current_hash {entry.get('current_hash')}"
            )
            continue

        # Verify file on disk re-hashes (canonically) to current_hash
        f = REPORTS_DIR / entry["current"]
        if not f.is_file():
            problems.append(f"{key}: current file {f.name} missing on disk")
            continue
        try:
            disk_sha = _canonical_hash_of_file(f)
        except Exception as e:
            problems.append(f"{key}: cannot parse {f.name}: {e}")
            continue
        if disk_sha != entry["current_hash"]:
            problems.append(
                f"{key}: canonical sha {disk_sha} != current_hash {entry['current_hash']} "
                f"(file={f.name})"
            )

    INDEX_FILE.write_text(
        json.dumps(idx, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[fix-index] linked supersedes chain — {total_changes} field updates", file=sys.stderr)
    if problems:
        print(f"[fix-index] {len(problems)} integrity problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    print("[fix-index] integrity OK — all current_hash values match disk", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
