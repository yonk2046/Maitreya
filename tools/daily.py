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
import urllib.request
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent      # Ai stock/tools/
_AI_STOCK = _HERE.parent                              # Ai stock/
_PROJECT_ROOT = _AI_STOCK.parent                      # SCD engine/  (parent of Ai stock & data)

REPORTS_DIR = _AI_STOCK / "reports"
DAILY_LOGS = REPORTS_DIR / "_daily_logs"
# Per-date market-pulse archive written by tools/fetch_market_pulse.py (P1-2).
# The trading-day oracle reads it first (free proof the market was open today)
# before falling back to a live TWSE probe.
MARKET_PULSE_DIR = _AI_STOCK / "data" / "market_pulse"
# fetch_daily.py is now in the same tools/ dir (repo-local copy for CI).
# Fall back to the legacy parent-dir location for local dev compatibility.
UPSTREAM_FETCH = (
    _HERE / "fetch_daily.py"
    if (_HERE / "fetch_daily.py").exists()
    else _PROJECT_ROOT / "tools" / "fetch_daily.py"
)
TODAY_JSON = (
    _AI_STOCK / "data" / "today.json"
    if (_HERE / "fetch_daily.py").exists()
    else _PROJECT_ROOT / "data" / "today.json"
)


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


def _fii_published() -> bool:
    """True iff today.json carries 三大法人 (T86) data — i.e. FII is published.

    TWSE T86 (外資/投信/自營) publishes after close (~15:30+). A mid-session run
    (e.g. 11:00 manual workflow_dispatch) fetches before it exists, so today.json's
    `t86` is empty and every fii_net_buy lands None. Building + committing that
    snapshot then blocks the proper post-close run via the skip-guard → the day
    loses FII forever. This gate makes such early runs skip cleanly instead.
    """
    if not TODAY_JSON.is_file():
        return False
    try:
        d = json.loads(TODAY_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not d.get("t86"):
        return False
    # Freshness check (2026-07-03 lag bug): HiNetCDN 307-blocks *today's*
    # uncached T86 from datacenter IPs while serving cached prior days, so a
    # stale t86 can masquerade as fresh — 7/03's snapshot carried 7/02's FII
    # (聯電 -12,538 vs actual +35,293). If the fetcher stamped which date it
    # pulled (t86Date), require it to match the trading date. Old today.json
    # without t86Date keeps prior behaviour.
    t86_date = str(d.get("t86Date") or "").strip()
    trading  = str(d.get("tradingDate") or d.get("date") or "").replace("-", "").strip()
    if t86_date and trading and t86_date != trading:
        return False
    return True


def _snapshot_is_partial(date: str) -> bool:
    """True iff reports/<date>.json exists and carries fii_pending=True.

    兩段式快照 (2026-07-07):雲端晚班在 T86 不可得時建的「部分快照」帶
    fii_pending=True;早晨 T86 到手後,trading_day_gate 的 skip 分支據此
    放行重建(supersede 補完)。讀檔失敗一律當 False(寧可跳過,不誤重建)。
    """
    path = REPORTS_DIR / f"{date}.json"
    if not path.is_file():
        return False
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(snap.get("fii_pending"))


# ---------------------------------------------------------------------------
# Trading-day oracle (MI_INDEX) — the authority behind --allow-partial
# ---------------------------------------------------------------------------
# 事故 (2026-07-10 颱風假): 放假日無交易, 但富邦網站照供「回收的」榜單 (35 檔與
# 前一日完全相同、股價全等前收)。系統的「今天是否交易日」判斷隱性依賴「T86 是否
# 存在」, 而 --allow-partial 正是繞過該訊號的開關 → 晚班把「放假日 T86 永不發布」
# 誤讀成「T86 晚到」, 用陳舊榜單產出永不會被 supersede 的殭屍 partial 快照。
#
# 修法: 用 TWSE MI_INDEX (與 P1-2 breadth 同源) 當「今天有沒有開盤」的權威訊號,
# 獨立於富邦、獨立於 T86。partial 只在 oracle 確認「今天有開盤」時才允許 (真晚到);
# 確認不了 (放假 / oracle 網路失敗) 一律 fail-closed → 不產 partial, 跳過。

_MI_INDEX_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?response=json&date={date}&type=ALLBUT0999"
)


