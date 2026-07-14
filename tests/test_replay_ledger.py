"""Tests for the replay attestation ledger (P2-W5, L2.5).

Covers the four W5 acceptance requirements:
  1. idempotent — same (date, canonical_hash) never double-recorded
  2. append-only — a new hash for the same date appends; old entry retained
  3. soft cross-check — missing ledger entry is NOT a failure (fable D-5)
  4. M-state discipline — ledger entries carry ZERO market-judgement fields
Plus environment-fingerprint drift diagnosis (R10).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.replay_ledger import (  # noqa: E402
    LEDGER_VERSION,
    append_attestation,
    attest_from_snapshot,
    current_env_fingerprint,
    env_drift,
    fingerprint_from_environment,
    latest_entry_for,
    load_ledger,
)

# The complete, closed set of keys a ledger entry may contain. Any key outside
# this set is a leak of non-M content into the verification record.
_ALLOWED_ENTRY_KEYS = {
    "date", "schema_version", "core_commit_sha", "config_hash",
    "canonical_hash", "check_replay_passed", "attested_at", "env_fingerprint",
}
_ALLOWED_FINGERPRINT_KEYS = {"python", "numpy", "pandas", "pyyaml", "jsonschema", "os"}

_SAMPLE_ENV = {
    "core_commit_sha": "a" * 40,
    "python": "3.9.6",
    "numpy": "2.0.2",
    "pandas": "2.3.3",
    "pyyaml": "6.0.3",
    "jsonschema": "4.25.1",
    "os": "darwin-24.6.0-arm64",
}


def _snapshot(date: str, config_hash: str = "sha256:cfg") -> dict:
    return {
        "date": date,
        "schema_version": "1.9.0",
        "config_hash": config_hash,
        "environment": dict(_SAMPLE_ENV),
    }


def _append(ledger_path, date, chash, passed=True):
    return attest_from_snapshot(
        ledger_path,
        _snapshot(date),
        canonical_hash=chash,
        check_replay_passed=passed,
        attested_at="2026-07-13T12:00:00Z",
    )


def test_load_missing_ledger_is_empty(tmp_path):
    led = load_ledger(tmp_path / "nope.json")
    assert led["entries"] == []
    assert led["ledger_version"] == LEDGER_VERSION


def test_idempotent_same_date_and_hash(tmp_path):
    lp = tmp_path / "_replay_ledger.json"
    assert _append(lp, "2026-07-13", "sha256:aaa") is True
    # Second run, byte-identical snapshot → same (date, hash) → no-op.
    assert _append(lp, "2026-07-13", "sha256:aaa") is False
    assert _append(lp, "2026-07-13", "sha256:aaa") is False
    led = load_ledger(lp)
    assert len(led["entries"]) == 1


def test_append_only_new_hash_retains_old(tmp_path):
    lp = tmp_path / "_replay_ledger.json"
    _append(lp, "2026-07-13", "sha256:partial")   # e.g. partial snapshot
    _append(lp, "2026-07-13", "sha256:complete")  # supersede → new hash
    led = load_ledger(lp)
    assert len(led["entries"]) == 2
    hashes = [e["canonical_hash"] for e in led["entries"]]
    assert hashes == ["sha256:partial", "sha256:complete"]  # old retained, order preserved


def test_failed_replay_recorded_as_flag_not_dropped(tmp_path):
    lp = tmp_path / "_replay_ledger.json"
    _append(lp, "2026-07-13", "sha256:bad", passed=False)
    led = load_ledger(lp)
    assert led["entries"][0]["check_replay_passed"] is False


def test_entry_has_zero_market_judgement_fields(tmp_path):
    """M-state discipline: only hash/version/timestamp/env fingerprint."""
    lp = tmp_path / "_replay_ledger.json"
    _append(lp, "2026-07-13", "sha256:aaa")
    led = load_ledger(lp)
    entry = led["entries"][0]
    assert set(entry.keys()) == _ALLOWED_ENTRY_KEYS
    assert set(entry["env_fingerprint"].keys()) == _ALLOWED_FINGERPRINT_KEYS
    # No nested structure that could smuggle a stock ticker / tier / score.
    blob = json.dumps(led).lower()
    for banned in ("ticker", "tier", "golden", "conviction", "grade", "stocks", "score"):
        assert banned not in blob


def test_attest_from_snapshot_pulls_snapshot_fields(tmp_path):
    lp = tmp_path / "_replay_ledger.json"
    snap = _snapshot("2026-07-13", config_hash="sha256:deadbeef")
    attest_from_snapshot(lp, snap, canonical_hash="sha256:h",
                         check_replay_passed=True, attested_at="2026-07-13T00:00:00Z")
    e = load_ledger(lp)["entries"][0]
    assert e["config_hash"] == "sha256:deadbeef"
    assert e["core_commit_sha"] == "a" * 40
    assert e["schema_version"] == "1.9.0"
    assert e["env_fingerprint"]["numpy"] == "2.0.2"


def test_latest_entry_for_missing_returns_none(tmp_path):
    """Soft cross-check: no ledger entry must be a benign None, never a failure."""
    lp = tmp_path / "_replay_ledger.json"
    _append(lp, "2026-07-13", "sha256:aaa")
    led = load_ledger(lp)
    assert latest_entry_for(led, "2026-07-13", "sha256:aaa") is not None
    # Different hash / unknown date → None (verify treats this as "not attested").
    assert latest_entry_for(led, "2026-07-13", "sha256:other") is None
    assert latest_entry_for(led, "2026-01-01", "sha256:aaa") is None
    assert latest_entry_for({"entries": []}, "2026-07-13", "sha256:aaa") is None


def test_latest_entry_prefers_newest_on_duplicate_scan(tmp_path):
    # Two entries with same (date, hash) shouldn't happen (idempotent), but the
    # scan must still return the last one deterministically if they did.
    led = {"entries": [
        {"date": "d", "canonical_hash": "h", "check_replay_passed": False},
        {"date": "d", "canonical_hash": "h", "check_replay_passed": True},
    ]}
    assert latest_entry_for(led, "d", "h")["check_replay_passed"] is True


def test_env_drift_detects_version_change():
    entry = {"env_fingerprint": dict(_SAMPLE_ENV)}
    same = fingerprint_from_environment(_SAMPLE_ENV)
    assert env_drift(entry, same) == {}
    drifted = dict(same)
    drifted["numpy"] = "2.1.0"
    d = env_drift(entry, drifted)
    assert d == {"numpy": ("2.0.2", "2.1.0")}


def test_env_drift_empty_when_no_fingerprint():
    assert env_drift({}, current_env_fingerprint()) == {}


def test_fingerprint_from_environment_subset_only():
    fp = fingerprint_from_environment(_SAMPLE_ENV)
    assert set(fp.keys()) == _ALLOWED_FINGERPRINT_KEYS
    assert "core_commit_sha" not in fp  # git sha is not a drift-diagnosis field
