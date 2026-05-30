"""Canonical hashing utilities — the single source of truth for snapshot integrity.

See docs/REPLAY.md §4 for the canonicalization rule.

Public API:
    canonical_bytes(obj)   -> bytes      # NFC-normalized + sort_keys + minified UTF-8
    canonical_sha256(obj)  -> str        # "sha256:<64-hex>"
    file_sha256(path)      -> str        # hash of file bytes verbatim (for raw data)
    write_sidecar(snapshot_path, snapshot_obj) -> str
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import unicodedata
from typing import Any


def _nfc_walk(x: Any) -> Any:
    """Recursively NFC-normalize all string values."""
    if isinstance(x, str):
        return unicodedata.normalize("NFC", x)
    if isinstance(x, dict):
        return {k: _nfc_walk(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_nfc_walk(v) for v in x]
    return x


def canonical_bytes(obj: Any) -> bytes:
    """Produce the canonical byte representation of a snapshot.

    Rules (per REPLAY.md §4):
      - NFC-normalize every string
      - sort_keys=True
      - ensure_ascii=False (UTF-8 native)
      - separators=(',', ':') — no whitespace
      - allow_nan=False — reject NaN/Inf
    """
    normalized = _nfc_walk(obj)
    return json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(obj: Any) -> str:
    """Return canonical SHA-256 of an object as 'sha256:<64-hex>'."""
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def file_sha256(path: str | os.PathLike) -> str:
    """Return SHA-256 of file bytes verbatim (no canonicalization)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def write_sidecar(snapshot_path: str | os.PathLike, snapshot_obj: Any) -> str:
    """Compute canonical SHA-256 and write `<path>.sha256` sidecar.

    Returns the hash string.
    """
    p = pathlib.Path(snapshot_path)
    h = canonical_sha256(snapshot_obj)
    sidecar = p.with_name(p.name + ".sha256")
    sidecar.write_text(f"{h}  {p.name}\n", encoding="utf-8")
    return h


def verify_sidecar(snapshot_path: str | os.PathLike) -> tuple[bool, str, str]:
    """Verify a snapshot file against its sidecar.

    Returns (matches, expected_hash, actual_hash).
    """
    p = pathlib.Path(snapshot_path)
    sidecar = p.with_name(p.name + ".sha256")
    expected = sidecar.read_text().strip().split()[0]
    obj = json.loads(p.read_text(encoding="utf-8"))
    actual = canonical_sha256(obj)
    return (expected == actual, expected, actual)