def _market_pulse_archive_open(target_date: str) -> bool:
    """True iff the P1-2 market-pulse archive for target_date proves a session.

    tools/fetch_market_pulse.py runs earlier in the same GHA job and archives
    data/market_pulse/<date>.json. A parsed `breadth` block (no 'error', a
    numeric `total`) is free proof the TWSE after-hours endpoint returned real
    data — i.e. the market WAS open — so we can skip the live probe entirely.

    Conservative: any missing file / read error / errored-or-empty breadth
    returns False (fall through to the live probe), never a false 'open'.
    """
    path = MARKET_PULSE_DIR / f"{target_date}.json"
    if not path.is_file():
        return False
    try:
        pulse = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    breadth = pulse.get("breadth")
    if not isinstance(breadth, dict):
        return False
    if "error" in breadth:
        return False
    return isinstance(breadth.get("total"), int)


def _mi_index_probe(target_date: str) -> bool | None:
    """Live TWSE MI_INDEX probe. Tri-state, independent of 富邦 and T86.

    Returns:
      True  — stat == 'OK': TWSE published after-hours data → market was open.
      False — stat != 'OK' (e.g. '很抱歉，沒有符合條件的資料！') → no session.
      None  — the probe itself is indeterminate (network error / TWSE down /
              unparseable body); caller treats this as fail-closed.
    """
    url = _MI_INDEX_URL.format(date=target_date.replace("-", ""))
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.twse.com.tw/",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return None
    if not isinstance(data, dict) or "stat" not in data:
        return None
    return data.get("stat") == "OK"


def _trading_day_oracle(target_date: str) -> tuple[bool, str]:
    """Authoritative 'was the market open on target_date?' — for --allow-partial.

    Resolution order (cheap → expensive):
      1. Local reuse: a parsed market-pulse archive for target_date proves open.
      2. Live TWSE MI_INDEX probe (tri-state).

    Returns (is_open, reason). is_open is True ONLY on positive proof of a
    session; a holiday/weekend (probe False) AND an indeterminate probe (None)
    both return False — fail-closed, so we never build a zombie partial off a
    holiday's recycled 榜單. `reason` is logged.
    """
    if _market_pulse_archive_open(target_date):
        return True, f"market_pulse archive {target_date}.json has parsed breadth (session confirmed)"
    probe = _mi_index_probe(target_date)
    if probe is True:
        return True, "TWSE MI_INDEX stat=OK (session confirmed)"
    if probe is False:
        return False, "TWSE MI_INDEX stat!=OK — no trading session (holiday/weekend)"
    return False, "TWSE MI_INDEX probe indeterminate (network/parse error) — fail-closed"


_ISO_DATE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def _latest_committed_report_date() -> str | None:
    """Most recent dated snapshot already on disk (reports/<YYYY-MM-DD>.json).

    Used by the staleness gate to detect a fetch that did not advance past
    what we already have. Ignores *.example.json / *.intelligence.json.
    """
    if not REPORTS_DIR.is_dir():
        return None
    dates = [
        p.stem for p in REPORTS_DIR.glob("*.json")
        if _ISO_DATE.match(p.stem)
    ]
    return max(dates) if dates else None


