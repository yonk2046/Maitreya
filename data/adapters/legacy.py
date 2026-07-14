"""Legacy adapter — bridges existing `data/today.json` + `data/branches/*.json`
into v1.4 canonical raw_inputs.

This adapter:
  - Reads existing files in /Users/yoncky/SCD engine/data/   (unchanged)
  - Returns a structure compatible with core/ingest.py
  - Records per-source SHA-256 for replay safety
  - Does NOT modify any source file (WORM)

Note: branches files have no date field; their `mtime` is used as `fetched_at`.
If branches are stale relative to the target snapshot date, a DATA_WARNING is emitted.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import unicodedata
from typing import Any

from core.hashing import file_sha256
from data.adapters.contract import validate_adapter_output


# ---- Path resolution ------------------------------------------------------

def _project_root() -> pathlib.Path:
    """Find the project root that contains the data/ directory.

    Resolution order:
      1. $SCD_PROJECT_ROOT env var (explicit override — wins everything).
         Accepts any dir that has a 'data' subdirectory. This includes:
           - The classic 'SCD engine/' parent layout (local dev)
           - The repo root itself (GitHub Actions / devcontainer)
      2. Anchor-file walk (MOST SPECIFIC — checked first): walk up from
         __file__ looking for the nearest parent that directly contains
         both 'tools/fetch_daily.py' and 'data/'. This uniquely identifies
         the actual project root regardless of what its parent directories
         are named, so it correctly resolves to '.../SCD engine/Ai stock'
         on the user's machine (NOT '.../SCD engine', which also happens to
         contain an 'Ai stock' dir AND its own stale leftover 'data/' dir
         from an old prototype layout — matching that broader, looser
         condition first was the root cause of a local/cloud data-sync bug,
         see [[scd_distribution_layer_plan]]). Also correctly handles
         GitHub Actions / devcontainer checkouts where the repo IS the root.
      3. Walk up from __file__ looking for a parent with both
         'Ai stock' and 'data' as children — fallback for unusual layouts
         where case 2's anchor file might be missing.
      4. Walk up looking for a sibling 'data' dir adjacent to an 'Ai stock'
         peer at any depth — handles the Cowork dual-mount case.

    Raises RuntimeError if none of the above resolves.
    """
    env_override = os.environ.get("SCD_PROJECT_ROOT")
    if env_override:
        p = pathlib.Path(env_override).resolve()
        # Relaxed check: just needs data/ to exist (works for both classic
        # parent layout and repo-as-root layout in CI).
        if (p / "data").is_dir():
            return p
        raise RuntimeError(
            f"SCD_PROJECT_ROOT={env_override} does not contain a 'data' subdir."
        )

    here = pathlib.Path(__file__).resolve()

    # Case 2: anchor-file walk — most specific, checked FIRST so it wins
    # over the looser name-based checks below. 'tools/fetch_daily.py' +
    # 'data/' as direct siblings uniquely identifies the real project root
    # (whether that's '.../SCD engine/Ai stock' locally or the repo
    # checkout root in CI), and stops us from matching a parent directory
    # that merely *contains* an 'Ai stock' folder and an unrelated 'data' dir.
    for parent in here.parents:
        if (parent / "tools" / "fetch_daily.py").is_file() and (parent / "data").is_dir():
            return parent

    # Case 3: standard parent walk — classic SCD engine/ layout fallback.
    for parent in here.parents:
        if (parent / "Ai stock").is_dir() and (parent / "data").is_dir():
            return parent

    # Case 4: Cowork dual-mount fallback.
    for parent in here.parents:
        candidate = parent / "SCD engine"
        if (candidate / "Ai stock").is_dir() and (candidate / "data").is_dir():
            return candidate

    raise RuntimeError(
        f"Could not locate project root from {here}. "
        "Expected a parent dir with 'data/' as a child, or set "
        "$SCD_PROJECT_ROOT to the project root explicitly."
    )


def legacy_paths() -> dict[str, pathlib.Path]:
    root = _project_root()
    return {
        "root":         root,
        "today_json":   root / "data" / "today.json",
        "branches_dir": root / "data" / "branches",
        "snapshots":    root / "data" / "snapshots",
    }


# ---- Helpers --------------------------------------------------------------

def _utc_iso(ts: float) -> str:
    """Convert a POSIX timestamp to ISO 8601 UTC with 'Z'."""
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _read_branches_dir(branches_dir: pathlib.Path) -> tuple[dict[str, dict], str, str]:
    """Read all per-ticker branch JSONs. Returns (by_ticker, dir_manifest_sha256, latest_mtime_iso).

    The dir manifest sha is SHA-256 over a deterministic listing of (filename, file_sha256).
    This lets us record one provenance entry for the whole branches directory.
    """
    if not branches_dir.is_dir():
        return ({}, "sha256:" + "0" * 64, _utc_iso(0))
    by_ticker: dict[str, dict] = {}
    manifest_lines: list[str] = []
    latest_mtime = 0.0
    for f in sorted(branches_dir.glob("*.json")):
        ticker = f.stem
        sha = file_sha256(f)
        manifest_lines.append(f"{f.name} {sha}")
        if f.stat().st_mtime > latest_mtime:
            latest_mtime = f.stat().st_mtime
        try:
            by_ticker[ticker] = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            by_ticker[ticker] = {"_error": str(e)}
    import hashlib
    manifest_bytes = ("\n".join(manifest_lines) + "\n").encode("utf-8")
    manifest_sha = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    return (by_ticker, manifest_sha, _utc_iso(latest_mtime))


def _trading_days_between(d1: str, d2: str) -> int:
    """Approx trading-day diff (calendar-day fallback; ignores holidays)."""
    if not d1 or not d2:
        return 0
    a = dt.date.fromisoformat(d1)
    b = dt.date.fromisoformat(d2)
    return abs((b - a).days)


# ---- Adapter contract ----------------------------------------------------

def adapt_legacy(
    date: str | None = None,
    *,
    paths_override: dict[str, pathlib.Path] | None = None,
    tdcc_asof: str | None = None,
) -> dict[str, Any]:
    """Read existing legacy data and return canonical raw_inputs.

    Args:
        date: Target snapshot date YYYY-MM-DD. If None, use today.json's tradingDate.
        paths_override: optional dict with keys {root, today_json, branches_dir}
            used for I/O. When provided, the adapter reads bytes from these
            paths but STILL records canonical "data/today.json" /
            "data/branches/" in provenance.raw_file — those strings are the
            adapter's logical contract, independent of where bytes physically
            live. Used by tools/verify_all_replay.py to replay against the
            immutable archive at reports/_raw_archive/<date>/.

    Returns dict:
        {
          "date": "2026-05-25",
          "raw_inputs_per_ticker": { "<ticker>": {raw fields...}, ... },
          "universe": ["<ticker>", ...],
          "provenance_sources": { "<source_id>": {...} },
          "audit_events": [ {event, reason, step, data}, ... ]
        }
    """
    paths = paths_override or legacy_paths()
    audit_events: list[dict] = []

    # --- Source 1: today.json (market-level + mainForceBuy) ---
    today_path = paths["today_json"]
    if not today_path.is_file():
        raise FileNotFoundError(f"today.json missing: {today_path}")
    today_raw = today_path.read_text(encoding="utf-8")
    today = json.loads(today_raw)
    today_sha = file_sha256(today_path)
    today_mtime = _utc_iso(today_path.stat().st_mtime)

    target_date = date or today.get("tradingDate") or today.get("date")
    if not target_date:
        raise ValueError("Cannot infer target date — neither --date passed nor tradingDate/date in today.json")

    # Validate today.json matches target date if --date passed
    if date and today.get("tradingDate") and today["tradingDate"] != date:
        audit_events.append({
            "ticker": None,
            "event": "DATA_WARNING",
            "reason": f"today.json.tradingDate={today['tradingDate']} != requested date={date}",
            "step": "adapters.legacy.adapt_legacy",
        })

    # --- Source 2: branches dir ---
    branches_by_ticker, branches_manifest_sha, branches_latest_iso = _read_branches_dir(paths["branches_dir"])
    # latest mtime → ISO date for lag calc
    branches_latest_date = branches_latest_iso[:10]
    lag_days = _trading_days_between(target_date, branches_latest_date)
    if lag_days > 1:
        audit_events.append({
            "ticker": None,
            "event": "DATA_WARNING",
            "reason": f"branches directory latest mtime is {branches_latest_date}, "
                      f"{lag_days} days behind target snapshot date {target_date}",
            "step": "adapters.legacy.branches",
        })

    # --- Build per-ticker raw_inputs ---
    raw_inputs_per_ticker: dict[str, dict] = {}

    # Primary universe: mainForceBuy (29 tickers today)
    main_force_buy = today.get("mainForceBuy", []) or []
    for row in main_force_buy:
        ticker = str(row.get("code", "")).strip()
        if not ticker:
            continue
        ri: dict[str, Any] = {
            "ticker":        ticker,
            "name":          _nfc(str(row.get("name", ""))),
            "rank":          row.get("rank"),
            "is_etf":        bool(row.get("isETF", False)),
            "current_price": row.get("close"),
            "change_pct":    row.get("chgPct"),
            "buy_vol_lots":  row.get("buyVol"),
        }
        # Branches detail if available
        bdata = branches_by_ticker.get(ticker)
        if bdata and "_error" not in bdata:
            buy_b = bdata.get("buyBranches", []) or []
            sell_b = bdata.get("sellBranches", []) or []
            ri["top5_branches"] = [
                {
                    "branch": _nfc(b.get("broker", "")),
                    "buy":    int(b.get("buyVol", 0)),
                    "sell":   int(b.get("sellVol", 0)),
                    "net":    int(b.get("netBuy", 0)),
                }
                for b in buy_b[:5]
            ]
            ri["all_buy_branches_count"]  = len(buy_b)
            ri["all_sell_branches_count"] = len(sell_b)
            ri["total_buy_vol"]   = bdata.get("totalBuyVol")
            ri["total_sell_vol"]  = bdata.get("totalSellVol")
            ri["avg_buy_cost"]    = bdata.get("avgBuyCost")
            ri["avg_sell_cost"]   = bdata.get("avgSellCost")
            ri["_branch_raw"]     = bdata   # full branch dict for weakening_profile W5
            ri["_branches_present"] = True
        else:
            ri["top5_branches"] = []
            ri["_branches_present"] = False
            audit_events.append({
                "ticker": ticker,
                "event": "DATA_WARNING",
                "reason": f"no branches file for {ticker}; top5_branches abstained",
                "step": "adapters.legacy.branches",
            })
        raw_inputs_per_ticker[ticker] = ri

    # --- Merge volRows market volume into per-ticker raw_inputs ---
    # today.json["volRows"] = [{code, name, todayVol, close, chgPct, ...}]
    # todayVol is in shares (股); convert to 張 (÷1000)
    vol_map = {
        str(r.get("code", "")).strip(): int(round(r.get("todayVol", 0) / 1000))
        for r in (today.get("volRows") or [])
        if r.get("code") and r.get("todayVol")
    }
    # A2 fix (2026-07-03): today.json["marketQuotes"] = {code: {vol(張), close,
    # chgPct(真%), chgAmt}} from STOCK_DAY_ALL — full-market coverage, so
    # market_volume is no longer limited to the volume-top20 list, and
    # change_pct gets an authoritative real-percent source (the Fubon rows'
    # chgPct was the NT$ move until the same-day fetch fix). Old raw archives
    # have no marketQuotes → both fall back to prior behaviour (replay-safe).
    market_quotes = today.get("marketQuotes") or {}
    for ticker, ri in raw_inputs_per_ticker.items():
        mq = market_quotes.get(ticker)
        if mq and mq.get("vol"):
            ri["market_volume"] = mq["vol"]          # 市場成交量（張）, full-market
        else:
            ri["market_volume"] = vol_map.get(ticker)  # top20 fallback, None if absent
        if mq and mq.get("chgPct") is not None:
            ri["change_pct"] = mq["chgPct"]          # TWSE authoritative real %

    # --- Merge next-day-settlement OPEN price (P3b backtest, spec §1) ---
    # today.json["openPrices"] = {code: 開盤價} full-market (STOCK_DAY_ALL).
    # None for historical snapshots whose today.json predates this field →
    # backtest falls back to close (documented limitation).
    open_map = today.get("openPrices") or {}
    for ticker, ri in raw_inputs_per_ticker.items():
        ri["open"] = open_map.get(ticker)

    # --- Merge T86 三大法人 data into per-ticker raw_inputs ---
    # today.json["t86"] = { code: {foreign, trust, prop, total3} } all in 張
    # 兩段式快照 (2026-07-07,schema 1.8.1):T86 必須屬於快照當日 — t86Date
    # 不符即整組丟棄(鐵律:絕不把非當日 T86 寫進快照)。過去這條只由
    # tools/daily.py 的 fii_gate 把守,直接呼叫 run_pipeline 會繞過;現在
    # adapter 層結構性擋死。t86 缺席(或被丟棄)→ fii_pending=True 進快照,
    # 標記「外資待補」,早晨 T86 到手後由 supersede 重建補完。
    t86 = today.get("t86") or {}
    _t86_date = str(today.get("t86Date") or "").strip()
    if t86 and _t86_date and _t86_date != target_date.replace("-", ""):
        audit_events.append({
            "ticker": None,
            "event": "DATA_WARNING",
            "reason": f"t86Date={_t86_date} != snapshot date {target_date} — "
                      "stale FII dropped entirely (fii_pending)",
            "step": "adapters.legacy.t86",
        })
        t86 = {}
    fii_pending = not t86
    for ticker, ri in raw_inputs_per_ticker.items():
        t86_row = t86.get(ticker) or {}
        ri["fii_net_buy"]              = t86_row.get("foreign")    # 外資淨買（張）
        ri["investment_trust_net_buy"] = t86_row.get("trust")      # 投信淨買（張）
        ri["prop_dealer_net_buy"]      = t86_row.get("prop")       # 自營商淨買（張）
        ri["total3_net_buy"]           = t86_row.get("total3")     # 三大法人合計（張）
        # fii_sync_count: how many of main_force / foreign / trust are net positive
        mfb   = ri.get("total_buy_vol") or ri.get("buy_vol_lots")
        fii   = ri["fii_net_buy"]
        trust = ri["investment_trust_net_buy"]
        ri["fii_sync_count"] = sum(1 for v in [mfb, fii, trust] if v is not None and v > 0)

        # --- Phase 1 正名 staging (NOTES #1 / CROSS-SESSION-NOTES.md#1) -------
        # dealer_net_buy (schema field, see core/ingest.py:182) is misnamed —
        # it actually carries investment_trust_net_buy (投信), while the real
        # 自營商 value computed above (prop_dealer_net_buy) is silently
        # dropped by ingest. These two keys stage the CORRECT names for the
        # 1.9.0 landing (registry: schema/field_registry.yaml, status=planned)
        # WITHOUT changing today's canonical snapshot:
        #   - core/ingest.py does not read "trust_net_buy" / "prop_net_buy"
        #     into any StockRecord field yet (staging only, zero consumption).
        #   - deliberately NOT added to provenance_sources[...]["provides_fields"]
        #     below — that list feeds provenance.field_to_source, which IS part
        #     of the canonical snapshot content. Adding these names there would
        #     change the hash even though no record field changes.
        # Verified inert via `make verify-all-replay` (43/43 dates, 0 failures,
        # identical to pre-change baseline) — see docs/migration/P1-worm-backfill-report.md.
        ri["trust_net_buy"] = ri["investment_trust_net_buy"]  # 投信正名（現被誤裝進 dealer_net_buy）
        ri["prop_net_buy"]  = ri["prop_dealer_net_buy"]        # 真自營商正名（現被 ingest 丟棄）

    # --- Merge TDCC weekly shareholder / large-holder data ---
    # data/tdcc/<YYYYMMDD>.json files are written by tools/fetch_tdcc.py (or
    # fetch_daily.py on Fridays).  This block is read-only — no writes here,
    # so WORM integrity of data/ is never at risk.
    tdcc_provenance: dict | None = None
    try:
        from data.adapters import tdcc_adapter as _tdcc
        tdcc_dir = paths["root"] / "data" / "tdcc"
        # tdcc_asof caps the weekly-file resolution at the week the snapshot
        # recorded (verify_only replay passes provenance.tdcc_weekly.report_date).
        # Reading still happens from the live cache — which keeps prior weeks
        # needed for week-over-week deltas — but capping prevents replay from
        # drifting to a NEWER weekly file that lands later (which isn't in this
        # snapshot's archive and crashes archive verification). Normal ingest
        # leaves tdcc_asof None → resolves as-of target_date as before.
        tdcc_map = _tdcc.load_for_date(tdcc_asof or target_date, tdcc_dir)
        if tdcc_map:
            _tdcc.enrich_universe(raw_inputs_per_ticker, tdcc_map)
            # Use an arbitrary entry's metadata to build provenance
            sample = next(iter(tdcc_map.values()))
            tdcc_provenance = {
                "dataset":         "TDCC.weekly.distribution",
                "url":             "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&key=Open",
                "fetched_at":      sample["tdcc_fetched_at"],
                "raw_file":        f"data/tdcc/{sample['tdcc_date']}.json",
                "raw_sha256":      file_sha256(tdcc_dir / f"{sample['tdcc_date']}.json"),
                "row_count":       len(tdcc_map),
                "vendor_id":       "TDCC",
                "report_date":     _tdcc._tdcc_yyyymmdd_to_iso(sample["tdcc_date"]),
                "data_lag_days":   (
                    dt.date.fromisoformat(target_date)
                    - dt.date.fromisoformat(_tdcc._tdcc_yyyymmdd_to_iso(sample["tdcc_date"]))
                ).days,
                "provides_fields": [
                    "shareholder_count", "shareholder_count_delta_pct",
                    "large_holder_400_pct", "large_holder_400_delta_pct",
                    "large_holder_1000_pct", "large_holder_1000_delta_pct",
                ],
            }
        else:
            audit_events.append({
                "ticker": None,
                "event":  "DATA_WARNING",
                "reason": f"No TDCC cache file found for date ≤ {target_date} in {tdcc_dir}; "
                          "shareholder/large-holder fields will be None. "
                          "Run tools/fetch_tdcc.py to populate.",
                "step":   "adapters.legacy.tdcc",
            })
    except Exception as _e:
        audit_events.append({
            "ticker": None,
            "event":  "DATA_WARNING",
            "reason": f"TDCC enrichment failed ({type(_e).__name__}: {_e}); "
                      "shareholder/large-holder fields will be None.",
            "step":   "adapters.legacy.tdcc",
        })

    universe = sorted(raw_inputs_per_ticker.keys())

    # --- Phase 1 staging: sell-side raw passthrough (NOTES #38 / C7) --------
    # today.json["sellList"]/["mainForceSell"] (Fubon 外資賣超/主力賣超 top-N
    # rankings) are the only sell-side evidence source but have never entered
    # canonical — distribution.py reads them disk-load-only, never through
    # the pipeline (S03 裁定 #38: "活 code 死輸出"). This stages a verbatim,
    # unmodified passthrough (C7 非破壞 — same list-of-dict shape as source,
    # no truncation/reshaping) as a NEW top-level adapter_output key so a
    # future obs_dist_consistency (1.9.0, see field_registry.yaml planned_fields)
    # can consume it. Deliberately:
    #   - NOT merged into raw_inputs_per_ticker / universe (sell-side tickers
    #     often aren't in the buy-side mainForceBuy universe; adding them
    #     would create new StockRecords in the snapshot — a real content
    #     change, not staging).
    #   - NOT registered as a provenance source (provenance_sources becomes
    #     snapshot.provenance.sources verbatim — any new source entry there
    #     changes the canonical hash).
    #   - NOT read by core/ingest.py (ingest only extracts named top-level
    #     keys from adapter_output; unknown keys are inert).
    # Net effect: zero canonical snapshot content change, verified via
    # `make verify-all-replay` — see docs/migration/P1-worm-backfill-report.md.
    sell_raw = {
        "fii_sell_raw":        today.get("sellList", []) or [],       # 外資賣超原始榜（Fubon ZGK_D topSell）
        "main_force_sell_raw": today.get("mainForceSell", []) or [],  # 主力賣超原始榜（Fubon ZGK_F topSell）
        # Buy-side rankings — passed through so the 1.9.0 ingest pipeline can
        # land obs_dist_consistency in memory (distribution needs both買/賣
        # sides for 一致性 scoring). These are NOT written to the snapshot as
        # top-level fields (ingest only stores fii_sell_raw/main_force_sell_raw);
        # they feed distribution.consistency_for_universe() at landing time,
        # matching distribution.run()'s archive-read path (same today.json bytes).
        "buy_list":            today.get("buyList", []) or [],        # 外資買超原始榜（Fubon ZGK_D topBuy）
        "main_force_buy_raw":  today.get("mainForceBuy", []) or [],   # 主力買超原始榜（Fubon ZGK_F topBuy）
    }

    # --- Provenance ---
    # raw_file is the LOGICAL identifier of the source under data/, not the
    # physical path of the bytes we read. When paths_override is set (replay
    # against the archive), we still record the canonical path here so the
    # snapshot's canonical hash is independent of where bytes were read from.
    provenance_sources = {
        "legacy_today_json": {
            "dataset":         "SCD.legacy.today_json",
            "url":             "file://data/today.json",
            "fetched_at":      today_mtime,
            "raw_file":        "data/today.json",
            "raw_sha256":      today_sha,
            "row_count":       len(main_force_buy),
            "vendor_id":       None,
            "report_date":     today.get("tradingDate"),
            "data_lag_days":   0,
            "provides_fields": [
                "ticker", "name", "rank", "is_etf",
                "current_price", "change_pct", "buy_vol_lots",
                "fii_net_buy", "investment_trust_net_buy",
                "prop_dealer_net_buy", "total3_net_buy", "fii_sync_count",
            ],
        },
        "legacy_branches": {
            "dataset":         "SCD.legacy.branches_dir",
            "url":             "file://data/branches/",
            "fetched_at":      branches_latest_iso,
            "raw_file":        "data/branches/",
            "raw_sha256":      branches_manifest_sha,  # manifest hash, not single file
            "row_count":       len(branches_by_ticker),
            "vendor_id":       None,
            "report_date":     branches_latest_date,
            "data_lag_days":   lag_days,
            "provides_fields": [
                "top5_branches", "total_buy_vol", "total_sell_vol",
                "avg_buy_cost", "avg_sell_cost",
            ],
        },
    }
    if tdcc_provenance is not None:
        provenance_sources["tdcc_weekly"] = tdcc_provenance

    out = {
        "date":                  target_date,
        "raw_inputs_per_ticker": raw_inputs_per_ticker,
        "universe":              universe,
        "provenance_sources":    provenance_sources,
        "audit_events":          audit_events,
        "fii_pending":           fii_pending,
        "sell_raw":              sell_raw,  # Phase 1 staging (NOTES #38) — inert, see comment above
        "_today_meta": {
            "fetchedAt": today.get("fetchedAt"),
            "sources":   today.get("sources", []),
        },
    }
    validate_adapter_output(out, adapter_name="legacy.adapt_legacy")
    return out
