"""Ingest engine — raw_inputs → v1.4 canonical snapshot.

Scoring is fully abstained at this stage (P3a):
  - All score_tree nodes: abstained=true, value="0.0000", reason="P3a ingest-only"
  - All tier values: "IGNORE"
  - All gates: passed=null (not evaluated)

This module is intentionally minimal. The goal is to validate plumbing
(replay-safe canonical hashing, lookback chain, provenance) before
activating any scoring logic.

Public API:
    ingest(adapter_output, config, prior_snapshots=None) -> Snapshot dict
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from typing import Any

import yaml

from core.hashing import canonical_sha256


SCHEMA_VERSION = "1.4.0"
CORE_VERSION = "core@0.1.0-p3a"
SCORING_RUBRIC_VERSION = "1.1.0"

# Tier enum — schema requires non-null even when abstained
ABSTAIN_TIER = "IGNORE"


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_sha(repo_root: str | os.PathLike | None) -> str:
    """Return current git SHA (40 hex) or 40 zeros if not in a git repo."""
    if repo_root is None:
        return "0" * 40
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if len(out) == 40 and all(c in "0123456789abcdef" for c in out):
            return out
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return "0" * 40


def _pkg_version(pkg: str, default: str = "0.0.0") -> str:
    try:
        import importlib.metadata as im
        return im.version(pkg)
    except Exception:
        return default


def _environment_block(repo_root: str | os.PathLike | None = None) -> dict:
    return {
        "core_commit_sha":  _git_sha(repo_root),
        "core_version":     CORE_VERSION,
        "python":           ".".join(map(str, sys.version_info[:3])),
        "numpy":            _pkg_version("numpy"),
        "pandas":           _pkg_version("pandas"),
        "pyyaml":           _pkg_version("pyyaml", "0.0.0"),
        "jsonschema":       _pkg_version("jsonschema"),
        "decimal_context":  {"prec": 28, "rounding": "ROUND_HALF_EVEN"},
        "locale":           {"LC_ALL": "C.UTF-8", "LC_NUMERIC": "C"},
        "timezone":         "UTC",
        "os":               f"{platform.system().lower()}-{platform.release()}-{platform.machine()}",
        "lookback_snapshots": {},     # filled below if priors provided
        "lookback_window_days": None,  # filled below
    }


def _abstain_stock_record(ticker: str, raw: dict, has_branches: bool) -> dict:
    """Build a StockRecord with all scoring fields abstained."""
    # buy_vol_lots from rollup buyList is NET buy (can be negative); volume must be >=0 or null.
    buy_vol = raw.get("buy_vol_lots")
    if buy_vol is not None and buy_vol < 0:
        volume_field = None        # signed net buy doesn't belong in 'volume'
    else:
        volume_field = buy_vol     # int >= 0 or None

    return {
        "ticker":        ticker,
        "name":          raw.get("name", ""),
        "market":        "TWSE",  # default; not verified by adapter
        "industry":      None,

        "current_price": raw.get("current_price"),
        "prev_close":    None,
        "change_pct":    raw.get("change_pct"),
        "volume":        volume_field,
        "volume_5d_avg": None,
        "volume_ratio":  None,

        # FII / main-force fields — populated from T86 (via adapter) where available
        "fii_net_buy":                raw.get("fii_net_buy"),         # 外資淨買（張）from T86
        "fii_buy_ratio":              None,
        "fii_holding_pct":             None,
        "fii_holding_trend_5d":        None,
        "fii_sync_count":              raw.get("fii_sync_count"),     # 0–3: how many participants net positive
        "fii_brokers_buying":          [],
        "fii_consecutive_buy_days":    None,
        # main_force_buy: prefer branches' total_buy_vol; fall back to rollup signed buyVol
        "main_force_buy":              raw.get("total_buy_vol") if raw.get("total_buy_vol") is not None else raw.get("buy_vol_lots"),
        "top5_branches":               raw.get("top5_branches", []),
        "main_force_cost":             raw.get("avg_buy_cost"),
        "main_force_consecutive_days": None,
        "main_force_volume_trend":     [],
        "volume_increasing_streak":    None,
        "top5_concentration":          None,
        "dealer_net_buy":              raw.get("investment_trust_net_buy"),  # 投信淨買（張）from T86
        "is_day_trader_branch":        False,

        "shareholder_count":                  None,
        "shareholder_count_delta_pct":        None,
        "broker_count_diff":                  None,
        "broker_count_diff_negative_streak":  None,
        "large_holder_400_pct":               None,
        "large_holder_400_delta_pct":         None,
        "large_holder_1000_pct":              None,
        "large_holder_1000_delta_pct":        None,

        "margin_balance":                    None,
        "margin_change":                     None,
        "margin_maintenance_ratio":          None,
        "price_down_margin_down_days_10d":   None,
        "price_down_margin_up_days_10d":     None,
        "margin_panic_signal":               False,

        "pa_signals_30m":   [],
        "trend_2h":         "flat",
        "above_20ema_2h":   False,
        "ema_slope_2h":     "flat",

        "gates": {"G1": False, "G2": False, "G3": False, "eliminated_by": None},

        # Scoring fully abstained (P3a)
        "stage_1": 0, "stage_1_breakdown": {"_abstained": "P3a ingest-only"},
        "stage_2": 0, "stage_2_breakdown": {"_abstained": "P3a ingest-only"},
        "stage_3": 0, "stage_3_breakdown": {"_abstained": "P3a ingest-only"},
        "composite_score":   0,
        "tier":              ABSTAIN_TIER,
        "trade_type":        None,
        "safety_margin_pct": None,

        "checklist": {
            "dual_engine_aligned":   False,
            "cost_within_5pct":      False,
            "shareholders_dropping": False,
            "margin_healthy":        False,
            "margin_ratio":          None,
            "pa_signal_present":     False,
        },

        # Temporal — bootstrap state when no priors
        "temporal_state": {
            "prior_tier":                 None,
            "tier_in_current_state_days": 1,
            "tier_history_lookback":      [],
            "score_history_lookback":     [],
            "score_velocity":             None,
            "score_acceleration":         None,
            "trend":                      None,
            "current_episode_ids":        [],
            "abstained": {
                "velocity": True, "acceleration": True, "trend": True,
                "reason": "P3a ingest-only; no scoring computed yet",
            },
        },
    }


def _field_to_source_map(provenance_sources: dict) -> dict[str, str]:
    """Reverse-index: field name → source_id."""
    m: dict[str, str] = {}
    for src_id, src in provenance_sources.items():
        for f in src.get("provides_fields", []):
            m.setdefault(f, src_id)
    return m


def ingest(
    adapter_output: dict,
    config: dict,
    *,
    repo_root: str | os.PathLike | None = None,
    prior_snapshots: dict[str, str] | None = None,  # {date: sha256}
) -> dict:
    """Build a v1.4 canonical snapshot from adapter output.

    Args:
        adapter_output: dict from data.adapters.legacy.adapt_legacy()
        config: loaded scd.example.yaml dict (frozen into config_snapshot)
        repo_root: path used to read git SHA
        prior_snapshots: optional {YYYY-MM-DD: "sha256:..."} for lookback chain

    Returns: snapshot dict (NOT yet written to disk).
    """
    date = adapter_output["date"]
    raw_per_ticker = adapter_output["raw_inputs_per_ticker"]
    universe = adapter_output["universe"]
    prov_sources = adapter_output["provenance_sources"]
    audit_events = list(adapter_output["audit_events"])

    env = _environment_block(repo_root=repo_root)
    if prior_snapshots:
        env["lookback_snapshots"] = dict(prior_snapshots)
        env["lookback_window_days"] = len(prior_snapshots)
        audit_events.append({
            "ticker": None,
            "event": "LOOKBACK_VERIFIED",
            "reason": f"Lookback chain attached: {len(prior_snapshots)} prior snapshots",
            "step": "core.ingest.attach_lookback",
            "data": {"lookback_snapshots": prior_snapshots},
        })
    else:
        env["lookback_snapshots"] = {}
        env["lookback_window_days"] = 0
        audit_events.append({
            "ticker": None,
            "event": "BOOTSTRAP_SNAPSHOT",
            "reason": "no prior snapshots in lookback; temporal state abstained",
            "step": "core.ingest.bootstrap",
            "data": {"affected_universe_size": len(universe)},
        })

    # Build per-stock records
    stocks = []
    for ticker in universe:
        raw = raw_per_ticker[ticker]
        rec = _abstain_stock_record(ticker, raw, has_branches=raw.get("_branches_present", False))
        stocks.append(rec)

    # config_hash — canonical hash of config dict (excluding ephemeral fields)
    config_hash = canonical_sha256(config)

    provenance = {
        "sources":         prov_sources,
        "field_to_source": _field_to_source_map(prov_sources),
        "derived_fields":  {},  # no derivations at ingest-only stage
    }

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "date":           date,
        "generated_at":   _now_utc_iso(),
        "config_hash":    config_hash,
        "core_version":   CORE_VERSION,
        "environment":    env,
        "provenance":     provenance,
        "config_snapshot": config,
        "universe_size":  len(universe),
        "eligible_count": 0,        # all abstained
        "market_regime": {
            "label": None,
            "classifier": "stub_v0",
            "confidence": None,
            "features": {"vix_proxy": None, "breadth_index": None, "regime_dwell": None},
        },
        "episodes_active_at_start": [],
        "episodes_changed_today": [],
        "tier_transitions": [],
        "stocks":         stocks,
        "rankings": {
            "golden":  [],
            "watch":   [],
            "neutral": [],
            "ignored": list(universe),  # everyone is IGNORE because abstained
            "sort_keys_used": ["P3a abstained — no scoring activated"],
        },
        "audit_log": audit_events,
    }
    return snapshot
