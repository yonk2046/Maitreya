"""Frozen contract for adapter output.

Every adapter that feeds `core.ingest.ingest()` MUST produce a dict matching
this shape. The contract is enforced by `validate_adapter_output()` which
adapters call as their last step before returning.

The contract intentionally stops at the structural level — it does not
inspect per-ticker raw_inputs in detail because adapters may legitimately
abstain different fields depending on data source (e.g., rollup adapter
has no branch detail). The required keys here are the *shape contract*
that ingest depends on.

See [[scd-priority-replay-first]] — adapter contracts are part of the
hardening lockdown that must hold before scoring goes live.
"""
from __future__ import annotations

import re
from typing import Any

_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Top-level keys every adapter must return.
_REQUIRED_TOP_KEYS: frozenset[str] = frozenset({
    "date",
    "raw_inputs_per_ticker",
    "universe",
    "provenance_sources",
    "audit_events",
})

# Per-ticker raw_input keys that ingest expects to be present (may be None).
# Adapters MUST emit these keys; nullability is allowed for missing data.
_REQUIRED_RAW_KEYS: frozenset[str] = frozenset({
    "ticker", "name", "rank", "is_etf",
    "current_price", "change_pct", "buy_vol_lots",
    "top5_branches", "_branches_present",
})

# Per-source provenance keys required by core/ingest.
_REQUIRED_SOURCE_KEYS: frozenset[str] = frozenset({
    "dataset", "url", "fetched_at", "raw_file", "raw_sha256",
    "row_count", "provides_fields",
})


class AdapterContractError(ValueError):
    """Raised when an adapter returns a dict that violates the frozen contract."""


def _violations(out: dict[str, Any]) -> list[str]:
    problems: list[str] = []

    # ----- Top-level shape -----
    if not isinstance(out, dict):
        return [f"adapter output is {type(out).__name__}, expected dict"]

    missing_top = _REQUIRED_TOP_KEYS - set(out.keys())
    if missing_top:
        problems.append(f"missing top-level keys: {sorted(missing_top)}")
        return problems  # can't safely inspect more

    # ----- date -----
    date = out["date"]
    if not isinstance(date, str) or not _DATE_RE.match(date):
        problems.append(f"date must be 'YYYY-MM-DD', got {date!r}")

    # ----- universe -----
    universe = out["universe"]
    if not isinstance(universe, list):
        problems.append("universe must be a list")
    elif universe != sorted(universe):
        # Universe must be sorted so canonical hashes are stable.
        problems.append("universe must be sorted ascending (replay determinism)")

    # ----- raw_inputs_per_ticker -----
    raw = out["raw_inputs_per_ticker"]
    if not isinstance(raw, dict):
        problems.append("raw_inputs_per_ticker must be a dict")
    else:
        ru_keys = set(raw.keys())
        un_set = set(universe) if isinstance(universe, list) else set()
        if ru_keys != un_set:
            extra = ru_keys - un_set
            absent = un_set - ru_keys
            if extra:
                problems.append(f"raw_inputs_per_ticker has tickers not in universe: {sorted(extra)[:5]}")
            if absent:
                problems.append(f"universe has tickers without raw_inputs: {sorted(absent)[:5]}")
        for ticker, ri in list(raw.items())[:50]:  # check first 50 to keep this O(n)
            if not isinstance(ri, dict):
                problems.append(f"raw_inputs_per_ticker[{ticker}] not a dict")
                continue
            missing = _REQUIRED_RAW_KEYS - set(ri.keys())
            if missing:
                problems.append(
                    f"raw_inputs_per_ticker[{ticker}] missing keys: {sorted(missing)}"
                )
            if ri.get("ticker") != ticker:
                problems.append(
                    f"raw_inputs_per_ticker[{ticker}].ticker = {ri.get('ticker')!r} (key mismatch)"
                )

    # ----- provenance_sources -----
    prov = out["provenance_sources"]
    if not isinstance(prov, dict):
        problems.append("provenance_sources must be a dict")
    else:
        if not prov:
            problems.append("provenance_sources is empty — every adapter must declare at least one source")
        for src_id, src in prov.items():
            if not isinstance(src, dict):
                problems.append(f"provenance_sources[{src_id}] not a dict")
                continue
            missing = _REQUIRED_SOURCE_KEYS - set(src.keys())
            if missing:
                problems.append(
                    f"provenance_sources[{src_id}] missing keys: {sorted(missing)}"
                )
            sha = src.get("raw_sha256")
            if not isinstance(sha, str) or not _SHA256_RE.match(sha):
                problems.append(
                    f"provenance_sources[{src_id}].raw_sha256 must match sha256:<64hex>, got {sha!r}"
                )
            fa = src.get("fetched_at")
            if not isinstance(fa, str) or not fa.endswith("Z"):
                problems.append(
                    f"provenance_sources[{src_id}].fetched_at must be ISO-8601 UTC ending in 'Z', got {fa!r}"
                )

    # ----- audit_events -----
    events = out["audit_events"]
    if not isinstance(events, list):
        problems.append("audit_events must be a list")
    else:
        for i, e in enumerate(events):
            if not isinstance(e, dict):
                problems.append(f"audit_events[{i}] not a dict")
                continue
            for k in ("event", "reason", "step"):
                if k not in e:
                    problems.append(f"audit_events[{i}] missing key '{k}'")

    return problems


def validate_adapter_output(out: dict[str, Any], *, adapter_name: str = "<unknown>") -> None:
    """Raise AdapterContractError with all violations, or return None on success.

    Adapters call this just before returning so downstream code can rely on
    a frozen shape.
    """
    problems = _violations(out)
    if problems:
        bullets = "\n  - " + "\n  - ".join(problems)
        raise AdapterContractError(
            f"Adapter '{adapter_name}' violated contract:{bullets}"
        )
