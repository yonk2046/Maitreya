"""WORM (Write-Once-Read-Many) self-check for the SCD ingest pipeline.

The pipeline must never mutate raw input files. This module captures a
manifest of (path, sha256) for every file the adapters read, then verifies
the manifest after ingest finishes. Any drift triggers a WORM_VIOLATION.

Files monitored:
  - <project>/data/today.json
  - <project>/data/branches/*.json
  - <project>/data/snapshots/*.json
  - <project>/data/history/*.json (if present)

Public API:
    snapshot_manifest(project_root)  -> dict[str, str]
    verify_manifest(project_root, before)  -> list[dict]   # WORM_VIOLATION events
"""
from __future__ import annotations

import pathlib
from typing import Iterable

from core.hashing import file_sha256


def _candidate_paths(project_root: pathlib.Path) -> Iterable[pathlib.Path]:
    data_root = project_root / "data"
    if not data_root.is_dir():
        return
    direct = data_root / "today.json"
    if direct.is_file():
        yield direct
    for sub in ("branches", "snapshots", "history"):
        d = data_root / sub
        if d.is_dir():
            for f in sorted(d.rglob("*.json")):
                yield f


def snapshot_manifest(project_root: str | pathlib.Path) -> dict[str, str]:
    """Capture (relative_path -> sha256) for every raw input file under data/.

    Relative paths are keyed from project_root so the manifest survives
    move between machines.
    """
    root = pathlib.Path(project_root).resolve()
    out: dict[str, str] = {}
    for f in _candidate_paths(root):
        rel = str(f.relative_to(root))
        out[rel] = file_sha256(f)
    return out


def verify_manifest(
    project_root: str | pathlib.Path,
    before: dict[str, str],
) -> list[dict]:
    """Re-hash every file in `before` and return WORM_VIOLATION events for any drift.

    Three kinds of drift are caught:
      - hash changed (file was modified mid-run)
      - file removed (gone after the run)
      - file added (new raw file appeared — also a violation of WORM contract)

    Returns an empty list if everything is byte-identical.
    """
    root = pathlib.Path(project_root).resolve()
    after = snapshot_manifest(root)
    violations: list[dict] = []

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    for rel in sorted(before_keys & after_keys):
        if before[rel] != after[rel]:
            violations.append({
                "ticker": None,
                "event": "WORM_VIOLATION",
                "reason": f"raw file modified during ingest: {rel}",
                "step": "core.worm_check.verify_manifest",
                "data": {
                    "path":   rel,
                    "before": before[rel],
                    "after":  after[rel],
                },
            })
    for rel in sorted(before_keys - after_keys):
        violations.append({
            "ticker": None,
            "event": "WORM_VIOLATION",
            "reason": f"raw file removed during ingest: {rel}",
            "step": "core.worm_check.verify_manifest",
            "data": {"path": rel, "before": before[rel], "after": None},
        })
    for rel in sorted(after_keys - before_keys):
        violations.append({
            "ticker": None,
            "event": "WORM_VIOLATION",
            "reason": f"new raw file appeared during ingest: {rel}",
            "step": "core.worm_check.verify_manifest",
            "data": {"path": rel, "before": None, "after": after[rel]},
        })
    return violations
