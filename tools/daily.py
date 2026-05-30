"""SCD Engine — daily auto-ingest orchestrator.

Chains the four post-close steps:

  1. fetch        — call ../tools/fetch_daily.py (writes SCD engine/data/today.json)
  2. pipeline     — run tools.run_pipeline for today's tradingDate (legacy adapter)
  3. verify       — run tools.verify_all_replay across the whole archive
  4. summary      — append structured outcome to reports/_daily_logs/<date>.log

Each step writes one JSON line to the log; the last line is a summary with
the overall status. Exit code:
    0  every step succeeded
    1  pipeline failed (no snapshot written, WORM violation, ...)
    2  verify failed (whole-archive integrity broke)
    3  fetch failed (upstream fetch_daily.py non-zero)

Usage:
    python -m tools.daily                  # full daily run
    python -m tools.daily --skip-fetch     # use the data/today.json already on disk
    python -m tools.daily --date 2026-05-25 --skip-fetch  # re-do a specific date

Design notes:
  - Each step is a subprocess (clean isolation, real exit codes, real stdout).
  - We do NOT import the pipeline directly — keeps the orchestrator from
    accidentally retaining state from a prior run.
  - The orchestrator itself never writes under data/ or reports/<date>.json;
    it only writes reports/_daily_logs/<date>.log. WORM/contracts still hold.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent      # Ai stock/tools/
_AI_STOCK = _HERE.parent                              # Ai stock/
_PROJECT_ROOT = _AI_STOCK.parent                      # SCD engine/  (parent of Ai stock & data)

REPORTS_DIR = _AI_STOCK / "reports"
DAILY_LOGS = REPORTS_DIR / "_daily_logs"
UPSTREAM_FETCH = _PROJECT_ROOT / "tools" / "fetch_daily.py"
TODAY_JSON = _PROJECT_ROOT / "data" / "today.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_today_trading_date() -> str | None:
    if not TODAY_JSON.is_file():
        return None
    try:
        d = json.loads(TODAY_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return d.get("tradingDate") or d.get("date")


def _run_step(
    name: str,
    argv: list[str],
    cwd: pathlib.Path,
    log_lines: list[dict[str, Any]],
    timeout_sec: int = 1800,
) -> tuple[int, str, str]:
    """Run one subprocess step. Append a log line. Return (returncode, stdout_tail, stderr_tail)."""
    started = _now_utc()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        rc = proc.returncode
        stdout_tail = (proc.stdout or "").splitlines()[-20:]
        stderr_tail = (proc.stderr or "").splitlines()[-20:]
        status = "ok" if rc == 0 else "fail"
    except subprocess.TimeoutExpired:
        rc = -1
        stdout_tail = []
        stderr_tail = [f"timeout after {timeout_sec}s"]
        status = "timeout"
    except FileNotFoundError as e:
        rc = -1
        stdout_tail = []
        stderr_tail = [str(e)]
        status = "fail"

    finished = _now_utc()
    log_lines.append({
        "step":         name,
        "started_at":   started,
        "finished_at":  finished,
        "argv":         argv,
        "cwd":          str(cwd),
        "returncode":   rc,
        "status":       status,
        "stdout_tail":  stdout_tail,
        "stderr_tail":  stderr_tail,
    })
    return rc, "\n".join(stdout_tail), "\n".join(stderr_tail)


def _write_log(date: str, log_lines: list[dict[str, Any]]) -> pathlib.Path:
    DAILY_LOGS.mkdir(parents=True, exist_ok=True)
    out = DAILY_LOGS / f"{date}.log"
    with out.open("a", encoding="utf-8") as fh:
        for line in log_lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(
    date: str | None = None,
    *,
    skip_fetch: bool = False,
) -> int:
    """Execute the daily flow. Returns the process exit code (0 / 1 / 2 / 3)."""
    log_lines: list[dict[str, Any]] = [{
        "step": "orchestrator_start",
        "at":   _now_utc(),
        "skip_fetch": skip_fetch,
        "requested_date": date,
        "pid":  os.getpid(),
    }]

    # ----- Step 1: fetch -----
    if not skip_fetch:
        if not UPSTREAM_FETCH.is_file():
            log_lines.append({
                "step": "fetch", "status": "skipped",
                "reason": f"upstream fetch_daily.py not found at {UPSTREAM_FETCH}",
            })
            print(f"[daily] fetch skipped — {UPSTREAM_FETCH} missing", file=sys.stderr)
        else:
            rc, _, err = _run_step(
                name="fetch",
                argv=[sys.executable, str(UPSTREAM_FETCH)],
                cwd=_PROJECT_ROOT,
                log_lines=log_lines,
                timeout_sec=1800,   # 30min
            )
            if rc != 0:
                _finalize(log_lines, "fetch_failed", date or "unknown")
                print(f"[daily] fetch FAILED rc={rc}:\n{err}", file=sys.stderr)
                return 3

    # Resolve target date from today.json if not given
    target_date = date or _read_today_trading_date()
    if not target_date:
        log_lines.append({
            "step": "resolve_date", "status": "fail",
            "reason": "cannot determine target date (no --date and no today.json)",
        })
        _finalize(log_lines, "no_target_date", "unknown")
        return 1
    print(f"[daily] target_date = {target_date}", file=sys.stderr)

    # ----- Step 2: pipeline -----
    rc, _, err = _run_step(
        name="pipeline",
        argv=[sys.executable, "-m", "tools.run_pipeline",
              "--date", target_date, "--check-replay"],
        cwd=_AI_STOCK,
        log_lines=log_lines,
        timeout_sec=600,
    )
    if rc != 0:
        _finalize(log_lines, "pipeline_failed", target_date)
        print(f"[daily] pipeline FAILED rc={rc}:\n{err}", file=sys.stderr)
        return 1

    # ----- Step 3: verify-all-replay -----
    rc, _, err = _run_step(
        name="verify_all_replay",
        argv=[sys.executable, "tools/verify_all_replay.py"],
        cwd=_AI_STOCK,
        log_lines=log_lines,
        timeout_sec=900,
    )
    if rc != 0:
        _finalize(log_lines, "verify_failed", target_date)
        print(f"[daily] verify-all-replay FAILED rc={rc}:\n{err}", file=sys.stderr)
        return 2

    # ----- Step 4: intelligence (P3h) -----
    # Generate daily intelligence report and persist as reports/<date>.intelligence.json.
    # Non-fatal: a failure here does not block the daily pipeline exit code.
    rc_intel, _, err_intel = _run_step(
        name="intelligence",
        argv=[sys.executable, "-m", "core.intelligence_delta",
              "--date", target_date],
        cwd=_AI_STOCK,
        log_lines=log_lines,
        timeout_sec=300,
    )
    if rc_intel != 0:
        print(f"[daily] ⚠ intelligence step FAILED rc={rc_intel} (non-fatal):\n{err_intel}",
              file=sys.stderr)

    # ----- Done -----
    _finalize(log_lines, "ok", target_date)
    print(f"[daily] ✅ {target_date} all green", file=sys.stderr)
    return 0


def _finalize(log_lines: list[dict[str, Any]], status: str, date: str) -> None:
    log_lines.append({
        "step":   "orchestrator_end",
        "at":     _now_utc(),
        "status": status,
        "date":   date,
    })
    _write_log(date, log_lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SCD Engine daily auto-ingest orchestrator")
    ap.add_argument("--date", help="target YYYY-MM-DD; default = today.json's tradingDate")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="skip the upstream fetch step (use existing data/today.json)")
    args = ap.parse_args(argv)
    return run(date=args.date, skip_fetch=args.skip_fetch)


if __name__ == "__main__":
    raise SystemExit(main())
