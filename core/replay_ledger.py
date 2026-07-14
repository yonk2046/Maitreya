"""Replay attestation ledger (P2-W5, candidate B / L2.5).

A **side-car verification record** — "a record about the records". Each entry
attests that a snapshot, at the moment it was generated, passed the same-machine
`--check-replay` (h1 == h2, byte-identical canonical hash on two runs), stamped
with the `core_commit_sha`, `config_hash`, canonical hash, and an environment
fingerprint (python/numpy/… versions — R10 drift diagnosis).

Constitutional boundary (fable D-5, design §5b):
  - The ledger is an **M-state verification proof**, NOT a second System of Record.
  - It carries **zero market-judgement content** — only hashes, versions,
    timestamps and an environment fingerprint.
  - Replay pass/fail **never depends on the ledger**. It records the result of a
    verification; it does not define truth. `verify_all_replay` cross-checks it
    **softly** (attested marker + drift warning) and never gates on it: a missing
    ledger entry is NOT a failure.

The ledger lives at `reports/_replay_ledger.json`, is append-only, and is
idempotent on `(date, canonical_hash)` — re-running `--check-replay` on a
byte-identical snapshot does not append a duplicate. A supersede (partial →
complete) produces a NEW canonical hash and therefore a new entry; the old
entry is retained (append-only: it records "this hash passed at creation time").
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

LEDGER_VERSION = "1.0.0"

# Environment fingerprint keys copied verbatim from a snapshot's `environment`
# block (M-state, already recorded per-snapshot). Kept to the drift-relevant
# subset (R10: python/numpy are the historical #1 cause of replay false-fails).
_FINGERPRINT_KEYS = ("python", "numpy", "pandas", "pyyaml", "jsonschema", "os")


def _pkg_version(pkg: str, default: str = "0.0.0") -> str:
    try:
        import importlib.metadata as im
        return im.version(pkg)
    except Exception:
        return default


def current_env_fingerprint() -> dict[str, str]:
    """Live environment fingerprint of the CURRENT interpreter/host.

    Used by `verify_all_replay` to detect drift against a ledger entry's
    recorded fingerprint. Mirrors the `environment` block subset that ingest
    stamps into each snapshot, so a ledger entry built from a snapshot's
    `environment` and this function are directly comparable.
    """
    import sys
    import platform

    return {
        "python":     ".".join(map(str, sys.version_info[:3])),
        "numpy":      _pkg_version("numpy"),
        "pandas":     _pkg_version("pandas"),
        "pyyaml":     _pkg_version("pyyaml"),
        "jsonschema": _pkg_version("jsonschema"),
        "os":         f"{platform.system().lower()}-{platform.release()}-{platform.machine()}",
    }


def fingerprint_from_environment(environment: dict[str, Any] | None) -> dict[str, str]:
    """Extract the drift-relevant fingerprint subset from a snapshot's
    `environment` block. Falls back to the live interpreter for any missing key
    so an older-epoch snapshot still yields a comparable dict."""
    env = environment or {}
    live = current_env_fingerprint()
    return {k: str(env.get(k, live[k])) for k in _FINGERPRINT_KEYS}


def load_ledger(ledger_path: str | pathlib.Path) -> dict:
    """Load the ledger, or return a fresh empty one if it does not exist."""
    p = pathlib.Path(ledger_path)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"ledger_version": LEDGER_VERSION, "entries": []}


def _write_ledger(ledger_path: str | pathlib.Path, ledger: dict) -> None:
    p = pathlib.Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def append_attestation(
    ledger_path: str | pathlib.Path,
    *,
    date: str,
    canonical_hash: str,
    core_commit_sha: str,
    config_hash: str,
    schema_version: str,
    check_replay_passed: bool,
    attested_at: str,
    env_fingerprint: dict[str, str],
) -> bool:
    """Append one attestation entry to the ledger (append-only, idempotent).

    Idempotency key = (date, canonical_hash). If an entry with the same date and
    canonical_hash already exists, this is a no-op (re-ingest of a byte-identical
    snapshot must not produce a duplicate record).

    Returns True if a new entry was appended, False if it was a no-op.
    """
    ledger = load_ledger(ledger_path)
    ledger.setdefault("ledger_version", LEDGER_VERSION)
    entries = ledger.setdefault("entries", [])

    for e in entries:
        if e.get("date") == date and e.get("canonical_hash") == canonical_hash:
            return False  # already attested — append-only no-op

    entries.append({
        "date":                date,
        "schema_version":      schema_version,
        "core_commit_sha":     core_commit_sha,
        "config_hash":         config_hash,
        "canonical_hash":      canonical_hash,
        "check_replay_passed": bool(check_replay_passed),
        "attested_at":         attested_at,
        "env_fingerprint":     dict(env_fingerprint),
    })
    _write_ledger(ledger_path, ledger)
    return True


def attest_from_snapshot(
    ledger_path: str | pathlib.Path,
    snapshot: dict,
    *,
    canonical_hash: str,
    check_replay_passed: bool,
    attested_at: str,
) -> bool:
    """Convenience wrapper: derive the ledger fields from a snapshot dict.

    Pulls schema_version / config_hash / core_commit_sha / env fingerprint
    straight out of the snapshot the pipeline just wrote, so the ledger reflects
    exactly what generated it.
    """
    env = snapshot.get("environment", {}) or {}
    return append_attestation(
        ledger_path,
        date=snapshot["date"],
        canonical_hash=canonical_hash,
        core_commit_sha=env.get("core_commit_sha", "0" * 40),
        config_hash=snapshot.get("config_hash", ""),
        schema_version=snapshot.get("schema_version", ""),
        check_replay_passed=check_replay_passed,
        attested_at=attested_at,
        env_fingerprint=fingerprint_from_environment(env),
    )


def latest_entry_for(ledger: dict, date: str, canonical_hash: str) -> dict | None:
    """Return the newest ledger entry matching (date, canonical_hash), or None.

    Used by verify_all_replay for a SOFT cross-check only. Never gates.
    """
    match = None
    for e in ledger.get("entries", []):
        if e.get("date") == date and e.get("canonical_hash") == canonical_hash:
            match = e  # later entries win (append order = chronological)
    return match


def env_drift(entry: dict, current: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """Compare a ledger entry's fingerprint against the current environment.

    Returns {key: (attested_value, current_value)} for every key that differs.
    Empty dict == no drift. Purely diagnostic (R10) — callers must NOT fail on
    a non-empty result.
    """
    cur = current if current is not None else current_env_fingerprint()
    attested = entry.get("env_fingerprint", {}) or {}
    drift: dict[str, tuple[str, str]] = {}
    for k in _FINGERPRINT_KEYS:
        a = str(attested.get(k, ""))
        c = str(cur.get(k, ""))
        if a and a != c:
            drift[k] = (a, c)
    return drift
