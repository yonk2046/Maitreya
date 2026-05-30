"""Raw data archival — make WORM provable by keeping an immutable copy.

Background:
  Provenance already records `raw_sha256` so we can detect drift, but if the
  raw file gets deleted or modified upstream, the hash alone doesn't let us
  reconstruct the inputs. This module copies every raw input referenced by
  provenance_sources into `reports/_raw_archive/<date>/<source_id>/...` and
  records the archive path + re-computed sha into the same provenance entry.

Effect on the snapshot dict:
  Each provenance.sources[src_id] gains two new fields:
    archived_copy_path: relative path under reports/_raw_archive/<date>/
    archived_sha256:    sha256 of the archived bytes (must equal raw_sha256)

  An audit_log entry `RAW_ARCHIVED` is appended summarizing what was copied.

Errors:
  - If archived_sha256 != raw_sha256 → raise (archive corruption).
  - If raw_file path doesn't resolve to a real file or directory → raise.

This module mutates the snapshot in place AFTER ingest() but BEFORE the
final canonical_sha256 / sidecar / index update so the archive paths
are part of what we hash.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
from typing import Any

from core.hashing import file_sha256


def _hash_dir_manifest(d: pathlib.Path) -> str:
    """Recompute the dir-manifest sha matching legacy.adapt_legacy's convention.

    Manifest = SHA-256 over "\n"-joined lines of "<filename> <sha>" for each
    sorted *.json file in the dir, with trailing "\n".
    """
    lines: list[str] = []
    for f in sorted(d.glob("*.json")):
        sha = file_sha256(f)
        lines.append(f"{f.name} {sha}")
    manifest_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    return "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()


def _resolve_raw(repo_root: pathlib.Path, raw_file: str) -> pathlib.Path:
    """Resolve a raw_file string (which may be relative to repo_root) to an absolute path.

    Accepts both file paths and directory paths (legacy branches uses "data/branches/").
    """
    p = pathlib.Path(raw_file)
    if not p.is_absolute():
        p = repo_root / p
    return p


def archive_raw_inputs(
    snapshot: dict[str, Any],
    repo_root: str | pathlib.Path,
    archive_root: str | pathlib.Path,
    *,
    verify_only: bool = False,
) -> None:
    """Copy every raw input referenced by provenance_sources into archive_root.

    Mutates snapshot in place:
      - Sets archived_copy_path + archived_sha256 on each source.
      - Appends a RAW_ARCHIVED audit_log event.

    Layout:
      archive_root/<date>/<src_id>/<original_filename(s)>

    Modes:
      verify_only=False (default) — normal ingest path: read bytes from
        data/<raw_file>, copy into archive, re-hash, validate sha equals
        raw_sha256.
      verify_only=True — replay path: do NOT copy. The archive at
        archive_root/<date>/<src_id>/ must already exist; re-hash its
        contents and stamp the provenance + audit event identically to the
        original ingest. Used by tools/verify_all_replay.py so the
        verifier replays against immutable archived bytes instead of the
        possibly-mutated live data/.

    Raises:
      RuntimeError if any archived sha mismatches the recorded raw_sha256
      (in either mode), or if verify_only=True and an archive dir is missing.
    """
    repo_root = pathlib.Path(repo_root).resolve()
    archive_root = pathlib.Path(archive_root).resolve()
    date = snapshot["date"]
    dest_base = archive_root / date
    if not verify_only:
        dest_base.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    sources = snapshot["provenance"]["sources"]
    for src_id, src in sources.items():
        raw_file = src["raw_file"]
        raw_sha = src["raw_sha256"]
        is_dir_source = raw_file.endswith("/")
        dest_dir = dest_base / src_id

        if not verify_only:
            # Normal: copy bytes from data/ into the archive.
            src_path = _resolve_raw(repo_root, raw_file)
            dest_dir.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                for f in sorted(src_path.glob("*.json")):
                    shutil.copy2(f, dest_dir / f.name)
            elif src_path.is_file():
                shutil.copy2(src_path, dest_dir / src_path.name)
            else:
                raise RuntimeError(
                    f"archive_raw_inputs: source {src_id} raw_file does not exist "
                    f"as file or dir: {src_path}"
                )
        else:
            # Verify-only: the archive dir must already exist.
            if not dest_dir.is_dir():
                raise RuntimeError(
                    f"archive_raw_inputs(verify_only): missing archive dir for "
                    f"{src_id}: {dest_dir}"
                )

        # Hash the archive copy (works the same in both modes).
        if is_dir_source:
            archived_sha = _hash_dir_manifest(dest_dir)
            kind = "dir"
        else:
            # File-mode: pick the specific file by raw_file basename, not "the
            # only file in dir". Upstream may legitimately roll filenames
            # (e.g., rollup_2026-05.json → rollup_2026-06.json) so the archive
            # dir can accumulate multiple file versions over time. Each
            # snapshot's raw_file pins exactly which one it depends on.
            basename = pathlib.PurePosixPath(raw_file).name
            target = dest_dir / basename
            if not target.is_file():
                raise RuntimeError(
                    f"archive_raw_inputs: archived file {basename} not found in "
                    f"{dest_dir} for file-mode source {src_id}. raw_file={raw_file}"
                )
            archived_sha = file_sha256(target)
            kind = "file"

        if archived_sha != raw_sha:
            raise RuntimeError(
                f"archive_raw_inputs: archive sha mismatch for {src_id}:\n"
                f"  raw_sha256       = {raw_sha}\n"
                f"  archived_sha256 = {archived_sha}\n"
                f"  archive_dir      = {dest_dir}\n"
                f"  verify_only      = {verify_only}"
            )

        archived_rel = str(dest_dir.relative_to(archive_root.parent)) + ("/" if kind == "dir" else "")
        src["archived_copy_path"] = archived_rel
        src["archived_sha256"]    = archived_sha
        summary.append({"source_id": src_id, "kind": kind, "archived_copy_path": archived_rel})

    snapshot["audit_log"].append({
        "ticker": None,
        "event": "RAW_ARCHIVED",
        "reason": (
            f"Archived {len(summary)} raw source(s) under {archive_root.name}/{date}/; "
            f"all archived sha equal raw_sha (WORM cryptographic proof)"
        ),
        "step": "core.archive.archive_raw_inputs",
        "data": {"archived": summary},
    })
