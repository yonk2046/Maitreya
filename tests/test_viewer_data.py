"""Viewer data-layer smoke tests + replay-safety proof.

The viewer's headline claim is that it's read-only and replay-safe. These
tests enforce that claim:

  - loading the index doesn't change index.json bytes
  - loading every snapshot doesn't change any reports/*.json bytes
  - computing every metric doesn't change any file under reports/
  - integrity_status agrees with what tests/test_contracts.py would say

We do NOT import streamlit at module load — the @st.cache_data decorators
in viewer/data.py work as plain no-ops when there's no active Streamlit
runtime, so we can call the functions directly under pytest.

Run:
    cd "Ai stock" && python -m pytest tests/test_viewer_data.py -v
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import pytest  # noqa: E402

from viewer import data as vd  # noqa: E402
from viewer import metrics as vm  # noqa: E402

REPORTS_DIR = _AI_STOCK / "reports"


def _fingerprint_tree(root: pathlib.Path) -> dict[str, str]:
    """{relative_path: sha256_hex} for every regular file under root."""
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            out[str(f.relative_to(root))] = h.hexdigest()
    return out


# ---------------------------------------------------------------------------
# Read-only proof: hash every file under reports/ before and after every
# viewer code path; assert no bytes changed.
# ---------------------------------------------------------------------------

@pytest.fixture
def reports_fingerprint() -> dict[str, str]:
    return _fingerprint_tree(REPORTS_DIR)


def test_loading_index_is_read_only(reports_fingerprint):
    _ = vd.load_index()
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint, \
        "viewer.data.load_index() changed bytes under reports/ — read-only violation"


def test_loading_every_snapshot_is_read_only(reports_fingerprint):
    for d in vd.real_dates():
        _ = vd.load_snapshot(d)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_canonical_hashing_is_read_only(reports_fingerprint):
    for d in vd.real_dates():
        _ = vd.integrity_status(d)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint


def test_metrics_computation_is_read_only(reports_fingerprint):
    _ = vm.coverage_summary()
    _ = vm.calendar_gaps()
    _ = vm.ticker_streaks()
    _ = vm.tier_transitions()
    _ = vm.audit_event_counts()
    _ = vm.global_event_summary()
    _ = vm.lookback_depth_distribution()
    _ = vm.all_audit_events_flat()
    _ = vm.integrity_summary_all()
    for d in vd.real_dates():
        _ = vm.lookback_chain_for(d)
        _ = vm.snapshot_summary_row(d)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint, \
        "viewer.metrics computation changed bytes under reports/ — read-only violation"


def test_daily_log_loaders_are_read_only(reports_fingerprint):
    """Loading daily logs (Panel 8 data) must not modify any file under reports/."""
    _ = vd.daily_log_dates()
    for d in vd.daily_log_dates():
        _ = vd.load_daily_log(d)
        _ = vd.daily_log_runs(d)
        _ = vd.daily_log_summary_row(d)
    assert _fingerprint_tree(REPORTS_DIR) == reports_fingerprint, \
        "daily-log loaders modified bytes under reports/ — read-only violation"


# ---------------------------------------------------------------------------
# Data-correctness sanity
# ---------------------------------------------------------------------------

def test_real_dates_present():
    dates = vd.real_dates()
    assert dates, "No real-date snapshots — cannot validate viewer"
    for d in dates:
        # Every date key must be ISO format
        import datetime as dt
        dt.date.fromisoformat(d)


def test_integrity_status_all_clean():
    """All snapshots should pass the viewer's three-witness check (it should agree
    with `tests/test_contracts.py::test_index_current_hash_matches_disk`).
    """
    failures: list[str] = []
    for d in vd.real_dates():
        s = vd.integrity_status(d)
        if not s["all_three_agree"]:
            failures.append(
                f"{d}: sidecar_matches={s['sidecar_matches']} "
                f"index_matches={s['index_matches']}"
            )
    assert not failures, "\n".join(failures)


def test_ticker_history_returns_one_row_per_date():
    tickers = vd.all_tickers_across_history()
    assert tickers, "No tickers across history — viewer ticker panel would be empty"
    sample = tickers[0]
    hist = vd.ticker_history(sample)
    assert len(hist) == len(vd.real_dates())
    for r in hist:
        assert set(r.keys()) >= {
            "date", "present", "tier", "composite_score",
            "current_price", "change_pct", "volume", "audit_events",
        }


def test_coverage_summary_internally_consistent():
    cov = vm.coverage_summary()
    assert cov["snapshot_count"] == len(vd.real_dates())
    if cov["snapshot_count"] >= 2:
        assert cov["first_date"] <= cov["last_date"]
        assert cov["calendar_span_days"] >= cov["snapshot_count"]


def test_lookback_chain_for_bootstrap_marks_bootstrap_true():
    # The earliest snapshot must be a BOOTSTRAP_SNAPSHOT (no priors)
    dates = vd.real_dates()
    info = vm.lookback_chain_for(dates[0])
    assert info["bootstrap"] is True, (
        f"Earliest snapshot {dates[0]} should be bootstrap but has "
        f"{len(info['lookback'])} priors"
    )


def test_streaks_sum_to_total_appearances():
    """Sum of all tickers' appearances must equal sum of universe sizes."""
    dates = vd.real_dates()
    total_universe_size = sum(len(vd.universe_for_date(d)) for d in dates)
    total_appearances = sum(s["appearances"] for s in vm.ticker_streaks())
    assert total_appearances == total_universe_size


