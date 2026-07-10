"""Replay participation contract — strip set derives from the Registry (RC-5 / S06).

Guards BLUEPRINT 不變量 #5: "Replay 參與權由 Registry 契約化——驗證器內不得
硬編碼任何 strip 清單." These tests assert that:

  1. the top-level normalize set is exactly the registry's excluded-M fields
     minus lineage fields (provenance),
  2. the provenance volatile sub-fields come from the registry,
  3. MUST-I / epoch-scoped-O fields are NEVER stripped,
  4. normalize_for_replay_compare() actually neutralizes those fields and
     leaves data (stocks / config_snapshot / provenance integrity) intact,
  5. adding a new excluded-M metadata field auto-extends the strip set with
     no code change (the whole point — no more drifting hardcoded lists).
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from core.replay_contract import (
    normalize_for_replay_compare,
    replay_normalized_toplevel,
    replay_volatile_provenance_subfields,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "schema" / "field_registry.yaml"


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_toplevel_strip_set_is_excluded_m_minus_lineage():
    reg = _registry()
    excluded_m = {
        e["name"] for e in reg["snapshot_fields"] if e.get("replay") == "excluded-M"
    }
    lineage = {
        e["name"]
        for e in reg["snapshot_fields"]
        if e.get("replay_role") == "lineage"
    }
    expected = excluded_m - lineage
    assert replay_normalized_toplevel() == expected
    # Sanity: the wall-clock / env / build fields are in; provenance (lineage) is out.
    assert {"generated_at", "environment", "audit_log"} <= replay_normalized_toplevel()
    assert "provenance" not in replay_normalized_toplevel()


def test_must_i_and_epoch_o_never_stripped():
    """The strip set must never touch replay-invariant data fields."""
    strip = replay_normalized_toplevel()
    # Input fact (config parameters) and the observation container must be compared.
    assert "config_snapshot" not in strip
    assert "stocks" not in strip
    assert "rankings" not in strip
    assert "config_hash" not in strip


def test_provenance_volatile_subfields_from_registry():
    assert replay_volatile_provenance_subfields() == frozenset(
        {"fetched_at", "report_date", "data_lag_days"}
    )
    # Lineage integrity fields must NOT be in the volatile (stripped) set.
    vol = replay_volatile_provenance_subfields()
    for integrity in ("raw_sha256", "archived_sha256", "archived_copy_path"):
        assert integrity not in vol


def test_normalize_neutralizes_metadata_keeps_data():
    reference = {
        "schema_version": "1.8.1",
        "generated_at": "2026-07-09T00:00:00Z",
        "core_version": "core@0.1.0-p3a",
        "environment": {"os": "macos", "python": "3.11"},
        "audit_log": [{"event": "RAW_ARCHIVED"}],
        "config_snapshot": {"threshold": 5},
        "stocks": [{"ticker": "2330", "tier": "IGNORE"}],
        "provenance": {
            "sources": {
                "legacy_today_json": {
                    "raw_sha256": "sha256:aaa",
                    "archived_sha256": "sha256:aaa",
                    "fetched_at": "2026-07-09T01:00:00Z",
                    "report_date": "2026-07-09",
                    "data_lag_days": 0,
                }
            }
        },
    }
    # A "replayed" snap that differs only in replay-excluded fields + integrity
    # data that should still be compared.
    snap = copy.deepcopy(reference)
    snap["generated_at"] = "2026-07-09T23:59:59Z"          # wall clock: differs
    snap["environment"] = {"os": "linux", "python": "3.12"}  # build machine: differs
    snap["audit_log"] = [{"event": "RAW_ARCHIVED"}, {"event": "EXTRA"}]
    snap["provenance"]["sources"]["legacy_today_json"]["fetched_at"] = "2026-07-10T09:00:00Z"
    snap["provenance"]["sources"]["legacy_today_json"]["data_lag_days"] = 1

    normalize_for_replay_compare(snap, reference)

    # Excluded-M fields are neutralized to the reference values.
    assert snap["generated_at"] == reference["generated_at"]
    assert snap["environment"] == reference["environment"]
    assert snap["audit_log"] == reference["audit_log"]
    # provenance volatile sub-fields normalized...
    src = snap["provenance"]["sources"]["legacy_today_json"]
    assert src["fetched_at"] == reference["provenance"]["sources"]["legacy_today_json"]["fetched_at"]
    assert src["data_lag_days"] == 0
    # ...but lineage integrity sub-fields untouched (still comparable).
    assert src["raw_sha256"] == "sha256:aaa"
    # Data fields untouched.
    assert snap["config_snapshot"] == {"threshold": 5}
    assert snap["stocks"] == [{"ticker": "2330", "tier": "IGNORE"}]


def test_new_excluded_m_field_auto_extends_strip_set():
    """The cure for RC-5: a NEW excluded-M field extends the strip set with
    ZERO code change — no hand-edited list to forget."""
    reg = copy.deepcopy(_registry())
    reg["snapshot_fields"].append(
        {
            "name": "build_host",
            "semantic": "hypothetical new metadata field",
            "state": "M",
            "grain": "date",
            "replay": "excluded-M",
            "owner": "Pipeline(ingest)",
            "status": "active",
        }
    )
    assert "build_host" in replay_normalized_toplevel(reg)


def test_tampering_a_compared_field_is_not_masked():
    """Integrity guard: a data field the contract does NOT strip stays different
    after normalization (i.e. would be caught by the hash comparison)."""
    reference = {
        "generated_at": "t0",
        "stocks": [{"ticker": "2330", "composite_score": 0}],
        "provenance": {"sources": {"s": {"raw_sha256": "sha256:good"}}},
    }
    snap = copy.deepcopy(reference)
    snap["stocks"][0]["composite_score"] = 99          # tampered data
    snap["provenance"]["sources"]["s"]["raw_sha256"] = "sha256:BAD"  # tampered lineage
    normalize_for_replay_compare(snap, reference)
    assert snap["stocks"][0]["composite_score"] == 99  # NOT masked
    assert snap["provenance"]["sources"]["s"]["raw_sha256"] == "sha256:BAD"  # NOT masked