def _trading_day_gate(target_date: str, latest: str | None) -> str:
    """Auto-daily disposition by comparing the resolved date to the latest commit.

    Pure (ISO-date string compare). Returns one of:
      'fail'    — target_date < latest: fetch regressed to old data.
      'skip'    — target_date == latest: no new trading session (holiday/weekend/
                  pre-publish); rebuilding would trip verify, so skip cleanly.
      'proceed' — target_date > latest, or no prior snapshot: genuine new session.
    """
    if latest is None:
        return "proceed"
    if target_date < latest:
        return "fail"
    if target_date == latest:
        return "skip"
    return "proceed"


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
    allow_partial: bool = False,
) -> int:
    """Execute the daily flow. Returns the process exit code (0 / 1 / 2 / 3).

    allow_partial: 兩段式快照的晚班模式(只給雲端 20:00 GHA schedule 用)。
    T86 不可得時不再 skip,改建 fii_pending=True 的部分快照(價格+分點);
    滯後 T86 已在 fetch/adapter 兩層被丟棄,絕不混入。早晨班次(strict)
    會經 trading_day_gate 的補完路徑 supersede 成完整快照。
    """
    log_lines: list[dict[str, Any]] = [{
        "step": "orchestrator_start",
        "at":   _now_utc(),
        "skip_fetch": skip_fetch,
        "allow_partial": allow_partial,
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

    # ----- Trading-day / staleness gate -----
    # Auto-daily path only (no explicit --date, fetch actually ran). Compare the
    # resolved target_date against the latest snapshot we already committed:
    #   target_date <  latest  → fetch REGRESSED (stale/timeout returned old
    #                            data). Fail loudly (exit 3) — never silent-green.
    #   target_date == latest  → no NEW trading session (holiday / weekend /
    #                            pre-publish). The system has no trading calendar,
    #                            so rebuilding the same date would overwrite a
    #                            committed snapshot and trip verify; instead SKIP
    #                            cleanly (exit 0). This is what makes 端午節 etc.
    #                            green instead of a spurious verify failure.
    #   target_date >  latest  → genuine new session → build normally.
    # Explicit --date and --skip-fetch are backfill/re-do paths and stay exempt.
    if date is None and not skip_fetch:
        latest = _latest_committed_report_date()
        decision = _trading_day_gate(target_date, latest)
        if decision == "fail":
            log_lines.append({
                "step": "staleness_gate", "status": "fail",
                "reason": f"fetched target_date={target_date} is older than latest "
                          f"committed report={latest}; fetch likely returned stale data",
            })
            _finalize(log_lines, "stale_fetch_regression", target_date)
            print(f"[daily] STALE FETCH — target_date={target_date} < latest committed "
                  f"{latest}; refusing to run (exit 3)", file=sys.stderr)
            return 3
        if decision == "skip":
            # 兩段式快照補完:latest 是昨晚的部分快照(fii_pending)且 T86
            # 現在到手(t86Date==tradingDate 由 _fii_published 把關)→ 放行
            # 重建,run_pipeline 會走 supersede 鏈把它補完。兩個條件缺一
            # 仍走原 skip(partial 但 T86 又沒到 → 留給下一班次重試)。
            if _snapshot_is_partial(target_date) and _fii_published():
                log_lines.append({
                    "step": "trading_day_gate", "status": "proceed_complete_partial",
                    "reason": f"reports/{target_date}.json is a partial snapshot "
                              f"(fii_pending) and fresh T86 is now available — "
                              f"rebuilding to supersede-complete it",
                })
                print(f"[daily] 部分快照補完 — {target_date} fii_pending 且 T86 已到手,"
                      f"重建 supersede", file=sys.stderr)
            else:
                log_lines.append({
                    "step": "trading_day_gate", "status": "skip",
                    "reason": f"resolved target_date={target_date} == latest committed report={latest}; "
                              f"no new trading session (holiday/weekend/pre-publish) — skipping cleanly",
                })
                _finalize(log_lines, "skip_no_new_trading_day", target_date)
                print(f"[daily] no new trading session — target_date={target_date} already "
                      f"committed; skipping cleanly (exit 0)", file=sys.stderr)
                return 0

        # ----- FII-published gate -----
        # Don't build a canonical snapshot before 三大法人(T86) is published —
        # an intraday run would commit an FII-less snapshot and the skip-guard
        # would then block the proper post-close run. Skip cleanly so 19:00/20:00
        # (or a later manual run after close) builds the complete snapshot.
        if not _fii_published():
            if allow_partial:
                # 兩段式快照晚班:CDN 擋雲端抓當日 T86 → 建部分快照
                # (fii_pending=True,fii 欄位全 None — 滯後 T86 已在
                # fetch/adapter 層丟棄,不會混入)。早晨班次補完。
                #
                # 但 T86 缺席有兩種成因:①有開盤、T86 晚到 (合法 partial) vs
                # ②今天沒開盤、T86 永不發布 (2026-07-10 颱風假殭屍事故)。
                # allow_partial 繞過了「T86 存在」這個隱性交易日訊號,所以先問
                # 一個獨立於富邦、獨立於 T86 的權威 oracle (TWSE MI_INDEX):
                # 確認有開盤才建 partial;確認不了 (放假 / oracle 失敗) fail-closed
                # 跳過 (寧可少一份晚上快照,早晨 T+1 路徑會再跑;絕不再產殭屍)。
                market_open, oracle_reason = _trading_day_oracle(target_date)
                if not market_open:
                    log_lines.append({
                        "step": "trading_day_oracle", "status": "skip",
                        "reason": "T86 absent and allow_partial=True, but the trading-day "
                                  "oracle could not confirm a session — refusing to build a "
                                  "partial snapshot off possibly-recycled 榜單 (2026-07-10 "
                                  f"zombie-partial guard). oracle: {oracle_reason}",
                    })
                    _finalize(log_lines, "skip_no_trading_day_oracle", target_date)
                    print(f"[daily] 交易日 oracle 未確認開盤 — 不建 partial,跳過 (exit 0)。"
                          f"oracle: {oracle_reason}", file=sys.stderr)
                    return 0
                log_lines.append({
                    "step": "fii_gate", "status": "partial",
                    "reason": "T86 unavailable and allow_partial=True — building PARTIAL "
                              "snapshot (fii_pending=True); a later strict run with fresh "
                              "T86 will supersede-complete it. "
                              f"trading-day oracle confirms open: {oracle_reason}",
                })
                print("[daily] 三大法人(T86) 不可得但交易日 oracle 確認有開盤 — "
                      f"建部分快照 (fii_pending),早晨班次自動補完。oracle: {oracle_reason}",
                      file=sys.stderr)
            else:
                log_lines.append({
                    "step": "fii_gate", "status": "skip",
                    "reason": "today.json t86 missing OR t86Date != tradingDate (stale FII must "
                              "not enter a snapshot) — skipping so a later run with fresh T86 builds it",
                })
                _finalize(log_lines, "skip_fii_not_published", target_date)
                print("[daily] 三大法人(T86) 尚未公布 — 跳過,等盤後重跑 (exit 0)", file=sys.stderr)
                return 0

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

    # ----- Step 5: backtest refresh (P3b) -----
    # 每日刷新 A/B 兩策略的回測 JSON,viewer 從 reports/backtest/ 讀檔渲染。
    # 非阻塞:回測失敗不擋 pipeline(資料/快照永遠優先)。
    # 用 latest_only=True 確保每日只留一份「最新版」(避免 _<lo>_<hi>.json 越積越多)。
    for _strategy in ("chip_anchored_swing", "momentum_continuation",
                      "chip_anchored_v2", "momentum_v2"):
        rc_bt, _, err_bt = _run_step(
            name=f"backtest_{_strategy}",
            argv=[sys.executable, "-m", "tools.run_backtest",
                  "--strategy", _strategy, "--latest-only"],
            cwd=_AI_STOCK,
            log_lines=log_lines,
            timeout_sec=180,
        )
        if rc_bt != 0:
            print(f"[daily] ⚠ backtest {_strategy} FAILED rc={rc_bt} (non-fatal):\n{err_bt}",
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
    ap.add_argument("--allow-partial", action="store_true",
                    help="兩段式快照晚班模式:T86 不可得時建 fii_pending 部分快照而非跳過 "
                         "(只給雲端 20:00 GHA schedule 用)")
    args = ap.parse_args(argv)
    return run(date=args.date, skip_fetch=args.skip_fetch,
               allow_partial=args.allow_partial)


if __name__ == "__main__":
    raise SystemExit(main())
