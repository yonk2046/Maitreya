"""Frozen adapter-contract tests.

Both adapters (legacy live, rollup backfill) must return outputs that satisfy
`data.adapters.contract.validate_adapter_output()`. These tests run both
adapters against real data and also verify the contract rejects mis-shaped
input via constructed negative cases.

Run:
    cd "Ai stock" && python -m pytest tests/test_adapter_contract.py -v
"""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from data.adapters.contract import (  # noqa: E402
    AdapterContractError,
    validate_adapter_output,
)
from data.adapters.legacy import adapt_legacy  # noqa: E402
from data.adapters.rollup import adapt_rollup, available_dates  # noqa: E402


def test_legacy_adapter_satisfies_contract():
    out = adapt_legacy()  # no date — uses today.json's tradingDate
    # If the adapter call returned at all, validate_adapter_output ran clean
    # inside it. Re-validate here as a belt-and-braces check.
    validate_adapter_output(out, adapter_name="legacy.adapt_legacy")


def test_rollup_adapter_satisfies_contract_for_every_available_date():
    dates = available_dates()
    assert dates, "Rollup has no available dates — cannot validate contract"
    for d in dates:
        out = adapt_rollup(d)
        validate_adapter_output(out, adapter_name=f"rollup.adapt_rollup({d})")


# ----- Negative cases: the validator must reject malformed output -----

def _good_minimum() -> dict:
    """Smallest dict that satisfies the contract."""
    return {
        "date": "2026-05-25",
        "raw_inputs_per_ticker": {
            "2330": {
                "ticker": "2330",
                "name": "TSMC",
                "rank": 1,
                "is_etf": False,
                "current_price": 1000.0,
                "change_pct": 1.5,
                "buy_vol_lots": 10000,
                "top5_branches": [],
                "_branches_present": False,
            },
        },
        "universe": ["2330"],
        "provenance_sources": {
            "test_src": {
                "dataset": "test",
                "url": "file:///tmp/x",
                "fetched_at": "2026-05-25T00:00:00Z",
                "raw_file": "x.json",
                "raw_sha256": "sha256:" + "a" * 64,
                "row_count": 1,
                "provides_fields": ["ticker"],
            },
        },
        "audit_events": [],
    }


def test_contract_accepts_minimal_valid():
    validate_adapter_output(_good_minimum(), adapter_name="test.minimal")


def test_contract_rejects_missing_top_key():
    bad = _good_minimum()
    del bad["date"]
    with pytest.raises(AdapterContractError, match="missing top-level keys"):
        validate_adapter_output(bad, adapter_name="test.no_date")


def test_contract_rejects_unsorted_universe():
    bad = _good_minimum()
    bad["universe"] = ["2330", "1101"]
    bad["raw_inputs_per_ticker"]["1101"] = copy.deepcopy(
        bad["raw_inputs_per_ticker"]["2330"]
    )
    bad["raw_inputs_per_ticker"]["1101"]["ticker"] = "1101"
    with pytest.raises(AdapterContractError, match="universe must be sorted"):
        validate_adapter_output(bad, adapter_name="test.unsorted")


def test_contract_rejects_ticker_key_mismatch():
    bad = _good_minimum()
    bad["raw_inputs_per_ticker"]["2330"]["ticker"] = "9999"
    with pytest.raises(AdapterContractError, match="key mismatch"):
        validate_adapter_output(bad, adapter_name="test.tickermismatch")


def test_contract_rejects_universe_raw_inputs_skew():
    bad = _good_minimum()
    bad["universe"] = ["2330", "2454"]  # universe claims 2454 but no raw_inputs
    with pytest.raises(AdapterContractError, match="without raw_inputs"):
        validate_adapter_output(bad, adapter_name="test.skew")


def test_contract_rejects_bad_sha256():
    bad = _good_minimum()
    bad["provenance_sources"]["test_src"]["raw_sha256"] = "not-a-sha"
    with pytest.raises(AdapterContractError, match="raw_sha256 must match"):
        validate_adapter_output(bad, adapter_name="test.badsha")


def test_contract_rejects_non_utc_fetched_at():
    bad = _good_minimum()
    bad["provenance_sources"]["test_src"]["fetched_at"] = "2026-05-25T08:00:00+08:00"
    with pytest.raises(AdapterContractError, match="fetched_at must be ISO-8601 UTC"):
        validate_adapter_output(bad, adapter_name="test.tz")


def test_contract_rejects_empty_provenance():
    bad = _good_minimum()
    bad["provenance_sources"] = {}
    with pytest.raises(AdapterContractError, match="provenance_sources is empty"):
        validate_adapter_output(bad, adapter_name="test.empty_prov")
