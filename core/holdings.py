"""core/holdings.py — 持倉重點關注 (P3b).

Pure evaluation of the user's manually-entered holdings (data/holdings.json)
against the live snapshot chain: P/L plus whether each position currently meets
Strategy A or B exit conditions, with an alert level for the cockpit warning
light. Logic lives here (core); the viewer only renders (governance redline #1).

Exit conditions mirror core/paper_trading + core/strategies:
  A 籌碼錨定: 轉弱 orange/red  OR  主力連 2 日淨賣(翻負)
  B 動能延續: 轉弱 orange/red  OR  外資連 2 日反向  OR  從近高回落 ≥ trailing_stop_pct
Alert: red  = 強訊號(轉弱red / 主力連2賣 / 外資連2反向)
       orange = 較軟(轉弱orange / 回落觸發)
       none = 未達任何出場條件
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from core.strategies import STRATEGY_B


def load_holdings(path: str | pathlib.Path) -> list[dict]:
    """Read data/holdings.json → list of {ticker, name, shares, cost}. Safe."""
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    items = d.get("holdings", d) if isinstance(d, dict) else d
    return [h for h in (items or []) if isinstance(h, dict) and h.get("ticker")]


def _seq(ticker: str, snaps: list[dict]) -> list[dict]:
    out = []
    for s in snaps:
        for r in s.get("stocks", []):
            if r.get("ticker") == ticker:
                out.append(r)
                break
    return out


def _weak_sev(rec: dict) -> str:
    return ((rec or {}).get("weakening") or {}).get("severity", "none")


def evaluate_holding(h: dict, snaps: list[dict]) -> dict[str, Any]:
    ticker = h.get("ticker")
    name = h.get("name") or ticker
    shares = h.get("shares")
    cost = h.get("cost")
    seq = _seq(ticker, snaps)
    latest = seq[-1] if seq else {}
    price = latest.get("current_price")
    pl_pct = ((price - cost) / cost) if (price and cost) else None
    mkt_value = (price * shares) if (price and shares) else None

    mfb = [r.get("main_force_buy") for r in seq]
    fii = [r.get("fii_net_buy") for r in seq]
    prices = [r.get("current_price") for r in seq if r.get("current_price") is not None]
    sev = _weak_sev(latest)

    a_reasons: list[str] = []
    b_reasons: list[str] = []
    if sev in ("orange", "red"):
        a_reasons.append(f"轉弱{sev}")
        b_reasons.append(f"轉弱{sev}")
    if len(mfb) >= 2 and (mfb[-1] or 0) < 0 and (mfb[-2] or 0) < 0:
        a_reasons.append("主力連2日淨賣")
    if len(fii) >= 2 and (fii[-1] or 0) < 0 and (fii[-2] or 0) < 0:
        b_reasons.append("外資連2日反向")
    retrace = None
    if prices and price:
        peak = max(prices)
        if peak > 0 and price <= peak * (1 - STRATEGY_B.trailing_stop_pct):
            retrace = (peak - price) / peak
            b_reasons.append(f"回落{retrace*100:.0f}%(近高{peak})")

    hard = (sev == "red") or ("主力連2日淨賣" in a_reasons) or ("外資連2日反向" in b_reasons)
    a_exit = bool(a_reasons)
    b_exit = bool(b_reasons)
    if hard:
        alert = "red"
    elif a_exit or b_exit:
        alert = "orange"
    else:
        alert = "none"

    return {
        "ticker": ticker, "name": name, "shares": shares, "cost": cost,
        "current_price": price,
        "pl_pct": round(pl_pct, 4) if pl_pct is not None else None,
        "market_value": round(mkt_value) if mkt_value is not None else None,
        "weakening": sev,
        "a_exit": a_exit, "a_reasons": a_reasons,
        "b_exit": b_exit, "b_reasons": b_reasons,
        "alert": alert,
        "in_universe": bool(seq),
    }


def evaluate_holdings(holdings: list[dict], snaps: list[dict]) -> list[dict]:
    """Evaluate all holdings; alert positions (red→orange) sort to the top."""
    rows = [evaluate_holding(h, snaps) for h in holdings]
    order = {"red": 0, "orange": 1, "none": 2}
    return sorted(rows, key=lambda r: (order.get(r["alert"], 3), -(r["pl_pct"] or 0)))
