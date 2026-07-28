"""SCD Engine pipeline CLI — P3a ingest-only.

Usage:
    python -m tools.run_pipeline --date 2026-05-25
    python -m tools.run_pipeline                     # uses today.json's tradingDate
    python -m tools.run_pipeline --date 2026-05-25 --check-replay

Outputs to Ai stock/reports/<date>.json + .sha256 + updates index.json.

Exit codes:
    EXIT_OK (0)                   — normal completion (snapshot written, or
                                     --backfill-all loop finished).
    EXIT_SKIP_EMPTY_UNIVERSE (3)  — universe==0 abstain (see below); no
                                     snapshot/index/ledger write happened.
    non-zero (unhandled exception)— genuine failure (WORM violation, stale
                                     lookback, ingest error, ...).

Empty-universe guard (2026-07-24 事故修法):
    上游富邦主力買超榜有時整晚缺席(晚間分點不可得的已知模式)——today.json
    仍有效但 mainForceBuy/buyList/sellList 全空,adapter 算出的 universe 因此
    為 0 檔。若照常往下跑,會寫出一個 stocks=[] 的空快照、更新 index.json、
    attest 進 _replay_ledger.json——這份空快照一旦 commit 上 origin,會滿足
    canary.yml 的「reports/<date>.json 存在」判斷而消音告警,也會滿足
    daily.yml 早班的 `[ -f reports/${TODAY}.json ]` 守門而跳過補建,真資料因
    此永久遺失(靜默失敗)。修法:universe==0 時在寫入前乾淨 abstain——不寫
    快照、不碰 index、不 attest,回傳 EXIT_SKIP_EMPTY_UNIVERSE 讓呼叫方
    (tools/daily.py)辨識為「跳過」而非「pipeline_failed」。與既有「T86 未
    公布→跳過等重跑」同語意(fail-closed skip,不是硬錯)。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Ensure project root is on sys.path so `core` / `data.adapters` imports work
_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent                            # .../SCD engine/Ai stock
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import yaml

from core.archive import archive_raw_inputs
from core.hashing import canonical_sha256, write_sidecar
from core.ingest import ingest
from core.replay_contract import normalize_for_replay_compare
from core.replay_ledger import attest_from_snapshot
from core.worm_check import snapshot_manifest, verify_manifest
from data.adapters.legacy import adapt_legacy, legacy_paths
from data.adapters.rollup import adapt_rollup, available_dates


REPORTS_DIR = _AI_STOCK / "reports"
CONFIG_FILE = _AI_STOCK / "config" / "scd.example.yaml"
INDEX_FILE = REPORTS_DIR / "index.json"
RAW_ARCHIVE_DIR = REPORTS_DIR / "_raw_archive"
REPLAY_LEDGER_FILE = REPORTS_DIR / "_replay_ledger.json"
STRATEGY_TAGS_DIR = REPORTS_DIR / "strategy_tags"

# Exit-code contract with tools/daily.py (subprocess boundary — see module
# docstring "Empty-universe guard"). daily.py imports EXIT_SKIP_EMPTY_UNIVERSE
# (the int constant only, not this module's functions) so the two files never
# drift on the sentinel value.
EXIT_OK = 0
EXIT_SKIP_EMPTY_UNIVERSE = 3


def _load_chain_upto(target_date: str) -> list[dict]:
    """Load every committed real snapshot with date <= target_date (oldest first).

    Mirrors the viewer's full-history golden feed (and the backtest's snaps[:i+1]
    slice) so the strategy_tags sidecar aligns with what the cockpit renders —
    the just-written snapshot is already on disk at call time.
    """
    import glob, os, re
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
    files = [f for f in glob.glob(str(REPORTS_DIR / "*.json"))
             if iso.match(os.path.basename(f)) and os.path.basename(f)[:10] <= target_date]
    chain: list[dict] = []
    for f in sorted(files):
        try:
            chain.append(json.loads(pathlib.Path(f).read_text(encoding="utf-8")))
        except Exception:
            pass
    return chain


# R1 五支策略 key 對應(唯一權威來源 = 本 dict;viewer/cockpit.py 的 _TAG_META
# 徽章 glyph/術語映射必須與此表的 key 集合一致,不得各自增減)。
#   A  = chip_anchored_swing   (v1,既有語意 — viewer/舊 sidecar 依賴,不可變動)
#   B  = momentum_continuation (v1,既有語意,同上)
#   A2 = chip_anchored_v2      (v2 分批加碼/減碼/TP1,spec §32-67)
#   B2 = momentum_v2           (v2 分批加碼,spec §32-67)
#   A3 = chip_anchored_v3      (v3 交換鬆緊,研究待審非上線 — core/strategies.py
#        Part 4.3 docstring;此處落地供 viewer 標記「研究中」樣式,非等同核准上線)
_STRATEGY_TAG_KEYS: dict[str, str] = {
    "A": "chip_anchored_swing",
    "B": "momentum_continuation",
    "A2": "chip_anchored_v2",
    "B2": "momentum_v2",
    "A3": "chip_anchored_v3",
}
# 4.3:研究待審,非上線(core/strategies.py STRATEGY_A_V3 docstring)。viewer 靠
# payload 裡的 research 旗標決定是否用降彩度/虛線樣式區隔,不自行判斷。
_STRATEGY_TAG_RESEARCH: frozenset[str] = frozenset({"A3"})


def _write_strategy_tags(target_date: str) -> None:
    """R1:快照建成後產生 reports/strategy_tags/<date>.json 落地 sidecar。

    決定論、來源=共用 core.strategies.would_enter(與回測同一實作)。此檔不進快照、
    不動 schema、不 bump minor(單一 bump 紀律);viewer 讀此檔渲染徽章,不新增
    render-time 引擎 import。Schema 2.0 時遷入快照 obs_*。

    涵蓋 core.strategies.ALL_STRATEGIES 全部五支(A/B/A2/B2/A3,見 _STRATEGY_TAG_KEYS
    docstring)。每筆 strategies[k] 附 research 布林欄位(v3=True,其餘 False),讓
    viewer 據以區隔「研究中」樣式,不必自行猜測哪支是研究版。

    切片=全歷史 ≤ target_date(對齊 viewer 全歷史 golden 與回測 snaps[:i+1])。
    永不因標示產生失敗而中斷 pipeline —— 快照本身(唯一事實來源)已寫入。
    """
    try:
        from core.strategies import ALL_STRATEGIES, strategy_tags_for_date
        # 前推守門:_STRATEGY_TAG_KEYS 必須完整覆蓋 ALL_STRATEGIES,否則新增/移除
        # 策略會被本 sidecar 靜默漏掉(徽章與回測集不同步)——寧可整段 skip(見下
        # except)也不要漏標一支。
        assert set(_STRATEGY_TAG_KEYS.values()) == set(ALL_STRATEGIES), (
            f"_STRATEGY_TAG_KEYS 與 ALL_STRATEGIES 不同步: "
            f"缺 {set(ALL_STRATEGIES) - set(_STRATEGY_TAG_KEYS.values())}, "
            f"多 {set(_STRATEGY_TAG_KEYS.values()) - set(ALL_STRATEGIES)}")
        chain = _load_chain_upto(target_date)
        strategies = {k: ALL_STRATEGIES[name] for k, name in _STRATEGY_TAG_KEYS.items()}
        tags = strategy_tags_for_date(chain, strategies)
        payload = {
            "date": target_date,
            "generated_from": "core.strategies.would_enter (single source of truth)",
            "strategies": {
                k: {
                    "name": v.name, "zh": v.zh, "kind": v.kind,
                    "research": k in _STRATEGY_TAG_RESEARCH,
                }
                for k, v in strategies.items()
            },
            "tags": tags,
        }
        STRATEGY_TAGS_DIR.mkdir(parents=True, exist_ok=True)
        out = STRATEGY_TAGS_DIR / f"{target_date}.json"
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"[strategy_tags] wrote strategy_tags/{target_date}.json "
              f"({len(tags)} tagged tickers)", file=sys.stderr)
    except Exception as e:  # never block the pipeline on a display sidecar
        print(f"[strategy_tags] skipped ({type(e).__name__}: {e})", file=sys.stderr)


def _now_utc_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))


def _load_snap_objects(lookback: dict[str, str], reports_dir: pathlib.Path) -> list[dict]:
    """Load actual snapshot content for the prior dates in lookback (oldest first).

    Used by ingest() to compute weakening_profile() per ticker.
    Silently skips dates whose file is missing or unreadable.
    """
    result: list[dict] = []
    for date in sorted(lookback.keys()):
        path = reports_dir / f"{date}.json"
        if path.is_file():
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return result


def _gather_lookback(target_date: str, window: int) -> dict[str, str]:
    """Walk REPORTS_DIR for prior real snapshots (excluding *.example.json) within `window` days.

    Returns {date: sha256} from index.json.
    """
    if not INDEX_FILE.is_file():
        return {}
    idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    snapshots = idx.get("snapshots", {})
    import datetime as dt
    tgt = dt.date.fromisoformat(target_date)
    out: dict[str, str] = {}
    for key, entry in snapshots.items():
        # Only use entries whose key is a real ISO date (skip 2026-05-22.example etc.)
        try:
            d = dt.date.fromisoformat(key)
        except ValueError:
            continue
        if d >= tgt:
            continue
        days_ago = (tgt - d).days
        if 0 < days_ago <= window:
            out[key] = entry["current_hash"]
    return out


def _assert_lookback_fresh(lookback: dict[str, str]) -> None:
    """BUILD-TIME strict-continuity assertion (fable 裁定 W6-1 條件 2).

    The strict invariant "lookback hash == prior date's current_hash" is a
    BUILD-TIME invariant: it must hold at the moment a snapshot is built, and
    only then (frozen/attested snapshots keep their as-was references when
    priors are later superseded — the contract test grandfathers those,
    tests/test_contracts.py::test_lookback_hash_matches_current_strict).

    Because the test-side check is grandfathered for attested snapshots, a
    build that records STALE prior hashes (e.g. gathered from a cached index
    object that missed an in-run supersede cascade) would slip through the
    test net once the pipeline attests it. This guard closes that hole:
    re-read index.json NOW and fail fast — before the snapshot is written or
    attested — if any recorded lookback hash is not the prior's current tip.
    """
    if not lookback or not INDEX_FILE.is_file():
        return
    snaps = json.loads(INDEX_FILE.read_text(encoding="utf-8")).get("snapshots", {})
    stale = []
    for lb_date, lb_hash in lookback.items():
        prior = snaps.get(lb_date)
        if prior is None:
            stale.append(f"{lb_date}: not in index")
        elif prior["current_hash"] != lb_hash:
            stale.append(
                f"{lb_date}: recorded {lb_hash[:20]}... != current "
                f"{prior['current_hash'][:20]}..."
            )
    if stale:
        raise RuntimeError(
            "LOOKBACK_STALE (W6-1 build-time invariant): snapshot about to be "
            "written references non-current prior hashes — the lookback was "
            "gathered from a stale index. Refusing to write/attest.\n  "
            + "\n  ".join(stale)
        )


def _update_index(snapshot_path: pathlib.Path, snapshot_hash: str, snapshot_obj: dict) -> None:
    """Append a new snapshot to index.json and link the supersedes chain.

    Invariants maintained:
      - history[0].supersedes is None
      - history[-1].superseded_by is None
      - history[i].supersedes == history[i-1].hash (for i > 0)
      - history[i].superseded_by == history[i+1].hash (for i < len-1)
      - current_hash == history[-1].hash

    If the new hash equals the existing current_hash, this is a no-op
    (re-ingest produced byte-identical output — exactly what we want
    for replay determinism).
    """
    if INDEX_FILE.is_file():
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    else:
        idx = {"schema_version": "1.4.0", "snapshots": {}}

    idx["schema_version"] = "1.4.0"
    key = snapshot_obj["date"]
    existing = idx["snapshots"].get(key)
    new_entry = {
        "file": snapshot_path.name,
        "hash": snapshot_hash,
        "created_at": snapshot_obj["generated_at"],
        "supersedes": None,
        "superseded_by": None,
    }
    if existing:
        # Replay-determinism no-op: byte-identical re-ingest.
        if existing["current_hash"] == snapshot_hash:
            return
        prior = existing["history"][-1]
        # Link backward
        new_entry["supersedes"] = prior["hash"]
        # Link forward on the prior tip
        prior["superseded_by"] = snapshot_hash
        existing["history"].append(new_entry)
        existing["current"] = snapshot_path.name
        existing["current_hash"] = snapshot_hash
    else:
        idx["snapshots"][key] = {
            "current": snapshot_path.name,
            "current_hash": snapshot_hash,
            "history": [new_entry],
        }
    INDEX_FILE.write_text(
        json.dumps(idx, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run(date: str | None, *, check_replay: bool = False, source: str = "auto") -> dict | None:
    """Run pipeline for a given date, write snapshot, update index. Returns the snapshot dict.

    Args:
        date: target YYYY-MM-DD; for 'auto', falls back to today.json's tradingDate.
        source: 'auto' (legacy for today, rollup for historical),
                'legacy' (force today.json), 'rollup' (force backfill from rollup).

    Returns:
        The snapshot dict on a normal write, or None if the run abstained
        (empty-universe guard — see module docstring). Callers that need to
        distinguish "abstained" from "wrote a snapshot" for exit-code purposes
        should check for None; `main()` below does this via
        EXIT_SKIP_EMPTY_UNIVERSE.
    """
    cfg = _load_config()

    paths = legacy_paths()
    repo_root = paths["root"]

    # WORM self-check: snapshot raw inputs before adapter touches anything.
    worm_before = snapshot_manifest(repo_root)
    print(
        f"[worm] manifest captured: {len(worm_before)} raw files",
        file=sys.stderr,
    )

    # Pick adapter — also resolves once and reuses for replay verification.
    def _run_adapter(d: str | None) -> dict:
        if source == "rollup":
            return adapt_rollup(d) if d is not None else adapt_rollup(date)
        if source == "legacy":
            return adapt_legacy(date=d)
        # auto: legacy for today.json's date, rollup otherwise
        today_json = paths["today_json"]
        td = None
        if today_json.is_file():
            today_obj = json.loads(today_json.read_text())
            td = today_obj.get("tradingDate") or today_obj.get("date")
        if d is None or d == td:
            return adapt_legacy(date=d)
        return adapt_rollup(d)

    adapter_out = _run_adapter(date)
    target_date = adapter_out["date"]
    print(f"[pipeline] date={target_date} source={source} universe={len(adapter_out['universe'])} stocks", file=sys.stderr)

    # ── Empty-universe guard (2026-07-24 事故修法)───────────────────────────
    # universe==0 means the upstream 主力買超榜 was empty (mainForceBuy/buyList/
    # sellList all empty) — a known "evening 分點 unavailable" pattern, NOT a
    # trading holiday (breadth/marketQuotes can be fully populated). Writing a
    # stocks=[] snapshot here would silently satisfy both the canary's
    # "reports/<date>.json exists" check and daily.yml's file-exists gate,
    # permanently losing the real data. Abstain cleanly BEFORE any write
    # (snapshot, index.json, replay ledger) — same fail-closed-skip semantics
    # as the existing "T86 未公布→跳過等重跑" branch in tools/daily.py, not an
    # error. See module docstring for the full incident writeup.
    if len(adapter_out["universe"]) == 0:
        print(
            "[pipeline] SKIP: 主力買超榜為空(universe=0)— 上游分點缺席,"
            "不建空快照,待下一班次重試",
            file=sys.stderr,
        )
        return None

    # Gather lookback chain
    window = cfg.get("temporal", {}).get("lookback_window_days", 5)
    lookback = _gather_lookback(target_date, window)
    print(f"[pipeline] lookback_window={window} found_priors={len(lookback)}: {sorted(lookback.keys())}", file=sys.stderr)

    # Load actual snapshot content for weakening_profile (P5)
    prior_snap_objects = _load_snap_objects(lookback, REPORTS_DIR)
    print(f"[pipeline] prior_snap_objects loaded: {len(prior_snap_objects)}", file=sys.stderr)

    snapshot = ingest(adapter_out, cfg, repo_root=str(repo_root),
                      prior_snapshots=lookback, prior_snap_objects=prior_snap_objects)

    # Archive raw inputs (immutable copy) and validate archived sha == raw sha.
    # This mutates snapshot.provenance.sources[*] to include archived_copy_path
    # and archived_sha256, plus appends a RAW_ARCHIVED audit event.
    archive_raw_inputs(snapshot, repo_root, RAW_ARCHIVE_DIR)
    print(f"[archive] raw inputs copied under reports/_raw_archive/{target_date}/", file=sys.stderr)

    # WORM verify: nothing under data/ should have changed during ingest.
    worm_violations = verify_manifest(repo_root, worm_before)
    if worm_violations:
        # Append to audit_log and abort hard — replay legitimacy is the priority.
        snapshot["audit_log"].extend(worm_violations)
        for v in worm_violations:
            print(f"[worm] ❌ {v['reason']}", file=sys.stderr)
        raise RuntimeError(
            f"WORM_VIOLATION: {len(worm_violations)} raw input file(s) drifted "
            f"during ingest. Pipeline aborted before write to preserve replay "
            f"legitimacy. See audit_log for details."
        )
    print(f"[worm] ✅ {len(worm_before)} raw files unchanged during ingest", file=sys.stderr)

    # W6-1 build-time invariant: recorded lookback hashes must be the priors'
    # CURRENT tips at write time. Fail fast before write/attest (fable 條件 2).
    _assert_lookback_fresh(lookback)

    # Write snapshot + sidecar
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{target_date}.json"
    out_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sha = write_sidecar(out_path, snapshot)
    print(f"[pipeline] wrote {out_path.name}  hash={sha}", file=sys.stderr)

    # Update index
    _update_index(out_path, sha, snapshot)
    print(f"[pipeline] updated {INDEX_FILE.name}", file=sys.stderr)

    # R1: strategy-tag sidecar (deterministic, shares would_enter with the
    # backtest). Written after the snapshot is built — snapshot is untouched.
    _write_strategy_tags(target_date)

    if check_replay:
        # Re-run end-to-end through the SAME adapter, the SAME lookback set,
        # and the SAME archive step so the second snapshot has identical
        # provenance.archived_copy_path values and the same RAW_ARCHIVED event.
        # Replay legitimacy = byte-identical canonical_sha256 modulo generated_at.
        adapter_out2 = _run_adapter(date)
        snap2 = ingest(adapter_out2, cfg, repo_root=str(repo_root),
                       prior_snapshots=lookback, prior_snap_objects=prior_snap_objects)
        archive_raw_inputs(snap2, repo_root, RAW_ARCHIVE_DIR)
        # Normalize the replay-excluded fields (generated_at + all excluded-M)
        # against run-1. The strip set is DERIVED from schema/field_registry.yaml
        # (replay level = excluded-M), NOT hardcoded here — single SoT shared with
        # verify_all_replay.py. See core/replay_contract.py (RC-5).
        normalize_for_replay_compare(snap2, snapshot)
        h1 = canonical_sha256(snapshot)
        h2 = canonical_sha256(snap2)
        replay_passed = h1 == h2
        if replay_passed:
            print(f"[replay] ✅ PASS — byte-identical hash on two runs: {h1}", file=sys.stderr)
        else:
            print(f"[replay] ❌ FAIL — hash mismatch: {h1} vs {h2}", file=sys.stderr)

        # Attestation ledger (L2.5, P2-W5): append a side-car verification proof
        # that this snapshot's hash was check-replay-verified at generation time.
        # M-state only (hashes/versions/timestamp/env fingerprint — zero market
        # judgement); append-only + idempotent on (date, canonical_hash). Replay
        # pass/fail above NEVER depends on this ledger — it records the result.
        appended = attest_from_snapshot(
            REPLAY_LEDGER_FILE,
            snapshot,
            canonical_hash=h1,
            check_replay_passed=replay_passed,
            attested_at=_now_utc_iso(),
        )
        if appended:
            print(f"[ledger] attestation appended → {REPLAY_LEDGER_FILE.name} "
                  f"(passed={replay_passed})", file=sys.stderr)
        else:
            print(f"[ledger] attestation already present (idempotent no-op)", file=sys.stderr)

        if not replay_passed:
            return snapshot

    return snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD; default = today.json's tradingDate")
    ap.add_argument("--source", default="auto", choices=["auto", "legacy", "rollup"],
                    help="Which adapter to use")
    ap.add_argument("--check-replay", action="store_true",
                    help="After writing, re-run ingest and verify hash equality")
    ap.add_argument("--backfill-all", action="store_true",
                    help="Backfill every date available in rollup (chronological order)")
    args = ap.parse_args()

    if args.backfill_all:
        from data.adapters.rollup import available_dates
        dates = available_dates()
        print(f"[pipeline] backfill: {len(dates)} dates: {dates}", file=sys.stderr)
        for d in dates:
            try:
                run(d, source="rollup", check_replay=args.check_replay)
            except Exception as e:
                print(f"[pipeline] ❌ {d}: {e}", file=sys.stderr)
    else:
        result = run(args.date, check_replay=args.check_replay, source=args.source)
        if result is None:
            # Empty-universe abstain — nothing was written (see module
            # docstring). Distinct exit code so tools/daily.py can treat this
            # as a clean skip instead of pipeline_failed.
            sys.exit(EXIT_SKIP_EMPTY_UNIVERSE)


if __name__ == "__main__":
    main()
