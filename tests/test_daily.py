"""Tests for the daily auto-ingest orchestrator.

We mock `subprocess.run` so these tests don't actually invoke fetch_daily.py
or the real pipeline. The orchestrator's job is to chain steps + write a
structured log + return the right exit code, and that's what we verify.

Run:
    cd "Ai stock" && python -m pytest tests/test_daily.py -v
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from tools import daily  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _read_log(date: str, tmp_logs_dir: pathlib.Path) -> list[dict]:
    log_path = tmp_logs_dir / f"{date}.log"
    if not log_path.is_file():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def tmp_logs_dir(tmp_path, monkeypatch):
    """Redirect daily.DAILY_LOGS to a tmp dir so we never touch real logs."""
    monkeypatch.setattr(daily, "DAILY_LOGS", tmp_path / "_daily_logs")
    return tmp_path / "_daily_logs"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_skip_fetch_skips_fetch_step(tmp_logs_dir):
    """--skip-fetch must NOT invoke the upstream fetch script."""
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return _FakeProc(0, "ok", "")

    with patch.object(subprocess, "run", side_effect=fake_run):
        rc = daily.run(date="2026-05-25", skip_fetch=True)

    assert rc == 0
    # No call should reference fetch_daily.py
    flat = " ".join(" ".join(c) for c in calls)
    assert "fetch_daily.py" not in flat

    log = _read_log("2026-05-25", tmp_logs_dir)
    step_names = [r["step"] for r in log]
    assert "orchestrator_start" in step_names
    assert "fetch" not in step_names
    assert "pipeline" in step_names
    assert "verify_all_replay" in step_names
    assert log[-1]["step"] == "orchestrator_end"
    assert log[-1]["status"] == "ok"


def test_pipeline_failure_returns_1_and_stops(tmp_logs_dir):
    """If the pipeline step fails, verify must NOT be attempted."""
    def fake_run(argv, **kw):
        if "tools.run_pipeline" in " ".join(argv):
            return _FakeProc(1, "", "boom")
        return _FakeProc(0, "ok", "")

    with patch.object(subprocess, "run", side_effect=fake_run):
        rc = daily.run(date="2026-05-25", skip_fetch=True)

    assert rc == 1
    log = _read_log("2026-05-25", tmp_logs_dir)
    step_names = [r["step"] for r in log]
    assert "pipeline" in step_names
    # verify must have been skipped
    assert "verify_all_replay" not in step_names
    assert log[-1]["status"] == "pipeline_failed"


def test_verify_failure_returns_2(tmp_logs_dir):
    def fake_run(argv, **kw):
        if "verify_all_replay" in " ".join(argv):
            return _FakeProc(1, "", "mismatch")
        return _FakeProc(0, "ok", "")

    with patch.object(subprocess, "run", side_effect=fake_run):
        rc = daily.run(date="2026-05-25", skip_fetch=True)

    assert rc == 2
    log = _read_log("2026-05-25", tmp_logs_dir)
    assert log[-1]["status"] == "verify_failed"


def test_fetch_failure_returns_3_and_no_pipeline_run(tmp_logs_dir, monkeypatch):
    """If fetch fails, pipeline + verify must NOT be attempted."""
    monkeypatch.setattr(daily, "UPSTREAM_FETCH", pathlib.Path(__file__))  # any existing file
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if "fetch_daily" in argv[-1] or argv[-1].endswith(".py"):
            return _FakeProc(2, "", "network down")
        return _FakeProc(0, "ok", "")

    # Use any existing python file as a stand-in so the file-exists check passes.
    with patch.object(daily, "UPSTREAM_FETCH", pathlib.Path(__file__)):
        with patch.object(subprocess, "run", side_effect=fake_run):
            rc = daily.run(date="2026-05-25", skip_fetch=False)

    assert rc == 3
    # Only the fetch call should have happened — no pipeline, no verify
    flat = " ".join(" ".join(c) for c in calls)
    assert "tools.run_pipeline" not in flat
    assert "verify_all_replay" not in flat


def test_log_lines_are_valid_json(tmp_logs_dir):
    """Every line written to the log must parse as JSON."""
    with patch.object(subprocess, "run", return_value=_FakeProc(0, "ok", "")):
        daily.run(date="2026-05-25", skip_fetch=True)

    log_path = tmp_logs_dir / "2026-05-25.log"
    assert log_path.is_file()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)   # raises if malformed


def test_log_records_argv_cwd_returncode(tmp_logs_dir):
    """Each step's log line must include argv, cwd, returncode, status, timestamps."""
    with patch.object(subprocess, "run", return_value=_FakeProc(0, "stdout-ok", "")):
        daily.run(date="2026-05-25", skip_fetch=True)

    log = _read_log("2026-05-25", tmp_logs_dir)
    step_records = [r for r in log if r["step"] in {"pipeline", "verify_all_replay"}]
    assert step_records
    for r in step_records:
        for k in ("argv", "cwd", "returncode", "status", "started_at", "finished_at"):
            assert k in r, f"missing key {k} in {r['step']} log line"
        assert r["returncode"] == 0
        assert r["status"] == "ok"


def test_orchestrator_resolves_date_from_today_json_when_not_provided(tmp_logs_dir, monkeypatch):
    """If neither --date nor a readable today.json is available, exit 1 with no_target_date."""
    monkeypatch.setattr(daily, "TODAY_JSON", pathlib.Path("/nonexistent/today.json"))
    with patch.object(subprocess, "run", return_value=_FakeProc(0, "", "")):
        rc = daily.run(date=None, skip_fetch=True)
    assert rc == 1
    log = _read_log("unknown", tmp_logs_dir)
    assert log[-1]["status"] == "no_target_date"


def test_skip_fetch_does_not_require_upstream_script(tmp_logs_dir, monkeypatch):
    """When --skip-fetch is set, the orchestrator must not check UPSTREAM_FETCH."""
    monkeypatch.setattr(daily, "UPSTREAM_FETCH", pathlib.Path("/definitely/not/a/real/path.py"))
    with patch.object(subprocess, "run", return_value=_FakeProc(0, "", "")):
        rc = daily.run(date="2026-05-25", skip_fetch=True)
    assert rc == 0


def test_missing_upstream_fetch_when_not_skipped_logs_skip_and_continues(tmp_logs_dir, monkeypatch):
    """If UPSTREAM_FETCH doesn't exist and --skip-fetch is FALSE, the orchestrator
    should LOG the fetch as skipped (with reason) and continue with downstream
    steps. This keeps the daily flow usable on machines where the upstream
    fetcher hasn't been installed yet.
    """
    monkeypatch.setattr(daily, "UPSTREAM_FETCH", pathlib.Path("/definitely/not/a/real/path.py"))
    with patch.object(subprocess, "run", return_value=_FakeProc(0, "", "")):
        rc = daily.run(date="2026-05-25", skip_fetch=False)
    assert rc == 0
    log = _read_log("2026-05-25", tmp_logs_dir)
    fetch_rows = [r for r in log if r["step"] == "fetch"]
    assert fetch_rows
    assert fetch_rows[0]["status"] == "skipped"
