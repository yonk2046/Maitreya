"""Replay participation contract — derived from the Canonical Field Registry.

WHY THIS EXISTS (RC-5 / S06 / NOTES #16):
  "Which fields do NOT participate in replay comparison" used to live as TWO
  hardcoded, drifting strip lists — `run_pipeline.py` stripped only
  {generated_at}; `verify_all_replay.py` stripped {generated_at, environment,
  audit_log} + provenance sub-fields {fetched_at, report_date, data_lag_days}.
  Any newly-added metadata field silently re-introduced cross-machine
  false-fails unless a human remembered to patch the right list.

  This module makes `schema/field_registry.yaml` the SINGLE source of truth:
  a field's `replay` level (excluded-M / MUST-I / epoch-scoped-O) is a CONTRACT
  DECLARATION, and the replay-comparison strip set is DERIVED from it, not
  maintained by hand. See BLUEPRINT 不變量 #5 ("Replay 參與權由 Registry
  契約化——驗證器內不得硬編碼任何 strip 清單").

THE GRAIN GAP (honest note — see docs/migration/P1-version-pinned-replay.md §3):
  Field-level `excluded-M` is *almost* enough, with one exception the registry
  encodes explicitly:
    - Most excluded-M top-level fields (generated_at, environment, audit_log,
      schema_version, core_version) are normalized WHOLESALE: their value is
      copied from the reference snapshot before hashing, so they never affect
      the comparison. -> replay_normalized_toplevel().
    - `provenance` is state=M but is a LINEAGE exception: its integrity
      sub-fields (raw_sha256 / archived_sha256 / archived_copy_path) MUST stay
      in the compared hash (they are how archive drift is detected). Only its
      mtime-derived volatile sub-fields are normalized. The registry marks this
      with `replay_role: lineage` + `replay_volatile_subfields: [...]`.
      -> replay_volatile_provenance_subfields().

Public API:
    replay_normalized_toplevel(registry=None)        -> frozenset[str]
    replay_volatile_provenance_subfields(registry=None) -> frozenset[str]
    normalize_for_replay_compare(snap, reference)    -> None  (mutates snap)
"""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "schema" / "field_registry.yaml"
)


def _load_registry() -> dict:
    return yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))


def replay_normalized_toplevel(registry: dict | None = None) -> frozenset[str]:
    """Top-level snapshot fields normalized away in replay comparison.

    = every top-level field declared `replay: excluded-M` in the registry,
    EXCEPT lineage fields (`replay_role: lineage`) whose content backs the
    integrity hash and must stay compared.
    """
    reg = registry or _load_registry()
    out: set[str] = set()
    for e in reg.get("snapshot_fields", []):
        if e.get("replay") == "excluded-M" and e.get("replay_role") != "lineage":
            out.add(e["name"])
    return frozenset(out)


def replay_volatile_provenance_subfields(registry: dict | None = None) -> frozenset[str]:
    """provenance.sources[*] sub-fields that are mtime-derived / environment
    timestamps and are normalized (fetched_at / report_date / data_lag_days).

    The lineage integrity sub-fields (raw_sha256 / archived_sha256 /
    archived_copy_path) are deliberately NOT in this set: they stay in the
    compared hash so that archive drift is caught.
    """
    reg = registry or _load_registry()
    for e in reg.get("snapshot_fields", []):
        if e.get("name") == "provenance":
            return frozenset(e.get("replay_volatile_subfields", []))
    return frozenset()


def normalize_for_replay_compare(snap: dict[str, Any], reference: dict[str, Any]) -> None:
    """Copy replay-excluded field values from `reference` into `snap` in place.

    After this call, `canonical_sha256(snap)` reflects ONLY replay-invariant
    content, so comparing it against the reference's canonical hash tests
    reproducibility of the data, not of wall-clock / build-environment / mtime
    metadata.

    Used by BOTH:
      - run_pipeline.py --check-replay (reference = run-1 snapshot; same machine)
      - verify_all_replay.py           (reference = on-disk snapshot; cross machine)

    The two callers differ only in WHAT they compare (two in-memory runs vs
    disk-vs-index); the CONTRACT for what is replay-invariant is identical and
    lives here, derived from the registry.
    """
    # (1) Whole-field normalization for excluded-M non-lineage top-level fields.
    for f in replay_normalized_toplevel():
        if f in reference:
            snap[f] = reference[f]
        elif f in snap:
            # Reference lacks it (unexpected for an active M field) — drop to
            # stay symmetric so an asymmetric presence can't false-fail.
            del snap[f]

    # (2) provenance lineage exception: keep integrity sub-fields in the hash,
    #     normalize only the enumerated volatile (mtime-derived) sub-fields.
    volatile = replay_volatile_provenance_subfields()
    if volatile:
        ref_sources = reference.get("provenance", {}).get("sources", {})
        for sid, src in snap.get("provenance", {}).get("sources", {}).items():
            if not isinstance(src, dict):
                continue
            ref_src = ref_sources.get(sid, {})
            if not isinstance(ref_src, dict):
                continue
            for f in volatile:
                if f in src and f in ref_src:
                    src[f] = ref_src[f]
