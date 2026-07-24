"""Tests for tools.run_pipeline — the empty-universe abstain guard.

2026-07-24 incident: upstream 富邦主力買超榜 was empty overnight
(mainForceBuy/buyList/sellList all []) — a known "evening 分點 unavailable"
pattern, NOT a trading holiday (breadth/marketQuotes were fully populated).
The adapter's `universe` was therefore 0 tickers, but run_pipeline used to
write out a stocks=[] snapshot anyway, update index.json, and attest it into
the replay ledger. That empty snapshot would silently satisfy both
canary.yml's "reports/<date>.json exists" check and daily.yml's morning
file-exists gate, permanently losing that day's real data.

The guard added to tools.run_pipeline.run() must abstain — return None,
write nothing (no snapshot, no index.json touch, no ledger attest) — BEFORE
any write, the instant universe==0, and must leave the universe>0 path
completely unaffected (same as the existing "T86 未公布→跳過等重跑" skip
semantics in tools/daily.py — not an error).

Run:
    cd "Ai stock" && python -m pytest tests/test_run_pipeline.py -v
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

from core.hashing import file_sha256  # noqa: E402
from tools import run_pipeline  # noqa: E402

# A real, static, small repo file used as the fake single-ticker source's
# raw_file — archive_raw_inputs() requires raw_file to resolve to a real file
# under repo_root (see core/archive.py), so we point it at something that
# genuinely exists rather than a fabricated path.
_REAL_RAW_FILE = "config/scd.example.yaml"


def _empty_adapter_out(date: str) -> dict:
    """Mirrors adapt_legacy()'s shape when mainForceBuy/buyList/sellList are
    all [] (the 2026-07-24 incident pattern) — universe == 0."""
    return {
        "date": date,
        "raw_inputs_per_ticker": {},
        "universe": [],
        "provenance_sources": {},
        "audit_events": [],
        "_today_meta": {"tradingDate": date},
    }


def _single_ticker_adapter_out(date: str) -> dict:
    """Minimal valid single-ticker adapter output (universe == 1) — the
    normal, guard-should-not-fire path."""
    raw_sha = file_sha256(_AI_STOCK / _REAL_RAW_FILE)
    return {
        "date": date,
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
                "url": "file:///test",
                "fetched_at": f"{date}T00:00:00Z",
                "raw_file": _REAL_RAW_FILE,
                "raw_sha256": raw_sha,
            },
        },
        "audit_events": [],
        "_today_meta": {"tradingDate": date},
    }


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    """Redirect every run_pipeline write target to a tmp dir, so a guard
    regression can never write into the real repo's reports/ during tests."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(run_pipeline, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(run_pipeline, "INDEX_FILE", reports_dir / "index.json")
    monkeypatch.setattr(run_pipeline, "RAW_ARCHIVE_DIR", reports_dir / "_raw_archive")
    monkeypatch.setattr(run_pipeline, "REPLAY_LEDGER_FILE", reports_dir / "_replay_ledger.json")
    monkeypatch.setattr(run_pipeline, "STRATEGY_TAGS_DIR", reports_dir / "strategy_tags")
    return reports_dir


# ---------------------------------------------------------------------------
# universe == 0 → abstain, nothing written
# ---------------------------------------------------------------------------

def test_empty_universe_returns_none(tmp_reports, monkeypatch):
    date = "2026-07-24"
    monkeypatch.setattr(
        run_pipeline, "adapt_legacy",
        lambda date=None, **kw: _empty_adapter_out(date or "2026-07-24"),
    )

    result = run_pipeline.run(date, check_replay=True, source="legacy")

    assert result is None


def test_empty_universe_writes_no_snapshot_no_index_no_ledger(tmp_reports, monkeypatch):
    date = "2026-07-24"
    monkeypatch.setattr(
        run_pipeline, "adapt_legacy",
        lambda date=None, **kw: _empty_adapter_out(date or "2026-07-24"),
    )

    run_pipeline.run(date, check_replay=True, source="legacy")

    assert not (tmp_reports / f"{date}.json").exists(), \
        "universe==0 must not write reports/<date>.json"
    assert not (tmp_reports / f"{date}.json.sha256").exists()
    assert not run_pipeline.INDEX_FILE.exists(), \
        "universe==0 must not touch index.json"
    assert not run_pipeline.REPLAY_LEDGER_FILE.exists(), \
        "universe==0 must not attest into the replay ledger"
    assert not (tmp_reports / "strategy_tags" / f"{date}.json").exists()
    assert not (tmp_reports / "_raw_archive" / date).exists(), \
        "universe==0 must abstain before the raw-archive step too"


def test_main_exits_with_skip_code_on_empty_universe(tmp_reports, monkeypatch, capsys):
    """CLI entrypoint: main() must sys.exit(EXIT_SKIP_EMPTY_UNIVERSE) — a
    distinct code from both success (0) and a genuine failure (unhandled
    exception → 1) — so tools/daily.py can tell "clean skip" from "broken"."""
    date = "2026-07-24"
    monkeypatch.setattr(
        run_pipeline, "adapt_legacy",
        lambda date=None, **kw: _empty_adapter_out(date or "2026-07-24"),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["run_pipeline", "--date", date, "--source", "legacy", "--check-replay"],
    )

    with pytest.raises(SystemExit) as exc_info:
        run_pipeline.main()

    assert exc_info.value.code == run_pipeline.EXIT_SKIP_EMPTY_UNIVERSE
    assert exc_info.value.code == 3
    assert not (tmp_reports / f"{date}.json").exists()


# ---------------------------------------------------------------------------
# universe > 0 → unaffected normal path
# ---------------------------------------------------------------------------

def test_nonempty_universe_writes_snapshot_updates_index_attests(tmp_reports, monkeypatch):
    date = "2026-05-25"
    monkeypatch.setattr(
        run_pipeline, "adapt_legacy",
        lambda date=None, **kw: _single_ticker_adapter_out(date or "2026-05-25"),
    )

    result = run_pipeline.run(date, check_replay=True, source="legacy")

    assert result is not None
    assert [s["ticker"] for s in result["stocks"]] == ["2330"]

    snap_path = tmp_reports / f"{date}.json"
    assert snap_path.exists()
    assert (tmp_reports / f"{date}.json.sha256").exists()

    idx = json.loads(run_pipeline.INDEX_FILE.read_text(encoding="utf-8"))
    assert date in idx["snapshots"]

    ledger = json.loads(run_pipeline.REPLAY_LEDGER_FILE.read_text(encoding="utf-8"))
    assert ledger, "check-replay run must attest into the ledger when universe>0"


def test_main_exits_zero_on_nonempty_universe(tmp_reports, monkeypatch):
    date = "2026-05-25"
    monkeypatch.setattr(
        run_pipeline, "adapt_legacy",
        lambda date=None, **kw: _single_ticker_adapter_out(date or "2026-05-25"),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["run_pipeline", "--date", date, "--source", "legacy", "--check-replay"],
    )

    # main() falls through with no sys.exit() call when the run succeeds —
    # i.e. the process exits 0 (no SystemExit raised at all).
    run_pipeline.main()

    assert (tmp_reports / f"{date}.json").exists()