def test_all_audit_events_flat_shape():
    """all_audit_events_flat returns rows with expected keys, and the
    total count equals the sum of per-date audit_log lengths.
    """
    events = vm.all_audit_events_flat()
    expected_keys = {"date", "event", "step", "ticker", "reason", "node_path", "has_data"}
    for e in events:
        assert set(e.keys()) >= expected_keys
    # totals must match per-date sums
    expected_total = 0
    for d in vd.real_dates():
        snap = vd.load_snapshot(d)
        expected_total += len(snap.get("audit_log", []))
    assert len(events) == expected_total


def test_integrity_summary_all_matches_per_date_integrity():
    """integrity_summary_all() is just batch projection of integrity_status."""
    summary = vm.integrity_summary_all()
    dates = vd.real_dates()
    assert len(summary) == len(dates)
    for s, d in zip(summary, dates):
        assert s["date"] == d
        # Re-derive integrity for this date and confirm equality on the booleans
        s2 = vd.integrity_status(d)
        assert s["all_three_agree"] == s2["all_three_agree"]
        assert s["sidecar_matches"] == s2["sidecar_matches"]
        assert s["index_matches"]   == s2["index_matches"]


def test_daily_log_runs_structure_when_present():
    """If any daily logs exist on disk, every run must start with orchestrator_start."""
    for d in vd.daily_log_dates():
        runs = vd.daily_log_runs(d)
        for i, run in enumerate(runs):
            assert run, f"empty run #{i} in {d}.log"
            assert run[0].get("step") == "orchestrator_start", (
                f"{d}.log run #{i} doesn't start with orchestrator_start"
            )


def test_daily_log_summary_consistency():
    """summary['run_count'] must equal len(daily_log_runs)."""
    for d in vd.daily_log_dates():
        summary = vd.daily_log_summary_row(d)
        runs = vd.daily_log_runs(d)
        assert summary["run_count"] == len(runs)
        assert summary["date"] == d


def test_audit_explorer_filterable_by_event_type():
    """Filtering the audit list by event type returns a subset with only that event."""
    events = vm.all_audit_events_flat()
    if not events:
        return
    # Pick an event type that exists
    sample_event = next(iter({e["event"] for e in events if e["event"]}))
    filtered = [e for e in events if e["event"] == sample_event]
    assert filtered
    for e in filtered:
        assert e["event"] == sample_event
