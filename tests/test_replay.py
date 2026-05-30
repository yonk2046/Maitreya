"""Replay determinism tests for P3a ingest.

Run:
    cd "Ai stock" && python -m pytest tests/ -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
import yaml

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core.hashing import canonical_sha256, canonical_bytes
from core.ingest import ingest
from data.adapters.legacy import adapt_legacy


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))


def _normalize_for_replay(snap: dict, ref_generated_at: str) -> dict:
    """generated_at is wall-clock; it's intentionally NOT part of replay-match.
    For test purposes, normalize the wall-clock field to a fixed value.
    """
    s = dict(snap)
    s["generated_at"] = ref_generated_at
    return s


def test_replay_determinism_two_runs(cfg):
    """Running ingest twice on the same raw inputs must produce identical canonical hash."""
    a1 = adapt_legacy()
    a2 = adapt_legacy()
    s1 = ingest(a1, cfg)
    s2 = ingest(a2, cfg)
    # Normalize wall-clock field (audit-level concession; everything else must match)
    s2n = _normalize_for_replay(s2, s1["generated_at"])
    h1 = canonical_sha256(s1)
    h2 = canonical_sha256(s2n)
    assert h1 == h2, (
        f"Replay non-determinism detected:\n  run1 hash: {h1}\n  run2 hash: {h2}"
    )


def test_canonical_bytes_round_trip(cfg):
    """canonical_bytes(parse(canonical_bytes(x))) == canonical_bytes(x)."""
    a = adapt_legacy()
    snap = ingest(a, cfg)
    b1 = canonical_bytes(snap)
    b2 = canonical_bytes(json.loads(b1.decode("utf-8")))
    assert b1 == b2


def test_environment_block_required_fields(cfg):
    a = adapt_legacy()
    snap = ingest(a, cfg)
    env = snap["environment"]
    for k in ("core_commit_sha", "python", "numpy", "pandas",
              "decimal_context", "locale", "timezone",
              "lookback_snapshots", "lookback_window_days"):
        assert k in env, f"environment.{k} missing"
    assert env["timezone"] == "UTC"
    assert env["decimal_context"]["rounding"] == "ROUND_HALF_EVEN"
    assert env["decimal_context"]["prec"] >= 28


def test_all_scoring_abstained_at_ingest(cfg):
    """P3a constraint: no scoring computed; everything IGNORE."""
    a = adapt_legacy()
    snap = ingest(a, cfg)
    for s in snap["stocks"]:
        assert s["tier"] == "IGNORE", f"{s['ticker']}: tier should be IGNORE at ingest-only stage"
        assert s["composite_score"] == 0
        assert s["stage_1"] == 0 and s["stage_2"] == 0 and s["stage_3"] == 0
        ts = s["temporal_state"]
        assert ts["abstained"]["velocity"] is True
        assert ts["abstained"]["acceleration"] is True


def test_provenance_per_source_complete(cfg):
    a = adapt_legacy()
    snap = ingest(a, cfg)
    prov = snap["provenance"]
    assert "sources" in prov
    assert "field_to_source" in prov
    # Every source has raw_sha256 conformant
    import re
    for src_id, src in prov["sources"].items():
        assert "raw_sha256" in src
        assert re.match(r"^sha256:[a-f0-9]{64}$", src["raw_sha256"]), f"{src_id} bad sha"


def test_bootstrap_emits_audit_event(cfg):
    a = adapt_legacy()
    snap = ingest(a, cfg, prior_snapshots=None)
    events = [e["event"] for e in snap["audit_log"]]
    assert "BOOTSTRAP_SNAPSHOT" in events


def test_lookback_emits_verified_event(cfg):
    a = adapt_legacy()
    fake_prior = {"2026-05-24": "sha256:" + "a" * 64}
    snap = ingest(a, cfg, prior_snapshots=fake_prior)
    events = [e["event"] for e in snap["audit_log"]]
    assert "LOOKBACK_VERIFIED" in events
    assert snap["environment"]["lookback_snapshots"] == fake_prior
