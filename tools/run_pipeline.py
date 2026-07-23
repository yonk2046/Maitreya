"""SCD Engine pipeline CLI — P3a ingest-only.

Usage:
    python -m tools.run_pipeline --date 2026-05-25
    python -m tools.run_pipeline                     # uses today.json's tradingDate
    python -m tools.run_pipeline --date 2026-05-25 --check-replay

Outputs to Ai stock/reports/<date>.json + .sha256 + updates index.json.
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


def _write_strategy_tags(target_date: str) -> None:
    """R1:快照建成後產生 reports/strategy_tags/<date>.json 落地 sidecar。

    決定論、來源=共用 core.strategies.would_enter(與回測同一實作)。此檔不進快照、
    不動 schema、不 bump minor(單一 bump 紀律);viewer 讀此檔渲染徽章,不新增
    render-time 引擎 import。Schema 2.0 時遷入快照 obs_*。

    切片=全歷史 ≤ target_date(對齊 viewer 全歷史 golden 與回測 snaps[:i+1])。
    永不因標示產生失敗而中斷 pipeline —— 快照本身(唯一事實來源)已寫入。
    """
    try:
        from core.strategies import STRATEGY_A, STRATEGY_B, strategy_tags_for_date
        chain = _load_chain_upto(target_date)
        strategies = {"A": STRATEGY_A, "B": STRATEGY_B}
        tags = strategy_tags_for_date(chain, strategies)
        payload = {
            "date": target_date,
            "generated_from": "core.strategies.would_enter (single source of truth)",
            "strategies": {k: {"name": v.name, "zh": v.zh, "kind": v.kind}
                           for k, v in strategies.items()},
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


def run(date: str | None, *, check_replay: bool = False, source: str = "auto") -> dict:
    """Run pipeline for a given date, write snapshot, update index. Returns the snapshot dict.

    Args:
        date: target YYYY-MM-DD; for 'auto', falls back to today.json's tradingDate.
        source: 'auto' (legacy for today, rollup for historical),
                'legacy' (force today.json), 'rollup' (force backfill from rollup).
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
        run(args.date, check_replay=args.check_replay, source=args.source)


if __name__ == "__main__":
    main()
