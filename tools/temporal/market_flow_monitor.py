"""SCD Engine — Market Flow Monitor  (P3c)

Cross-date CLI tool that runs all five market-context analyses and
prints a concise terminal report (or --json for structured output).

Usage:
  python -m tools.temporal.market_flow_monitor
  python -m tools.temporal.market_flow_monitor --dates 5   # last N dates
  python -m tools.temporal.market_flow_monitor --json
  python -m tools.temporal.market_flow_monitor --ticker 2317

Makefile target: make market-flow
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools.temporal._loader import real_dates, load_snapshot
from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
    regime_shift,
    failed_breakout_memory,
    leadership_rotation,
    full_ticker_context,
)
from core.watchlists import TIER_A, tier_a_tickers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_recent(n: int) -> tuple[list[str], list[dict[str, Any]]]:
    dates = real_dates()[-n:]
    snaps = [load_snapshot(d) for d in dates]
    return dates, snaps


def _records_for_ticker(ticker: str, snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snap in snaps:
        rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
        rows.append({
            "date":           snap.get("date", "?"),
            "main_force_buy": rec.get("main_force_buy")  if rec else None,
            "volume":         rec.get("volume")           if rec else None,
            "change_pct":     rec.get("change_pct")       if rec else None,
            "current_price":  rec.get("current_price")    if rec else None,
            "top5_branches":  rec.get("top5_branches")    if rec else [],
            "present":        rec is not None,
        })
    return rows


def _bar(value: float, lo: float, hi: float, width: int = 20) -> str:
    """ASCII bar for a value in [lo, hi]."""
    pct = max(0.0, min(1.0, (value - lo) / max(hi - lo, 1e-9)))
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _print_regime(regime: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"  市場體制  Market Regime")
    print("=" * 60)
    print(f"  {regime['regime_label_zh']}  /  {regime['regime_label_en']}")
    print(f"  廣度  Breadth : {regime['latest_breadth']*100:.1f}%   "
          f"[{_bar(regime['latest_breadth'], 0, 1)}]")
    print(f"  均漲  Avg Chg  : {regime['latest_avg_chg']:+.2f}%")
    print(f"  廣度趨勢 Trend   : {regime['breadth_trend']}")
    if regime["transition_detected"]:
        print(f"  ⚡ 轉換偵測  {regime['transition_note']}")
    print()
    if len(regime["dates"]) >= 2:
        print("  日期       廣度%   均漲%   量能指數")
        print("  ─" * 20)
        for i, d in enumerate(regime["dates"]):
            b   = regime["breadth_series"][i] * 100
            c   = regime["avg_chg_series"][i]
            vol = regime["vol_series"][i]
            print(f"  {d}  {b:5.1f}%  {c:+6.2f}%  {vol:.2f}×")
    print()


def _print_leadership(rot: dict[str, Any]) -> None:
    print("─" * 60)
    print("  資金輪動  Leadership Rotation")
    print("─" * 60)
    if rot["rotation_detected"]:
        print(f"  ⚡ 輪動偵測：{rot['rotation_from']} → {rot['rotation_to']}")
    print(f"  今日領漲  Leading: {rot['leading_label_zh']} / {rot['leading_label_en']}")
    print()
    flows = rot["sector_flows"]
    if not flows:
        print("  (無資料)")
    else:
        max_buy = max((v["total_buy"] for v in flows.values()), default=1)
        for sector in rot["ranked_sectors"]:
            data = flows[sector]
            buy  = data["total_buy"]
            bar  = _bar(buy, 0, max(max_buy, 1))
            sign = "+" if buy > 0 else ""
            print(f"  {data['label_zh']:<10} {sign}{buy:>8,}張  {bar}")
    print()


def _print_ticker_context(ctx: dict[str, Any]) -> None:
    acc  = ctx["accumulation"]
    spon = ctx["sponsorship"]
    fb   = ctx["failed_breakout"]
    t    = ctx["ticker"]
    meta = TIER_A.get(t, {})
    name = meta.get("name", t)

    print(f"  {t} {name}")
    print(f"    累積 Accum : {acc['label_zh']} / {acc['label_en']}")
    print(f"    連續 Streak: {acc['streak']}日  "
          f"買:{acc['buy_days']}日  賣:{acc['sell_days']}日  "
          f"累計:{acc['net_cumulative']:+,}張")
    if acc["velocity_3d"] is not None:
        print(f"    速度 Vel3d : {acc['velocity_3d']:+,.0f}張/日")
    if spon["days_with_branches"] > 0:
        print(f"    贊助 Spon  : {spon['label_zh']}  "
              f"持續分: {spon['persistence_score']:.2f}  "
              f"主力分點: {spon['top_persistent_broker'] or '─'} × {spon['top_broker_days']}日")
    if fb["failed_breakout_detected"]:
        print(f"    ⚠  {fb['label_zh']} / {fb['label_en']}")
        print(f"       突破日: {fb['breakout_date']}  +{fb['breakout_chg']:.1f}%  "
              f"量比: {fb['vol_ratio']:.1f}×  退卻: {fb['retreat_days']}日")


def _print_ticker_block(
    header: str,
    tickers: list[str],
    snaps: list[dict[str, Any]],
) -> None:
    print("─" * 60)
    print(f"  {header}")
    print("─" * 60)
    if not tickers:
        print("  (無符合條件標的)")
    for t in tickers:
        ctx = full_ticker_context(t, snaps)
        _print_ticker_context(ctx)
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    dates_n: int = 10,
    ticker: str | None = None,
    as_json: bool = False,
) -> dict[str, Any]:
    d_list, snaps = _load_recent(dates_n)

    if not snaps:
        result: dict[str, Any] = {"error": "no snapshots found"}
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("no snapshots found")
        return result

    # ── Single-ticker mode ────────────────────────────────────────────────
    if ticker:
        recs = _records_for_ticker(ticker, snaps)
        acc  = accumulation_velocity(ticker, recs)
        spon = sponsorship_persistence(ticker, recs)
        fb   = failed_breakout_memory(ticker, recs)
        result = {"ticker": ticker, "dates": d_list,
                  "accumulation": acc, "sponsorship": spon, "failed_breakout": fb}
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        print()
        _print_ticker_context({"ticker": ticker, "accumulation": acc,
                                "sponsorship": spon, "failed_breakout": fb})
        return result

    # ── Full market mode ──────────────────────────────────────────────────
    regime = regime_shift(snaps)
    rot    = leadership_rotation(snaps)

    # Collect all tickers across all snapshots
    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")

    # Compute context for every ticker
    contexts = {t: full_ticker_context(t, snaps) for t in sorted(all_tickers)}

    # Classify
    strengthening:    list[str] = []
    failed_breakouts: list[str] = []
    persistent_accum: list[str] = []

    for t, ctx in contexts.items():
        acc = ctx["accumulation"]
        spon = ctx["sponsorship"]
        fb   = ctx["failed_breakout"]
        if acc["streak"] >= 2:
            strengthening.append(t)
        if fb["failed_breakout_detected"]:
            failed_breakouts.append(t)
        if spon["persistence_score"] >= 0.4 and acc["buy_days"] >= 2:
            persistent_accum.append(t)

    # Sort by streak desc
    strengthening.sort(key=lambda t: -contexts[t]["accumulation"]["streak"])
    persistent_accum.sort(key=lambda t: -contexts[t]["sponsorship"]["persistence_score"])

    result = {
        "dates":          d_list,
        "regime":         regime,
        "leadership":     rot,
        "strengthening":  strengthening,
        "failed_breakouts": failed_breakouts,
        "persistent_accumulation": persistent_accum,
        "ticker_contexts": contexts,
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    # ── Terminal report ───────────────────────────────────────────────────
    print()
    _print_regime(regime)
    _print_leadership(rot)

    # Tier A summary
    print("─" * 60)
    print("  Tier A 永久追蹤  Regime Anchors")
    print("─" * 60)
    for ta in tier_a_tickers():
        if ta in contexts:
            ctx = contexts[ta]
            _print_ticker_context(ctx)
            print()

    _print_ticker_block(
        "轉強訊號  Strengthening Signals  (連續≥2日買超)",
        [t for t in strengthening if t not in tier_a_tickers()],
        snaps,
    )
    _print_ticker_block(
        "假突破警報  Failed Breakout Warnings",
        failed_breakouts,
        snaps,
    )
    _print_ticker_block(
        "持續吸籌  Persistent Accumulation  (贊助分≥0.4)",
        [t for t in persistent_accum if t not in strengthening[:3]],
        snaps,
    )

    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SCD Market Flow Monitor")
    ap.add_argument("--dates",  type=int, default=10, help="lookback window (default 10)")
    ap.add_argument("--ticker", type=str, default=None, help="single-ticker mode")
    ap.add_argument("--json",   action="store_true",   help="output JSON instead of text")
    args = ap.parse_args(argv)
    run(dates_n=args.dates, ticker=args.ticker, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
