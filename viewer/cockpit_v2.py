"""SCD Engine — Market Intelligence Cockpit  v2
五層式市場智慧終端  ·  30秒讀懂市場

Pulse  大盤脈搏    (always pinned)
L1     市場全覽    Market Overview        + regime + temperature
L2     黃金名單    Golden Layer v2        ★★ Core value
L3     信心 & 風險  Confidence & Risk      2-D per-ticker profile
L4     時序視圖    Temporal Visualization  charts
L5     深層指標    Deep Metrics           collapsed
L6     工程診斷    Engineering Diagnostics hidden

Run:  streamlit run viewer/cockpit_v2.py  --server.port 8503
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

_HERE     = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from viewer import data as vd
from core.narrative_engine import generate as _narrative_generate
from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
    regime_shift,
    failed_breakout_memory,
    leadership_rotation,
    full_ticker_context,
)
from core.watchlists import TIER_A, build_name_map, RADAR_TICKERS
from core.golden     import run as golden_run, GoldenEntry, TIER_PRIME_KEY, TIER_STRONG_KEY, TIER_QUALIFIED_KEY
from core.confidence import run as confidence_run, ConfidenceProfile
from core.state_machine import run_all as sm_run_all, state_summary as sm_state_summary, STATE_ZH, STATE_ORDER

_NAME_MAP: dict[str, str] = {}

def _name(t: str) -> str:
    n = _NAME_MAP.get(t) or TIER_A.get(t, {}).get("name", "")
    return f"{t} {n}" if n and n != t else t

def _short(t: str) -> str:
    return _NAME_MAP.get(t) or TIER_A.get(t, {}).get("name", t)


# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SCD · 市場情報終端 v2",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0B0F17 !important;
    color: #C9D1DC !important;
}
[data-testid="stSidebar"]  { background-color: #0F141C !important; }
[data-testid="stHeader"]   { background-color: #0B0F17 !important; }
.main .block-container { padding-top: 1rem; padding-bottom: 3rem; max-width: 1520px; }
html, body, p, div, span, td, th { font-size: 14px !important; }
h1,h2,h3,h4 { font-family: 'SF Pro Display','Helvetica Neue',sans-serif !important; letter-spacing: -0.01em; }
[data-testid="stTabs"] button { font-size: 13px !important; font-weight: 600; color: #6B8499 !important; padding: 8px 16px; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #7EB8D4 !important; border-bottom-color: #7EB8D4 !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] { min-width: 230px !important; max-width: 260px !important; }
[data-testid="stSidebar"] .block-container { padding: 1rem 0.85rem !important; }
.sb-logo    { font-size: 16px; font-weight: 800; color: #E0E8F0; letter-spacing:-0.02em; }
.sb-sub     { font-size: 10px; color: #3A4A5A; letter-spacing:.08em; text-transform:uppercase; margin-bottom:14px; }
.sb-divider { border:none; border-top:1px solid #1A2330; margin:12px 0; }
.sb-label   { font-size:10px; color:#3D6480; letter-spacing:.1em; text-transform:uppercase; font-weight:700; margin-bottom:6px; }
.sb-row     { display:flex; justify-content:space-between; padding:3px 0; }
.sb-key     { font-size:12px; color:#5B7A8E; }
.sb-val     { font-size:12px; font-weight:700; color:#C9D1DC; font-family:monospace; }

/* ── Narrative card ── */
.narrative-card {
    background: linear-gradient(135deg, #0F1720 0%, #111C28 100%);
    border: 1px solid #1E3045; border-left: 4px solid #7EB8D4;
    border-radius: 12px; padding: 20px 24px; margin-bottom: 18px;
}
.narrative-title { font-size:11px; color:#4A7A9A; letter-spacing:.1em; text-transform:uppercase; margin-bottom:10px; }
.narrative-body  { font-size:15px; color:#C9D1DC; line-height:1.65; font-weight:400; }

/* ── Regime pill ── */
.regime-pill {
    display: inline-flex; align-items:center; gap:10px;
    border-radius: 24px; padding: 8px 20px;
    font-size:14px; font-weight:700; letter-spacing:.01em;
    border: 1px solid; margin-bottom: 8px;
}

/* ── KPI row ── */
.kpi-row { display:flex; gap:10px; flex-wrap:wrap; margin:12px 0 20px 0; }
.kpi { background:#0F1820; border:1px solid #1C2D3E; border-radius:10px; padding:14px 18px; flex:1; min-width:120px; }
.kpi-label { font-size:10px; color:#4A6A80; letter-spacing:.08em; text-transform:uppercase; margin-bottom:6px; }
.kpi-value { font-size:26px; font-weight:700; line-height:1.1; }
.kpi-sub   { font-size:11px; color:#4A6A80; margin-top:4px; }

/* ── Pulse strip ── */
.pulse-strip { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; }
.pulse-cell  {
    background:#0F1820; border:1px solid #1C2D3E; border-radius:8px;
    padding:10px 14px; flex:1; min-width:105px;
}
.pulse-label { font-size:10px; color:#4A6A80; text-transform:uppercase; letter-spacing:.07em; margin-bottom:4px; }
.pulse-val   { font-size:19px; font-weight:700; line-height:1.2; }
.pulse-sub   { font-size:11px; color:#4A6A80; margin-top:2px; }

/* ── Layer dividers ── */
.layer-header {
    display:flex; align-items:center; gap:12px;
    border-bottom:1px solid #1A2C3E;
    padding:0 0 10px 0; margin:28px 0 18px 0;
}
.layer-num  { font-size:10px; color:#2C5A78; font-weight:700; letter-spacing:.1em; width:32px; }
.layer-zh   { font-size:17px; font-weight:700; color:#C9D1DC; }
.layer-en   { font-size:12px; color:#4A6A80; font-style:italic; }
.layer-count{ margin-left:auto; background:#0F1820; border:1px solid #1C3050; border-radius:16px; padding:2px 10px; font-size:11px; color:#7EB8D4; }

/* ── Tags ── */
.sig-tags   { display:flex; flex-wrap:wrap; gap:5px; margin-top:9px; }
.tag        { border-radius:5px; padding:2px 8px; font-size:11px; border:1px solid; }
.tag-green  { color:#52B788; border-color:#1E4A32; background:#071510; }
.tag-blue   { color:#7EB8D4; border-color:#1C3A52; background:#060F18; }
.tag-amber  { color:#D4A84B; border-color:#4A3510; background:#0E0A02; }
.tag-purple { color:#9E8AC8; border-color:#3A2860; background:#0A0616; }
.tag-red    { color:#E05C7A; border-color:#5A1C28; background:#110408; }
.tag-dim    { color:#5B7A8E; border-color:#1A2C3E; background:#070C12; }
.tag-gold   { color:#F4C842; border-color:#5A4010; background:#110C00; }

/* ── Golden cards ── */
.gc-wrap { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:10px; margin-top:6px; }
.gc {
    background:#0C1520; border:1px solid #1C2D3E; border-radius:10px;
    padding:14px 16px; position:relative;
}
.gc.prime     { border-left:3px solid #F4C842; }
.gc.strong    { border-left:3px solid #52B788; }
.gc.qualified { border-left:3px solid #7EB8D4; }
.gc.near-miss { border-left:3px solid #3A5060; }
.gc-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; }
.gc-ticker { font-size:15px; font-weight:800; color:#7EB8D4; font-family:monospace; }
.gc-name   { font-size:12px; color:#4A6A80; margin-left:5px; }
.gc-conv   { font-size:12px; font-weight:700; font-family:monospace; }
.gc-bars   { margin:8px 0; }
.gc-bar-row{ display:flex; align-items:center; gap:6px; margin-bottom:4px; }
.gc-bar-lbl{ font-size:10px; color:#3A5060; width:28px; text-align:right; }
.gc-bar-bg { flex:1; background:#0F1A26; border-radius:4px; height:6px; overflow:hidden; }
.gc-bar-fill{ height:100%; border-radius:4px; }
.gc-bar-val { font-size:10px; color:#4A6A80; width:32px; text-align:left; font-family:monospace; }

/* ── Confidence 2D scatter labels ── */
.conf-row {
    background:#0C1520; border:1px solid #1C2D3E; border-radius:8px;
    padding:10px 14px; margin-bottom:6px;
    display:flex; align-items:center; gap:12px;
}
.cr-ticker  { font-size:14px; font-weight:800; color:#7EB8D4; font-family:monospace; width:50px; }
.cr-name    { font-size:12px; color:#4A6A80; flex:1; }
.cr-scores  { font-size:12px; font-family:monospace; color:#C9D1DC; }
.cr-profile { font-size:11px; padding:2px 8px; border-radius:5px; border:1px solid; }

/* ── Temperature gauge ── */
.temp-gauge {
    background:#0F1820; border:1px solid #1C2D3E; border-radius:12px;
    padding:16px 20px; margin-bottom:16px;
}
.temp-title { font-size:10px; color:#3D6480; letter-spacing:.1em; text-transform:uppercase; margin-bottom:10px; }
.temp-bar-bg { background:#0B0F17; border-radius:8px; height:16px; overflow:hidden; margin:8px 0; }
.temp-bar-fill { height:100%; border-radius:8px; transition:width .4s; }
.temp-stats { display:flex; gap:20px; flex-wrap:wrap; margin-top:8px; }
.temp-stat  { font-size:11px; color:#4A6A80; }
.temp-stat strong { color:#C9D1DC; }

/* ── Leader mini-cards ── */
.leader-card {
    background:#0C1520; border:1px solid #1C3050;
    border-radius:10px; padding:14px 14px; height:100%;
}
.lc-ticker { font-size:14px; font-weight:800; color:#7EB8D4; font-family:monospace; }
.lc-name   { font-size:12px; color:#4A6A80; display:block; margin-top:1px; }
.lc-price  { font-size:20px; font-weight:700; margin:8px 0 2px 0; }
.lc-streak { display:inline-block; border-radius:12px; padding:2px 9px; font-size:11px; font-weight:700; margin-top:6px; }
.ls-active { background:#0E2018; color:#52B788; border:1px solid #1E4A32; }
.ls-warn   { background:#180A10; color:#E05C7A; border:1px solid #5A1C28; }
.ls-none   { background:#0F141C; color:#3A5060; border:1px solid #182030; }

/* ── Signal cards ── */
.sig-card { border-radius:10px; padding:14px 16px; margin-bottom:10px; border:1px solid #1C2D3E; background:#0C1520; }
.sig-card.accum  { border-left:3px solid #52B788; }
.sig-card.strong { border-left:3px solid #7EB8D4; }
.sig-card.warn   { border-left:3px solid #E05C7A; }
.sig-ticker { font-size:16px; font-weight:800; color:#7EB8D4; font-family:monospace; }
.sig-name   { font-size:12px; color:#5B7A8E; margin-left:5px; }
.sig-price  { font-size:14px; font-weight:700; color:#C9D1DC; }
.sig-chg-up { color:#52B788; font-weight:600; }
.sig-chg-dn { color:#E05C7A; font-weight:600; }
.sig-chg-fl { color:#5B7A8E; }

/* ── Breadth bar ── */
.hr-dark { border:none; border-top:1px solid #131E28; margin:20px 0; }
.empty-state { text-align:center; padding:30px; color:#3A5060; font-size:13px; border:1px dashed #182030; border-radius:10px; }
.stDataFrame { background:#0C1520 !important; }
div[data-testid="stExpander"] { border:1px solid #1A2C3E !important; border-radius:8px !important; }
div[data-testid="stExpander"] summary { font-size:13px !important; color:#5B7A8E !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _load_all_snapshots() -> list[dict]:
    index = vd.load_index()
    dates = sorted(k for k in index.get("snapshots", {}).keys()
                   if len(k) == 10 and k.replace("-", "").isdigit())
    result = []
    for d in dates:
        try:
            result.append(vd.load_snapshot(d))
        except Exception:
            pass
    return result


@st.cache_data(ttl=120, show_spinner=False)
def _load_branches_for_ticker(ticker: str) -> dict:
    branches_dir = _AI_STOCK.parent / "data" / "branches"
    path = branches_dir / f"{ticker}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@st.cache_data(ttl=300, show_spinner=False)
def _load_market_pulse() -> dict:
    path = _AI_STOCK.parent / "data" / "market_pulse.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@st.cache_data(ttl=120, show_spinner=False)
def _run_golden(snaps_key: str, snaps: list[dict]):
    """Cached golden layer run. snaps_key is a cache discriminator."""
    return golden_run(snaps)


@st.cache_data(ttl=120, show_spinner=False)
def _run_confidence(snaps_key: str, snaps: list[dict]):
    """Cached confidence run."""
    return confidence_run(snaps)


@st.cache_data(ttl=120, show_spinner=False)
def _run_sm_summary(snaps_key: str, snaps: list[dict]):
    return sm_state_summary(snaps)


def _snaps_key(snaps: list[dict]) -> str:
    """Cheap cache key from last date + count."""
    if not snaps:
        return "empty"
    return f"{snaps[-1].get('date','?')}_{len(snaps)}"


def _real_dates() -> list[str]:
    index = vd.load_index()
    return sorted(k for k in index.get("snapshots", {}).keys()
                  if len(k) == 10 and k.replace("-", "").isdigit())


# ─────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _layer_header(num: str, zh: str, en: str, count: int | None = None) -> None:
    badge = f'<span class="layer-count">{count}</span>' if count is not None else ""
    st.markdown(
        f'<div class="layer-header">'
        f'<span class="layer-num">{num}</span>'
        f'<span class="layer-zh">{zh}</span>'
        f'<span class="layer-en">{en}</span>'
        f'{badge}</div>',
        unsafe_allow_html=True,
    )


def _chg_cls(v: float | None) -> str:
    if v is None: return "sig-chg-fl"
    return "sig-chg-up" if v > 0 else ("sig-chg-dn" if v < 0 else "sig-chg-fl")


def _chg_color(v: float | None) -> str:
    if v is None: return "#5B7A8E"
    return "#52B788" if v > 0 else ("#E05C7A" if v < 0 else "#5B7A8E")


def _sign(v) -> str:
    return "+" if isinstance(v, (int, float)) and v > 0 else ""


def _fmt(v, fmt="{:,.0f}", fallback="—") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else fallback


def _plotly_layout(title: str = "", height: int = 280) -> dict:
    return dict(
        title=dict(text=title, font=dict(color="#4A6A80", size=12)),
        paper_bgcolor="#0B0F17", plot_bgcolor="#0C1520",
        font=dict(color="#4A6A80", size=11),
        xaxis=dict(showgrid=False, zeroline=False, color="#2C4050"),
        yaxis=dict(showgrid=True, zeroline=False, color="#2C4050", gridcolor="#131E28"),
        margin=dict(l=40, r=16, t=36, b=36),
        height=height,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def _render_sidebar(snaps: list[dict]) -> str:
    dates_available = _real_dates()
    latest_date = dates_available[-1] if dates_available else "—"
    universe_n  = len(snaps[-1].get("stocks", [])) if snaps else 0

    with st.sidebar:
        st.markdown(
            '<div class="sb-logo">◈ SCD 市場終端</div>'
            '<div class="sb-sub">MARKET INTELLIGENCE v2</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

        st.markdown('<div class="sb-label">📅 快照日期 Snapshot</div>', unsafe_allow_html=True)

        if dates_available:
            if "sb_idx" not in st.session_state:
                st.session_state["sb_idx"] = len(dates_available) - 1
            st.session_state["sb_idx"] = max(0, min(st.session_state["sb_idx"], len(dates_available) - 1))

            cur = st.session_state["sb_idx"]
            c1, c2 = st.columns(2)
            with c1:
                if st.button("◀ 前日", disabled=(cur == 0), use_container_width=True, key="v2_prev"):
                    st.session_state["sb_idx"] = cur - 1
                    st.rerun()
            with c2:
                if st.button("次日 ▶", disabled=(cur == len(dates_available) - 1), use_container_width=True, key="v2_next"):
                    st.session_state["sb_idx"] = cur + 1
                    st.rerun()

            active_date = st.selectbox("", dates_available, index=st.session_state["sb_idx"],
                                       label_visibility="collapsed")
            new_idx = dates_available.index(active_date)
            if new_idx != st.session_state["sb_idx"]:
                st.session_state["sb_idx"] = new_idx
        else:
            active_date = "—"
            st.caption("尚無快照")

        st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

        st.markdown('<div class="sb-label">📊 系統狀態 Status</div>', unsafe_allow_html=True)
        pulse = _load_market_pulse()
        updated = (pulse.get("fetched_at", "") or "")[:16]
        for k, v in [("最新日期", latest_date), ("快照數量", str(len(snaps))),
                     ("宇宙規模", f"{universe_n} 支"),
                     ("脈搏更新", updated[11:] if len(updated) > 11 else updated)]:
            st.markdown(
                f'<div class="sb-row"><span class="sb-key">{k}</span>'
                f'<span class="sb-val">{v}</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

        with st.expander("🔧 開發者工具 Dev Tools", expanded=False):
            if snaps and active_date and active_date != "—":
                snap   = vd.load_snapshot(active_date)
                stocks = snap.get("stocks", [])
                st.markdown(f"**{active_date}** — {len(stocks)} tickers")
                t1, t2, t3 = st.tabs(["Raw", "Audit", "Schema"])
                with t1:
                    st.json({"date": snap.get("date"), "universe_size": snap.get("universe_size"),
                             "market_regime": snap.get("market_regime"),
                             "schema_version": snap.get("schema_version"),
                             "generated_at": snap.get("generated_at")})
                with t2:
                    events = snap.get("audit_log", [])
                    if events:
                        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
                    else:
                        st.info("No audit events.")
                with t3:
                    st.json(snap.get("provenance", {}))
            else:
                st.info("No snapshot data.")

    return active_date if active_date != "—" else (latest_date if latest_date != "—" else "")


# ─────────────────────────────────────────────────────────────────────────────
# PULSE — Market Pulse strip
# ─────────────────────────────────────────────────────────────────────────────

def _render_pulse_strip() -> None:
    pulse = _load_market_pulse()
    if not pulse:
        st.markdown(
            '<div style="background:#141A0E;border:1px solid #2A3A10;border-radius:8px;'
            'padding:10px 16px;margin-bottom:16px;font-size:12px;color:#6A7A4A;">'
            '📡 大盤脈搏尚未取得 — 執行 <code>make fetch-pulse</code></div>',
            unsafe_allow_html=True,
        )
        return

    taiex = pulse.get("taiex", {})
    tx    = pulse.get("tx_futures", {})
    inst  = pulse.get("institutional_futures", {})
    date  = pulse.get("date", "")

    tc   = taiex.get("close");    tch = taiex.get("change"); tpct = taiex.get("change_pct")
    tvol = taiex.get("volume_b_ntd")
    txc  = tx.get("close");       txch = tx.get("change");   basis = tx.get("basis")
    txoi = tx.get("open_interest")
    fii  = inst.get("foreign", {}).get("net_oi")
    it   = inst.get("investment_trust", {}).get("net_oi")
    dlr  = inst.get("dealer", {}).get("net_oi")

    arrow    = "▲" if isinstance(tch, (int,float)) and tch > 0 else ("▼" if isinstance(tch,(int,float)) and tch < 0 else "─")
    basis_lbl = "正價差" if isinstance(basis,(int,float)) and basis>0 else ("逆價差" if isinstance(basis,(int,float)) and basis<0 else "─")

    def cell(lbl, val, sub, color="#C9D1DC"):
        return (f'<div class="pulse-cell">'
                f'<div class="pulse-label">{lbl}</div>'
                f'<div class="pulse-val" style="color:{color};">{val}</div>'
                f'<div class="pulse-sub">{sub}</div></div>')

    cells = ""
    cells += cell("加權指數 TAIEX", _fmt(tc,"{:,.2f}"),
                  f"{arrow} {_sign(tch)}{_fmt(tch,'{:,.2f}')}  ({_sign(tpct)}{_fmt(tpct,'{:.2f}')}%)  成交 {_fmt(tvol,'{:.1f}')}億",
                  _chg_color(tch))
    cells += cell("台指期 TX", _fmt(txc,"{:,.0f}"),
                  f"{_sign(txch)}{_fmt(txch,'{:,.0f}')} 點", _chg_color(txch))
    cells += cell("期現價差 Basis", f"{_sign(basis)}{_fmt(basis,'{:,.1f}')}",
                  basis_lbl, _chg_color(basis))
    cells += cell("台指期未平倉 OI", f"{_fmt(txoi,'{:,}')}口", "—", "#C9D1DC")
    cells += cell("外資期貨淨部位", f"{_sign(fii)}{_fmt(fii,'{:,}')}口", "Foreign futures net OI", _chg_color(fii))
    cells += cell("投信 / 自營", f"{_sign(it)}{_fmt(it,'{:,}')}口",
                  f"自營 {_sign(dlr)}{_fmt(dlr,'{:,}')}口", _chg_color(it))

    st.markdown(
        f'<div style="font-size:10px;color:#2C4A5A;letter-spacing:.07em;margin-bottom:6px;">'
        f'大盤脈搏  MARKET PULSE &nbsp;·&nbsp; {date}</div>'
        f'<div class="pulse-strip">{cells}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# L1 — Market Overview  市場全覽
# ─────────────────────────────────────────────────────────────────────────────

def _render_layer1(snaps: list[dict], cr=None) -> None:
    _layer_header("L1", "市場全覽", "Market Overview")

    if not snaps:
        st.markdown('<div class="empty-state">尚無快照資料 · No snapshot data</div>', unsafe_allow_html=True)
        return

    reg    = regime_shift(snaps)
    latest = snaps[-1]

    # ── Narrative ──────────────────────────────────────────────────────────
    try:
        narrative = _narrative_generate(snaps)
        narr_text = narrative.get("summary_zh") or narrative.get("summary") or ""
        narr_en   = narrative.get("summary_en") or ""
    except Exception:
        narr_text = latest.get("market_regime", {}).get("narrative", "")
        narr_en   = ""

    if narr_text:
        en_block = f'<div style="font-size:13px;color:#3D6070;margin-top:8px;font-style:italic;">{narr_en}</div>' if narr_en else ""
        st.markdown(
            f'<div class="narrative-card">'
            f'<div class="narrative-title">📰 市場敘事  Market Narrative</div>'
            f'<div class="narrative-body">{narr_text}</div>'
            f'{en_block}</div>',
            unsafe_allow_html=True,
        )

    # ── Regime pill ────────────────────────────────────────────────────────
    color   = reg["regime_color"]
    bg_map  = {"#52B788":"rgba(82,183,136,.12)","#7EB8D4":"rgba(126,184,212,.1)",
               "#E05C7A":"rgba(224,92,122,.1)","#D4A84B":"rgba(212,168,75,.1)",
               "#6B8EAA":"rgba(107,142,170,.08)"}
    pill_bg = bg_map.get(color, "rgba(107,142,170,.08)")
    st.markdown(
        f'<div class="regime-pill" style="background:{pill_bg};border-color:{color};color:{color};">'
        f'◈ {reg["regime_label_zh"]}&nbsp;&nbsp;'
        f'<span style="font-size:12px;opacity:.7;font-weight:400;">{reg["regime_label_en"]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if reg.get("transition_detected"):
        st.markdown(
            f'<div style="background:#1A1208;border-left:3px solid #D4A84B;border-radius:6px;'
            f'padding:8px 14px;margin:8px 0 12px 0;font-size:13px;color:#D4A84B;">'
            f'⚡ {reg["transition_note"]}</div>',
            unsafe_allow_html=True,
        )

    b_pct = reg["latest_breadth"] * 100
    c_val = reg["latest_avg_chg"]
    trend_icons = {"rising_fast":"↑↑ 急漲","rising":"↑ 上升",
                   "falling_fast":"↓↓ 急跌","falling":"↓ 下跌","flat":"→ 持平"}
    breadth_color = "#52B788" if b_pct >= 60 else ("#D4A84B" if b_pct >= 30 else "#E05C7A")
    chg_color     = "#52B788" if c_val >= 0 else "#E05C7A"

    # KPIs — add temperature if available
    mt = cr.market_temperature if cr else None
    kpis = [
        ("廣度 Breadth",   f"{b_pct:.1f}%", "主力買超股佔比", breadth_color),
        ("均漲 Avg Δ",     f"{c_val:+.2f}%", "宇宙均漲幅",    chg_color),
        ("廣度趨勢 Trend", trend_icons.get(reg["breadth_trend"], "—"), "近3日走勢", "#7EB8D4"),
        ("快照天數 Days",  str(len(reg["dates"])), "歷史紀錄",  "#5B7A8E"),
    ]
    if mt:
        temp_color = mt.temperature_color
        kpis += [
            ("風險溫度 Temp", f"{mt.temperature:.0%}", mt.temperature_zh, temp_color),
            ("強勢低風險",    str(mt.high_confidence_low_risk) + " 支", "High conf / low risk", "#52B788"),
        ]

    cells = "".join(
        f'<div class="kpi"><div class="kpi-label">{lb}</div>'
        f'<div class="kpi-value" style="color:{vc};">{val}</div>'
        f'<div class="kpi-sub">{sub}</div></div>'
        for lb, val, sub, vc in kpis
    )
    st.markdown(f'<div class="kpi-row">{cells}</div>', unsafe_allow_html=True)

    # ── State distribution bar (from state machine) ────────────────────────
    if cr and mt:
        state_cells = ""
        sm_summary = _run_sm_summary(_snaps_key(snaps), snaps)
        for s in STATE_ORDER:
            n = sm_summary.state_counts.get(s, 0)
            if n == 0:
                continue
            zh   = STATE_ZH[s]
            state_cells += (
                f'<div style="background:#0F1820;border:1px solid #1C2D3E;border-radius:8px;'
                f'padding:6px 12px;font-size:12px;">'
                f'<span style="color:#3A5A6A;">{zh}</span> '
                f'<span style="color:#C9D1DC;font-weight:700;font-family:monospace;">{n}</span>'
                f'</div>'
            )
        if state_cells:
            st.markdown(
                f'<div style="font-size:10px;color:#2C4A5A;letter-spacing:.07em;margin-bottom:6px;">'
                f'狀態分布 STATE DISTRIBUTION</div>'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:20px;">{state_cells}</div>',
                unsafe_allow_html=True,
            )

        # Temperature alerts
        for alert in mt.alerts:
            st.markdown(
                f'<div style="background:#1A1208;border-left:3px solid {mt.temperature_color};'
                f'border-radius:6px;padding:8px 14px;margin:4px 0;font-size:12px;'
                f'color:{mt.temperature_color};">{alert}</div>',
                unsafe_allow_html=True,
            )

    # ── Breadth chart ──────────────────────────────────────────────────────
    if len(reg["dates"]) >= 2:
        col_b, col_c = st.columns(2)
        with col_b:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=reg["dates"], y=[v * 100 for v in reg["breadth_series"]],
                mode="lines+markers", name="廣度%",
                line=dict(color="#7EB8D4", width=2),
                marker=dict(size=5),
                fill="tozeroy", fillcolor="rgba(126,184,212,0.06)",
            ))
            fig.add_hline(y=50, line_dash="dot", line_color="#1E3A4A", line_width=1)
            fig.update_layout(**_plotly_layout("主力廣度 Breadth %", 200))
            fig.update_yaxes(ticksuffix="%", range=[0, 105])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with col_c:
            colors_bar = ["#52B788" if v >= 0 else "#E05C7A" for v in reg["avg_chg_series"]]
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=reg["dates"], y=reg["avg_chg_series"],
                                  marker_color=colors_bar, name="均漲%"))
            fig2.add_hline(y=0, line_color="#1E3A4A", line_width=1)
            fig2.update_layout(**_plotly_layout("宇宙均漲 Avg Δ%", 200))
            fig2.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})


# ─────────────────────────────────────────────────────────────────────────────
# L2 — Golden Layer v2  黃金名單
# ─────────────────────────────────────────────────────────────────────────────

def _gc_html(e: GoldenEntry, latest_stocks: dict) -> str:
    """Build one golden card HTML."""
    tier_cls   = {"prime": "prime", "strong": "strong", "qualified": "qualified"}.get(e.tier, "near-miss")
    tier_icon  = {"prime": "★", "strong": "◆", "qualified": "●"}.get(e.tier, "○")
    tier_color = {"prime": "#F4C842", "strong": "#52B788", "qualified": "#7EB8D4"}.get(e.tier, "#3A5060")
    stock      = latest_stocks.get(e.ticker, {})
    price      = stock.get("current_price")
    chg        = stock.get("change_pct")
    price_str  = f"NT${price:,.2f}" if price else "—"
    chg_str    = f"{chg:+.2f}%" if chg is not None else "—"
    chg_color  = _chg_color(chg)

    # Conviction bar
    conv_pct   = int(e.conviction * 100)
    conv_fill  = f"width:{conv_pct}%;background:{tier_color};"

    # Risk bar
    risk_color = {"low": "#52B788", "medium": "#7EB8D4", "elevated": "#D4A84B", "critical": "#E05C7A"}.get(e.transition_risk, "#4A6A80")
    # risk_score from confidence if available; approximate from transition_risk
    risk_approx = {"low": 10, "medium": 25, "elevated": 50, "critical": 75}.get(e.transition_risk, 0)
    risk_fill   = f"width:{risk_approx}%;background:{risk_color};"

    # Tags
    tags = ""
    tags += f'<span class="tag tag-dim">{e.sm_state_zh}</span>'
    if e.streak >= 1:
        tags += f'<span class="tag tag-green">連買 {e.streak}日</span>'
    if e.net_cumulative > 0:
        tags += f'<span class="tag tag-green">累計 {e.net_cumulative:+,}張</span>'
    if e.velocity_3d is not None:
        cls = "tag-green" if e.velocity_3d > 0 else "tag-red"
        tags += f'<span class="tag {cls}">v{e.velocity_3d:+,.0f}</span>'
    if e.sponsorship_score >= 0.5:
        tags += f'<span class="tag tag-blue">贊助 {e.sponsorship_score:.2f}</span>'
    if e.is_tier_a:
        tags += '<span class="tag tag-gold">Tier A</span>'
    risk_map = {"low":"", "medium":"⚬ 中風險", "elevated":"⚠ 風險偏高", "critical":"⚠ 高風險"}
    r_label = risk_map.get(e.transition_risk, "")
    if r_label:
        tags += f'<span class="tag tag-amber">{r_label}</span>'

    return (
        f'<div class="gc {tier_cls}">'
        f'<div class="gc-top">'
        f'<div><span style="color:{tier_color};font-size:14px;margin-right:4px;">{tier_icon}</span>'
        f'<span class="gc-ticker">{e.ticker}</span>'
        f'<span class="gc-name">{e.name}</span></div>'
        f'<div style="text-align:right;">'
        f'<div style="font-size:14px;font-weight:700;color:{chg_color};">{price_str}</div>'
        f'<div style="font-size:11px;color:{chg_color};">{chg_str}</div>'
        f'</div></div>'
        f'<div class="gc-bars">'
        f'<div class="gc-bar-row"><span class="gc-bar-lbl">信心</span>'
        f'<div class="gc-bar-bg"><div class="gc-bar-fill" style="{conv_fill}"></div></div>'
        f'<span class="gc-bar-val" style="color:{tier_color};">{e.conviction:.2f}</span></div>'
        f'<div class="gc-bar-row"><span class="gc-bar-lbl">風險</span>'
        f'<div class="gc-bar-bg"><div class="gc-bar-fill" style="{risk_fill}"></div></div>'
        f'<span class="gc-bar-val" style="color:{risk_color};">{e.transition_risk[:3]}</span></div>'
        f'</div>'
        f'<div class="sig-tags">{tags}</div>'
        f'</div>'
    )


def _render_layer2(snaps: list[dict]) -> None:
    key = _snaps_key(snaps)
    gr  = _run_golden(key, snaps)

    _layer_header("L2", "黃金名單 v2", "Golden Layer",
                  count=gr.total)

    if not snaps:
        st.markdown('<div class="empty-state">尚無快照資料</div>', unsafe_allow_html=True)
        return

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    # ── 5 Tech Leaders ────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:11px;color:#3D6480;letter-spacing:.08em;'
        'text-transform:uppercase;margin-bottom:10px;">'
        '⬡ 龍頭五虎  CORE TECH LEADERS</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    for i, ticker in enumerate(RADAR_TICKERS):
        stock  = latest_stocks.get(ticker, {})
        branch = _load_branches_for_ticker(ticker)
        ctx    = full_ticker_context(ticker, snaps)
        acc    = ctx.get("accumulation", {})
        price  = stock.get("current_price")
        chg    = stock.get("change_pct")
        cost   = stock.get("main_force_cost") or branch.get("avgBuyCost")
        streak = acc.get("streak", 0)
        name   = TIER_A.get(ticker, {}).get("name", ticker)
        price_str = f"NT${price:,.2f}" if price else "—"
        chg_str   = f"{chg:+.2f}%" if chg is not None else "—"
        pc        = _chg_color(chg)

        # Check if in golden
        gold_entry = next((e for e in gr.all_golden if e.ticker == ticker), None)
        gold_badge = ""
        if gold_entry:
            tier_color = {"prime": "#F4C842", "strong": "#52B788", "qualified": "#7EB8D4"}.get(gold_entry.tier, "#4A6A80")
            tier_icon  = {"prime": "★", "strong": "◆", "qualified": "●"}.get(gold_entry.tier, "")
            gold_badge = f'<div style="font-size:11px;color:{tier_color};margin-top:4px;">{tier_icon} Conv {gold_entry.conviction:.2f}</div>'

        if streak >= 3:  sc, sl = "ls-active", f"▲ {streak}日連買"
        elif streak >= 1: sc, sl = "ls-active", f"▲ {streak}日"
        elif (stock.get("main_force_buy") or 0) < 0: sc, sl = "ls-warn", "▼ 賣超"
        else: sc, sl = "ls-none", "─"

        with cols[i]:
            st.markdown(
                f'<div class="leader-card">'
                f'<span class="lc-ticker">{ticker}</span>'
                f'<span class="lc-name">{name}</span>'
                f'<div class="lc-price" style="color:{pc};">{price_str}</div>'
                f'<div style="font-size:12px;color:{pc};">{chg_str}</div>'
                + (f'<div style="font-size:11px;color:#3D5A6E;margin-top:4px;">成本 NT${cost:,.2f}</div>' if cost else "")
                + f'{gold_badge}'
                + f'<span class="lc-streak {sc}">{sl}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<hr class="hr-dark">', unsafe_allow_html=True)

    # ── Golden tabs ────────────────────────────────────────────────────────
    tab_prime, tab_strong, tab_qual, tab_near = st.tabs([
        f"★ 頂級黃金 Prime  ({len(gr.prime)})",
        f"◆ 強勢確認 Strong ({len(gr.strong)})",
        f"● 入選合格 Qualified ({len(gr.qualified)})",
        f"○ 近乎入選 Near-miss ({len(gr.near_miss)})",
    ])

    def _render_gc_grid(entries: list[GoldenEntry]) -> None:
        if not entries:
            st.markdown('<div class="empty-state">本層目前無標的</div>', unsafe_allow_html=True)
            return
        # Build grid in columns
        cols = st.columns(2)
        for idx, e in enumerate(entries):
            with cols[idx % 2]:
                st.markdown(_gc_html(e, latest_stocks), unsafe_allow_html=True)

    with tab_prime:
        _render_gc_grid(gr.prime)
    with tab_strong:
        _render_gc_grid(gr.strong)
    with tab_qual:
        _render_gc_grid(gr.qualified)
    with tab_near:
        if not gr.near_miss:
            st.markdown('<div class="empty-state">目前無近乎入選標的</div>', unsafe_allow_html=True)
        else:
            st.caption("以下標的通過 4/5 門檻，差一個條件就能入選黃金名單")
            cols = st.columns(2)
            for idx, e in enumerate(gr.near_miss):
                with cols[idx % 2]:
                    st.markdown(_gc_html(e, latest_stocks), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# L3 — Confidence & Risk Profile  信心 & 風險
# ─────────────────────────────────────────────────────────────────────────────

def _render_conf_row(p: ConfidenceProfile, latest_stocks: dict) -> str:
    stock = latest_stocks.get(p.ticker, {})
    price = stock.get("current_price")
    chg   = stock.get("change_pct")
    price_str = f"NT${price:,.2f}" if price else "—"
    chg_str   = f"{chg:+.2f}%" if chg is not None else "—"
    chg_c     = _chg_color(chg)

    pc = p.profile_color
    vel_str = f"v{p.velocity_3d:+,.0f}" if p.velocity_3d is not None else "—"
    tier_a  = '<span class="tag tag-gold" style="font-size:10px;padding:1px 6px;">A</span>' if p.is_tier_a else ""
    gold_tag = f'<span class="tag tag-gold" style="font-size:10px;padding:1px 6px;">★{p.golden_conviction:.2f}</span>' if p.in_golden else ""

    return (
        f'<div class="gc" style="border-left:3px solid {pc};margin-bottom:8px;">'
        f'<div class="gc-top">'
        f'<div><span class="gc-ticker">{p.ticker}</span>'
        f'<span class="gc-name">{p.name}</span></div>'
        f'<div style="text-align:right;font-size:12px;color:{chg_c};">{price_str}<br>{chg_str}</div>'
        f'</div>'
        f'<div class="gc-bars">'
        f'<div class="gc-bar-row"><span class="gc-bar-lbl">信心</span>'
        f'<div class="gc-bar-bg"><div class="gc-bar-fill" style="width:{int(p.confidence*100)}%;background:#52B788;"></div></div>'
        f'<span class="gc-bar-val" style="color:#52B788;">{p.confidence:.2f}</span></div>'
        f'<div class="gc-bar-row"><span class="gc-bar-lbl">風險</span>'
        f'<div class="gc-bar-bg"><div class="gc-bar-fill" style="width:{int(p.risk_score*100)}%;background:{p.risk_color};"></div></div>'
        f'<span class="gc-bar-val" style="color:{p.risk_color};">{p.risk_score:.2f}</span></div>'
        f'</div>'
        f'<div class="sig-tags">'
        f'<span class="tag tag-dim">{p.sm_state_zh}</span>'
        f'<span class="tag tag-dim">{p.profile_zh}</span>'
        f'<span class="tag tag-green">連買{p.streak}日</span>'
        f'<span class="tag tag-blue">贊助{p.sponsorship_score:.2f}</span>'
        f'<span class="tag tag-dim">{vel_str}</span>'
        f'{tier_a}{gold_tag}'
        f'</div>'
        f'</div>'
    )


def _render_layer3(snaps: list[dict]) -> None:
    key = _snaps_key(snaps)
    cr  = _run_confidence(key, snaps)
    mt  = cr.market_temperature

    _layer_header("L3", "信心 & 風險", "Confidence & Risk Profile",
                  count=mt.total_tracked)

    if not snaps:
        st.markdown('<div class="empty-state">尚無快照資料</div>', unsafe_allow_html=True)
        return

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    # ── Temperature gauge ─────────────────────────────────────────────────
    bar_pct  = int(mt.temperature * 100)
    bar_fill = f"width:{bar_pct}%;background:{mt.temperature_color};"
    st.markdown(
        f'<div class="temp-gauge">'
        f'<div class="temp-title">🌡 市場風險溫度  Market Risk Temperature</div>'
        f'<div style="display:flex;align-items:baseline;gap:12px;">'
        f'<span style="font-size:32px;font-weight:800;color:{mt.temperature_color};">{mt.temperature:.0%}</span>'
        f'<span style="font-size:16px;font-weight:700;color:{mt.temperature_color};">{mt.temperature_zh}</span>'
        f'<span style="font-size:12px;color:#4A6A80;">/ {mt.temperature_level.upper()}</span>'
        f'</div>'
        f'<div class="temp-bar-bg"><div class="temp-bar-fill" style="{bar_fill}"></div></div>'
        f'<div class="temp-stats">'
        f'<span class="temp-stat">高風險比例 <strong style="color:{mt.temperature_color};">{mt.elevated_risk_ratio:.0%}</strong></span>'
        f'<span class="temp-stat">出貨比例 <strong style="color:#D4A84B;">{mt.distributing_ratio:.0%}</strong></span>'
        f'<span class="temp-stat">廣度訊號 <strong style="color:#7EB8D4;">{"↑改善" if mt.breadth_signal >= 0.7 else ("→穩定" if mt.breadth_signal >= 0.3 else "↓惡化")}</strong></span>'
        f'<span class="temp-stat">強勢低風險 <strong style="color:#52B788;">{mt.high_confidence_low_risk} 支</strong></span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    for alert in mt.alerts:
        st.markdown(
            f'<div style="background:#1A1208;border-left:3px solid {mt.temperature_color};'
            f'border-radius:6px;padding:8px 14px;margin:4px 0 8px 0;font-size:12px;'
            f'color:{mt.temperature_color};">{alert}</div>',
            unsafe_allow_html=True,
        )

    # ── 2D Scatter: confidence vs risk ────────────────────────────────────
    if cr.profiles:
        profs = list(cr.profiles.values())
        x_risk = [p.risk_score for p in profs]
        y_conf = [p.confidence for p in profs]
        labels = [f"{p.ticker} {p.name}<br>C:{p.confidence:.2f} R:{p.risk_score:.2f}<br>{p.profile_zh}" for p in profs]
        colors = [p.profile_color for p in profs]
        sizes  = [12 + p.golden_conviction * 10 for p in profs]  # bigger = in golden

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_risk, y=y_conf,
            mode="markers+text",
            marker=dict(size=sizes, color=colors, opacity=0.85,
                        line=dict(width=0.5, color="#0B0F17")),
            text=[p.ticker for p in profs],
            textposition="top center",
            textfont=dict(size=9, color="#4A7A9A"),
            hovertext=labels,
            hoverinfo="text",
            name="",
        ))
        # Quadrant lines
        fig.add_vline(x=0.30, line_dash="dot", line_color="#1E3A4A", line_width=1)
        fig.add_hline(y=0.55, line_dash="dot", line_color="#1E3A4A", line_width=1)
        fig.add_annotation(x=0.05, y=0.95, text="理想區", font=dict(size=10, color="#52B788"),
                           showarrow=False, xanchor="left")
        fig.add_annotation(x=0.65, y=0.95, text="強勢但有警示", font=dict(size=10, color="#D4A84B"),
                           showarrow=False, xanchor="left")
        fig.add_annotation(x=0.65, y=0.20, text="高風險低信心", font=dict(size=10, color="#E05C7A"),
                           showarrow=False, xanchor="left")
        layout = _plotly_layout("信心 × 風險 2D 分布  Confidence × Risk", 340)
        layout["xaxis"]["title"] = "風險分 Risk Score"
        layout["yaxis"]["title"] = "信心度 Confidence"
        layout["xaxis"]["range"] = [-0.02, 1.02]
        layout["yaxis"]["range"] = [-0.02, 1.08]
        fig.update_layout(**layout)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Profile groups in tabs ─────────────────────────────────────────────
    tab_ideal, tab_watch, tab_det = st.tabs([
        f"✓ 理想 Ideal  ({len(cr.ideal)})",
        f"⚠ 強勢警示 Watch ({len(cr.watch)})",
        f"↘ 惡化中 Deteriorating ({len(cr.deteriorating)})",
    ])

    def _render_cr_grid(profiles: list[ConfidenceProfile]) -> None:
        if not profiles:
            st.markdown('<div class="empty-state">本組目前無標的</div>', unsafe_allow_html=True)
            return
        cols = st.columns(2)
        for idx, p in enumerate(profiles):
            with cols[idx % 2]:
                st.markdown(_render_conf_row(p, latest_stocks), unsafe_allow_html=True)

    with tab_ideal:
        _render_cr_grid(cr.ideal)
    with tab_watch:
        _render_cr_grid(cr.watch)
    with tab_det:
        _render_cr_grid(cr.deteriorating)


# ─────────────────────────────────────────────────────────────────────────────
# L4 — Temporal Visualization  時序視圖
# ─────────────────────────────────────────────────────────────────────────────

def _render_layer4(snaps: list[dict]) -> None:
    _layer_header("L4", "時序視圖", "Temporal Visualization")

    if len(snaps) < 2:
        st.markdown('<div class="empty-state">需要至少 2 個快照才能顯示時序圖</div>', unsafe_allow_html=True)
        return

    tab_streak, tab_heat, tab_breadth, tab_flow = st.tabs([
        "連買時序 Streak Timeline",
        "持續熱圖 Persistence Heatmap",
        "廣度演化 Breadth Evolution",
        "資金流向 Capital Flow",
    ])

    with tab_streak:
        _max = max(3, min(len(snaps), 15))
        _def = max(3, min(len(snaps), 10))
        lookback = st.slider("觀察天數 Days", 3, _max, _def, key="v2_lb") if len(snaps) >= 3 else 3
        recent_snaps = snaps[-lookback:]
        recent_dates = [s.get("date", "") for s in recent_snaps]

        active_tickers: set[str] = set()
        for snap in recent_snaps:
            for s in snap.get("stocks", []):
                active_tickers.add(s.get("ticker", ""))
        active_tickers.discard("")

        if not active_tickers:
            st.markdown('<div class="empty-state">近期無資料</div>', unsafe_allow_html=True)
        else:
            snap_lookup = {s.get("date", ""): {st2["ticker"]: st2 for st2 in s.get("stocks", [])} for s in recent_snaps}
            rows = []
            for ticker in sorted(active_tickers):
                row = {"標的": _short(ticker), "代號": ticker}
                for d in recent_dates:
                    stk = snap_lookup.get(d, {}).get(ticker, {})
                    mfb = stk.get("main_force_buy") or 0
                    row[d[-5:]] = mfb
                rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                date_cols = [c for c in df.columns if c not in ("標的", "代號")]
                st.dataframe(
                    df.style.background_gradient(subset=date_cols, cmap="RdYlGn", axis=None),
                    use_container_width=True, hide_index=True,
                )

    with tab_heat:
        all_t: set[str] = set()
        for snap in snaps:
            for s in snap.get("stocks", []):
                all_t.add(s.get("ticker", ""))
        all_t.discard("")

        heat_data = []
        for ticker in sorted(all_t):
            ctx = full_ticker_context(ticker, snaps)
            sp  = ctx["sponsorship"]
            acc = ctx["accumulation"]
            heat_data.append({
                "標的": _short(ticker), "代號": ticker,
                "持續分 Score": round(sp.get("persistence_score", 0) or 0, 2),
                "贊助天數 Days": sp.get("days_with_branches", 0) or 0,
                "連買天數 Streak": acc.get("streak", 0),
                "累計張數 Net": acc.get("net_cumulative") or 0,
            })
        heat_data.sort(key=lambda x: (-x["持續分 Score"], -x["連買天數 Streak"]))
        if heat_data:
            df2 = pd.DataFrame(heat_data[:30])
            st.dataframe(
                df2.style.background_gradient(subset=["持續分 Score", "連買天數 Streak"], cmap="Blues", axis=0),
                use_container_width=True, hide_index=True,
            )

    with tab_breadth:
        reg = regime_shift(snaps)
        if len(reg["dates"]) >= 2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=reg["dates"], y=[v * 100 for v in reg["breadth_series"]],
                mode="lines+markers", name="廣度%",
                line=dict(color="#7EB8D4", width=2),
                marker=dict(size=6, color="#7EB8D4"),
                fill="tozeroy", fillcolor="rgba(126,184,212,0.05)",
            ))
            fig.add_trace(go.Scatter(
                x=reg["dates"], y=reg["avg_chg_series"],
                mode="lines+markers", name="均漲% (右)",
                line=dict(color="#D4A84B", width=2, dash="dot"),
                marker=dict(size=5), yaxis="y2",
            ))
            fig.add_hline(y=50, line_dash="dot", line_color="#1E3A4A", line_width=1)
            fig.update_layout(
                **_plotly_layout("廣度 + 均漲 Breadth & Avg Change", 320),
                yaxis2=dict(overlaying="y", side="right", showgrid=False,
                            ticksuffix="%", color="#4A6A80"),
            )
            fig.update_yaxes(ticksuffix="%", range=[0, 105])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with tab_flow:
        rot = leadership_rotation(snaps)
        sector_flow = rot.get("sector_flow", {})
        if not sector_flow:
            st.markdown('<div class="empty-state">無資金輪動資料</div>', unsafe_allow_html=True)
        else:
            sectors_sorted = sorted(sector_flow.items(), key=lambda x: -(x[1] or 0))
            labels = [s[0] for s in sectors_sorted]
            vals   = [s[1] or 0 for s in sectors_sorted]
            colors_flow = ["#52B788" if v >= 0 else "#E05C7A" for v in vals]
            fig4 = go.Figure()
            fig4.add_trace(go.Bar(x=labels, y=vals, marker_color=colors_flow, name="淨主力買超"))
            fig4.add_hline(y=0, line_color="#1E3A4A", line_width=1)
            fig4.update_layout(**_plotly_layout("板塊資金流向 Sector Capital Flow", 280))
            fig4.update_yaxes(ticksuffix="張")
            st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})

            top_in  = rot.get("top_inflow", [])
            top_out = rot.get("top_outflow", [])
            if top_in or top_out:
                ci, co = st.columns(2)
                with ci:
                    st.markdown('<div style="font-size:11px;color:#2A5A3A;letter-spacing:.06em;margin-bottom:6px;">▲ 資金流入 Inflow</div>', unsafe_allow_html=True)
                    for item in top_in[:5]:
                        tk = item.get("ticker","")
                        v  = item.get("net_mfb", 0) or 0
                        st.markdown(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #0F1C28;"><span style="color:#7EB8D4;font-family:monospace;">{_short(tk)}</span><span style="color:#52B788;font-weight:700;">{v:+,}張</span></div>', unsafe_allow_html=True)
                with co:
                    st.markdown('<div style="font-size:11px;color:#5A2A3A;letter-spacing:.06em;margin-bottom:6px;">▼ 資金流出 Outflow</div>', unsafe_allow_html=True)
                    for item in top_out[:5]:
                        tk = item.get("ticker","")
                        v  = item.get("net_mfb", 0) or 0
                        st.markdown(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #0F1C28;"><span style="color:#7EB8D4;font-family:monospace;">{_short(tk)}</span><span style="color:#E05C7A;font-weight:700;">{v:+,}張</span></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# L5 — Deep Metrics  深層指標 (collapsed)
# ─────────────────────────────────────────────────────────────────────────────

def _render_layer5(snaps: list[dict]) -> None:
    with st.expander("L5 · 深層指標 Deep Metrics", expanded=False):
        if not snaps:
            st.info("尚無資料")
            return

        reg = regime_shift(snaps)

        st.markdown("**歷史體制紀錄 Regime History**")
        rows = []
        for i, d in enumerate(reg["dates"]):
            b = reg["breadth_series"][i] * 100
            c = reg["avg_chg_series"][i]
            v = reg["vol_series"][i] if reg.get("vol_series") and i < len(reg["vol_series"]) else None
            rows.append({"日期": d, "廣度%": f"{b:.1f}%", "均漲%": f"{c:+.2f}%",
                         "量能指數": f"{v:.2f}×" if v is not None else "—"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("<br>**全量指標 Full Ticker Metrics**")
        all_t: set[str] = set()
        for snap in snaps:
            for s in snap.get("stocks", []):
                all_t.add(s.get("ticker", ""))
        all_t.discard("")

        metric_rows = []
        latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
        key = _snaps_key(snaps)
        cr  = _run_confidence(key, snaps)
        gr  = _run_golden(key, snaps)
        golden_set = {e.ticker for e in gr.all_golden}

        for tk in sorted(all_t):
            ctx = full_ticker_context(tk, snaps)
            acc = ctx["accumulation"]
            sp  = ctx["sponsorship"]
            fb  = ctx["failed_breakout"]
            stk = latest_stocks.get(tk, {})
            prof = cr.profiles.get(tk)
            metric_rows.append({
                "代號": tk,
                "名稱": _short(tk),
                "價格": stk.get("current_price"),
                "漲跌%": stk.get("change_pct"),
                "連買天數": acc.get("streak", 0),
                "累計張數": acc.get("net_cumulative") or 0,
                "速度/日": acc.get("velocity_3d"),
                "持續分": round(sp.get("persistence_score", 0) or 0, 3),
                "假突破": "⚠" if fb.get("failed_breakout_detected") else "─",
                "信心度": round(prof.confidence, 2) if prof else "—",
                "風險分": round(prof.risk_score, 2) if prof else "—",
                "側寫": prof.profile_zh if prof else "—",
                "黃金": "★" if tk in golden_set else "─",
            })
        if metric_rows:
            st.dataframe(pd.DataFrame(metric_rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# L6 — Engineering Diagnostics  工程診斷 (hidden)
# ─────────────────────────────────────────────────────────────────────────────

def _render_layer6(snaps: list[dict], active_date: str) -> None:
    with st.expander("L6 · 工程診斷 Engineering Diagnostics", expanded=False):
        st.caption("Replay integrity · WORM verification · Provenance · Audit logs")
        if not snaps or not active_date:
            st.info("No snapshot selected.")
            return

        snap = vd.load_snapshot(active_date)
        t1, t2, t3, t4 = st.tabs(["Provenance", "Replay Hash", "Audit Log", "Schema"])

        with t1:
            st.json(snap.get("provenance", {}))
        with t2:
            prov = snap.get("provenance", {})
            replay_hash = prov.get("replay_hash") or prov.get("content_hash") or "—"
            st.code(replay_hash, language=None)
            st.caption("WORM integrity — this hash must match replay output")
        with t3:
            events = snap.get("audit_log", [])
            if events:
                st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
            else:
                st.info("No audit events for this snapshot.")
        with t4:
            st.json({k: snap.get(k) for k in
                     ("date", "schema_version", "universe_size", "market_regime", "generated_at")})


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    global _NAME_MAP
    snaps    = _load_all_snapshots()
    _NAME_MAP = build_name_map(snaps)

    active_date   = _render_sidebar(snaps)
    snaps_to_date = [s for s in snaps if s.get("date", "") <= active_date] if active_date else snaps

    # Pre-compute confidence result (shared between L1 and L3)
    cr = None
    if snaps_to_date:
        try:
            cr = _run_confidence(_snaps_key(snaps_to_date), snaps_to_date)
        except Exception:
            cr = None

    st.markdown(
        '<div style="font-size:20px;font-weight:800;color:#E0E8F0;letter-spacing:-0.02em;margin-bottom:4px;">'
        '◈ SCD 市場情報終端 '
        '<span style="color:#3D6480;font-size:13px;font-weight:400;">Market Intelligence Terminal v2</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border:none;border-top:1px solid #131E28;margin:8px 0 16px 0;">', unsafe_allow_html=True)

    _render_pulse_strip()

    _render_layer1(snaps_to_date, cr=cr)
    st.markdown('<hr style="border:none;border-top:1px solid #0F1820;margin:24px 0;">', unsafe_allow_html=True)

    _render_layer2(snaps_to_date)
    st.markdown('<hr style="border:none;border-top:1px solid #0F1820;margin:24px 0;">', unsafe_allow_html=True)

    _render_layer3(snaps_to_date)
    st.markdown('<hr style="border:none;border-top:1px solid #0F1820;margin:24px 0;">', unsafe_allow_html=True)

    _render_layer4(snaps_to_date)
    st.markdown('<hr style="border:none;border-top:1px solid #0F1820;margin:24px 0;">', unsafe_allow_html=True)

    _render_layer5(snaps_to_date)
    _render_layer6(snaps_to_date, active_date)


main()
