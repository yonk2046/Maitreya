"""SCD Engine — Market Intelligence Cockpit  P3c
雙語市場行為智慧終端

Seven observation panels:
  1  市場體制    Market Regime
  2  雷達觀察    Watchlist Radar
  3  轉強訊號    Strengthening Signals
  4  假突破警報  Failed Breakout Warnings
  5  持續吸籌    Persistent Accumulation
  6  資金輪動    Leadership Rotation
  7  時序演化    Temporal Chains

Developer / Audit mode is collapsed at the bottom.

Run:  make cockpit   (from Ai stock/)
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from viewer import data as vd
from viewer import intelligence as vi
from core.narrative_engine import generate as _narrative_generate
from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
    regime_shift,
    failed_breakout_memory,
    leadership_rotation,
    full_ticker_context,
    weakening_profile,
)
from core.watchlists import TIER_A, SECTOR_GROUPS, tier_a_tickers, stock_group, build_name_map, RADAR_TICKERS
from core import golden as _golden_mod
from core import confidence as _conf_mod
from core import state_machine as _sm_mod
from core import resonance as _resonance_mod
from core import chip_score as _chip_mod
from core import holdings as _holdings_mod
from core.distribution import load_for_date as _dist_load
from core.intelligence_delta import (
    load_for_date as _intel_load,
    DailyIntelligenceReport,
    DailyEvent,
    BiggestChange,
    WatchEntry,
    SEV_CRITICAL, SEV_ALERT, SEV_WATCH, SEV_INFO,
)

# Module-level name map; populated once per cockpit session in main().
# All render functions call _name(ticker) — never raw ticker strings in UI.
_NAME_MAP: dict[str, str] = {}


def _name(ticker: str) -> str:
    """Return display label: '2344 華邦電'.  Falls back to ticker if unknown."""
    n = _NAME_MAP.get(ticker) or TIER_A.get(ticker, {}).get("name", "")
    return f"{ticker} {n}" if n and n != ticker else ticker


def _short_name(ticker: str) -> str:
    """Return just the company name part, or ticker if unknown."""
    return _NAME_MAP.get(ticker) or TIER_A.get(ticker, {}).get("name", ticker)

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Maitreya · 市場情報終端",
    page_icon="🪷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS — Bloomberg + Notion + Trading Desk
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0D1117 !important;
    color: #CDD5E0 !important;
}
[data-testid="stSidebar"] { background-color: #13191F !important; }
[data-testid="stHeader"]  { background-color: #0D1117 !important; }
.main .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1440px; }
html, body, p, div, span, td, th { font-size: 15px !important; }
h1, h2, h3, h4 { font-family: 'SF Pro Display','Helvetica Neue',sans-serif !important; letter-spacing: -0.01em; }
[data-testid="stTabs"] button { font-size: 14px !important; font-weight: 600; color: #8B949E !important; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #7EB8D4 !important; border-bottom-color: #7EB8D4 !important; }

/* ── Regime banner ── */
.regime-banner {
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 20px;
    border-left-width: 5px;
    border-left-style: solid;
}
.regime-label-zh { font-size: 32px !important; font-weight: 800; line-height: 1.2; margin-bottom: 4px; }
.regime-label-en { font-size: 14px !important; font-style: italic; opacity: 0.7; margin-bottom: 16px; }
.regime-transition { background: #2A1E0E; border: 1px solid #6A5020; border-radius: 8px; padding: 10px 14px; font-size: 13px !important; color: #D4A84B; margin-top: 12px; }

/* ── Metric strip ── */
.metric-strip { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
.metric-cell { background: #161B26; border: 1px solid #1F2D3D; border-radius: 8px; padding: 12px 16px; min-width: 110px; flex: 1; }
.metric-label { font-size: 11px !important; color: #6B8EAA; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 5px; }
.metric-value { font-size: 24px !important; font-weight: 700; color: #E6EDF3; line-height: 1.2; }
.metric-sub { font-size: 12px !important; color: #6B8EAA; margin-top: 3px; }
.val-green { color: #52B788 !important; } .val-cyan { color: #7EB8D4 !important; }
.val-amber { color: #D4A84B !important; } .val-red { color: #E05C7A !important; }
.val-dim   { color: #6B8EAA !important; }

/* ── Section header ── */
.section-header { display: flex; align-items: center; gap: 10px; margin: 28px 0 14px 0; border-bottom: 1px solid #1F2D3D; padding-bottom: 10px; }
.section-icon { font-size: 18px; opacity: 0.7; }
.section-title-zh { font-size: 18px !important; font-weight: 700; color: #CDD5E0; }
.section-title-en { font-size: 13px !important; color: #6B8EAA; font-style: italic; }
.section-badge { margin-left: auto; background: #161B26; border: 1px solid #253A52; border-radius: 20px; padding: 2px 12px; font-size: 12px !important; color: #7EB8D4; }

/* ── Stock cards ── */
.stock-card { background: #111820; border: 1px solid #1F2D3D; border-radius: 10px; padding: 16px 18px; margin-bottom: 10px; }
.stock-card:hover { border-color: #3A5570; }
.stock-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.stock-ticker { font-size: 18px !important; font-weight: 800; color: #7EB8D4; font-family: 'SF Mono','Fira Code',monospace; }
.stock-name   { font-size: 14px !important; color: #8B949E; margin-left: 7px; }
.stock-price  { font-size: 17px !important; font-weight: 700; color: #E6EDF3; }
.chg-up   { color: #52B788 !important; font-weight: 600; }
.chg-down { color: #E05C7A !important; font-weight: 600; }
.chg-flat { color: #8B949E !important; }

/* ── Signal tags ── */
.signal-tag { display: inline-block; background: #161B26; border: 1px solid #1F2D3D; border-radius: 5px; padding: 3px 9px; font-size: 12px !important; color: #7EB8D4; margin: 2px 4px 2px 0; }
.signal-tag.fii  { border-color: #2E6B4A; color: #52B788;  background: #0F1E17; }
.signal-tag.warn { border-color: #7A3A18; color: #D4A84B;  background: #1E1408; }
.signal-tag.mf   { border-color: #4A3880; color: #9E8AC8;  background: #160F22; }
.signal-tag.cost { border-color: #2A4F6A; color: #7EB8D4;  background: #0F1820; }
.signal-tag.red  { border-color: #7A2A38; color: #E05C7A;  background: #1A0810; }

/* ── Timeline chain cells ── */
.chain-row { display: flex; gap: 6px; align-items: center; padding: 6px 0; border-bottom: 1px solid #1A2030; }
.chain-date { font-size: 12px !important; color: #6B8EAA; width: 78px; flex-shrink: 0; font-family: monospace; }
.chain-price { font-size: 13px !important; color: #CDD5E0; width: 60px; flex-shrink: 0; }
.chain-chg  { font-size: 13px !important; width: 56px; flex-shrink: 0; font-weight: 600; }
.chain-mf   { font-size: 12px !important; color: #9E8AC8; width: 90px; flex-shrink: 0; }
.chain-dot  { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

/* ── Tier A radar cards ── */
.radar-card { background: #111820; border: 1px solid #253A52; border-radius: 10px; padding: 14px 16px; margin-bottom: 8px; height: 100%; }
.radar-ticker { font-size: 15px !important; font-weight: 800; color: #7EB8D4; font-family: monospace; }
.radar-name   { font-size: 13px !important; color: #8B949E; margin-left: 5px; }
.radar-group  { font-size: 11px !important; color: #4A6A8A; margin-top: 2px; text-transform: uppercase; }
.radar-cost   { font-size: 20px !important; font-weight: 700; color: #D4A84B; margin: 8px 0 2px 0; }
.radar-mfbuy  { font-size: 13px !important; color: #9E8AC8; }
.radar-streak { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px !important; font-weight: 700; margin-top: 6px; }
.streak-active { background: #142A1E; color: #52B788; border: 1px solid #2E6B4A; }
.streak-none   { background: #1C2028; color: #4A5A6A; border: 1px solid #2D3748; }
.streak-warn   { background: #2A1218; color: #E05C7A; border: 1px solid #5A1A28; }

/* ── Data gap notice ── */
.data-gap-notice { background: #1E1408; border-left: 4px solid #D4A84B; border-radius: 6px; padding: 10px 14px; font-size: 13px !important; color: #D4A84B; margin: 12px 0; }

/* ── Rotation bars ── */
.rot-bar-wrap { display: flex; align-items: center; gap: 10px; margin: 5px 0; }
.rot-sector-label { font-size: 13px !important; color: #CDD5E0; width: 90px; flex-shrink: 0; }
.rot-bar-bg { flex: 1; background: #161B26; border-radius: 4px; height: 16px; position: relative; overflow: hidden; }
.rot-bar-fill { height: 100%; border-radius: 4px; }
.rot-bar-val { font-size: 12px !important; color: #8B949E; width: 80px; flex-shrink: 0; text-align: right; }

/* ── Golden Layer cards ── */
.golden-card { background: #111820; border: 1px solid #1F2D3D; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; border-left-width: 4px; border-left-style: solid; }
.golden-card:hover { filter: brightness(1.07); }
.tier-prime     { border-left-color: #D4A84B !important; }
.tier-strong    { border-left-color: #7EB8D4 !important; }
.tier-qualified { border-left-color: #52B788 !important; }
.tier-badge-prime     { display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:800;background:#1F1508;color:#D4A84B;border:1px solid #6A5020;letter-spacing:.04em; }
.tier-badge-strong    { display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:800;background:#0A1520;color:#7EB8D4;border:1px solid #253A52;letter-spacing:.04em; }
.tier-badge-qualified { display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:800;background:#0A1F12;color:#52B788;border:1px solid #2E6B4A;letter-spacing:.04em; }
.conv-bar-wrap { display:flex;align-items:center;gap:8px;margin:8px 0 6px 0; }
.conv-bar-bg   { flex:1;background:#1A2030;border-radius:4px;height:7px;overflow:hidden; }
.conv-bar-fill { height:100%;border-radius:4px; }
.conv-score    { font-size:12px;color:#8B949E;width:36px;text-align:right;flex-shrink:0; }
.gate-row      { display:flex;flex-wrap:wrap;gap:5px;margin-top:4px; }
.gate-pass     { font-size:11px;color:#52B788;background:#0A1F12;border:1px solid #2E6B4A;border-radius:5px;padding:1px 7px; }
.gate-fail     { font-size:11px;color:#E05C7A;background:#1A0810;border:1px solid #5A1A28;border-radius:5px;padding:1px 7px; }
/* ── Confidence / Risk cards ── */
.conf-card  { background:#111820;border:1px solid #1F2D3D;border-radius:10px;padding:14px 18px;margin-bottom:10px; }
.conf-2d-bar-wrap { display:flex;flex-direction:column;gap:4px;margin:8px 0 4px 0; }
.conf-bar-label { font-size:11px;color:#6B8EAA;width:52px;flex-shrink:0;letter-spacing:.06em;text-transform:uppercase; }
.conf-bar-row   { display:flex;align-items:center;gap:7px; }
/* ── Temperature gauge strip ── */
.temp-strip { border-radius:10px;padding:16px 20px;margin-bottom:18px;border-left:4px solid; }
/* ── Intelligence / event timeline ── */
.intel-story-item { background:#111820;border:1px solid #1F2D3D;border-radius:8px;padding:10px 16px;margin-bottom:7px;font-size:14px;color:#CDD5E0; }
.intel-event { display:flex;align-items:flex-start;gap:10px;padding:8px 14px;margin-bottom:6px;border-radius:8px;border:1px solid #1F2D3D; }
.intel-event.new     { background:#0A1F12;border-color:#2E6B4A; }
.intel-event.upgrade { background:#0A1520;border-color:#253A52; }
.intel-event.down    { background:#1A0810;border-color:#5A1A28; }
.intel-event.risk    { background:#1E1408;border-color:#6A5020; }
.intel-event.struct  { background:#10161E;border-color:#1F2D3D; }
.intel-sev-icon  { font-size:16px;flex-shrink:0;margin-top:1px; }
.intel-event-body { flex:1; }
.intel-event-zh  { font-size:14px;color:#CDD5E0;line-height:1.4; }
.intel-event-en  { font-size:11px;color:#4A6A8A;font-style:italic;margin-top:2px; }
.intel-no-prev   { background:#1A1E12;border:1px solid #3A4A20;border-radius:8px;padding:12px 18px;color:#8A9A6A;font-size:13px; }
.watch-card      { background:#111820;border:1px solid #253A52;border-radius:10px;padding:13px 16px;margin-bottom:8px; }
.watch-ticker    { font-size:17px;font-weight:800;color:#7EB8D4;font-family:monospace; }
.watch-name      { font-size:13px;color:#8B949E;margin-left:6px; }
.watch-state     { display:inline-block;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:700;background:#0A1520;color:#7EB8D4;border:1px solid #253A52;margin:6px 0 4px 0; }
.watch-reason    { font-size:12px;color:#6B8EAA;margin-top:4px;line-height:1.5; }
.delta-row       { display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #1A2030; }
.delta-ticker    { font-size:13px;font-weight:700;color:#7EB8D4;font-family:monospace;width:48px;flex-shrink:0; }
.delta-name      { font-size:12px;color:#8B949E;width:72px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }
.delta-from      { font-size:12px;color:#4A6A8A;width:52px;flex-shrink:0;text-align:right; }
.delta-arrow     { font-size:12px;color:#3A5A6A;flex-shrink:0; }
.delta-to        { font-size:13px;font-weight:700;width:52px;flex-shrink:0; }
.delta-change    { font-size:12px;flex-shrink:0;width:52px;text-align:right; }
/* ── Streamlit native elements ── */
.stDataFrame { background: #111820 !important; }
div[data-testid="stExpander"] { border: 1px solid #1F2D3D !important; border-radius: 8px !important; }
/* ── P3h.5 Research-style golden cards ── */
.g5-card { background:#111820;border:1px solid #1F2D3D;border-radius:12px;padding:18px 20px;margin-bottom:12px;border-left:4px solid; }
.g5-card.g5-prime     { border-left-color:#D4A84B; }
.g5-card.g5-strong    { border-left-color:#7EB8D4; }
.g5-card.g5-qualified { border-left-color:#52B788; }
.g5-card.g5-new       { border-left-color:#9E8AC8;box-shadow:0 0 0 1px #4A3880; }
.g5-head { display:flex;align-items:center;gap:10px;margin-bottom:10px; }
.g5-ticker { font-size:20px;font-weight:800;color:#7EB8D4;font-family:'SF Mono','Fira Code',monospace; }
.g5-name   { font-size:14px;color:#8B949E; }
.g5-tier-badge { display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:800;letter-spacing:.04em; }
.g5-tier-prime     { background:#1F1508;color:#D4A84B;border:1px solid #6A5020; }
.g5-tier-strong    { background:#0A1520;color:#7EB8D4;border:1px solid #253A52; }
.g5-tier-qualified { background:#0A1F12;color:#52B788;border:1px solid #2E6B4A; }
.g5-tier-new       { background:#160F22;color:#9E8AC8;border:1px solid #4A3880; }
.g5-state-badge { display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600;margin-left:6px; }
.g5-core-strip { display:flex;gap:10px;flex-wrap:wrap;margin:8px 0; }
.g5-kv { background:#161B26;border:1px solid #1F2D3D;border-radius:7px;padding:6px 12px; }
.g5-kv-label { font-size:10px;color:#6B8EAA;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px; }
.g5-kv-val   { font-size:16px;font-weight:700;color:#E6EDF3;line-height:1.2; }
.g5-kv-sub   { font-size:11px;color:#6B8EAA;margin-top:1px; }
.g5-section-label { font-size:10px;color:#4A6A8A;text-transform:uppercase;letter-spacing:.1em;margin:10px 0 4px 0;font-weight:700; }
.g5-why-text  { font-size:14px;color:#CDD5E0;line-height:1.6;background:#0D1520;border-radius:7px;padding:9px 14px; }
.g5-tag-row   { display:flex;flex-wrap:wrap;gap:5px;margin:4px 0; }
.g5-tag       { font-size:11px;border-radius:5px;padding:2px 8px;display:inline-block; }
.g5-tag-change-up   { background:#0A1F12;color:#52B788;border:1px solid #2E6B4A; }
.g5-tag-change-down { background:#1A0810;color:#E05C7A;border:1px solid #5A1A28; }
.g5-tag-watch       { background:#1E1408;color:#D4A84B;border:1px solid #6A5020; }
.g5-tag-inval       { background:#1A0810;color:#E05C7A;border:1px solid #5A1A28; }
.g5-tag-neutral     { background:#161B26;color:#8B949E;border:1px solid #2D3748; }
/* ── Lifecycle timeline ── */
.lc-wrap { display:flex;align-items:center;gap:0;margin:8px 0 4px 0;overflow-x:auto;padding-bottom:2px; }
.lc-node { display:flex;flex-direction:column;align-items:center;flex-shrink:0; }
.lc-dot  { width:10px;height:10px;border-radius:50%;border:2px solid; }
.lc-dot-active { width:13px;height:13px;box-shadow:0 0 6px; }
.lc-label { font-size:9px;color:#6B8EAA;margin-top:3px;max-width:52px;text-align:center;line-height:1.2; }
.lc-line { flex:1;height:2px;background:#1F2D3D;min-width:12px;align-self:center;margin-bottom:14px; }
/* ── Session narrative header ── */
.g5-narrative-wrap { background:#0D1117;border:1px solid #1F2D3D;border-radius:10px;padding:14px 18px;margin-bottom:18px; }
.g5-narrative-title { font-size:11px;color:#4A6A8A;text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:8px; }
.g5-narrative-bullet { display:flex;gap:8px;align-items:flex-start;margin-bottom:6px;font-size:13px;color:#CDD5E0;line-height:1.5; }
.g5-narrative-dot { color:#D4A84B;flex-shrink:0;margin-top:2px; }
/* ── New entrants area ── */
.g5-new-header { background:linear-gradient(90deg,#160F22,#0D1117);border:1px solid #4A3880;border-radius:10px;padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px; }
.g5-new-header-text { font-size:15px;font-weight:700;color:#9E8AC8; }
.g5-new-header-sub  { font-size:12px;color:#4A3880;margin-left:auto; }
/* ── Momentum group headers ── */
.g5-momentum-head { display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:8px;margin:14px 0 8px 0;border-left:3px solid; }
.g5-momentum-strengthening { background:#0A1F12;border-left-color:#52B788; }
.g5-momentum-stable        { background:#0A1520;border-left-color:#7EB8D4; }
.g5-momentum-weakening     { background:#1E1408;border-left-color:#D4A84B; }
.g5-momentum-icon  { font-size:16px; }
.g5-momentum-label { font-size:14px;font-weight:700; }
.g5-momentum-count { font-size:12px;opacity:.7;margin-left:auto; }
/* ── Near-miss scout section ── */
.g5-scout-section { background:#0D0F1A;border:1px solid #2A2A4A;border-radius:10px;padding:14px 18px;margin-top:20px; }
.g5-scout-header  { display:flex;align-items:center;gap:8px;margin-bottom:12px;border-bottom:1px solid #2A2A4A;padding-bottom:8px; }
.g5-scout-title   { font-size:13px;font-weight:700;color:#6B5FA8;letter-spacing:.04em; }
.g5-scout-sub     { font-size:11px;color:#3A3A6A;margin-left:auto; }
.g5-scout-card    { background:#12122A;border:1px solid #2A2A4A;border-radius:8px;padding:10px 14px;margin-bottom:6px; }
.g5-scout-head    { display:flex;align-items:center;gap:8px;margin-bottom:6px; }
.g5-scout-ticker  { font-size:15px;font-weight:800;color:#7B6EC8;font-family:monospace; }
.g5-scout-name    { font-size:12px;color:#5A5A8A; }
.g5-scout-badge   { display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:700;background:#1A1232;color:#7B6EC8;border:1px solid #3A3870;margin-left:auto; }
.g5-scout-miss    { font-size:11px;color:#4A4A7A;margin-top:4px;line-height:1.5; }
.g5-scout-bar-wrap { display:flex;align-items:center;gap:6px;margin:5px 0; }
.g5-scout-bar-bg   { flex:1;background:#1A1232;border-radius:3px;height:4px;overflow:hidden; }
.g5-scout-bar-fill { height:100%;border-radius:3px;background:#5A4A98; }

/* ── P4 Fixed-height observation cards ── */
.gc-card { background:#111820;border:1px solid #1F2D3D;border-radius:12px;padding:14px 16px;margin-bottom:10px;border-left:4px solid;box-sizing:border-box; }
.gc-card.gc-prime     { border-left-color:#D4A84B; }
.gc-card.gc-strong    { border-left-color:#7EB8D4; }
.gc-card.gc-qualified { border-left-color:#52B788; }
.gc-card.gc-new       { border-left-color:#9E8AC8;box-shadow:0 0 0 1px #3A2870; }
/* Row 1: header */
.gc-head { display:flex;align-items:center;gap:8px;margin-bottom:8px; }
.gc-ticker { font-size:18px;font-weight:800;color:#7EB8D4;font-family:monospace; }
.gc-name   { font-size:13px;color:#8B949E; }
.gc-badge  { display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:800;letter-spacing:.04em; }
.gc-badge-prime     { background:#1F1508;color:#D4A84B;border:1px solid #6A5020; }
.gc-badge-strong    { background:#0A1520;color:#7EB8D4;border:1px solid #253A52; }
.gc-badge-qualified { background:#0A1F12;color:#52B788;border:1px solid #2E6B4A; }
.gc-badge-new       { background:#160F22;color:#9E8AC8;border:1px solid #4A3880; }
.gc-state  { display:inline-block;padding:1px 8px;border-radius:8px;font-size:11px;font-weight:600; }
.gc-price  { margin-left:auto;font-size:15px;font-weight:700;font-family:monospace; }
/* Row 2: divider */
.gc-divider { border:none;border-top:1px solid #1F2D3D;margin:6px 0; }
/* Row 3: key metrics grid */
.gc-metrics { display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;margin:6px 0; }
.gc-metric  { display:flex;justify-content:space-between;align-items:baseline; }
.gc-metric-label { font-size:11px;color:#6B8EAA; }
.gc-metric-val   { font-size:13px;font-weight:700;color:#E6EDF3;font-family:monospace; }
/* Row 4: signal row */
.gc-signals { display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0 4px 0; }
.gc-signal-pill { display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;padding:3px 9px;border-radius:12px;white-space:nowrap; }
/* Tooltip */
.gc-tooltip-wrap { position:relative;display:inline-block; }
.gc-tooltip-wrap .gc-tooltip { visibility:hidden;background:#1A2540;color:#CDD5E0;font-size:11px;line-height:1.7;border-radius:7px;padding:8px 12px;position:absolute;z-index:99;bottom:125%;left:50%;transform:translateX(-50%);white-space:nowrap;border:1px solid #2D3F5A;min-width:220px; }
.gc-tooltip-wrap:hover .gc-tooltip { visibility:visible; }
.gc-tooltip-icon { color:#4A6A8A;font-size:12px;cursor:help;margin-left:3px; }
/* ── Sidebar ── */
[data-testid="stSidebar"] { min-width: 220px !important; max-width: 260px !important; }
[data-testid="stSidebar"] .block-container { padding: 1rem 0.8rem !important; }
.sidebar-logo { font-size: 17px; font-weight: 800; color: #E6EDF3; letter-spacing: -0.02em; margin-bottom: 4px; }
.sidebar-sub  { font-size: 11px; color: #4A5A6A; letter-spacing: .06em; margin-bottom: 16px; }
.sidebar-divider { border: none; border-top: 1px solid #1F2D3D; margin: 14px 0; }
.sidebar-section-label { font-size: 10px; color: #4A6A8A; letter-spacing: .1em; text-transform: uppercase; margin-bottom: 8px; font-weight: 700; }
.sidebar-stat-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; }
.sidebar-stat-key { font-size: 12px; color: #6B8EAA; }
.sidebar-stat-val { font-size: 12px; font-weight: 700; color: #CDD5E0; font-family: monospace; }
.sidebar-date-badge {
    display: inline-block; background: #0A1520; border: 1px solid #253A52;
    border-radius: 6px; padding: 6px 10px; font-size: 13px; font-weight: 700;
    color: #7EB8D4; font-family: monospace; width: 100%; text-align: center;
    margin-bottom: 4px;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Data loading — multi-date
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _load_all_snapshots() -> list[dict]:
    """Load all real (non-example) snapshots in chronological order."""
    import datetime as _dt
    index = vd.load_index()
    dates = sorted(
        k for k in index.get("snapshots", {}).keys()
        if len(k) == 10 and k.replace("-", "").isdigit()
    )
    result = []
    for d in dates:
        try:
            result.append(vd.load_snapshot(d))
        except Exception:
            pass
    return result


@st.cache_data(ttl=120, show_spinner=False)
def _load_branches_for_ticker(ticker: str) -> dict:
    """Load data/branches/<ticker>.json if it exists."""
    import json as _json
    branches_dir = _AI_STOCK / "data" / "branches"
    path = branches_dir / f"{ticker}.json"
    if path.exists():
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@st.cache_data(ttl=300, show_spinner=False)
def _load_market_pulse() -> dict:
    """Load data/market_pulse.json written by fetch_market_pulse.py."""
    import json as _json
    path = _AI_STOCK / "data" / "market_pulse.json"
    if path.exists():
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _real_dates() -> list[str]:
    index = vd.load_index()
    return sorted(
        k for k in index.get("snapshots", {}).keys()
        if len(k) == 10 and k.replace("-", "").isdigit()
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1.8.0 衍生欄位讀取(優先讀 snapshot,不再 render-time 重算)
# ─────────────────────────────────────────────────────────────────────────────
# 原本 viewer 對全 viewer 載入的 snapshot 跑 full_ticker_context() →
# accumulation_velocity() 即時算 streak/net_cumulative,造成「前端 14 日 vs
# JSON 4 日」的不一致(窗口不同 + None 透明處理)。1.8.0 後 ingest 直接寫回
# main_force_strict_streak_days / main_force_positive_days_in_window /
# net_accumulation_in_window,viewer 用下面的 helper 讀取,確保前後端一致。

def _stock_streak(stock: dict) -> int:
    """主力嚴格連續買超天數(1.8.0:讀 snapshot,缺日視為中斷)。"""
    v = stock.get("main_force_strict_streak_days")
    if v is None:
        v = stock.get("main_force_consecutive_days")  # 1.7.0 兼容欄位
    return int(v) if v is not None else 0


def _stock_buy_days_in_window(stock: dict) -> int:
    """過去 lookback_window_days 內主力買超天數(忽略缺日,不要求連續)。"""
    v = stock.get("main_force_positive_days_in_window")
    return int(v) if v is not None else 0


def _stock_buy_days_in_window_or_none(stock: dict) -> int | None:
    """同 _stock_buy_days_in_window,但欄位完全缺失(1.7.0 舊快照)時回 None,
    讓 viewer 顯示「—」而不是 0/20(避免明天前看起來像「全部標的窗口都沒買」)。"""
    return stock.get("main_force_positive_days_in_window")


def _stock_net_accumulation(stock: dict) -> int:
    """過去 lookback_window_days 內主力買超累計(張)。1.7.0 兼容退回 weakening.net_cumulative。"""
    v = stock.get("net_accumulation_in_window")
    if v is None:
        v = (stock.get("weakening") or {}).get("net_cumulative")
    return int(v) if v is not None else 0


# ─────────────────────────────────────────────────────────────────────────────
# Shared HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _section_header(icon: str, zh: str, en: str, count: int | None = None) -> None:
    badge = f'<span class="section-badge">{count}</span>' if count is not None else ""
    st.markdown(
        f'<div class="section-header"><span class="section-icon">{icon}</span>'
        f'<span class="section-title-zh">{zh}</span>'
        f'<span class="section-title-en">{en}</span>{badge}</div>',
        unsafe_allow_html=True,
    )


def _metric_strip(metrics: list[tuple[str, str, str, str]]) -> None:
    """metrics: [(label, value, sub, val_class), ...]"""
    cells = "".join(
        f'<div class="metric-cell"><div class="metric-label">{lb}</div>'
        f'<div class="metric-value {vc}">{val}</div>'
        f'<div class="metric-sub">{sub}</div></div>'
        for lb, val, sub, vc in metrics
    )
    st.markdown(f'<div class="metric-strip">{cells}</div>', unsafe_allow_html=True)


def _chg_cls(chg: float | None) -> str:
    if chg is None:
        return "chg-flat"
    return "chg-up" if chg > 0 else ("chg-down" if chg < 0 else "chg-flat")


def _plotly_layout(title: str = "", height: int = 280) -> dict:
    return dict(
        title=dict(text=title, font=dict(color="#8B949E", size=13)),
        paper_bgcolor="#0D1117",
        plot_bgcolor="#111820",
        font=dict(color="#8B949E", size=12),
        xaxis=dict(showgrid=False, zeroline=False, color="#4A5A6A"),
        yaxis=dict(showgrid=True,  zeroline=False, color="#4A5A6A",
                   gridcolor="#1A2030"),
        margin=dict(l=40, r=20, t=36, b=36),
        height=height,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 大盤脈搏  Market Pulse Banner  (pinned above tabs)
# ─────────────────────────────────────────────────────────────────────────────

def _render_market_pulse_banner() -> None:
    """Render a full-width market pulse strip above all tabs.
    Reads data/market_pulse.json; shows a soft notice if missing.
    """
    pulse = _load_market_pulse()

    if not pulse:
        st.markdown(
            '<div style="background:#1A1E12;border:1px solid #3A4A20;border-radius:8px;'
            'padding:10px 18px;margin-bottom:14px;font-size:13px;color:#8A9A6A;">'
            '📡 大盤脈搏尚未取得 — 執行 <code>make fetch-pulse</code> 以抓取 TAIEX / 台指期 / 三大法人資料'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    taiex  = pulse.get("taiex", {})
    tx     = pulse.get("tx_futures", {})
    inst   = pulse.get("institutional_futures", {})
    date   = pulse.get("date", "")
    fat    = pulse.get("fetched_at", "")[:16]

    # ── Value helpers ─────────────────────────────────────────────────────
    def _fmt_num(v, fmt="{:,.0f}", fallback="—"):
        return fmt.format(v) if isinstance(v, (int, float)) else fallback

    def _chg_color(v):
        if not isinstance(v, (int, float)):
            return "#8B949E"
        return "#52B788" if v > 0 else ("#E05C7A" if v < 0 else "#8B949E")

    def _sign(v):
        if not isinstance(v, (int, float)):
            return ""
        return "+" if v > 0 else ""

    # TAIEX
    taiex_close  = taiex.get("close")
    taiex_chg    = taiex.get("change")
    taiex_pct    = taiex.get("change_pct")
    taiex_vol    = taiex.get("volume_b_ntd")
    taiex_color  = _chg_color(taiex_chg)
    taiex_arrow  = "▲" if isinstance(taiex_chg, (int, float)) and taiex_chg > 0 else ("▼" if isinstance(taiex_chg, (int, float)) and taiex_chg < 0 else "─")

    # TX Futures
    tx_close    = tx.get("close")
    tx_chg      = tx.get("change")
    tx_basis    = tx.get("basis")          # positive = contango 正價差
    tx_oi       = tx.get("open_interest")
    tx_oi_chg   = tx.get("oi_change")
    tx_color    = _chg_color(tx_chg)
    basis_color = "#52B788" if isinstance(tx_basis, (int, float)) and tx_basis > 0 else ("#E05C7A" if isinstance(tx_basis, (int, float)) and tx_basis < 0 else "#8B949E")
    basis_label = "正價差" if isinstance(tx_basis, (int, float)) and tx_basis > 0 else ("逆價差" if isinstance(tx_basis, (int, float)) and tx_basis < 0 else "價差")

    # Institutional futures net OI
    fii_oi   = inst.get("foreign", {}).get("net_oi")
    it_oi    = inst.get("investment_trust", {}).get("net_oi")
    dlr_oi   = inst.get("dealer", {}).get("net_oi")
    fii_chg  = inst.get("foreign", {}).get("oi_change")

    # ── Build HTML ────────────────────────────────────────────────────────
    def _cell(label: str, value: str, sub: str = "", color: str = "#E6EDF3") -> str:
        return (
            f'<div style="background:#111820;border:1px solid #1F2D3D;border-radius:8px;'
            f'padding:10px 14px;min-width:110px;flex:1;">'
            f'<div style="font-size:10px;color:#6B8EAA;text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:4px;">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:{color};line-height:1.2;">{value}</div>'
            f'<div style="font-size:11px;color:#6B8EAA;margin-top:2px;">{sub}</div>'
            f'</div>'
        )

    cells = ""

    # 1. TAIEX
    cells += _cell(
        "加權指數 TAIEX",
        f"{_fmt_num(taiex_close, '{:,.2f}')}",
        f"{taiex_arrow} {_sign(taiex_chg)}{_fmt_num(taiex_chg, '{:,.2f}')}  ({_sign(taiex_pct)}{_fmt_num(taiex_pct, '{:.2f}')}%)  成交 {_fmt_num(taiex_vol, '{:.1f}')}億",
        taiex_color,
    )

    # 2. TX Close + change
    cells += _cell(
        "台指期近月 TX",
        f"{_fmt_num(tx_close, '{:,.0f}')}",
        f"{_sign(tx_chg)}{_fmt_num(tx_chg, '{:,.0f}')}",
        tx_color,
    )

    # 3. 正逆價差 Basis
    cells += _cell(
        f"期現價差 Basis",
        f"{_sign(tx_basis)}{_fmt_num(tx_basis, '{:,.1f}')}",
        basis_label,
        basis_color,
    )

    # 4. TX Open Interest
    oi_chg_str = f"  {_sign(tx_oi_chg)}{_fmt_num(tx_oi_chg, '{:,}')}口" if isinstance(tx_oi_chg, (int, float)) else ""
    cells += _cell(
        "台指期未平倉 OI",
        f"{_fmt_num(tx_oi, '{:,}')}口",
        f"變化{oi_chg_str}",
        "#CDD5E0",
    )

    # 5. 外資台指期淨部位
    cells += _cell(
        "外資台指期淨部位",
        f"{_sign(fii_oi)}{_fmt_num(fii_oi, '{:,}')}口",
        f"變化 {_sign(fii_chg)}{_fmt_num(fii_chg, '{:,}')}口" if isinstance(fii_chg, (int, float)) else "—",
        _chg_color(fii_oi),
    )

    # 6. 投信 + 自營商
    it_str  = f"投信 {_sign(it_oi)}{_fmt_num(it_oi, '{:,}')}口"
    dlr_str = f"自營 {_sign(dlr_oi)}{_fmt_num(dlr_oi, '{:,}')}口"
    cells += _cell(
        "三大法人台指期",
        it_str,
        dlr_str,
        _chg_color(it_oi),
    )

    st.markdown(
        f'<div style="margin-bottom:4px;font-size:11px;color:#4A5A6A;letter-spacing:.06em;">'
        f'大盤脈搏  MARKET PULSE &nbsp;·&nbsp; {date} &nbsp;·&nbsp; 更新 {fat}</div>'
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;">{cells}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 1 — Market Regime  市場體制
# ─────────────────────────────────────────────────────────────────────────────

def _render_regime(snaps: list[dict]) -> None:
    if not snaps:
        st.info("尚無快照資料 No snapshot data available.")
        return

    reg = regime_shift(snaps)

    # Colour scheme
    color = reg["regime_color"]
    bg_map = {
        "#52B788": "#0A1F12",
        "#7EB8D4": "#0A1520",
        "#E05C7A": "#1F0A10",
        "#D4A84B": "#1F1508",
        "#C47A5A": "#1F1208",
        "#6B8EAA": "#10161E",
    }
    bg = bg_map.get(color, "#10161E")

    # Regime banner
    st.markdown(
        f'<div class="regime-banner" style="background:{bg};border-left-color:{color};">'
        f'<div class="regime-label-zh" style="color:{color};">{reg["regime_label_zh"]}</div>'
        f'<div class="regime-label-en" style="color:{color};">{reg["regime_label_en"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if reg["transition_detected"]:
        st.markdown(
            f'<div class="regime-transition">⚡ {reg["transition_note"]}</div>',
            unsafe_allow_html=True,
        )

    # Metrics
    b_pct = reg["latest_breadth"] * 100
    b_cls = "val-green" if b_pct >= 60 else ("val-amber" if b_pct >= 30 else "val-red")
    c_val = reg["latest_avg_chg"]
    c_cls = "val-green" if c_val > 0 else "val-red"
    trend_icons = {
        "rising_fast": "↑↑ 快速上升", "rising": "↑ 上升",
        "falling_fast": "↓↓ 快速下跌", "falling": "↓ 下跌", "flat": "→ 持平"
    }
    _metric_strip([
        ("廣度 Breadth", f"{b_pct:.1f}%",      "買超股佔比", b_cls),
        ("均漲 Avg Chg", f"{c_val:+.2f}%",      "全宇宙均值", c_cls),
        ("廣度趨勢 Trend", trend_icons.get(reg["breadth_trend"], reg["breadth_trend"]), "近3日走勢", "val-cyan"),
        ("快照數 Dates",  str(len(reg["dates"])), "歷史紀錄",   "val-dim"),
    ])

    st.markdown("<br>", unsafe_allow_html=True)

    # Breadth + AvgChg chart
    if len(reg["dates"]) >= 2:
        col1, col2 = st.columns(2)
        with col1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=reg["dates"], y=[v * 100 for v in reg["breadth_series"]],
                mode="lines+markers", name="廣度%",
                line=dict(color="#7EB8D4", width=2.5),
                marker=dict(size=6),
                fill="tozeroy", fillcolor="rgba(126,184,212,0.08)",
            ))
            fig.add_hline(y=50, line_dash="dot", line_color="#2A3A4A", line_width=1)
            fig.update_layout(**_plotly_layout("主力廣度 Breadth %", 240))
            fig.update_yaxes(ticksuffix="%", range=[0, 105])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with col2:
            colors = [("#52B788" if v >= 0 else "#E05C7A") for v in reg["avg_chg_series"]]
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=reg["dates"], y=reg["avg_chg_series"],
                marker_color=colors, name="均漲%",
            ))
            fig2.add_hline(y=0, line_color="#3A4A5A", line_width=1)
            fig2.update_layout(**_plotly_layout("宇宙均漲 Avg Change %", 240))
            fig2.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

        # History table
        st.markdown("<br>", unsafe_allow_html=True)
        _section_header("📋", "歷史體制紀錄", "Regime History", len(reg["dates"]))
        rows = []
        for i, d in enumerate(reg["dates"]):
            b = reg["breadth_series"][i] * 100
            c = reg["avg_chg_series"][i]
            v = reg["vol_series"][i]
            rows.append({"日期 Date": d, "廣度% Breadth": f"{b:.1f}%",
                         "均漲% Avg Chg": f"{c:+.2f}%", "量能指數 Vol": f"{v:.2f}×"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# P3 — 全市場熱度觀察  Heat Radar (additive ranking layer, display-only)
# ─────────────────────────────────────────────────────────────────────────────
# AI_GOVERNANCE: this is a parallel display layer.
# Zero impact on composite_score / tier / gates / golden list.
# ─────────────────────────────────────────────────────────────────────────────

def _heat_score(streak: int, fii, conf_tier: str, weak_sev: str) -> int:
    """Additive heat score (0–65). Display-only, not a gate/score input.

    Components:
      Streak      +30/22/14/5/0  (≥7/≥5/≥3/≥1/0)
      FII         +15 same-dir, -5 opposite
      Data qual   +10 FULL, +5 PARTIAL, 0 SKELETON
      Weakening   -25 red, -15 orange, -5 yellow, 0 none
    """
    s = 0
    if streak >= 7:   s += 30
    elif streak >= 5: s += 22
    elif streak >= 3: s += 14
    elif streak >= 1: s += 5

    if fii is not None:
        if fii > 0:   s += 15
        elif fii < 0: s -= 5

    if conf_tier == "FULL":    s += 10
    elif conf_tier == "PARTIAL": s += 5

    if weak_sev == "red":    s -= 25
    elif weak_sev == "orange": s -= 15
    elif weak_sev == "yellow": s -= 5

    return s


def _heat_bar(score: int) -> str:
    """Inline HTML progress bar, colour-coded by score tier."""
    pct = max(0, min(100, int(score / 65 * 100)))
    if score >= 40:   color = "#52B788"   # green
    elif score >= 20: color = "#D4A84B"   # amber
    elif score >= 5:  color = "#7EB8D4"   # blue-grey
    else:             color = "#4A5A6A"   # dim
    return (
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="flex:1;height:6px;border-radius:3px;background:#1E2A3A;">'
        f'<div style="width:{pct}%;height:100%;border-radius:3px;background:{color};"></div>'
        f'</div>'
        f'<span style="font-size:11px;color:{color};font-weight:700;min-width:22px;">{score}</span>'
        f'</div>'
    )


def _heat_obs_tags(streak: int, fii, conf_tier: str, weak: dict) -> str:
    """Build inline observation tag HTML — positive signals + blockers."""
    tags = []
    # Positive
    if streak >= 3:
        tags.append(f'<span class="signal-tag">連買{streak}日</span>')
    elif streak >= 1:
        tags.append(f'<span class="signal-tag" style="color:#7EB8D4;">{streak}日</span>')
    if fii is not None and fii > 0:
        tags.append('<span class="signal-tag">外資同向</span>')
    if conf_tier == "FULL":
        tags.append('<span class="signal-tag">資料完整</span>')
    # Concerns
    if fii is not None and fii < 0:
        tags.append('<span class="signal-tag warn">外資反向</span>')
    if conf_tier == "SKELETON":
        tags.append('<span class="signal-tag warn">資料偏薄</span>')
    sev = weak.get("severity", "none")
    if sev != "none":
        label = weak.get("label_zh", "轉弱")
        flag_codes = "+".join(f["code"] for f in weak.get("flags", []))
        tags.append(
            f'<span class="signal-tag red" title="{flag_codes}">'
            f'🔻 {label}</span>'
        )
    return "".join(tags)


def _render_heat_radar(snaps: list[dict]) -> None:
    """P3: additive heat-score ranking for all tracked stocks.

    Reads only from the latest snapshot + prior snap context.
    Display-only — zero impact on composite_score / tier / gates.
    """
    if not snaps:
        return

    latest_snap   = snaps[-1]
    latest_stocks = {s["ticker"]: s for s in latest_snap.get("stocks", [])}
    if not latest_stocks:
        return

    st.markdown("---")
    _section_header(
        "📡", "全市場熱度觀察", "Heat Radar — All Tracked Stocks",
        len(latest_stocks),
    )
    st.markdown(
        '<div class="data-gap-notice" style="background:#0F1408;border-left-color:#52B788;color:#8B9E8A;">'
        '熱度分 = 連買積分 + 外資對齊 + 資料品質 − 轉弱扣分。'
        ' <b>純觀察層</b>，不影響黃金名單評分 / 閘門 / Tier。'
        ' P3b 啟動後方顯示正式評分。</div>',
        unsafe_allow_html=True,
    )

    # Build rows
    rows = []
    for ticker, stock in latest_stocks.items():
        # 1.8.0:直接讀 snapshot,不再 render-time 跑 full_ticker_context
        streak = _stock_streak(stock)
        fii    = stock.get("fii_net_buy")
        tier   = stock.get("confidence_tier", "SKELETON")
        weak   = stock.get("weakening", {})
        sev    = weak.get("severity", "none")
        score  = _heat_score(streak, fii, tier, sev)
        price  = stock.get("current_price")
        chg    = stock.get("change_pct")
        name   = stock.get("name", "") or _short_name(ticker)
        rows.append({
            "ticker": ticker,
            "name":   name,
            "score":  score,
            "streak": streak,
            "fii":    fii,
            "tier":   tier,
            "weak":   weak,
            "sev":    sev,
            "price":  price,
            "chg":    chg,
        })

    rows.sort(key=lambda r: (-r["score"], -r["streak"]))

    # Render cards in 2 columns
    col_a, col_b = st.columns(2)
    for i, r in enumerate(rows):
        col = col_a if i % 2 == 0 else col_b
        price_str = f"NT${r['price']:,.2f}" if r["price"] else "—"
        chg_str   = f"{r['chg']:+.2f}%" if r["chg"] is not None else "—"
        chg_cls   = _chg_cls(r["chg"])
        bar_html  = _heat_bar(r["score"])
        obs_html  = _heat_obs_tags(r["streak"], r["fii"], r["tier"], r["weak"])
        rank_str  = f"#{i+1}"

        with col:
            st.markdown(
                f'<div class="watch-card" style="padding:10px 14px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<div>'
                f'<span style="font-size:11px;color:#4A6A8A;margin-right:4px;">{rank_str}</span>'
                f'<span class="stock-ticker">{r["ticker"]}</span>'
                f'<span class="stock-name">{r["name"]}</span>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<span class="stock-price">{price_str}</span>&nbsp;'
                f'<span class="{chg_cls}" style="font-size:12px;">{chg_str}</span>'
                f'</div>'
                f'</div>'
                f'<div style="margin:6px 0 4px 0;">{bar_html}</div>'
                f'<div style="margin-top:4px;">{obs_html}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 2 — Watchlist Radar  雷達觀察
# ─────────────────────────────────────────────────────────────────────────────

def _render_watchlist_radar(snaps: list[dict]) -> None:
    _section_header("🎯", "龍頭雷達", "Tech Leaders Radar", len(RADAR_TICKERS))
    st.markdown(
        '<div class="data-gap-notice" style="background:#0F1820;border-left-color:#7EB8D4;color:#7EB8D4;">'
        '台積電 · 鴻海 · 聯發科 · 台達電 · 廣達 — 每日必抓分點，無論是否在三榜。'
        ' Core tech leaders tracked daily regardless of cross-signal status.</div>',
        unsafe_allow_html=True,
    )

    # Latest snapshot
    latest_snap = snaps[-1] if snaps else {}
    latest_stocks = {s["ticker"]: s for s in latest_snap.get("stocks", [])}

    cols = st.columns(5)
    for idx, ticker in enumerate(RADAR_TICKERS):
        meta   = TIER_A[ticker]
        stock  = latest_stocks.get(ticker, {})
        branch = _load_branches_for_ticker(ticker)

        price      = stock.get("current_price")
        chg        = stock.get("change_pct")
        mfb        = stock.get("main_force_buy")
        cost       = stock.get("main_force_cost") or branch.get("avgBuyCost")
        # 1.8.0:讀 snapshot 持久化欄位
        streak     = _stock_streak(stock)

        price_str = f"NT${price:,.2f}" if price else "—"
        chg_str   = f"{chg:+.2f}%" if chg is not None else "—"
        chg_cls   = _chg_cls(chg)
        cost_str  = f"NT${cost:,.2f}" if cost else "—"
        mfb_str   = f"{mfb:+,}張" if mfb else "—"

        if streak >= 3:
            streak_cls, streak_lbl = "streak-active", f"▲ {streak}日連買"
        elif streak >= 1:
            streak_cls, streak_lbl = "streak-active", f"▲ {streak}日"
        elif mfb and mfb < 0:
            streak_cls, streak_lbl = "streak-warn", "▼ 賣超"
        else:
            streak_cls, streak_lbl = "streak-none", "─ 未進榜"

        in_today = ticker in latest_stocks
        border_color = "#253A52" if not in_today else "#3A5A7A"

        with cols[idx % 5]:
            st.markdown(
                f'<div class="radar-card" style="border-color:{border_color};">'
                f'<span class="radar-ticker">{ticker}</span>'
                f'<span class="radar-name">{meta["name"]}</span>'
                f'<div class="radar-group">{meta["group_zh"]} · {meta["group"]}</div>'
                f'<div class="radar-cost">{cost_str}</div>'
                f'<div class="radar-mfbuy">主力 {mfb_str} &nbsp; <span class="{chg_cls}">{chg_str}</span></div>'
                f'<span class="radar-streak {streak_cls}">{streak_lbl}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── P3.0: 全市場熱度觀察已拆出,由 tab 佈線獨立呼叫(排序:Yonki 2026-07-04)──


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 3 — Strengthening Signals  轉強訊號
# ─────────────────────────────────────────────────────────────────────────────

_MOMENTUM_GREEN = "#52B788"
_MOMENTUM_RED   = "#E05C7A"
_MOMENTUM_DIM   = "#8B93A3"


def _presence_dates(snaps: list[dict]) -> tuple[dict, dict]:
    """Map ticker → first / last snapshot date where it was present.

    Pure presentation lookup over already-computed snapshot data —
    no scoring, ranking, or gate logic (AI_GOVERNANCE compliant).
    """
    first: dict[str, str] = {}
    last:  dict[str, str] = {}
    for snap in snaps:
        d = snap.get("date", "?")
        for s in snap.get("stocks", []):
            t = s.get("ticker", "")
            if not t:
                continue
            first.setdefault(t, d)
            last[t] = d
    return first, last


def _momentum_glyph(vel, accel) -> tuple[str, int]:
    """Render core-computed velocity_3d / acceleration as a direction glyph.

    Returns (display_text, sort_rank) — rank 0 is strongest.
    Formatting only; the numbers come straight from accumulation_velocity().
    """
    if vel is None:
        return "—", 2
    if vel > 0 and (accel or 0) > 0:
        return "▲▲ 加速", 0
    if vel > 0:
        return "▲ 增溫", 1
    if vel < 0:
        return "▼ 減速", 3
    return "─ 持平", 2


def _freshness_label(ticker: str, first: dict, last: dict, latest_date: str) -> tuple[str, int]:
    """(display, sort_rank): NEW > current > stale."""
    f = first.get(ticker)
    l = last.get(ticker)
    if f == latest_date:
        return "NEW", 0
    if l == latest_date:
        return latest_date[5:], 1
    return f"⚠ {l[5:] if l else '?'}", 2


def _style_signal_df(df, color_cols: list[str], text_cols: list[str], fmt: dict):
    """Shared Styler: green/red on numeric sign, momentum text coloring."""
    def _num_color(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        try:
            x = float(str(v).replace("%", "").replace(",", "").replace("+", ""))
        except (ValueError, TypeError):
            return ""
        if x > 0:
            return f"color: {_MOMENTUM_GREEN}"
        if x < 0:
            return f"color: {_MOMENTUM_RED}"
        return ""

    def _text_color(v):
        s = str(v)
        if s.startswith("▲"):
            return f"color: {_MOMENTUM_GREEN}; font-weight: 600"
        if s.startswith("▼"):
            return f"color: {_MOMENTUM_RED}"
        if s == "NEW":
            return "color: #4A9EFF; font-weight: 700"
        if s.startswith("⚠"):
            return f"color: {_MOMENTUM_DIM}"
        return ""

    sty = df.style.format(fmt, na_rep="—")
    cc = [c for c in color_cols if c in df.columns]
    tc = [c for c in text_cols if c in df.columns]
    if cc:
        sty = sty.map(_num_color, subset=cc)
    if tc:
        sty = sty.map(_text_color, subset=tc)
    return sty


@st.cache_data(ttl=120, show_spinner=False)
def _strengthening_rows(key: str, snaps: list[dict]) -> list[dict]:
    """轉強表資料列(P3.1 加快取:full_ticker_context 很重,每次 rerun 別重算)。"""
    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")

    rows = []
    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    latest_date = snaps[-1].get("date", "?")
    first_seen, last_seen = _presence_dates(snaps)

    for ticker in sorted(all_tickers):
        stock = latest_stocks.get(ticker, {})
        # 1.8.0:streak / net / vel / accel 直接讀 snapshot;sponsorship 仍走
        # full_ticker_context(尚未持久化,屬於 P2 後續工作)
        streak = _stock_streak(stock)
        if streak < 2:
            continue
        ctx  = full_ticker_context(ticker, snaps)
        spon = ctx["sponsorship"]
        name  = stock.get("name") or _short_name(ticker)
        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        cost  = stock.get("main_force_cost")
        vel   = stock.get("velocity_3d")
        accel = stock.get("acceleration")
        net   = _stock_net_accumulation(stock)
        spon_score = spon.get("persistence_score") or 0
        spon_days  = spon.get("days_with_branches") or 0
        mom_txt, mom_rank = _momentum_glyph(vel, accel)
        fresh_txt, fresh_rank = _freshness_label(ticker, first_seen, last_seen, latest_date)
        rows.append({
            "資料": fresh_txt,
            "代號": ticker,
            "名稱": name,
            "動能": mom_txt,
            "現價": f"NT${price:,.2f}" if price else "—",
            "漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            "連買(日)": streak,
            "窗口買(日)": _stock_buy_days_in_window_or_none(stock),  # 1.7.0 缺欄位顯示「—」
            "累計(張)": net,
            "速度(張/日)": round(vel) if vel is not None else None,
            "主力回頭率": _lvl_sponsor(spon_score, spon_days),
            "成本": f"NT${cost:,.2f}" if cost else "—",
            "Tier A": "★" if ticker in TIER_A else "",
            "_mom": mom_rank,
            "_fresh": fresh_rank,
            "_spon": spon_score,
            "_spon_days": spon_days,
        })
    return rows


def _render_strengthening(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    rows = list(_strengthening_rows(_snaps_key(snaps), snaps))

    # P3.1:獨立搜尋框已移除——它每打一個字就觸發整頁重算(慢);
    # 表格右上角內建 🔍(hover 出現)是純前端搜尋,即時零延遲。
    only_acc = st.checkbox("◉ 只看持續吸籌（主力回頭率 中等以上）",
                           key="strong_acc_filter")
    if only_acc:
        rows = [r for r in rows if r["_spon"] >= 0.35 and r["_spon_days"] >= 3]

    _section_header("↑", "轉強訊號", "Strengthening Signals", len(rows))
    st.markdown(_EXPLAIN_DIV.format(
        text="連續 2 日以上主力買超的全部標的（最寬的潛力篩網），想自己挖的人從這裡找。"
             "搜尋:滑鼠移到表格右上角點 🔍（即時、不重算頁面）。"
             "主力回頭率＝同一家分點回頭買的頻率（高＝同一個主力在鎖碼；低＝每天換人像散戶追價；"
             "樣本不足＝分點資料未滿 3 天，不評分）。"),
        unsafe_allow_html=True)

    if not rows:
        st.markdown(
            '<div class="data-gap-notice">目前無符合條件的標的。</div>',
            unsafe_allow_html=True,
        )
        return

    import pandas as _pd
    df = (
        _pd.DataFrame(rows)
        .sort_values(["_mom", "_fresh", "累計(張)"], ascending=[True, True, False])
        .drop(columns=["_mom", "_fresh", "_spon", "_spon_days"])
    )
    st.caption("排序：動能方向 → 資料新鮮度 → 累計買超 ｜ ▼ 減速中的標的代表動能衰竭，連買天數高也應降權看待")
    st.dataframe(
        _style_signal_df(
            df,
            color_cols=["漲跌", "速度(張/日)"],
            text_cols=["動能", "資料"],
            fmt={"累計(張)": "{:+,.0f}", "速度(張/日)": "{:+,.0f}",
                 "連買(日)": "{:d} 日", "窗口買(日)": "{:d}/20"},
        ),
        use_container_width=True,
        hide_index=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 3b — Weakening / Distribution Signals  轉弱出貨
# ─────────────────────────────────────────────────────────────────────────────

_SEV_STYLE = {
    "red":    ("#E05C7A", "🔴"),
    "orange": ("#E8A33D", "🟠"),
    "yellow": ("#D4C95A", "🟡"),
}


def _render_weakening(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    # P5: read pre-computed weakening from latest snapshot (no render-time compute)
    latest_snap = snaps[-1]
    results = []
    for s in latest_snap.get("stocks", []):
        w_stored = s.get("weakening")
        if w_stored and w_stored.get("severity", "none") != "none":
            results.append({"ticker": s["ticker"], **w_stored})

    # Fallback for old snapshots without weakening field: compute on-the-fly
    if not results and any("weakening" not in s for s in latest_snap.get("stocks", [])):
        all_tickers: set[str] = set()
        for snap in snaps:
            for s in snap.get("stocks", []):
                all_tickers.add(s.get("ticker", ""))
        all_tickers.discard("")
        for ticker in sorted(all_tickers):
            branch = _load_branches_for_ticker(ticker)
            w = weakening_profile(ticker, snaps, branch or None)
            if w["severity"] != "none":
                results.append(w)

    _order = {"red": 0, "orange": 1, "yellow": 2}
    results.sort(key=lambda w: (_order.get(w["severity"], 3), -w["flag_count"], -w.get("net_cumulative", 0)))

    _section_header("🔻", "轉弱出貨", "Weakening / Distribution", len(results))

    # W1–W5 flag legend (hover ⓘ, same pattern as the 量能比 tooltip)
    st.markdown(
        '<div style="margin:-6px 0 10px 2px;font-size:12px;color:#8B949E;">'
        '五旗標偵測'
        '<div class="gc-tooltip-wrap">'
        '<span class="gc-tooltip-icon">ⓘ</span>'
        '<div class="gc-tooltip" style="white-space:normal;width:340px;">'
        '<b>W1 動能衰竭</b> — 連買≥3日但速度轉負、買量遞減<br>'
        '<b>W2 雙引擎分歧</b> — 主力買超但外資賣超達主力買量30%<br>'
        '<b>W3 主力消失</b> — 曾連買≥3日，從買超榜缺席（≠賣出；缺席1日可能只是輪動，缺席≥2日才可合成紅燈）<br>'
        '<b>W4 散戶接盤</b> — 券商家數差轉正，或價跌融資增≥3日/10日<br>'
        '<b>W5 分點賣壓</b> — 分點總賣&gt;總買，或前三買點邊買邊倒（賣出自身買量≥60%）<br>'
        '<span style="color:#D4A84B;">嚴重度：紅 = 實錘W3+佐證 或 ≥3旗標；橙 = 2旗標 或 W3單獨；黃 = 1旗標</span>'
        '</div></div></div>',
        unsafe_allow_html=True,
    )

    n_red = sum(1 for r in results if r["severity"] == "red")
    n_org = sum(1 for r in results if r["severity"] == "orange")
    n_yel = sum(1 for r in results if r["severity"] == "yellow")
    st.caption(
        f"🔴 出貨確認 {n_red} ｜ 🟠 轉弱 {n_org} ｜ 🟡 失速 {n_yel} ｜ "
        "規則：紅 = 主力消失+佐證 或 ≥3旗標；橙 = 2旗標；黃 = 1旗標。"
        "缺席 >3 個快照的標的自動移出（陳舊訊號）。"
    )

    if not results:
        st.markdown(
            '<div class="data-gap-notice" style="border-left-color:#52B788;background:#0A1F12;color:#52B788;">'
            '✓ 目前追蹤範圍內無轉弱訊號。 No weakening signals detected.</div>',
            unsafe_allow_html=True,
        )
        return

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    for w in results:
        ticker = w["ticker"]
        stock  = latest_stocks.get(ticker, {})
        name   = stock.get("name") or _short_name(ticker)
        color, dot = _SEV_STYLE[w["severity"]]

        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        price_str = f"NT${price:,.2f}" if price else "—"
        chg_str   = f"{chg:+.2f}%" if chg is not None else "—"
        chg_cls   = _chg_cls(chg)

        flag_tags = "".join(
            f'<span class="signal-tag warn" title="{f["detail"]}">{f["code"]} {f["zh"]}</span>'
            for f in w["flags"]
        )
        detail_line = " ｜ ".join(f["detail"] for f in w["flags"])

        absent_note = ""
        if not w["present_latest"]:
            absent_note = (f'<span class="signal-tag red">缺席 {w["snaps_since_seen"]} 個快照</span>')

        st.markdown(
            f'<div class="stock-card" style="border-left: 3px solid {color};">'
            f'<div class="stock-card-header">'
            f'<div><span class="stock-ticker">{ticker}</span>'
            f'<span class="stock-name">{name}</span>&nbsp;'
            f'<span style="color:{color};font-weight:700;">{dot} {w["label_zh"]}</span></div>'
            f'<div><span class="stock-price">{price_str}</span>&nbsp;'
            f'<span class="{chg_cls}">{chg_str}</span></div>'
            f'</div>'
            f'<span class="signal-tag">窗口累計 {w["net_cumulative"]:+,} 張</span>'
            f'{flag_tags}{absent_note}'
            f'<div style="margin-top:6px;font-size:12.5px;color:#8B93A3;">{detail_line}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 4 — Failed Breakout Warnings  假突破警報
# ─────────────────────────────────────────────────────────────────────────────

def _render_failed_breakouts(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")

    warnings = []
    for ticker in sorted(all_tickers):
        ctx = full_ticker_context(ticker, snaps)
        fb  = ctx["failed_breakout"]
        if fb["failed_breakout_detected"]:
            warnings.append((ticker, ctx))

    _section_header("⚠", "假突破警報", "Failed Breakout Warnings", len(warnings))

    if not warnings:
        st.markdown(
            '<div class="data-gap-notice" style="border-left-color:#52B788;background:#0A1F12;color:#52B788;">'
            '✓ 目前追蹤範圍內無明顯假突破跡象。 No failed breakout signals detected.</div>',
            unsafe_allow_html=True,
        )
        return

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    for ticker, ctx in warnings:
        fb    = ctx["failed_breakout"]
        stock = latest_stocks.get(ticker, {})
        meta  = TIER_A.get(ticker, {})
        name  = stock.get("name") or _short_name(ticker)

        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        price_str = f"NT${price:,.2f}" if price else "—"
        chg_str   = f"{chg:+.2f}%" if chg is not None else "—"
        chg_cls   = _chg_cls(chg)

        risk_cls = "signal-tag red" if "高風險" in fb["label_zh"] else "signal-tag warn"

        st.markdown(
            f'<div class="stock-card" style="border-left: 3px solid #E05C7A;">'
            f'<div class="stock-card-header">'
            f'<div><span class="stock-ticker">{ticker}</span>'
            f'<span class="stock-name">{name}</span></div>'
            f'<div><span class="stock-price">{price_str}</span>&nbsp;'
            f'<span class="{chg_cls}">{chg_str}</span></div>'
            f'</div>'
            f'<span class="{risk_cls}">{fb["label_zh"]}</span>'
            f'<span class="signal-tag">突破日 {fb["breakout_date"]} +{fb["breakout_chg"]:.1f}%</span>'
            f'<span class="signal-tag warn">量比 {fb["vol_ratio"]:.1f}×</span>'
            f'<span class="signal-tag warn">退卻 {fb["retreat_days"]} 日</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 5 — Persistent Accumulation  持續吸籌
# ─────────────────────────────────────────────────────────────────────────────

def _render_persistent_accumulation(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")

    # 1.8.0:用 snapshot 的 main_force_positive_days_in_window 取代
    # full_ticker_context 重算的 buy_days;sponsorship 仍走 ctx
    latest_for_persist = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    candidates = []
    for ticker in sorted(all_tickers):
        ctx  = full_ticker_context(ticker, snaps)
        spon = ctx["sponsorship"]
        stk_for_count = latest_for_persist.get(ticker, {})
        buy_days = _stock_buy_days_in_window(stk_for_count)
        if spon.get("persistence_score", 0) >= 0.35 and buy_days >= 2:
            candidates.append((ticker, ctx))

    candidates.sort(key=lambda x: (
        -x[1]["sponsorship"]["persistence_score"],
        -_stock_net_accumulation(latest_for_persist.get(x[0], {})),
    ))

    _section_header("◉", "持續吸籌", "Persistent Accumulation", len(candidates))

    if not candidates:
        st.markdown(
            '<div class="data-gap-notice">分點資料尚不完整，持續吸籌分析需要多日分點記錄。'
            ' Branch data coverage building up.</div>',
            unsafe_allow_html=True,
        )
        return

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    latest_date = snaps[-1].get("date", "?")
    first_seen, last_seen = _presence_dates(snaps)

    rows_pa = []
    for ticker, ctx in candidates:
        spon  = ctx["sponsorship"]
        # 1.8.0:vel/accel/net_cumulative/buy_days 都從 snapshot 直接讀
        stock = latest_stocks.get(ticker, {})
        name  = stock.get("name") or _short_name(ticker)
        cost  = stock.get("main_force_cost")
        vel   = stock.get("velocity_3d")
        accel = stock.get("acceleration")
        mom_txt, mom_rank = _momentum_glyph(vel, accel)
        fresh_txt, fresh_rank = _freshness_label(ticker, first_seen, last_seen, latest_date)
        rows_pa.append({
            "資料": fresh_txt,
            "代號": ticker,
            "名稱": name,
            "動能": mom_txt,
            "累計(張)": _stock_net_accumulation(stock),
            "買超(日)": _stock_buy_days_in_window_or_none(stock),  # 1.7.0 缺欄位顯示「—」
            "主力分點": spon.get("top_persistent_broker") or "—",
            "分點(日)": spon.get("top_broker_days") or 0,
            "成本": f"NT${cost:,.2f}" if cost else "—",
            "Tier A": "★" if ticker in TIER_A else "",
            "_mom": mom_rank,
            "_fresh": fresh_rank,
        })

    import pandas as _pd
    df_pa = (
        _pd.DataFrame(rows_pa)
        .sort_values(["_mom", "_fresh", "累計(張)"], ascending=[True, True, False])
        .drop(columns=["_mom", "_fresh"])
    )
    st.caption("排序：動能方向 → 資料新鮮度 → 累計買超 ｜ 贊助分已移除（全名單同值無鑑別度），明細請見個股展開")
    st.dataframe(
        _style_signal_df(
            df_pa,
            color_cols=[],
            text_cols=["動能", "資料"],
            fmt={"累計(張)": "{:+,.0f}", "買超(日)": "{:d}/20", "分點(日)": "{:d} 日"},
        ),
        use_container_width=True,
        hide_index=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 6 — Leadership Rotation  資金輪動
# ─────────────────────────────────────────────────────────────────────────────

def _render_leadership_rotation(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    rot = leadership_rotation(snaps)

    _section_header("⟳", "資金輪動", "Leadership Rotation")

    if rot.get("rotation_detected"):
        f_zh = SECTOR_GROUPS.get(rot["rotation_from"], {}).get("zh", rot["rotation_from"] or "?")
        t_zh = SECTOR_GROUPS.get(rot["rotation_to"],   {}).get("zh", rot["rotation_to"]   or "?")
        st.markdown(
            f'<div class="regime-transition">⚡ 輪動偵測：{f_zh} → {t_zh}'
            f' &nbsp; Rotation detected: {rot["rotation_from"]} → {rot["rotation_to"]}</div>',
            unsafe_allow_html=True,
        )

    if rot["leading_sector"]:
        st.markdown(
            f'<div style="margin:12px 0;font-size:16px;color:#CDD5E0;">'
            f'今日資金主流 &nbsp; <strong style="color:#52B788;">'
            f'{rot["leading_label_zh"]} / {rot["leading_label_en"]}</strong></div>',
            unsafe_allow_html=True,
        )

    # Horizontal bar chart
    flows = rot["sector_flows"]
    if flows:
        max_abs = max((abs(v["total_buy"]) for v in flows.values()), default=1)
        for sector in rot["ranked_sectors"]:
            data  = flows[sector]
            buy   = data["total_buy"]
            label = data.get("label_zh", sector)
            pct   = abs(buy) / max(max_abs, 1) * 100
            color = "#52B788" if buy > 0 else "#E05C7A"
            sign  = "+" if buy >= 0 else ""
            count = data.get("ticker_count", 0)
            st.markdown(
                f'<div class="rot-bar-wrap">'
                f'<div class="rot-sector-label">{label}</div>'
                f'<div class="rot-bar-bg"><div class="rot-bar-fill" style="width:{pct:.1f}%;background:{color};"></div></div>'
                f'<div class="rot-bar-val" style="color:{color};">{sign}{buy:,}張</div>'
                f'<div style="font-size:11px;color:#4A5A6A;width:40px;">{count}支</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Cross-date sector chart
    if len(snaps) >= 2:
        st.markdown("<br>", unsafe_allow_html=True)
        _section_header("📈", "族群走勢", "Sector Flow Trend (Last 5 Dates)")
        dates = rot.get("snap_dates", [])[-5:]

        # Build sector flows per date
        sector_series: dict[str, list[int]] = {}
        for snap in snaps[-5:]:
            snap_flows: dict[str, int] = {}
            for s in snap.get("stocks", []):
                grp = stock_group(s.get("ticker", ""))
                snap_flows[grp] = snap_flows.get(grp, 0) + (s.get("main_force_buy") or 0)
            for grp, val in snap_flows.items():
                if grp not in sector_series:
                    sector_series[grp] = [0] * max(0, len(snaps[-5:]) - 1)
                sector_series[grp].append(val)

        fig = go.Figure()
        colors_map = {
            "semiconductor": "#7EB8D4", "electronics": "#9E8AC8",
            "financials": "#52B788", "shipping": "#D4A84B",
            "memory": "#E05C7A", "ai_infra": "#5ABCB8", "other": "#4A5A6A",
        }
        top_sectors = sorted(sector_series.keys(),
                             key=lambda k: abs(sector_series[k][-1]) if sector_series[k] else 0,
                             reverse=True)[:5]
        for grp in top_sectors:
            vals = sector_series.get(grp, [])
            if len(vals) < len(dates):
                vals = [0] * (len(dates) - len(vals)) + vals
            vals = vals[-len(dates):]
            label = SECTOR_GROUPS.get(grp, {}).get("zh", grp)
            fig.add_trace(go.Scatter(
                x=dates, y=vals,
                mode="lines+markers",
                name=label,
                line=dict(color=colors_map.get(grp, "#6B8EAA"), width=2),
                marker=dict(size=5),
            ))
        fig.update_layout(**_plotly_layout("族群主力買超趨勢", 260))
        fig.update_yaxes(ticksuffix="張")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 7 — Temporal Chains  時序演化
# ─────────────────────────────────────────────────────────────────────────────

def _render_temporal_chains(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return

    all_tickers: set[str] = set()
    for snap in snaps:
        for s in snap.get("stocks", []):
            all_tickers.add(s.get("ticker", ""))
    all_tickers.discard("")
    sorted_tickers = sorted(all_tickers)

    # Always include Tier A in selector; all others also get company names
    select_options = (
        ["全部 All"] +
        [_name(t) for t in tier_a_tickers() if t in all_tickers] +
        [_name(t) for t in sorted_tickers if t not in TIER_A]
    )

    col_sel, col_lookback = st.columns([3, 1])
    with col_sel:
        selected = st.selectbox("選擇標的 Select ticker", select_options, key="tc_ticker")
    with col_lookback:
        _tc_max = max(3, min(len(snaps), 15))
        _tc_def = max(3, min(len(snaps), 10))
        if len(snaps) < 3:
            st.caption(f"快照不足 3 天，無法顯示時序圖 (目前 {len(snaps)} 天)")
            return
        lookback = st.slider("觀察天數 Days", 3, _tc_max, _tc_def, key="tc_lb")

    focus_tickers: list[str]
    if selected == "全部 All":
        # Show cross-date table for all tickers
        focus_tickers = sorted_tickers
    else:
        code = selected.split(" ")[0]
        focus_tickers = [code]

    recent_snaps = snaps[-lookback:]
    recent_dates = [s.get("date", "?") for s in recent_snaps]

    _section_header("⌛", "時序演化", "Temporal Chains", len(focus_tickers))

    if len(focus_tickers) == 1:
        # ── Single ticker: detailed chain view ───────────────────────────
        ticker = focus_tickers[0]
        meta   = TIER_A.get(ticker, {})

        st.markdown(
            f'<div style="font-size:20px;font-weight:800;color:#7EB8D4;margin-bottom:16px;">'
            f'{_name(ticker)}</div>',
            unsafe_allow_html=True,
        )

        # 1.8.0:streak / net_accumulation 從 snapshot 讀;sponsorship 仍走 ctx
        latest_snap = snaps[-1] if snaps else {}
        stock_latest = next((s for s in latest_snap.get("stocks", []) if s.get("ticker") == ticker), {})
        ctx = full_ticker_context(ticker, snaps)
        spon = ctx["sponsorship"]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("連買天數 Strict",  f"{_stock_streak(stock_latest)}日",
                    help="嚴格連續尾部買超天數(任何缺日或賣超皆中斷)")
        _win_v = _stock_buy_days_in_window_or_none(stock_latest)
        col2.metric("窗口買超 Window",
                    f"{_win_v}/20" if _win_v is not None else "—",
                    help="過去 20 個交易日內主力買超天數(鬆語意,缺日不計但不中斷)。"
                         "舊 1.7.0 快照無此欄位,顯示「—」;明日 pipeline 跑出 1.8.0 即生效。")
        col3.metric("累計買超 Net",      f"{_stock_net_accumulation(stock_latest):+,}張",
                    help="20 天窗口內主力買超累計")
        col4.metric("贊助持續 Sponsor", f"{spon['persistence_score']:.0%}")

        st.markdown("<br>", unsafe_allow_html=True)

        # Chain rows
        header = ('<div class="chain-row" style="border-bottom:2px solid #253A52;">'
                  '<div class="chain-date" style="color:#7EB8D4;font-weight:700;">日期 Date</div>'
                  '<div class="chain-price" style="color:#7EB8D4;font-weight:700;">收盤 Close</div>'
                  '<div class="chain-chg" style="color:#7EB8D4;font-weight:700;">漲跌% Chg</div>'
                  '<div class="chain-mf" style="color:#7EB8D4;font-weight:700;">主力買超 MF</div>'
                  '<div style="flex:1;color:#7EB8D4;font-weight:700;font-size:12px;">分點/成本</div>'
                  '</div>')

        rows_html = header
        for snap in recent_snaps:
            rec = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
            date  = snap.get("date", "?")
            price = rec.get("current_price") if rec else None
            chg   = rec.get("change_pct")    if rec else None
            mfb   = rec.get("main_force_buy") if rec else None
            cost  = rec.get("main_force_cost") if rec else None
            br    = rec.get("top5_branches")   if rec else []

            chg_col  = "#52B788" if (chg or 0) > 0 else ("#E05C7A" if (chg or 0) < 0 else "#6B8EAA")
            dot_col  = "#52B788" if (mfb or 0) > 0 else ("#E05C7A" if (mfb or 0) < 0 else "#3A4A5A")
            price_s  = f"NT${price:,.1f}" if price else "—"
            chg_s    = f"{chg:+.2f}%" if chg is not None else "—"
            mfb_s    = f"{mfb:+,}" if mfb is not None else "—"
            br_s     = f"{len(br)}支分點" if br else ("無分點" if rec else "不在追蹤")
            cost_s   = f"成本 NT${cost:,.2f}" if cost else ""
            detail   = f"{br_s} {cost_s}".strip() if rec else "─ 不在本日宇宙"

            rows_html += (
                f'<div class="chain-row">'
                f'<div class="chain-date">{date}</div>'
                f'<div class="chain-price">{price_s}</div>'
                f'<div class="chain-chg" style="color:{chg_col};">{chg_s}</div>'
                f'<div class="chain-mf"><span class="chain-dot" style="background:{dot_col};display:inline-block;vertical-align:middle;margin-right:4px;"></span>{mfb_s}張</div>'
                f'<div style="flex:1;font-size:11px;color:#4A5A6A;">{detail}</div>'
                f'</div>'
            )

        st.markdown(rows_html, unsafe_allow_html=True)

    else:
        # ── Multi-ticker: heatmap table ──────────────────────────────────
        rows = []
        for ticker in focus_tickers:
            row: dict = {"標的": _name(ticker)}
            for snap in recent_snaps:
                date = snap.get("date", "?")
                rec  = next((s for s in snap.get("stocks", []) if s.get("ticker") == ticker), None)
                if rec:
                    mfb  = rec.get("main_force_buy") or 0
                    chg  = rec.get("change_pct") or 0
                    row[date] = f"{mfb:+,}"
                else:
                    row[date] = "—"
            rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 8 — Market Narrative  市場敘事
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _cached_narrative(n_dates: int) -> dict:
    """Generate narrative report; keyed by number of loaded dates so it
    invalidates whenever a new snapshot is added."""
    return _narrative_generate(lookback=n_dates)


def _render_narrative(snaps: list[dict], part: str = "all") -> None:
    """P3.0 拆分:part='themes' 只渲染主題觀察;'watchpoints' 只渲染
    持續出現/重要轉換/可能假突破;'all' 含雙語長文(已無人呼叫,封存備查)。"""
    if not snaps:
        st.info("尚無快照資料 No snapshot data.")
        return

    with st.spinner("生成市場敘事… generating narrative…"):
        report = _cached_narrative(len(snaps))

    if part in ("all", "themes"):
        _render_narrative_bullets_and_themes(report, include_bullets=(part == "all"))
    if part in ("all", "watchpoints"):
        _render_narrative_watchpoints(report)


def _render_narrative_bullets_and_themes(report: dict, include_bullets: bool) -> None:
    if include_bullets:
        _render_narrative_bullets(report)
    _render_narrative_themes(report)


def _render_narrative_bullets(report: dict) -> None:
    dr = report.get("date_range", [])
    dr_str = f"{dr[0]}  →  {dr[-1]}" if len(dr) == 2 else report.get("latest_date", "")

    # ── Header strip ─────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:12px;color:#6B8EAA;margin-bottom:18px;letter-spacing:.06em;">'
        f'GENERATED {report.get("generated_at","")} &nbsp;·&nbsp; WINDOW {dr_str}</div>',
        unsafe_allow_html=True,
    )

    # ── Section A: Market Narrative bullets ──────────────────────────────
    _section_header("📰", "市場敘事", "Market Narrative")
    bullets = report.get("market_narrative", [])
    rows = ""
    for i, b in enumerate(bullets, 1):
        zh = b.get("zh", "")
        en = b.get("en", "")
        is_alert = zh.startswith("⚡")
        bg = "#1E1A0A" if is_alert else "#111820"
        border = "#D4A84B" if is_alert else "#1F2D3D"
        rows += (
            f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
            f'padding:12px 16px;margin-bottom:8px;">'
            f'<div style="font-size:15px;font-weight:600;color:#CDD5E0;margin-bottom:4px;">'
            f'{i}. {zh}</div>'
            f'<div style="font-size:13px;color:#6B8EAA;font-style:italic;">{en}</div>'
            f'</div>'
        )
    st.markdown(rows, unsafe_allow_html=True)

    st.markdown('<div style="margin:28px 0 0 0;"></div>', unsafe_allow_html=True)


def _render_narrative_themes(report: dict) -> None:
    # ── Section B: Key Themes  (3 columns) ───────────────────────────────
    _section_header("🔑", "主題觀察", "Key Themes")
    st.markdown(_EXPLAIN_DIV.format(
        text="從近幾日快照歸納的三個市場主題：板塊輪動（錢在換場子嗎）、資金方向（整體進或出）、"
             "強弱對比（誰在領漲誰在破位）。"),
        unsafe_allow_html=True)
    themes = report.get("key_themes", {})
    theme_defs = [
        ("sector_rotation",      "⟳", "板塊輪動", "Sector Rotation"),
        ("capital_flow",         "◉", "資金方向", "Capital Flow"),
        ("strength_vs_weakness", "↕", "強弱對比", "Strength vs Weakness"),
    ]
    cols = st.columns(3, gap="small")
    for col, (key, icon, zh_label, en_label) in zip(cols, theme_defs):
        t = themes.get(key, {})
        with col:
            st.markdown(
                f'<div class="stock-card">'
                f'<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                f'letter-spacing:.08em;margin-bottom:8px;">{icon} {zh_label} / {en_label}</div>'
                f'<div style="font-size:14px;color:#CDD5E0;margin-bottom:6px;line-height:1.5;">'
                f'{t.get("zh","—")}</div>'
                f'<div style="font-size:12px;color:#6B8EAA;font-style:italic;line-height:1.5;">'
                f'{t.get("en","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="margin:28px 0 0 0;"></div>', unsafe_allow_html=True)


def _render_narrative_watchpoints(report: dict) -> None:
    # ── Section C: Notable Entities ──────────────────────────────────────
    st.markdown(_EXPLAIN_DIV.format(
        text="持續出現＝在每日買超榜反覆現身的個股（主力沒走）；重要轉換＝首次上榜或消失後重現；"
             "可能假突破＝放量急漲後連續回落，籌碼沒跟上價格。"),
        unsafe_allow_html=True)
    ent = report.get("notable_entities", {})
    col_left, col_mid, col_right = st.columns(3, gap="small")

    # Persistent tickers
    with col_left:
        pers = ent.get("persistent_tickers", [])
        _section_header("◈", "持續出現個股", "Persistent Tickers")
        if not pers:
            st.markdown('<div class="data-gap-notice">無符合資料</div>', unsafe_allow_html=True)
        for e in pers:
            streak = e.get("current_streak", 0)
            cov    = e.get("coverage_pct", 0)
            sc = "streak-active" if streak >= 3 else ("streak-warn" if streak >= 1 else "streak-none")
            st.markdown(
                f'<div class="stock-card">'
                f'<span class="stock-ticker">{e["ticker"]}</span>'
                f'<span class="stock-name">{_short_name(e["ticker"])}</span>'
                f'<div style="margin-top:6px;">'
                f'<span class="radar-streak {sc}">{streak}日連續</span>'
                f'<span class="signal-tag" style="margin-left:6px;">覆蓋率 {cov:.0f}%</span>'
                f'</div>'
                f'<div style="font-size:12px;color:#6B8EAA;margin-top:6px;font-style:italic;">'
                f'{e.get("note_en","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Strongest transitions
    with col_mid:
        trans = ent.get("strongest_transitions", [])
        _section_header("↩", "重要轉換", "Notable Transitions")
        if not trans:
            st.markdown('<div class="data-gap-notice">無符合資料</div>', unsafe_allow_html=True)
        for e in trans:
            ev = e.get("event", "")
            tag_cls = "fii" if "REAPPEAR" in ev else "mf"
            tag_label = "重現" if "REAPPEAR" in ev else "首次"
            st.markdown(
                f'<div class="stock-card">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                f'<span><span class="stock-ticker">{e["ticker"]}</span>'
                f'<span class="stock-name">{_short_name(e["ticker"])}</span></span>'
                f'<span class="signal-tag {tag_cls}">{tag_label}</span>'
                f'</div>'
                f'<div style="font-size:12px;color:#8B949E;margin-top:6px;">{e.get("date","")}</div>'
                f'<div style="font-size:12px;color:#6B8EAA;margin-top:4px;font-style:italic;line-height:1.4;">'
                f'{e.get("note_en","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # False breakouts
    with col_right:
        fbs = ent.get("possible_false_breakouts", [])
        _section_header("⚠", "可能假突破", "Possible False Breakouts")
        if not fbs:
            st.markdown(
                '<div class="data-gap-notice" style="background:#0F1E17;border-color:#2E6B4A;color:#52B788;">'
                '目前未偵測到假突破訊號</div>',
                unsafe_allow_html=True,
            )
        for e in fbs:
            bchg = e.get("breakout_chg", 0)
            vrat = e.get("vol_ratio", 0)
            ret  = e.get("retreat_days", 0)
            st.markdown(
                f'<div class="stock-card" style="border-color:#5A1A28;">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                f'<span><span class="stock-ticker" style="color:#E05C7A;">{e["ticker"]}</span>'
                f'<span class="stock-name">{_short_name(e["ticker"])}</span></span>'
                f'<span class="signal-tag red">假突破</span>'
                f'</div>'
                f'<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">'
                f'<span class="signal-tag">突破 +{bchg:.1f}%</span>'
                f'<span class="signal-tag">量比 {vrat:.1f}×</span>'
                f'<span class="signal-tag warn">回落 {ret}日</span>'
                f'</div>'
                f'<div style="font-size:12px;color:#6B8EAA;margin-top:6px;font-style:italic;line-height:1.4;">'
                f'{e.get("note_en","")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 9 — Golden Layer  黃金名單
# ─────────────────────────────────────────────────────────────────────────────

def _snaps_key(snaps: list[dict]) -> str:
    """Cheap cache discriminator — date of last snap + count."""
    if not snaps:
        return "empty"
    return f"{snaps[-1].get('date')}_{len(snaps)}"


@st.cache_data(ttl=120, show_spinner=False)
def _run_golden(key: str, snaps: list[dict]) -> "_golden_mod.GoldenResult":
    return _golden_mod.run(snaps)


@st.cache_data(ttl=120, show_spinner=False)
def _run_confidence(key: str, snaps: list[dict]) -> "_conf_mod.ConfidenceResult":
    return _conf_mod.run(snaps)


def _run_sm_all(snaps: list[dict]) -> "dict[str, _sm_mod.TickerState]":
    """Not cached via st.cache_data — nested dataclasses can trip pickle/display magic.
    Golden result is already cached; SM adds minimal overhead."""
    return _sm_mod.run_all(snaps)


def _render_golden(snaps: list[dict], show_near_miss: bool = True) -> None:  # noqa: C901  (P3h.5 research UX)
    if not snaps:
        st.info("尚無快照資料 No snapshot data.")
        return

    key = _snaps_key(snaps)
    with st.spinner("計算黃金名單… computing golden layer…"):
        result        = _run_golden(key, snaps)
        sm_states     = _run_sm_all(snaps)
        resonance_map = _resonance_mod.run_all(snaps)

    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    active_date   = snaps[-1].get("date", "")
    intel         = _intel_load(active_date)  # may be None

    # Distribution Intelligence Layer (display-only; parallel to Golden, never
    # affects Golden scoring/tiers — see core/distribution.py docstring + the
    # "scd-distribution-layer-plan" memory for the architectural contract).
    dist_result = _dist_load(active_date)  # may be None
    dist_map: dict[str, "_dist_mod.DistributionEntry"] = (
        {entry.ticker: entry for entry in dist_result.entries} if dist_result else {}
    )

    prime_n  = len(result.prime)
    strong_n = len(result.strong)
    qual_n   = len(result.qualified)
    miss_n   = len(result.near_miss)
    all_entries = result.prime + result.strong + result.qualified

    # ── Weakening cross-check (display-only, parallel to Golden) ─────────
    # P5: read pre-computed weakening from latest snapshot stocks.
    # NEVER affects tier/score/gates — purely a contradiction witness.
    _golden_universe = {e.ticker for e in all_entries} | {e.ticker for e in result.near_miss}
    _latest_stocks_map = {s["ticker"]: s for s in (snaps[-1].get("stocks", []) if snaps else [])}
    weak_map: dict[str, dict] = {}
    for _t in _golden_universe:
        _s = _latest_stocks_map.get(_t, {})
        _w_stored = _s.get("weakening")
        if _w_stored and _w_stored.get("severity", "none") != "none":
            weak_map[_t] = {"ticker": _t, **_w_stored}
        elif not _w_stored:
            # Fallback for old snapshots: compute on-the-fly
            _bd = _load_branches_for_ticker(_t)
            _w = weakening_profile(_t, snaps, _bd or None)
            if _w["severity"] != "none":
                weak_map[_t] = _w

    # ── Helpers ──────────────────────────────────────────────────────────

    # State display metadata
    _STATE_META = {
        "undiscovered":  ("#4A5A6A", "未發現"),
        "accumulating":  ("#7EB8D4", "吸籌中"),
        "confirmed":     ("#52B788", "成熟確認"),
        "strengthening": ("#D4A84B", "轉強中"),
        "distributing":  ("#E05C7A", "疑似出貨"),
        "exited":        ("#3A4A5A", "已出場"),
        "watching":      ("#9E8AC8", "觀察中"),
    }

    def _state_color(state: str) -> str:
        return _STATE_META.get(state, ("#8B949E", "—"))[0]

    def _state_zh(state: str, fallback: str = "—") -> str:
        return _STATE_META.get(state, ("#8B949E", fallback))[1]

    # Determine new entrant tickers from today's intelligence events
    _new_entrant_tickers: set[str] = set()
    if intel:
        from core.intelligence_delta import EVT_GOLDEN_ENTRY
        for ev in intel.new_today:
            if ev.event_type == EVT_GOLDEN_ENTRY and ev.ticker:
                _new_entrant_tickers.add(ev.ticker)

    # Determine momentum: Strengthening / Stable / Weakening
    # Uses acceleration + velocity trend from GoldenEntry
    def _momentum(e: "_golden_mod.GoldenEntry") -> str:
        acc = e.acceleration or 0
        vel = e.velocity_3d or 0
        if acc > 500 or (acc > 0 and vel > 3000):
            return "strengthening"
        if acc < -500 or (acc < 0 and vel < 0):
            return "weakening"
        return "stable"

    # ── P1: PRIME category labels (observational, display only) ─────────
    _CAT_META = {
        "institutional": ("🏛", "Institutional Prime", "#D4A84B"),
        "momentum":      ("🔥", "Momentum Prime",      "#52B788"),
        "emerging":      ("🌱", "Emerging Prime",       "#7EB8D4"),
        "aging":         ("⚠",  "Aging Prime",          "#E8A838"),
    }

    def _prime_categories(e: "_golden_mod.GoldenEntry") -> list[str]:
        """Return observational category labels for a PRIME entry.
        A ticker may belong to multiple categories."""
        if e.tier.lower() != "prime":
            return []
        cats: list[str] = []
        vel = e.velocity_3d or 0
        acc = e.acceleration or 0
        # Institutional: steady accumulation with strong sponsorship
        if (e.streak or 0) >= 5 and e.sponsorship_score >= 0.7 and (e.net_cumulative or 0) > 0:
            cats.append("institutional")
        # Momentum: velocity + acceleration both positive, in strong state
        if vel > 0 and acc > 0 and e.sm_state in {"strengthening", "confirmed", "accumulating"}:
            cats.append("momentum")
        # Emerging: recently entered current state (proxy for newly PRIME)
        if (e.days_in_sm_state or 0) <= 3:
            cats.append("emerging")
        # Aging: still PRIME but momentum fading
        if vel < 0 or acc < 0:
            cats.append("aging")
        return cats if cats else ["institutional"]  # fallback

    # ── P2: Institutional Checklist ──────────────────────────────────────
    def _institutional_checklist(e: "_golden_mod.GoldenEntry", stock: dict) -> tuple[int, int, str]:
        """Returns (passed, total, html_detail) for the institutional checklist."""
        mf_cost   = getattr(e, "main_force_cost", None)
        cur_price_val = stock.get("current_price") or getattr(e, "current_price", None)
        items = []

        # 1. Consecutive accumulation
        streak_n = e.streak or 0
        if streak_n >= 5:
            items.append(("✓", "連續買超", f"{streak_n} 日連續主力買超", True))
        elif streak_n >= 1:
            items.append(("△", "連續買超", f"連買 {streak_n} 日（≥5日視為確認）", None))
        else:
            items.append(("✗", "連續買超", "無持續買超紀錄", False))

        # 2. Sponsorship strength
        spon = e.sponsorship_score
        if spon >= 0.7:
            items.append(("✓", "主力回頭率", f"回頭率 {spon:.0%}（≥70%,同一主力鎖碼）", True))
        elif spon >= 0.45:
            items.append(("△", "主力回頭率", f"回頭率 {spon:.0%}（≥70% 視為強）", None))
        else:
            items.append(("✗", "主力回頭率", f"回頭率 {spon:.0%}，偏低（買盤分散）", False))

        # 3. Institutional alignment — from T86 fii_sync_count (0-3)
        sync = stock.get("fii_sync_count")
        fii  = stock.get("fii_net_buy")
        trust = stock.get("dealer_net_buy")   # 投信，mapped from T86 trust
        if sync is None:
            items.append(("—", "法人同向", "資料待補（T86 三大法人）", None))
        elif sync >= 2:
            parts = []
            if (stock.get("main_force_buy") or 0) > 0: parts.append("主力✓")
            if fii and fii > 0: parts.append("外資✓")
            if trust and trust > 0: parts.append("投信✓")
            items.append(("✓", "法人同向", f"{'  '.join(parts)}  （{sync}/3 方淨買）", True))
        elif sync == 1:
            items.append(("△", "法人同向", f"單方淨買（{sync}/3 方），同向未達標", None))
        else:
            items.append(("✗", "法人同向", "三大法人均未淨買", False))

        # 4. Cost support
        if mf_cost and mf_cost > 0 and cur_price_val and cur_price_val > 0:
            dist = (cur_price_val - mf_cost) / mf_cost * 100
            if abs(dist) <= 5:
                items.append(("✓", "主力成本支撐", f"現價距成本 {dist:+.1f}%，在安全區間 ±5% 內", True))
            elif dist > 5:
                items.append(("△", "主力成本支撐", f"現價高於成本 {dist:.1f}%（偏離安全區）", None))
            else:
                items.append(("✗", "主力成本支撐", f"現價低於成本 {abs(dist):.1f}%", False))
        else:
            items.append(("—", "主力成本支撐", "無主力成本資料", None))

        # 5. Concentration (data unavailable in current pipeline)
        items.append(("—", "籌碼集中度", "資料待補（大戶持股變化）", None))

        passed = sum(1 for sym, _, _, ok in items if ok is True)
        total  = sum(1 for sym, _, _, ok in items if ok is not None)

        # Build inline checklist rows (compact)
        rows = []
        for sym, label, detail, ok in items:
            sym_col = {"✓": "#52B788", "✗": "#E05C7A", "△": "#E8A838", "—": "#4A5A6A"}[sym]
            label_col = "#CDD5E0" if ok is True else ("#8B949E" if ok is False else "#6B8EAA")
            rows.append(
                f'<div style="display:flex;gap:6px;align-items:baseline;padding:3px 0;">'
                f'<span style="color:{sym_col};font-size:12px;width:14px;flex-shrink:0;">{sym}</span>'
                f'<span style="font-size:12px;color:{label_col};width:80px;flex-shrink:0;">{label}</span>'
                f'<span style="font-size:11px;color:#4A6A8A;">{detail}</span>'
                f'</div>'
            )
        detail_html = "".join(rows)
        return passed, total, detail_html

    # ── P3: Learning Layer — load/update checklist history ───────────────
    import json as _json_ll
    _HISTORY_PATH = _AI_STOCK / "data" / "checklist_history.json"

    def _load_history() -> dict:
        if _HISTORY_PATH.exists():
            try:
                return _json_ll.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_history(h: dict) -> None:
        try:
            _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_PATH.write_text(_json_ll.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _update_history(history: dict, entries: list) -> dict:
        """Record today's checklist state; mark past entries as still_active or not."""
        active_tickers = {e.ticker for e in entries}
        # Mark past entries
        for ticker, records in history.items():
            for rec in records:
                if rec.get("still_active") is None:  # not yet resolved
                    rec["still_active"] = ticker in active_tickers
        # Add today's records for active entries
        for e in entries:
            stock = latest_stocks.get(e.ticker, {})
            _, _, _ = _institutional_checklist(e, stock)  # just compute state
            streak_ok = (e.streak or 0) >= 5
            spon_ok   = e.sponsorship_score >= 0.7
            mf_cost   = getattr(e, "main_force_cost", None)
            cur_p     = stock.get("current_price") or getattr(e, "current_price", None)
            cost_ok   = bool(mf_cost and cur_p and abs((cur_p - mf_cost) / mf_cost * 100) <= 5)
            rec = {
                "date": active_date,
                "tier": e.tier,
                "streak": e.streak,
                "sponsorship": round(e.sponsorship_score, 3),
                "checklist": {"consecutive": streak_ok, "sponsorship": spon_ok, "cost_support": cost_ok},
                "still_active": None,  # resolved on next run
            }
            # Only add if not already recorded for this date
            ticker_records = history.setdefault(e.ticker, [])
            if not any(r["date"] == active_date for r in ticker_records):
                ticker_records.append(rec)
        return history

    def _history_stats(history: dict, ticker: str) -> str:
        """Return a short HTML stats line if history exists for this ticker."""
        records = [r for r in history.get(ticker, []) if r.get("still_active") is not None]
        if len(records) < 3:  # not enough history to show
            return ""
        still = sum(1 for r in records if r["still_active"])
        failed = len(records) - still
        pct = still / len(records) * 100
        return (
            f'<div style="font-size:11px;color:#6B8EAA;margin-top:4px;padding:4px 8px;'
            f'background:#0D1821;border-radius:5px;">'
            f'📊 觀測紀錄 {len(records)} 次 · 持續在列 {still} · 離開 {failed} · 留存率 {pct:.0f}%'
            f'</div>'
        )

    # Build lifecycle timeline HTML from TickerState.transitions
    def _lifecycle_timeline(e: "_golden_mod.GoldenEntry") -> str:
        ts = sm_states.get(e.ticker)
        if not ts or not ts.transitions:
            # Fallback: just show current state
            col = _state_color(e.sm_state)
            return (
                f'<div class="lc-wrap">'
                f'<div class="lc-node">'
                f'<div class="lc-dot lc-dot-active" style="background:{col};border-color:{col};box-shadow:0 0 7px {col};"></div>'
                f'<div class="lc-label" style="color:{col};">{e.sm_state_zh}<br>{e.sm_state_entered or ""}</div>'
                f'</div></div>'
            )

        # Show up to last 5 transitions + current state
        transitions = ts.transitions[-5:]
        nodes = []
        for tr in transitions:
            col = _state_color(tr.from_state)
            zh  = _state_zh(tr.from_state, tr.from_state)
            d   = tr.date[5:] if tr.date else ""  # MM-DD
            nodes.append(
                f'<div class="lc-node">'
                f'<div class="lc-dot" style="background:{col}40;border-color:{col};"></div>'
                f'<div class="lc-label">{zh}<br>{d}</div>'
                f'</div>'
                f'<div class="lc-line"></div>'
            )
        # Current state node (active)
        cur_col = _state_color(e.sm_state)
        entered = (e.sm_state_entered or "")
        entered_short = entered[5:] if len(entered) >= 7 else entered
        nodes.append(
            f'<div class="lc-node">'
            f'<div class="lc-dot lc-dot-active" style="background:{cur_col};border-color:{cur_col};box-shadow:0 0 7px {cur_col};"></div>'
            f'<div class="lc-label" style="color:{cur_col};font-weight:700;">{e.sm_state_zh}<br>{entered_short}</div>'
            f'</div>'
        )
        return f'<div class="lc-wrap">{"".join(nodes)}</div>'

    # Build "Why It Matters" text
    def _why_matters(e: "_golden_mod.GoldenEntry") -> str:
        parts = []
        if e.streak >= 5:
            parts.append(f"連續 {e.streak} 日主力買超")
        elif e.streak >= 3:
            parts.append(f"連買 {e.streak} 日呈現持續吸籌")
        if e.sponsorship_score >= 0.8:
            parts.append(f"贊助強度達 {e.sponsorship_score:.0%}，法人高度集中")
        elif e.sponsorship_score >= 0.5:
            parts.append(f"贊助度 {e.sponsorship_score:.0%}")
        if (e.velocity_3d or 0) > 5000:
            parts.append("近三日動能加速顯著")
        elif (e.velocity_3d or 0) > 1000:
            parts.append("近三日動能為正")
        if e.sm_state in ("confirmed", "strengthening"):
            parts.append(f"狀態進入「{e.sm_state_zh}」")
        if e.is_tier_a:
            parts.append("屬 Tier-A 核心標的")
        if not parts:
            return "通過所有篩選門檻，觀察中。"
        return "，".join(parts) + "。"

    # Build "Watch Next" tags
    def _watch_next(e: "_golden_mod.GoldenEntry") -> list[str]:
        tags = []
        if e.sm_state == "accumulating":
            tags.append("等待確認突破")
        if e.sm_state == "confirmed":
            tags.append("觀察是否延續")
        if e.sm_state == "strengthening":
            tags.append("動能持續確認中")
        if (e.velocity_3d or 0) > 0 and (e.acceleration or 0) > 0:
            tags.append("加速中")
        return tags or ["持續觀察"]

    # Build "Invalidation" tags
    def _invalidation(e: "_golden_mod.GoldenEntry") -> list[str]:
        tags = []
        if e.sm_state == "distributing":
            tags.append("已進入出貨警戒")
        if (e.streak or 0) == 0:
            tags.append("連買中斷")
        if (e.acceleration or 0) < -500:
            tags.append("動能快速衰退")
        if e.sponsorship_score < 0.3:
            tags.append("贊助顯著下滑")
        return tags or ["無明顯失效訊號"]

    # Build "Recent Changes" from intel events — strips redundant ticker/name prefix,
    # prefixes each line with MM-DD date so context is clear without repetition.
    def _recent_changes(ticker: str) -> list[tuple[str, str]]:
        """Returns list of (date_str, text) tuples."""
        if not intel:
            return []
        date_pfx = active_date[5:] if len(active_date) >= 7 else active_date  # MM-DD
        changes = []
        for ev in (intel.new_today + intel.upgrades + intel.downgrades + intel.risk_alerts):
            if ev.ticker != ticker or not ev.zh:
                continue
            text = ev.zh
            # Strip leading "XXXX Name " prefix since card already shows the ticker
            for prefix in (f"{ev.ticker} {ev.name} ", f"{ev.ticker} "):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
            changes.append((date_pfx, text.strip()))
        return changes[:3]

    # Gate labels (kept for diagnostics expander)
    _GATE_LABELS = {
        "G1": "G1 漏斗確認", "G2": "G2 狀態強勢",
        "G3": "G3 贊助≥45%", "G4": "G4 風險<臨界", "G5": "G5 淨累計>0",
    }

    # ── Load learning-layer history once, update at end ─────────────────
    _checklist_history = _load_history()

    # ── Research card renderer (P4 fixed-height observation card) ────────
    def _research_card(
        e: "_golden_mod.GoldenEntry",
        is_new: bool = False,
        near_miss: bool = False,
    ) -> None:
        stock     = latest_stocks.get(e.ticker, {})
        price     = stock.get("current_price")
        chg       = stock.get("change_pct")
        price_s   = f"NT${price:,.2f}" if price else "—"
        chg_s     = f"{chg:+.2f}%" if chg is not None else "—"
        chg_col   = "#52B788" if (chg or 0) > 0 else ("#E05C7A" if (chg or 0) < 0 else "#6B8EAA")
        streak_n  = e.streak or 0

        # Card + badge classes — P2.6 action-aware label (可買進/增強/中)
        _dt      = _golden_mod.display_tier(
            e, weak_map.get(e.ticker, {}).get("severity", "none"))
        _dt_css  = {_golden_mod.DTIER_BUY: "prime",
                    _golden_mod.DTIER_STRENGTHEN: "qualified",
                    _golden_mod.DTIER_MID: "strong"}[_dt]
        _dt_zh   = _golden_mod.DTIER_ZH[_dt]
        _dt_icon = _dt_stars(_dt)   # P2.9: 星級取代色點 icon
        if near_miss:
            card_cls = "gc-card gc-qualified"
            badge_cls = "gc-badge gc-badge-qualified"
            badge_txt = "△ 差一步"
        elif is_new:
            card_cls = "gc-card gc-new"
            badge_cls = "gc-badge gc-badge-new"
            badge_txt = f"✦ 新進 {_dt_icon}{_dt_zh}"
        else:
            card_cls = f"gc-card gc-{_dt_css}"
            badge_cls = f"gc-badge gc-badge-{_dt_css}"
            badge_txt = f"{_dt_icon} {_dt_zh}"

        # ── Weakening cross-check pill (display-only) ────────────────────
        _wk = weak_map.get(e.ticker)
        card_style = ""
        weak_html = ""
        if _wk and _wk["severity"] in ("red", "orange"):
            _wc = "#E05C7A" if _wk["severity"] == "red" else "#E8A33D"
            _wdot = "🔴" if _wk["severity"] == "red" else "🟠"
            _wcodes = "·".join(f["code"] for f in _wk["flags"])
            # Hover ⓘ: this ticker's triggered flags (detail) + W1–W5 legend
            _w_lines = "".join(
                f'<b>{f["code"]} {f["zh"]}</b> — {f["detail"]}<br>' for f in _wk["flags"])
            _w_tip = (
                '<div class="gc-tooltip-wrap">'
                '<span class="gc-tooltip-icon">ⓘ</span>'
                '<div class="gc-tooltip" style="white-space:normal;width:330px;">'
                f'{_w_lines}'
                '<span style="color:#6B8EAA;">'
                'W1 動能衰竭｜W2 雙引擎分歧｜W3 主力消失（缺席買超榜≠賣出）｜'
                'W4 散戶接盤｜W5 分點賣壓'
                '</span></div></div>'
            )
            weak_html = (
                f'<div class="gc-signal-pill" style="background:{_wc}20;color:{_wc};'
                f'border:1px solid {_wc}60;font-weight:700;">'
                f'{_wdot} {_wk["label_zh"]}警示 {_wcodes}{_w_tip}'
                f'</div>'
            )
            if _wk["severity"] == "red":
                card_style = ' style="border-color:#E05C7A;"'

        state_col = _state_color(e.sm_state)
        days_txt  = f" Day{e.days_in_sm_state}" if e.days_in_sm_state else ""

        # ── Cost / price distance ─────────────────────────────────────────
        mf_cost   = getattr(e, "main_force_cost", None)
        cur_price = price or getattr(e, "current_price", None)
        if mf_cost and mf_cost > 0 and cur_price and cur_price > 0:
            dist_pct  = (cur_price - mf_cost) / mf_cost * 100
            cost_s    = f"NT${mf_cost:,.2f}"
            if abs(dist_pct) <= 5:
                dist_col, dist_sym = "#52B788", "✓"
            elif dist_pct > 5:
                dist_col, dist_sym = "#E8A838", "↑"
            else:
                dist_col, dist_sym = "#E05C7A", "↓"
            dist_s = f'<span style="color:{dist_col};font-weight:700;">{dist_pct:+.1f}% {dist_sym}</span>'
        else:
            cost_s, dist_s, dist_pct = "—", '<span style="color:#6B8EAA;">—</span>', None

        # ── Resonance (Sprint 2) ──────────────────────────────────────────
        res = resonance_map.get(e.ticker)
        if res and res.resonance_level >= 1:
            res_col  = {1: "#6B8EAA", 2: "#7EB8D4", 3: "#D4A84B"}.get(res.resonance_level, "#6B8EAA")
            res_stars = res.stars
            res_label = res.resonance_label_zh
            # Member checkmarks
            _p_labels = {"main_force": "主力", "foreign": "外資", "invest_trust": "投信"}
            members_html = " ".join(
                f'<span style="color:{"#52B788" if s is True else "#3A4A5A" if s is False else "#4A5A6A"};">'
                f'{zh}{"✓" if s is True else "✗" if s is False else "—"}</span>'
                for pid, zh in _p_labels.items()
                for s in [res.participant_status.get(pid)]
            )
            res_html = (
                f'<div class="gc-signal-pill" style="background:{res_col}15;'
                f'color:{res_col};border:1px solid {res_col}40;">'
                f'{res_stars} {res_label}'
                f'&nbsp;&nbsp;<span style="font-size:10px;font-weight:400;">{members_html}</span>'
                + (f'&nbsp;<span style="font-size:10px;color:#6B8EAA;">連{res.resonance_streak}日</span>'
                   if res.resonance_streak >= 2 else "")
                + f'</div>'
            )
        else:
            res_html = '<div class="gc-signal-pill" style="background:#1A1A2A;color:#4A5A6A;border:1px solid #2A2A3A;">共振 資料待補</div>'

        # ── Chip momentum score ───────────────────────────────────────────
        mkt_vol = stock.get("market_volume")
        cs = _chip_mod.compute(
            streak=streak_n,
            sponsorship=e.sponsorship_score,
            fii_sync_count=stock.get("fii_sync_count"),
            main_force_buy=stock.get("main_force_buy"),
            market_volume=mkt_vol,
            main_force_cost=mf_cost,
            current_price=cur_price,
        )
        # 卡片上只露「強度」標籤,不露分子/分母(分母會隨缺資料浮動,無參考意義)
        chip_bar = (
            f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
            f'background:{cs.grade_color};margin-right:5px;vertical-align:middle;"></span>'
            f'<b style="color:{cs.grade_color};">{cs.grade}</b>'
        )

        # ── Volume ratio ─────────────────────────────────────────────────
        # Compute from snapshot history
        vol_ratio: float | None = None
        if mkt_vol and mkt_vol > 0:
            vol_hist = [
                s_snap.get("stocks", [])
                for s_snap in snaps[-20:]
            ]
            vol_vals = []
            for snap_stocks in vol_hist:
                sv = next((x.get("market_volume") for x in snap_stocks if x.get("ticker") == e.ticker), None)
                if sv and sv > 0:
                    vol_vals.append(sv)
            if len(vol_vals) >= 3:
                avg_vol  = sum(vol_vals[:-1]) / len(vol_vals[:-1])
                vol_ratio = mkt_vol / avg_vol if avg_vol > 0 else None

        vol_label, vol_col = _chip_mod.volume_label(vol_ratio)
        vol_ratio_s = f"{vol_ratio:.1f}x" if vol_ratio is not None else "—"

        # Tooltip for 量能比
        tooltip_html = (
            '<div class="gc-tooltip-wrap">'
            '<span class="gc-tooltip-icon">ⓘ</span>'
            '<div class="gc-tooltip">'
            '主力大買 + 健康放量 → 市場跟進<br>'
            '主力大買 + 縮量 → 可能默默吸籌<br>'
            '主力大買 + 爆量 → 留意出貨可能'
            '</div></div>'
        )

        # ── PRIME category tags 已移除（觀察分類無實際意義,Yonki 2026-06-27）───
        cat_html = ""

        # ── Momentum ──────────────────────────────────────────────────────
        mom = _momentum(e)
        mom_col = {"strengthening": "#52B788", "stable": "#7EB8D4", "weakening": "#E8A838"}.get(mom, "#6B8EAA")
        mom_zh  = {"strengthening": "↑ 動能強化", "stable": "→ 穩定", "weakening": "↓ 動能衰退"}.get(mom, "—")

        # ── Distribution Intelligence Layer (display-only, parallel system) ──
        # Shows 籌碼一致性 / 安全邊際 / 建議動作 from core/distribution.py.
        # This NEVER feeds into Golden tier/score — purely supplemental risk
        # display per the user's "Golden 邏輯保持不變" requirement.
        dist_e = dist_map.get(e.ticker)
        if dist_e is not None:
            dist_html = (
                f'<div class="gc-signal-pill" style="background:{dist_e.consistency_color}15;'
                f'color:{dist_e.consistency_color};border:1px solid {dist_e.consistency_color}40;" '
                f'title="{dist_e.consistency_reason}">'
                f'籌碼一致性&nbsp;<b>{dist_e.consistency_grade}</b>'
                f'&nbsp;({dist_e.consistency_score:+d})'
                f'</div>'
                f'<div class="gc-signal-pill" style="background:{dist_e.safety_color}15;'
                f'color:{dist_e.safety_color};border:1px solid {dist_e.safety_color}40;" '
                f'title="{dist_e.safety_hint}">'
                f'安全邊際&nbsp;<b>{dist_e.safety_label}</b>'
                + (f'&nbsp;{dist_e.safety_margin:.2f}x' if dist_e.safety_margin is not None else "")
                + f'</div>'
                f'<div class="gc-signal-pill" style="background:#161B26;color:#9E8AC8;'
                f'border:1px solid #9E8AC840;" title="{dist_e.suggested_detail}">'
                f'建議動作&nbsp;<b>{dist_e.suggested_action}</b>'
                f'</div>'
            )
            if dist_e.flagged_for_removal:
                dist_html += (
                    f'<div class="gc-signal-pill" style="background:#E05C7A20;color:#E05C7A;'
                    f'border:1px solid #E05C7A60;font-weight:700;" '
                    f'title="{dist_e.flag_reason or ""}">'
                    f'⚠ 建議自黃金名單移出（display-only）'
                    f'</div>'
                )
        else:
            dist_html = ""

        # ── LAYER 1: Fixed-height card HTML ──────────────────────────────
        card_html = (
            f'<div class="{card_cls}"{card_style}>'
            # Row 1: header
            f'<div class="gc-head">'
            f'<span class="gc-ticker">{e.ticker}</span>'
            f'<span class="gc-name">{e.name}</span>'
            f'<span class="{badge_cls}">{badge_txt}</span>'
            f'<span class="gc-state" style="background:{state_col}20;color:{state_col};border:1px solid {state_col}50;">'
            f'{e.sm_state_zh}{days_txt}</span>'
            + (f'<span style="margin-left:2px;">{cat_html}</span>' if cat_html else "")
            + f'<span class="gc-price" style="color:{chg_col};">{price_s} <span style="font-size:12px;">{chg_s}</span></span>'
            f'</div>'
            # Divider
            f'<hr class="gc-divider">'
            # Row 2: key metrics grid (3-column, 6 items)
            + f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 8px;margin:6px 0;">'
            f'<div class="gc-metric"><span class="gc-metric-label">主力連買</span><span class="gc-metric-val" style="color:#7EB8D4;">{streak_n}日{(" · 窗" + str(_stock_buy_days_in_window(stock))) if _stock_buy_days_in_window(stock) > streak_n else ""}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">贊助強度</span><span class="gc-metric-val" style="color:#D4A84B;">{e.sponsorship_score:.0%}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">主力成本</span><span class="gc-metric-val">{cost_s}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">3日速度</span><span class="gc-metric-val">{f"{e.velocity_3d:+,.0f}" if e.velocity_3d is not None else "—"}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">加速度</span><span class="gc-metric-val">{f"{e.acceleration:+,.0f}" if e.acceleration is not None else "—"}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">淨累計</span><span class="gc-metric-val">{f"{e.net_cumulative:+,}" if e.net_cumulative else "—"}張</span></div>'
            f'</div>'
            # Divider
            f'<hr class="gc-divider">'
            # Row 3: signals
            f'<div class="gc-signals">'
            f'{res_html}'
            f'<div class="gc-signal-pill" style="background:#161B26;color:{cs.grade_color};border:1px solid {cs.grade_color}40;">'
            f'籌碼動能&nbsp;{chip_bar}'
            f'</div>'
            f'<div class="gc-signal-pill" style="background:#161B26;color:{vol_col};border:1px solid {vol_col}40;">'
            f'量能比&nbsp;<b>{vol_ratio_s}</b>&nbsp;{vol_label}'
            f'&nbsp;{tooltip_html}'
            f'</div>'
            f'<div class="gc-signal-pill" style="background:#161B26;color:{mom_col};border:1px solid {mom_col}40;">'
            f'{mom_zh}'
            f'</div>'
            + dist_html + weak_html +
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

        # ── LAYER 2: Expandable detail ────────────────────────────────────
        with st.expander(f"展開詳細 — {e.ticker} {e.name}", expanded=False):
            # 2a. Institutional checklist
            cl_passed, cl_total, cl_detail = _institutional_checklist(e, stock)
            history_stats = _history_stats(_checklist_history, e.ticker)
            # 2b. Chip momentum evidence — 改為「證據列表」格式(Yonki 2026-06-27)
            # 不再露分子/分母(分母浮動無意義);改成 ✓/△/— 列出 6 個訊號各自的可讀說明。
            _evidence: list[tuple[str, str]] = []  # [(sym, text), ...]

            def _ev_row(sym: str, text: str) -> None:
                _evidence.append((sym, text))

            # 1) 投量比(主力買超占當日成交量)
            it_vr = cs.items.get("vol_ratio", {})
            if it_vr.get("available"):
                mfb_local = stock.get("main_force_buy") or 0
                ratio = abs(mfb_local) / mkt_vol if mkt_vol else 0
                if ratio >= 0.12:
                    _ev_row("✓", f"買超占成交量 {ratio:.0%}")
                elif ratio >= 0.06:
                    _ev_row("△", f"買超占成交量 {ratio:.0%}（中等）")
                else:
                    _ev_row("△", f"買超占成交量 {ratio:.0%}（偏低）")
            else:
                _ev_row("—", "買超占成交量（市場成交量資料待補）")

            # 2) 連續買超(嚴格) + 窗口買超(鬆語意)
            if streak_n >= 7:
                _ev_row("✓", f"連續買超 {streak_n} 天")
            elif streak_n >= 3:
                _ev_row("△", f"連續買超 {streak_n} 天（≥7天為強）")
            elif streak_n >= 1:
                _ev_row("△", f"連續買超 {streak_n} 天（≥3天為基本）")
            else:
                _ev_row("—", "無連續買超")

            # 2b) 窗口買超 — 20 天內主力買超天數(鬆語意,輔助參考)
            _pos_days = _stock_buy_days_in_window(stock)
            if _pos_days > streak_n:  # 只有當鬆語意大於嚴格時才有額外資訊量
                if _pos_days >= 12:
                    _ev_row("✓", f"窗口買超 {_pos_days}/20 天（高頻吸籌）")
                elif _pos_days >= 7:
                    _ev_row("△", f"窗口買超 {_pos_days}/20 天（中頻）")
                else:
                    _ev_row("△", f"窗口買超 {_pos_days}/20 天（偶現）")

            # 3) 主力成本支撐
            if mf_cost and mf_cost > 0 and cur_price and cur_price > 0:
                dist = (cur_price - mf_cost) / mf_cost * 100
                if abs(dist) <= 2:
                    _ev_row("✓", f"主力成本 {dist:+.1f}%（貼近）")
                elif dist <= 5:
                    _ev_row("✓", f"主力成本 {dist:+.1f}%（安全區）")
                elif dist > 5:
                    _ev_row("△", f"主力成本 {dist:+.1f}%（偏離安全區）")
                else:
                    _ev_row("△", f"主力成本 {dist:+.1f}%（低於成本）")
            else:
                _ev_row("—", "主力成本資料待補")

            # 4) Velocity(3 日速度)
            vel = e.velocity_3d
            if vel is None:
                _ev_row("—", "3 日速度資料待補")
            elif vel > 1000:
                _ev_row("✓", f"Velocity ↑（3 日速度 +{vel:,.0f}）")
            elif vel > 0:
                _ev_row("△", f"Velocity ↑（3 日速度 +{vel:,.0f},力道有限）")
            elif vel < -1000:
                _ev_row("△", f"Velocity ↓（3 日速度 {vel:,.0f}）")
            else:
                _ev_row("△", f"Velocity 持平（3 日速度 {vel:,.0f}）")

            # 5) 法人同向
            sync = stock.get("fii_sync_count")
            if sync is None:
                _ev_row("—", "法人同向資料待補（T86）")
            elif sync >= 2:
                _ev_row("✓", f"法人同向 {sync}/3 方淨買")
            elif sync == 1:
                _ev_row("△", "法人未同步（僅 1/3 方）")
            else:
                _ev_row("△", "法人未同步（0/3 方淨買）")

            # 6) TDCC 集中度(永遠未接,顯示一致)
            _ev_row("—", "TDCC 籌碼集中度未接入")

            # Build evidence rows HTML
            chip_rows = ""
            for sym, text in _evidence:
                sc = {"✓": "#52B788", "△": "#E8A838", "—": "#4A5A6A"}[sym]
                tc = "#CDD5E0" if sym == "✓" else ("#9E8AB8" if sym == "△" else "#6B8EAA")
                chip_rows += (
                    f'<div style="display:flex;gap:10px;align-items:baseline;padding:3px 0;">'
                    f'<span style="color:{sc};width:14px;flex-shrink:0;font-weight:700;">{sym}</span>'
                    f'<span style="font-size:12px;color:{tc};flex:1;">{text}</span>'
                    f'</div>'
                )
            # 2c. Lifecycle + changes
            lifecycle_html = _lifecycle_timeline(e)
            changes = _recent_changes(e.ticker)
            changes_html = ""
            if changes:
                tags = "".join(
                    f'<span class="g5-tag g5-tag-change-up">'
                    f'<span style="color:#4A6A8A;font-size:10px;margin-right:4px;">{d}</span>{txt}'
                    f'</span>'
                    for d, txt in changes
                )
                changes_html = f'<div class="g5-section-label">近期變化</div><div class="g5-tag-row">{tags}</div>'
            watch_tags = "".join(f'<span class="g5-tag g5-tag-watch">{t}</span>' for t in _watch_next(e))
            inval_tags = "".join(f'<span class="g5-tag g5-tag-inval">{t}</span>' for t in _invalidation(e))
            st.markdown(
                # Checklist
                f'<div style="padding:8px 10px;background:#0A1018;border-radius:7px;border:1px solid #1A2232;margin-bottom:8px;">'
                f'<div style="font-size:10px;color:#4A6A8A;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">🏛 機構觀察清單 · 通過 {cl_passed}/{cl_total}</div>'
                f'{cl_detail}{history_stats}</div>'
                # Chip Momentum Evidence(改證據列表,不再顯示浮動的分子/分母)
                f'<div style="padding:8px 10px;background:#0A1018;border-radius:7px;border:1px solid #1A2232;margin-bottom:8px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
                f'<div style="font-size:10px;color:#4A6A8A;text-transform:uppercase;letter-spacing:.06em;">'
                f'Chip Momentum Evidence · 籌碼動能證據</div>'
                f'<div style="font-size:11px;color:#6B8EAA;">'
                f'Strength <b style="color:{cs.grade_color};">{cs.grade}</b></div>'
                f'</div>'
                f'{chip_rows}</div>'
                # Lifecycle + Changes
                f'<div class="g5-section-label">狀態演進</div>{lifecycle_html}'
                f'{changes_html}'
                f'<div style="margin-top:8px;">'
                f'<div class="g5-section-label">觀察重點</div><div class="g5-tag-row">{watch_tags}</div>'
                f'<div class="g5-section-label" style="margin-top:6px;">失效訊號</div>'
                f'<div class="g5-tag-row">{inval_tags}</div></div>',
                unsafe_allow_html=True,
            )

        # ── Diagnostics expander (gates + score breakdown) ────────────────
        gate_labels = _GATE_LABELS
        gates_html  = '<div class="gate-row">'
        for gk in ["G1", "G2", "G3", "G4", "G5"]:
            passed   = gk in (e.gates_passed or [])
            cls      = "gate-pass" if passed else "gate-fail"
            lbl      = gate_labels.get(gk, gk)
            gates_html += f'<span class="{cls}">{"✓" if passed else "✗"} {lbl}</span>'
        gates_html += '</div>'
        sb_items = "".join(
            f'<span class="g5-tag g5-tag-neutral">{k}: {v:.2f}</span>'
            for k, v in (e.score_breakdown or {}).items()
        )
        conv_pct = int(e.conviction * 100)
        with st.expander(f"▼ 診斷資料 — {e.ticker} {e.name}", expanded=False):
            st.markdown(
                f'<div style="font-size:13px;color:#CDD5E0;margin-bottom:8px;line-height:1.6;">'
                f'<b style="color:#D4A84B;">黃金分 {conv_pct}%</b> — 過五道門後的加分賽總分（0–100%）。'
                f' 分數越高代表證據越多元且一致：連買天數長、主力回頭率高、動能為正且加速、處於強勢狀態。'
                f' ≥65% 為最高級（搭配價格條件才會顯示 🟢可買進），40–64% 增強，&lt;40% 中。'
                f'</div>'
                f'{gates_html}'
                f'<div style="margin-top:8px;"><div class="g5-section-label">各項得分拆解</div>'
                f'<div class="g5-tag-row">{sb_items}</div></div>',
                unsafe_allow_html=True,
            )

    # ── P2: Action grouping (行動分組) — logic lives in core.golden ──────
    # Each ticker lands in exactly ONE group; new entrants render first as
    # their own section then rejoin their action group next session.
    _red = {t for t, w in weak_map.items() if w["severity"] == "red"}
    action_of: dict[str, str] = {
        e.ticker: _golden_mod.action_group(
            e, weak_map.get(e.ticker, {}).get("severity", "none"))
        for e in all_entries
    }

    # P2.6: action-aware plain-language tier (可買進/增強/中). Logic in core.golden.
    dtier_of: dict[str, str] = {
        e.ticker: _golden_mod.display_tier(
            e, weak_map.get(e.ticker, {}).get("severity", "none"))
        for e in all_entries
    }
    _buy_n = sum(1 for v in dtier_of.values() if v == _golden_mod.DTIER_BUY)
    _str_n = sum(1 for v in dtier_of.values() if v == _golden_mod.DTIER_STRENGTHEN)
    _mid_n = sum(1 for v in dtier_of.values() if v == _golden_mod.DTIER_MID)

    new_entrants = sorted(
        [e for e in all_entries if e.ticker in _new_entrant_tickers
         and action_of[e.ticker] != _golden_mod.ACTION_WEAKENING],
        key=lambda e: e.conviction, reverse=True)
    _shown_new = {e.ticker for e in new_entrants}

    action_groups: dict[str, list] = {k: [] for k in _golden_mod.ACTION_ORDER}
    for e in all_entries:
        if e.ticker in _shown_new:
            continue
        action_groups[action_of[e.ticker]].append(e)
    for k in action_groups:
        # Within group: conviction desc; weakening group puts red lights first
        if k == _golden_mod.ACTION_WEAKENING:
            action_groups[k].sort(key=lambda e: (e.ticker not in _red, -e.conviction))
        else:
            action_groups[k].sort(key=lambda e: e.conviction, reverse=True)

    _n_of = {k: len(v) for k, v in action_groups.items()}

    # ── Summary metric strip — action-first (P2) ─────────────────────────
    _metric_strip([
        ("黃金總覽 Total", str(prime_n + strong_n + qual_n),
         f"⭐⭐⭐可買進{_buy_n} ⭐⭐增強{_str_n} ⭐中{_mid_n}", "val-cyan"),
        ("🟢 可執行",   str(_n_of[_golden_mod.ACTION_EXECUTABLE]),    "價格在保守錨容忍內", "val-green"),
        ("🟡 等回檔",   str(_n_of[_golden_mod.ACTION_WAIT_PULLBACK]), "結構好、價格延伸",   "val-amber"),
        ("🔵 資料待補", str(_n_of[_golden_mod.ACTION_DATA_PENDING]),  "SKELETON/缺錨點",   "val-cyan"),
        ("🔻 動能轉弱", str(_n_of[_golden_mod.ACTION_WEAKENING]),
         "紅橙燈/疑似出貨", "val-red" if _n_of[_golden_mod.ACTION_WEAKENING] else "val-dim"),
        ("⊘ 差一步",    str(miss_n), "僅差1個門檻", "val-dim"),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Session Narrative ─────────────────────────────────────────────────
    bullets: list[str] = []
    total_n = prime_n + strong_n + qual_n
    if total_n == 0:
        bullets.append("目前黃金名單無符合標的，需要更多歷史快照積累。")
    else:
        bullets.append(f"本日黃金名單共 {total_n} 檔，其中 ⭐⭐⭐可買進 {_buy_n} / ⭐⭐增強 {_str_n} / ⭐中 {_mid_n}。三星＝結構強＋現價在主力成本5%內＋未轉弱。")
    if new_entrants:
        tickers_s = "、".join(f"{e.ticker} {e.name}" for e in new_entrants[:3])
        suffix = f"等{len(new_entrants)}檔" if len(new_entrants) > 3 else ""
        bullets.append(f"今日新進名單：{tickers_s}{suffix}。")
    _exec_list = action_groups[_golden_mod.ACTION_EXECUTABLE]
    if _exec_list:
        tickers_s = "、".join(f"{e.ticker} {e.name}" for e in _exec_list[:3])
        bullets.append(f"🟢 可執行：{tickers_s}{'等' if len(_exec_list) > 3 else ''}。")
    _weak_list = action_groups[_golden_mod.ACTION_WEAKENING]
    if _weak_list:
        tickers_s = "、".join(f"{e.ticker} {e.name}" for e in _weak_list[:2])
        bullets.append(f"🔻 需注意動能轉弱：{tickers_s}。")
    if intel and intel.market_story:
        story_txt = intel.market_story[0] if isinstance(intel.market_story, list) else str(intel.market_story)
        bullets.append(story_txt[:80] + ("…" if len(story_txt) > 80 else ""))

    bullet_html = "".join(
        f'<div class="g5-narrative-bullet"><span class="g5-narrative-dot">◆</span><span>{b}</span></div>'
        for b in bullets[:4]
    )
    st.markdown(
        f'<div class="g5-narrative-wrap">'
        f'<div class="g5-narrative-title">📋 今日情況摘要  Session Narrative</div>'
        f'{bullet_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not all_entries:
        st.markdown(
            '<div class="data-gap-notice">目前無符合黃金名單條件的標的，需要更多歷史快照。'
            ' No golden entries yet — more snapshot history needed.</div>',
            unsafe_allow_html=True,
        )
        return

    def _render_section(entries: list, header_html: str, is_new: bool = False) -> None:
        """Render a 2-column grid of research cards under a section header."""
        if not entries:
            return
        st.markdown(header_html, unsafe_allow_html=True)
        cols = st.columns(2, gap="medium")
        for i, e in enumerate(entries):
            with cols[i % 2]:
                _research_card(e, is_new=is_new)

    # ── SECTION A: New Entrants (above Prime) ────────────────────────────
    _render_section(
        new_entrants,
        f'<div class="g5-new-header">'
        f'<span style="font-size:18px;">✦</span>'
        f'<span class="g5-new-header-text">今日新進名單  New Entrants</span>'
        f'<span class="g5-new-header-sub">{active_date} · {len(new_entrants)} 檔</span>'
        f'</div>',
        is_new=True,
    )

    # ── SECTIONS B–E: Action groups in execution-priority order (P2) ─────
    _W_LEGEND = (
        '<div class="gc-tooltip-wrap">'
        '<span class="gc-tooltip-icon">ⓘ</span>'
        '<div class="gc-tooltip" style="white-space:normal;width:340px;">'
        '<b>W1 動能衰竭</b> — 連買≥3日但速度轉負、買量遞減<br>'
        '<b>W2 雙引擎分歧</b> — 主力買超但外資賣超達主力買量30%<br>'
        '<b>W3 主力消失</b> — 曾連買≥3日，從買超榜缺席（≠賣出；缺席≥2日才可合成紅燈）<br>'
        '<b>W4 散戶接盤</b> — 券商家數差轉正，或價跌融資增≥3日/10日<br>'
        '<b>W5 分點賣壓</b> — 分點總賣&gt;總買，或前三買點邊買邊倒<br>'
        '<span style="color:#D4A84B;">紅 = 實錘W3+佐證 或 ≥3旗標；只有紅燈會強制移入本組</span>'
        '</div></div>'
    )
    for _ak in _golden_mod.ACTION_ORDER:
        _meta = _golden_mod.ACTION_META[_ak]
        _legend = _W_LEGEND if _ak == _golden_mod.ACTION_WEAKENING else ""
        _render_section(
            action_groups[_ak],
            f'<div class="g5-momentum-head">'
            f'<span class="g5-momentum-icon">{_meta["icon"]}</span>'
            f'<span class="g5-momentum-label" style="color:{_meta["color"]};">'
            f'{_meta["zh"]}  {_meta["en"]}</span>'
            f'<span class="g5-momentum-count">{len(action_groups[_ak])} 檔</span>'
            f'{_legend}'
            f'</div>',
        )

    # ── P3: Update and persist learning-layer history ────────────────────
    try:
        _checklist_history = _update_history(_checklist_history, all_entries)
        _save_history(_checklist_history)
    except Exception:
        pass  # never block rendering on history write failure

    # ── SECTION E: Near-miss — compact scout cards, distinct section ─────
    if show_near_miss and result.near_miss:
        near_sorted = sorted(result.near_miss, key=lambda e: e.conviction, reverse=True)

        # Build scout cards HTML
        scout_cards = []
        for e in near_sorted:
            # near-miss failed a gate → never 可買進; label by conviction only
            _sdt = (_golden_mod.DTIER_STRENGTHEN if e.conviction >= _golden_mod.TIER_STRONG
                    else _golden_mod.DTIER_MID)
            tier_sym = _golden_mod.DTIER_ICON[_sdt]
            _sdt_zh  = _golden_mod.DTIER_ZH[_sdt]
            conv_pct = int(e.conviction * 100)
            # Which gate(s) are missing?
            all_gates = ["G1", "G2", "G3", "G4", "G5"]
            failed_gs = [g for g in all_gates if g not in (e.gates_passed or [])]
            fail_txt  = "缺 " + "、".join({
                "G1": "漏斗確認", "G2": "狀態強勢", "G3": "贊助≥45%",
                "G4": "風險<臨界", "G5": "淨累計>0",
            }.get(g, g) for g in failed_gs) if failed_gs else "全通"
            state_col = _state_color(e.sm_state)
            scout_cards.append(
                f'<div class="g5-scout-card">'
                f'<div class="g5-scout-head">'
                f'<span class="g5-scout-ticker">{e.ticker}</span>'
                f'<span class="g5-scout-name">{e.name}</span>'
                f'<span class="g5-scout-badge">{tier_sym} {_sdt_zh}</span>'
                f'<span style="font-size:11px;padding:1px 7px;border-radius:8px;'
                f'background:{state_col}20;color:{state_col};border:1px solid {state_col}50;margin-left:6px;">'
                f'{e.sm_state_zh}</span>'
                f'</div>'
                f'<div class="g5-scout-bar-wrap">'
                f'<span style="font-size:10px;color:#4A4A7A;width:52px;flex-shrink:0;">信念</span>'
                f'<div class="g5-scout-bar-bg"><div class="g5-scout-bar-fill" style="width:{conv_pct}%;"></div></div>'
                f'<span style="font-size:11px;color:#6B5FA8;width:28px;flex-shrink:0;text-align:right;">{conv_pct}%</span>'
                f'</div>'
                f'<div class="g5-scout-miss">△ {fail_txt}'
                f'&nbsp;·&nbsp; 連買 {e.streak}日 &nbsp;·&nbsp; 贊助 {e.sponsorship_score:.0%}</div>'
                f'</div>'
            )

        # Render as 3 columns inside the scout section block
        st.markdown(
            f'<div class="g5-scout-section">'
            f'<div class="g5-scout-header">'
            f'<span style="font-size:14px;">△</span>'
            f'<span class="g5-scout-title">觀察候補  Near-Miss Watchzone</span>'
            f'<span class="g5-scout-sub">僅差 1 個門檻 · {miss_n} 檔</span>'
            f'</div>'
            f'<div style="columns:3;column-gap:10px;">{"".join(scout_cards)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL — 潛力區 helpers  (P2.7: watch table + near-miss table; display-only,
# 全部讀既有 core 計算結果, 不做任何 render-time 業務邏輯)
# ─────────────────────────────────────────────────────────────────────────────

_EXPLAIN_DIV = ('<div style="font-size:10px;color:#969696;margin:-4px 0 10px 0;'
                'line-height:1.5;">{text}</div>')


# ── P2.9 星級顯示:黃金分級 = 星數(Yonki 2026-07-04:與三星階梯統一) ──────
def _dt_stars(dt: str) -> str:
    """display_tier → 星級(⭐進名單/⭐⭐增強/⭐⭐⭐可買進)。"""
    return {"buy": "⭐⭐⭐", "strengthen": "⭐⭐", "mid": "⭐"}.get(dt, "⭐")


# ── P2.8 降維顯示:分數不放 %,改 高/中/低 色點(門檻見 📖 說明) ──────────
def _lvl(score, hi: float, mid: float) -> str:
    """0-1 分數 → 🟢高/🟡中/⚪低(正向指標用)。"""
    if score is None:
        return "—"
    return f"🟢高" if score >= hi else (f"🟡中" if score >= mid else "⚪低")


def _lvl_risk(score) -> str:
    """警訊分(越高越糟)→ 🔴高/🟠中/🟢低。"""
    if score is None:
        return "—"
    return "🔴高" if score >= 0.5 else ("🟠中" if score >= 0.3 else "🟢低")


def _lvl_sponsor(score, days) -> str:
    """主力回頭率;分點樣本 <3 天 → 樣本不足(1/1=100% 假訊號防呆)。"""
    if not days or days < 3:
        return "⚪樣本不足"
    return _lvl(score, 0.7, 0.4)


def _render_score_glossary() -> None:
    """📖 邏輯說明 — 折疊區(P2.9:無粗體、灰字、無 code block —
    fenced block 會觸發 Streamlit SyntaxHighlighter 動態載入,雲端曾 TypeError)。"""
    with st.expander("📖 邏輯說明", expanded=False):
        st.markdown(
            '<div style="font-size:11px;color:#969696;line-height:1.9;">'
            '兩套獨立的計分系統，互相對照用:'
            '<br><br>'
            '① 黃金引擎（★進場機會）— 五道門檻＋加分賽，用星級表示:'
            '<br>⭐ 進黃金名單 ＝ 過五道門（G1 有在持續吃貨／G2 行為已成型／G3 主力有回頭／G4 無出貨嫌疑／G5 整體淨買）'
            '<br>⭐⭐ 增強 ＝ 黃金分高（過門後的加分賽:連買越久、回頭率越高、動能越正，分越高）'
            '<br>⭐⭐⭐ 可買進 ＝ 再加價格條件（現價 ≤ 主力成本×1.05 且未轉弱 — 5% 鐵則）'
            '<br><br>'
            '② 多空計分（🌱潛力區的精選觀察）— 獨立的證據天平:'
            '<br>多頭分 ＝ 多頭證據總量:連買＋回頭率＋動能＋黃金身分加權（🟢高≥60%｜🟡中≥40%）'
            '<br>警訊分 ＝ 空頭證據總量:疑似出貨+25%、假突破+20%、速度轉負+15% 等（🔴高≥50%｜🟠中≥30%）'
            '<br>兩者獨立計算，可能同時高——代表多空證據並存，要特別小心'
            '<br><br>'
            '共用的基礎指標:'
            '<br>主力回頭率 ＝ 同一家分點回頭買的頻率（🟢高≥70%:同一主力鎖碼｜🟡中≥40%｜⚪低:每天換人像散戶追價｜樣本不足:分點資料未滿 3 天不評分）'
            '<br>連買(日) ＝ 主力連續淨買超天數 ｜ 累計(張) ＝ 20 日窗口總買超 ｜ 速度 ＝ 近 3 日平均每天買幾張'
            '<br>疑似出貨 ＝ 之前強勢吸籌但買超動能連續轉負——主力可能在倒貨的「嫌疑」狀態（未定罪:缺席買超榜 ≠ 一定在賣）'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_watch_table(active_date: str) -> None:
    """精選觀察 — intelligence report watch_list rendered as a sortable table."""
    report = _intel_load(active_date) if active_date else None
    _section_header("◉", "精選觀察", "Top Watch (next 3–5 sessions)",
                    len(report.watch_list) if report else 0)
    st.markdown(_EXPLAIN_DIV.format(
        text="狀態機已達 吸籌中/轉強/已確認 的股票，依「狀態層級＋主力回頭率＋連買＋多頭分」加權排序取前 8。"
             "多頭分/警訊分是獨立於黃金名單的另一套多空證據計分——兩邊互相對照用。"
             "只有 10 秒的話，看這張表就夠。"),
        unsafe_allow_html=True)
    if not report or not report.watch_list:
        st.markdown('<div class="data-gap-notice">無觀察名單資料（今日情報尚未生成）</div>',
                    unsafe_allow_html=True)
        return
    import pandas as _pd
    rows = [{
        "代號": w.ticker,
        "名稱": w.name,
        "狀態": w.sm_state_zh,
        "連買(日)": w.streak,
        "主力回頭率": _lvl(w.sponsorship, 0.7, 0.4),
        "多頭分": _lvl(w.confidence, 0.6, 0.4),
        "警訊分": _lvl_risk(w.risk_score),
        "在此狀態(天)": w.days_in_state,
        "入選理由": w.reason_zh,
    } for w in report.watch_list]
    st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_near_miss_table(snaps: list[dict]) -> None:
    """黃金候補 — near-miss entries as a table (moved out of the golden tab)."""
    key = _snaps_key(snaps)
    result = _run_golden(key, snaps)
    near = sorted(result.near_miss, key=lambda e: e.conviction, reverse=True)
    _section_header("△", "黃金候補", "Near-Miss Watchzone", len(near))
    st.markdown(_EXPLAIN_DIV.format(
        text="黃金名單 5 道門檻（G1 漏斗確認／G2 狀態強勢／G3 回頭率≥45%／G4 無疑似出貨等臨界風險／G5 淨累計>0）"
             "剛好通過 4 道的股票——距離升級黃金最近的預備隊。「缺門檻」欄標出還差哪一道。"
             "黃金分＝過門後的加分賽總分（連買越久、回頭率越高、動能越正分數越高）。"),
        unsafe_allow_html=True)
    if not near:
        st.markdown('<div class="data-gap-notice">今日無候補標的（沒有剛好過 4 道門檻的股票）</div>',
                    unsafe_allow_html=True)
        return
    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    _gate_zh = {"G1": "漏斗確認", "G2": "狀態強勢", "G3": "回頭率≥45%",
                "G4": "風險<臨界", "G5": "淨累計>0"}
    import pandas as _pd
    rows = []
    for e in near:
        stock = latest_stocks.get(e.ticker, {})
        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        cost  = stock.get("main_force_cost")
        premium = (price / cost - 1) * 100 if (price and cost) else None
        failed = [g for g in ("G1", "G2", "G3", "G4", "G5")
                  if g not in (e.gates_passed or [])]
        rows.append({
            "代號": e.ticker,
            "名稱": e.name,
            "黃金分": _lvl(e.conviction, 0.65, 0.40),
            "缺門檻": "、".join(_gate_zh.get(g, g) for g in failed) or "—",
            "狀態": e.sm_state_zh,
            "連買(日)": e.streak or 0,
            "主力回頭率": _lvl(e.sponsorship_score, 0.7, 0.4),
            "現價": f"NT${price:,.2f}" if price else "—",
            "漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            "距主力成本": f"{premium:+.1f}%" if premium is not None else "—",
        })
    st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("距主力成本 >+5% 即使升級黃金也會被標「等回檔」，不符 5% 鐵則不追高。")


_EVT_LABEL = {
    "state_transition":        ("狀態轉換", False),
    "golden_entry":            ("進入黃金名單", False),
    "golden_exit":             ("退出黃金名單", False),
    "golden_tier_change":      ("黃金分級變化", False),
    "confidence_upgrade":      ("多頭分上升", True),
    "confidence_downgrade":    ("多頭分下降", True),
    "sponsorship_jump":        ("主力回頭率跳升", True),
    "sponsorship_collapse":    ("主力回頭率崩落", True),
    "risk_elevation":          ("警訊分上升", True),
    "risk_reduction":          ("警訊分下降", True),
}

_SEV_MARK = {"info": "·", "watch": "👀", "alert": "⚠", "critical": "🔴"}


def _event_table(events: list) -> None:
    """DailyEvent list → compact table（取代舊的逐筆卡片，省 2/3 篇幅）."""
    import pandas as _pd
    rows = []
    for e in events:
        label, is_pct = _EVT_LABEL.get(e.event_type, (e.event_type, False))
        fv, tv = e.from_value, e.to_value
        if is_pct and isinstance(fv, (int, float)) and isinstance(tv, (int, float)):
            change = f"{fv:.0%} → {tv:.0%} ({(tv - fv):+.0%})"
        elif fv is not None and tv is not None:
            change = f"{fv} → {tv}"
        else:
            change = "—"
        rows.append({
            "": _SEV_MARK.get(e.severity, "·"),
            "代號": e.ticker or "—",
            "名稱": e.name or "",
            "事件": label,
            "變化": change,
        })
    st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 height=min(38 + 35 * len(rows), 330))


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 10 — Confidence & Risk  信心風險
# ─────────────────────────────────────────────────────────────────────────────

def _render_confidence(snaps: list[dict]) -> None:
    if not snaps:
        st.info("尚無快照資料 No snapshot data.")
        return

    key = _snaps_key(snaps)
    with st.spinner("計算多空體檢… computing profiles…"):
        result = _run_confidence(key, snaps)

    temp  = result.market_temperature
    # profiles is a dict; use the pre-sorted lists
    profs = result.ideal + result.watch + result.deteriorating + result.weak

    # ── Temperature banner ────────────────────────────────────────────────
    temp_color_map = {
        "cool":    ("#7EB8D4", "#0A1520", "冷靜"),
        "stable":  ("#52B788", "#0A1F12", "穩定"),
        "warm":    ("#D4A84B", "#1F1508", "偏熱"),
        "hot":     ("#E05C7A", "#1F0A10", "過熱"),
        "extreme": ("#FF6B9D", "#2A0818", "極端"),
    }
    tc, tbg, tzh = temp_color_map.get(temp.temperature_level, ("#8B949E","#111820","—"))
    t_pct = int(temp.temperature * 100)

    st.markdown(
        f'<div class="temp-strip" style="background:{tbg};border-left-color:{tc};">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;">'
        f'<div>'
        f'<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">市場風險溫度 MARKET RISK TEMPERATURE</div>'
        f'<div style="font-size:28px;font-weight:800;color:{tc};line-height:1.2;">{tzh} · {temp.temperature_level.upper()}</div>'
        f'<div style="font-size:13px;color:#8B949E;margin-top:4px;">{temp.temperature_zh}</div>'
        f'</div>'
        f'<div style="text-align:right;">'
        f'<div style="font-size:36px;font-weight:800;color:{tc};">{t_pct}%</div>'
        f'<div style="font-size:11px;color:#6B8EAA;">溫度指數</div>'
        f'</div>'
        f'</div>'
        f'<div style="margin-top:12px;background:#1A2030;border-radius:6px;height:8px;overflow:hidden;">'
        f'<div style="width:{t_pct}%;height:100%;background:{tc};border-radius:6px;"></div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 數字條已刪(P3.2:與下方表格重複);溫度橫幅補說明 ─────────────────────
    st.markdown(_EXPLAIN_DIV.format(
        text="市場風險溫度＝全市場警訊訊號的加權濃度（高風險股佔比＋出貨中佔比＋廣度風險）。"
             "溫度越高，越該收手觀望。"),
        unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── 信心 × 風險 × 籌碼 三維泡泡圖 (Yonki 確認偏好此版, 2026-06-18) ────────
    #   X = 風險 (log scale, 避免擠角落)   Y = 信心   泡泡大小 = 淨累計買超
    #   顏色 = 引擎型態 (來自 core resonance, viewer 不做分級)
    #   PROXY: 信心/風險目前用 core/confidence 的代理值; P3b 評分引擎啟動後
    #   只需把 p.confidence / p.risk_score 換成系統真實欄位, 圖骨架不變。
    if profs:
        _section_header("◉", "多頭 × 警訊 × 籌碼 三維泡泡圖", "Bull × Alert × Flow Bubble Map")
        st.markdown(_EXPLAIN_DIV.format(
            text="一眼看全市場分布：越靠左上（多頭分高、警訊分低）越理想；泡泡越大＝主力累計買超越多。"
                 "滑鼠停在泡泡上看個股明細。"),
            unsafe_allow_html=True)
        reson_map = _resonance_mod.run_all(snaps)
        latest_ls = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
        KIND_COLOR = {"dual": "#4A9E6B", "single": "#4A7FC4", "diverge": "#C4544A"}
        KIND_ZH    = {"dual": "雙/三方共振", "single": "單引擎", "diverge": "法人背離"}

        def _engine_kind(ticker: str) -> str:
            # Display-only colour bucket from core signals (resonance level +
            # FII sign). No tier/score/gate logic — same display tier as heat radar.
            stk = latest_ls.get(ticker, {})
            fii = stk.get("fii_net_buy")
            rs  = reson_map.get(ticker)
            level = rs.resonance_level if rs else 0
            if fii is not None and fii < 0:
                return "diverge"
            if level >= 2:
                return "dual"
            return "single"

        # ── P3a DISPLAY-ONLY proxies (same tier as heat radar; NOT scoring) ──
        # Core risk_score piles ~35% of names at exactly 0 → they overlap on the
        # log axis into one blob. These spread the cloud using the demo's chip
        # proxy. Swap to the real confidence/risk fields when P3b activates; the
        # axes/skeleton stay the same.
        def _risk_proxy(stk: dict) -> float:
            # 追高風險: 當日漲幅 + 距主力成本距離 (越追高越右). Distinct non-zero
            # values so the log axis can separate names instead of stacking at 0.
            chg  = stk.get("change_pct") or 0
            price, cost = stk.get("current_price"), stk.get("main_force_cost")
            cdist = abs((price - cost) / cost * 100) if (price and cost) else 0
            return max(4.0, min(100.0, 4 + max(0.0, chg) * 1.8 + cdist * 1.2))

        def _conf_proxy(stk: dict, rs) -> float:
            # 雙引擎強度: 共振層級 + 外資同向 + 流量規模.
            fii   = stk.get("fii_net_buy") or 0
            net   = (stk.get("weakening") or {}).get("net_cumulative") or 0
            level = rs.resonance_level if rs else 0
            align = 12 if fii > 0 else (-12 if fii < 0 else 0)
            flow_b = min(25.0, (abs(net) ** 0.5) / 30)
            return max(2.0, min(100.0, 30 + level * 15 + align + flow_b))

        # Plot the main-force-flow universe (net cumulative ≠ 0), largest first,
        # capped for readability — mirrors the demo's "主力流向" set, not all 117 profiles.
        def _net_of(p):
            return (latest_ls.get(p.ticker, {}).get("weakening") or {}).get("net_cumulative") or 0
        flow = sorted([p for p in profs if _net_of(p)], key=lambda p: abs(_net_of(p)), reverse=True)[:30] or profs[:30]

        xs, ys, labels, sizes, colors, hover = [], [], [], [], [], []
        for p in flow:
            stk   = latest_ls.get(p.ticker, {})
            rs    = reson_map.get(p.ticker)
            net   = (stk.get("weakening") or {}).get("net_cumulative") or 0
            price = stk.get("current_price")
            chg   = stk.get("change_pct")
            cost  = stk.get("main_force_cost")
            dist  = ((price - cost) / cost * 100) if (price and cost) else None
            kind  = _engine_kind(p.ticker)
            risk_pct = _risk_proxy(stk)
            conf_pct = _conf_proxy(stk, rs)
            xs.append(risk_pct)
            ys.append(conf_pct)
            sizes.append(14 + (abs(net) ** 0.5) / 20)         # demo radius formula
            colors.append(KIND_COLOR[kind])
            labels.append(stk.get("name") or p.ticker)
            hover.append(
                f"<b>{p.ticker} {p.name}</b><br>"
                f"現價 {('NT$%.2f' % price) if price else '—'} "
                f"({('%+.2f%%' % chg) if chg is not None else '—'})<br>"
                f"淨累計 {net:+,} 張<br>"
                f"距主力成本 {('%+.1f%%' % dist) if dist is not None else '—'}<br>"
                f"多頭分(代理) {conf_pct:.0f}　警訊分(代理) {risk_pct:.0f}<br>"
                f"型態 {KIND_ZH[kind]}"
            )

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            text=labels, textposition="middle center",
            textfont=dict(size=9, color="#E8E4D8"),
            marker=dict(size=sizes, color=colors, opacity=0.45,
                        line=dict(width=1.5, color=colors), sizemode="diameter"),
            hovertext=hover, hoverinfo="text",
        ))
        # 理想區 (左上: 高信心 · 低風險)
        fig.add_shape(type="rect", x0=4, x1=12, y0=55, y1=100, layer="below",
                      fillcolor="rgba(201,151,58,0.06)", line=dict(width=0))
        fig.add_annotation(x=4, y=99, text="★ 理想區（多頭高·警訊低）", showarrow=False,
                           xanchor="left", yanchor="top",
                           font=dict(size=11, color="rgba(201,151,58,0.7)"))
        # 50% 多頭分隔線
        fig.add_hline(y=50, line_dash="dot", line_color="#2A3A4A", line_width=1)

        layout = _plotly_layout("多頭 × 警訊 × 籌碼 三維泡泡圖", 460)
        layout["xaxis"].update(dict(title="警訊分（代理 · 對數刻度）→", type="log",
                                    range=[0.60206, 2.0],
                                    tickvals=[5, 10, 20, 40, 80],
                                    ticktext=["5%", "10%", "20%", "40%", "80%"]))
        layout["yaxis"].update(dict(title="多頭分 ↑", range=[0, 105]))
        fig.update_layout(**layout)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            '<div style="font-size:11px;color:#7A8070;margin-top:-6px;line-height:1.7;">'
            '<span style="color:#4A9E6B;">●</span> 雙/三方共振　'
            '<span style="color:#4A7FC4;">●</span> 單引擎　'
            '<span style="color:#C4544A;">●</span> 法人背離　·　泡泡大小＝淨累計買超張數<br>'
            '⚠ P3a 代理值：多頭分/警訊分在圖上為籌碼代理計算；評分引擎正式啟動後改用系統真實欄位，圖骨架不變。'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 全市場體檢表(P3.2:側寫卡片牆 → 一張表格,舊詞全換新) ────────────────
    latest_stocks_ls = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    _section_header("☑", "全市場體檢表", "All Profiles", len(profs))
    st.markdown(_EXPLAIN_DIV.format(
        text="評級：🟢理想＝多頭分高＋警訊分低｜🟡中性＝多頭中等＋警訊低｜🟠留意＝警訊偏高｜"
             "🔴轉弱＝多頭崩、警訊竄升。排序：理想在前。搜尋用表格右上角 🔍。"),
        unsafe_allow_html=True)

    mid_low   = [p for p in result.profiles.values() if p.profile_code == "mid_low"]
    watch_all = result.watch + result.deteriorating + result.weak
    _grade_of = {}
    for p in result.ideal:
        _grade_of[p.ticker] = "🟢理想"
    for p in mid_low:
        _grade_of.setdefault(p.ticker, "🟡中性")
    for p in result.watch:
        _grade_of.setdefault(p.ticker, "🟠留意")
    for p in result.deteriorating + result.weak:
        _grade_of.setdefault(p.ticker, "🔴轉弱")

    ordered = result.ideal + mid_low + [p for p in watch_all if p.ticker not in
                                        {q.ticker for q in result.ideal} | {q.ticker for q in mid_low}]
    import pandas as _pd
    prof_rows = []
    for p in ordered:
        stock = latest_stocks_ls.get(p.ticker, {})
        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        prof_rows.append({
            "評級": _grade_of.get(p.ticker, "—"),
            "代號": p.ticker,
            "名稱": p.name,
            "現價": f"NT${price:,.2f}" if price else "—",
            "漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            "多頭分": _lvl(p.confidence, 0.6, 0.4),
            "警訊分": _lvl_risk(p.risk_score),
            "連買(日)": p.streak,
            "狀態": p.sm_state_zh,
            "風險描述": p.risk_zh,
        })
    if prof_rows:
        st.dataframe(_pd.DataFrame(prof_rows), use_container_width=True, hide_index=True,
                     height=min(38 + 35 * len(prof_rows), 500))

    if not profs:
        st.markdown(
            '<div class="data-gap-notice">尚無多空體檢資料，需要更多歷史快照。'
            ' No confidence profiles yet — more snapshot history needed.</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 11 — Daily Intelligence  📡 今日情報
# Reads from reports/YYYY-MM-DD.intelligence.json — NEVER recomputes.
# ─────────────────────────────────────────────────────────────────────────────

_SEV_ICON  = {SEV_CRITICAL: "🔴", SEV_ALERT: "🟠", SEV_WATCH: "🟡", SEV_INFO: "⚪"}
_SEV_COLOR = {SEV_CRITICAL: "#E05C7A", SEV_ALERT: "#D4A84B", SEV_WATCH: "#7EB8D4", SEV_INFO: "#6B8EAA"}


def _event_card(e: DailyEvent, card_cls: str) -> str:
    icon  = _SEV_ICON.get(e.severity, "●")
    return (
        f'<div class="intel-event {card_cls}">'
        f'<span class="intel-sev-icon">{icon}</span>'
        f'<div class="intel-event-body">'
        f'<div class="intel-event-zh">{e.zh}</div>'
        f'<div class="intel-event-en">{e.en}</div>'
        f'</div></div>'
    )


def _delta_table(changes: list[BiggestChange], pct_format: bool = True) -> str:
    if not changes:
        return '<div class="data-gap-notice">無顯著變化</div>'
    rows = ""
    for c in changes:
        color = "#52B788" if c.direction == "up" else "#E05C7A"
        arrow = "↑" if c.direction == "up" else "↓"
        if pct_format:
            fv = f"{c.from_value:.0%}"
            tv = f"{c.to_value:.0%}"
            dv = f"{c.delta:+.0%}"
        else:
            fv = f"{c.from_value:+,.0f}"
            tv = f"{c.to_value:+,.0f}"
            dv = f"{c.delta:+,.0f}"
        rows += (
            f'<div class="delta-row">'
            f'<span class="delta-ticker">{c.ticker}</span>'
            f'<span class="delta-name">{c.name}</span>'
            f'<span class="delta-from">{fv}</span>'
            f'<span class="delta-arrow">→</span>'
            f'<span class="delta-to" style="color:{color};">{tv}</span>'
            f'<span class="delta-change" style="color:{color};">{arrow} {dv}</span>'
            f'</div>'
        )
    return rows


def _render_intelligence(active_date: str, snaps: list[dict], part: str = "story") -> None:
    """P3.2 拆件:深度數據 tab 解散(Yonki 2026-07-04),三個部分各自歸位 —
    part='story'   今日綜述(市場故事)      → 市場敘事 tab 頂部
    part='changes' Δ排行 + 今日事件(質變)  → 潛力區
    part='risk'    風險警報                → 出場警示 tab 頂部
    """
    report = _intel_load(active_date) if active_date else None

    if report is None:
        if part == "story":
            st.markdown(
                f'<div class="intel-no-prev">'
                f'📡 <strong>reports/{active_date}.intelligence.json</strong> 尚未生成。<br>'
                f'執行 <code>make intelligence DATE={active_date}</code> 以建立本日情報報告，'
                f'或執行 <code>make intelligence-backfill</code> 補生成所有缺失日期。'
                f'</div>',
                unsafe_allow_html=True,
            )
            if snaps and st.button("⚡ 立即生成本日情報", key="intel_gen_btn"):
                from core.intelligence_delta import generate as _intel_generate
                with st.spinner("生成情報報告中…"):
                    report = _intel_generate(active_date, force=False)
                st.rerun()
        else:
            st.markdown('<div class="data-gap-notice">今日情報尚未生成（到「📰 市場敘事」分頁可一鍵生成）</div>',
                        unsafe_allow_html=True)
        return

    # ═══ part: story — 今日綜述(市場故事) ═══════════════════════════════════
    if part == "story":
        prev_str = f"vs {report.prev_date}" if report.prev_date else "首日（無前日可比較）"
        _section_header("📖", "今日綜述", "Market Story")
        st.markdown(_EXPLAIN_DIV.format(
            text=f"把今天所有變化濃縮成幾句事實陳述（生成 {report.generated_at} · {prev_str}）。"
                 "量化明細在「🌱 潛力區→今日變化」與「🔻 出場警示→風險警報」。"),
            unsafe_allow_html=True)
        if report.market_story:
            for s in report.market_story:
                st.markdown(f'<div class="intel-story-item">• {s}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="data-gap-notice">無市場故事資料</div>', unsafe_allow_html=True)
        return

    # ═══ part: changes — Δ排行 + 今日事件(質變) ═════════════════════════════
    if part == "changes":
        _section_header("△", "最大變化排行", "Biggest Changes (last 24h)")
        st.markdown(_EXPLAIN_DIV.format(
            text="三個核心指標 24 小時變化最大的股票——和下方轉強全表交叉比對用。"
                 "主力回頭率＝同一家分點回頭買的頻率；速度＝近 3 日平均買超張數/日；"
                 "多頭分＝連買/回頭率/動能/黃金身分的加權綜合分。"),
            unsafe_allow_html=True)
        col_s, col_v, col_c = st.columns(3, gap="small")
        with col_s:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                'letter-spacing:.08em;margin-bottom:8px;">主力回頭率 Δ</div>',
                unsafe_allow_html=True)
            st.markdown(_delta_table(report.biggest_sponsorship_changes, pct_format=True),
                        unsafe_allow_html=True)
        with col_v:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                'letter-spacing:.08em;margin-bottom:8px;">速度 Velocity Δ (張/日)</div>',
                unsafe_allow_html=True)
            st.markdown(_delta_table(report.biggest_velocity_changes, pct_format=False),
                        unsafe_allow_html=True)
        with col_c:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                'letter-spacing:.08em;margin-bottom:8px;">多頭分 Δ</div>',
                unsafe_allow_html=True)
            st.markdown(_delta_table(report.biggest_confidence_changes, pct_format=True),
                        unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        quality_events = list(report.new_today) + list(report.upgrades) + list(report.downgrades)
        _section_header("↕", "今日事件", "Today's Events", len(quality_events))
        st.markdown(_EXPLAIN_DIV.format(
            text="昨天到今天的質變：首次進入吸籌狀態、進出黃金名單、指標顯著升降（變化≥15%）。"
                 "風險類事件在「🔻 出場警示」。"),
            unsafe_allow_html=True)
        if quality_events:
            _event_table(quality_events)
        else:
            st.markdown('<div class="data-gap-notice">今日無質變事件</div>', unsafe_allow_html=True)
        return

    # ═══ part: risk — 風險警報 ══════════════════════════════════════════════
    if part == "risk":
        _section_header("⚠", "風險警報", "Risk Alerts", report.risk_count)
        st.markdown(_EXPLAIN_DIV.format(
            text="警訊分＝空頭證據加總：疑似出貨 +25%、假突破 +20%、買超速度轉負 +15%、"
                 "狀態轉換風險 +10~40% 等；單日上升 ≥15% 即列入，⚠＝警訊分已 ≥60%。"),
            unsafe_allow_html=True)
        if report.risk_alerts:
            _event_table(report.risk_alerts)
        else:
            st.markdown(
                '<div class="data-gap-notice" style="background:#0F1E17;border-color:#2E6B4A;color:#52B788;">'
                '✓ 無風險警報</div>',
                unsafe_allow_html=True)
        return


def _render_holdings(snaps: list[dict]) -> None:
    if not snaps:
        st.info("無快照資料")
        return
    holdings, err = _holdings_mod.load_holdings_with_status(_AI_STOCK / "data" / "holdings.json")
    if err:
        _section_header("💼", "持倉重點關注", "Holdings Watch")
        st.markdown(
            f'<div class="data-gap-notice" style="border-left:3px solid #E05C7A;">⚠ {err}</div>',
            unsafe_allow_html=True,
        )
        return
    if not holdings:
        _section_header("💼", "持倉重點關注", "Holdings Watch", 0)
        st.markdown(
            '<div class="data-gap-notice">尚無持倉。編輯 <code>data/holdings.json</code> 加入 '
            '{ticker, name, shares, cost} 後 commit,這裡就會出現卡片;達到策略 A/B 出場條件時亮橘/紅燈。</div>',
            unsafe_allow_html=True,
        )
        return

    rows = _holdings_mod.evaluate_holdings(holdings, snaps)
    n_red = sum(1 for r in rows if r["alert"] == "red")
    n_org = sum(1 for r in rows if r["alert"] == "orange")
    _section_header("💼", "持倉重點關注", "Holdings Watch", len(rows))
    _metric_strip([
        ("持倉數 Holdings", str(len(rows)), "manual", "val-dim"),
        ("🔴 強出場警示", str(n_red), "轉弱red/主力連2賣/外資連2反向", "val-red"),
        ("🟠 出場留意",   str(n_org), "轉弱orange/回落", "val-amber"),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    ALERT = {"red": ("#E05C7A", "🔴", "出場條件成立"),
             "orange": ("#D4A84B", "🟠", "接近出場"),
             "none": ("#52B788", "🟢", "持續持有")}
    for r in rows:
        col, dot, zh = ALERT.get(r["alert"], ALERT["none"])
        price = r["current_price"]
        price_s = f"NT${price:,.2f}" if price else "—"
        pl = r["pl_pct"]
        pl_s = f"{pl*100:+.2f}%" if pl is not None else "—"
        pl_col = "#52B788" if (pl or 0) > 0 else ("#E05C7A" if (pl or 0) < 0 else "#6B8EAA")
        cost_s = f"NT${r['cost']:,.2f}" if r.get("cost") else "—"
        shares_s = f"{r['shares']:,}" if r.get("shares") else "—"
        mv_s = f"NT${r['market_value']:,}" if r.get("market_value") else "—"
        reasons = []
        if r["a_reasons"]:
            reasons.append("策略A:" + "、".join(r["a_reasons"]))
        if r["b_reasons"]:
            reasons.append("策略B:" + "、".join(r["b_reasons"]))
        reasons_html = (f'<div style="font-size:12px;color:{col};margin-top:6px;">⚠ '
                        + "　｜　".join(reasons) + '</div>') if reasons else (
                        '<div style="font-size:12px;color:#6B8EAA;margin-top:6px;">未達 A/B 出場條件</div>')
        univ = "" if r["in_universe"] else '<span style="font-size:11px;color:#6B8EAA;"> · 今日不在追蹤池</span>'
        st.markdown(
            f'<div style="background:#13191F;border:1px solid #1F2D3D;border-left:4px solid {col};'
            f'border-radius:0 10px 10px 0;padding:12px 16px;margin-bottom:10px;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;">'
            f'<div><span style="font-size:16px;font-weight:600;">{dot} {r["ticker"]} {r["name"]}</span>{univ}</div>'
            f'<div style="font-size:13px;color:{col};font-weight:600;">{zh}</div>'
            f'</div>'
            f'<div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:#8B949E;margin-top:8px;">'
            f'<span>現價 <b style="color:#CDD5E0;">{price_s}</b></span>'
            f'<span>成本 <b style="color:#CDD5E0;">{cost_s}</b></span>'
            f'<span>股數 <b style="color:#CDD5E0;">{shares_s}</b></span>'
            f'<span>市值 <b style="color:#CDD5E0;">{mv_s}</b></span>'
            f'<span>損益 <b style="color:{pl_col};">{pl_s}</b></span>'
            f'</div>{reasons_html}</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Backtest tab — 模擬績效(讀 reports/backtest/<strategy>_latest.json,有樣本門檻)
# ─────────────────────────────────────────────────────────────────────────────

_BACKTEST_MIN_TRADES = 30   # 未達標只顯示累積進度,避免小樣本誤導
_BACKTEST_STRATEGIES = [
    ("chip_anchored_swing", "A 籌碼錨定波段", "保守"),
    ("momentum_continuation", "B 動能延續",   "積極"),
    ("chip_anchored_v2",    "A v2 分批",     "進階"),
    ("momentum_v2",         "B v2 分批",     "進階"),
]


def _load_backtest_payload(strategy: str) -> dict | None:
    p = _AI_STOCK / "reports" / "backtest" / f"{strategy}_latest.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_backtest(snaps: list[dict]) -> None:
    """模擬績效 tab — 每日 pipeline 跑完自動刷新;樣本不足顯示進度。"""
    _section_header("📈", "模擬績效", "Backtest Performance")
    st.markdown(
        f'<div style="font-size:12px;color:#6B8EAA;margin:-6px 0 14px 0;">'
        f'資料來源:每日 pipeline 自動跑 <code>tools.run_backtest</code> '
        f'寫入 <code>reports/backtest/&lt;strategy&gt;_latest.json</code>。'
        f'樣本 ≥ <b>{_BACKTEST_MIN_TRADES}</b> 筆才顯示績效,'
        f'否則只顯示累積進度(避免小樣本噪音誤導決策)。</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(2, gap="medium")
    for idx, (sname, label, kind) in enumerate(_BACKTEST_STRATEGIES):
        with cols[idx % 2]:
            payload = _load_backtest_payload(sname)
            if not payload:
                st.markdown(
                    f'<div style="padding:14px 16px;background:#0A1018;border:1px solid #1A2232;'
                    f'border-radius:8px;margin-bottom:12px;">'
                    f'<div style="font-size:14px;font-weight:700;color:#CDD5E0;">{label}'
                    f'<span style="font-size:11px;color:#6B8EAA;margin-left:8px;">{kind}</span></div>'
                    f'<div style="font-size:12px;color:#6B8EAA;margin-top:8px;">'
                    f'尚無回測結果。下次 pipeline 跑完(<code>tools.daily</code>)會自動生成。</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                continue

            summary = payload.get("summary", {})
            n_trades = int(summary.get("trades") or 0)
            date_range = payload.get("date_range", [None, None])
            d_lo, d_hi = (date_range[0] or "—"), (date_range[1] or "—")

            # 樣本不足 → 進度條
            if n_trades < _BACKTEST_MIN_TRADES:
                pct = n_trades / _BACKTEST_MIN_TRADES
                pct_w = min(pct, 1.0) * 100
                st.markdown(
                    f'<div style="padding:14px 16px;background:#0A1018;border:1px solid #1A2232;'
                    f'border-radius:8px;margin-bottom:12px;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
                    f'<div style="font-size:14px;font-weight:700;color:#CDD5E0;">{label}'
                    f'<span style="font-size:11px;color:#6B8EAA;margin-left:8px;">{kind}</span></div>'
                    f'<div style="font-size:11px;color:#6B8EAA;">{d_lo} → {d_hi}</div>'
                    f'</div>'
                    f'<div style="font-size:12px;color:#9E8AB8;margin:10px 0 6px 0;">'
                    f'樣本累積中:<b style="color:#CDD5E0;">{n_trades}</b> / {_BACKTEST_MIN_TRADES} 筆</div>'
                    f'<div style="background:#1A2232;border-radius:4px;height:6px;overflow:hidden;">'
                    f'<div style="background:#7EB8D4;width:{pct_w:.1f}%;height:100%;"></div>'
                    f'</div>'
                    f'<div style="font-size:11px;color:#4A6A8A;margin-top:8px;">'
                    f'再累積 <b>{_BACKTEST_MIN_TRADES - n_trades}</b> 筆才會顯示績效。'
                    f'隨著每日 pipeline 跑、universe 變寬,進度自動推進。</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                continue

            # 樣本達標 → 顯示 KPI
            win_rate = summary.get("win_rate")
            avg_ret  = summary.get("avg_return")
            median   = summary.get("median_return")
            max_dd   = summary.get("max_drawdown")
            sharpe   = summary.get("sharpe_per_trade") or summary.get("sharpe")
            avg_hold = summary.get("avg_holding_days")

            def _fmt_pct(v):
                if v is None: return "—"
                try:    return f"{float(v) * 100:+.1f}%" if abs(float(v)) < 1.5 else f"{float(v):+.1f}%"
                except Exception: return "—"

            def _fmt_num(v, dp=2):
                if v is None: return "—"
                try:    return f"{float(v):.{dp}f}"
                except Exception: return "—"

            kpi_rows = [
                ("勝率", f"{(win_rate * 100):.0f}%" if isinstance(win_rate, (int, float)) else "—",
                 "#52B788" if (isinstance(win_rate, (int, float)) and win_rate >= 0.6) else "#CDD5E0"),
                ("平均報酬", _fmt_pct(avg_ret),
                 "#52B788" if (isinstance(avg_ret, (int, float)) and avg_ret > 0) else "#E05C7A"),
                ("中位報酬", _fmt_pct(median), "#CDD5E0"),
                ("最大回撤", _fmt_pct(max_dd),
                 "#E05C7A" if (isinstance(max_dd, (int, float)) and max_dd < -0.05) else "#CDD5E0"),
                ("Sharpe", _fmt_num(sharpe, 2),
                 "#52B788" if (isinstance(sharpe, (int, float)) and sharpe >= 1.0) else "#CDD5E0"),
                ("平均持有", f"{_fmt_num(avg_hold, 1)} 日", "#CDD5E0"),
            ]
            kpi_html = ""
            for k, v, c in kpi_rows:
                kpi_html += (
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                    f'border-bottom:1px dashed #1A2232;">'
                    f'<span style="font-size:12px;color:#6B8EAA;">{k}</span>'
                    f'<span style="font-size:13px;font-weight:700;color:{c};">{v}</span>'
                    f'</div>'
                )

            exit_reasons = summary.get("exit_reasons") or {}
            er_html = ""
            if exit_reasons:
                er_html = '<div style="font-size:11px;color:#6B8EAA;margin-top:10px;">出場原因:'
                er_html += " · ".join(f"{k} <b style='color:#CDD5E0;'>{v}</b>" for k, v in exit_reasons.items())
                er_html += "</div>"

            st.markdown(
                f'<div style="padding:14px 16px;background:#0A1018;border:1px solid #1A2232;'
                f'border-radius:8px;margin-bottom:12px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
                f'<div style="font-size:14px;font-weight:700;color:#CDD5E0;">{label}'
                f'<span style="font-size:11px;color:#6B8EAA;margin-left:8px;">{kind}</span></div>'
                f'<div style="font-size:11px;color:#6B8EAA;">{d_lo} → {d_hi} · {n_trades} 筆</div>'
                f'</div>'
                f'<div style="margin-top:10px;">{kpi_html}</div>'
                f'{er_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # 詳版 report.html 入口
    report_path = _AI_STOCK / "reports" / "backtest" / "report.html"
    if report_path.is_file():
        st.markdown(
            f'<div style="font-size:12px;color:#6B8EAA;margin-top:12px;">'
            f'詳版報表(權益曲線/逐筆/掃描):<code>reports/backtest/report.html</code> '
            f'— 在本機 Mac 跑 <code>python -m tools.render_backtest_report</code> 刷新。'
            f'</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — control panel, date navigator, dev/audit
# ─────────────────────────────────────────────────────────────────────────────

def _render_sidebar(snaps: list[dict]) -> str:
    """Render sidebar and return the user-selected active date string (YYYY-MM-DD).

    The returned date is used to filter all panels to a historical snapshot.
    """
    dates_available = _real_dates()
    latest_date     = dates_available[-1] if dates_available else "—"
    universe_n      = len(snaps[-1].get("stocks", [])) if snaps else 0

    with st.sidebar:
        # ── Logo ─────────────────────────────────────────────────────────
        st.markdown(
            '<div class="sidebar-logo">◈ SCD 市場終端</div>'
            '<div class="sidebar-sub">MARKET INTELLIGENCE TERMINAL</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

        # ── Date navigator ────────────────────────────────────────────────
        st.markdown('<div class="sidebar-section-label">📅 快照日期 Snapshot</div>', unsafe_allow_html=True)

        if dates_available:
            # Use a separate index key so buttons can modify it freely
            if "sb_date_idx" not in st.session_state:
                st.session_state["sb_date_idx"] = len(dates_available) - 1
            # Clamp in case snapshot list grew/shrank
            st.session_state["sb_date_idx"] = max(0, min(st.session_state["sb_date_idx"], len(dates_available) - 1))

            cur_idx = st.session_state["sb_date_idx"]

            # Quick ◀ ▶ prev/next buttons — placed BEFORE selectbox so they fire first
            col_prev, col_next = st.columns(2)
            with col_prev:
                if st.button("◀ 前日", disabled=(cur_idx == 0), use_container_width=True, key="sb_prev"):
                    st.session_state["sb_date_idx"] = cur_idx - 1
                    st.rerun()
            with col_next:
                if st.button("次日 ▶", disabled=(cur_idx == len(dates_available) - 1), use_container_width=True, key="sb_next"):
                    st.session_state["sb_date_idx"] = cur_idx + 1
                    st.rerun()

            active_date = st.selectbox(
                "",
                dates_available,
                index=st.session_state["sb_date_idx"],
                label_visibility="collapsed",
            )
            # Sync index if user picked manually from dropdown
            new_idx = dates_available.index(active_date)
            if new_idx != st.session_state["sb_date_idx"]:
                st.session_state["sb_date_idx"] = new_idx
        else:
            active_date = "—"
            st.markdown('<div class="data-gap-notice">尚無快照</div>', unsafe_allow_html=True)

        st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

        # ── System stats ──────────────────────────────────────────────────
        st.markdown('<div class="sidebar-section-label">📊 系統狀態 Status</div>', unsafe_allow_html=True)
        pulse = _load_market_pulse()
        updated = pulse.get("fetched_at", "")[:16] if pulse else "—"
        stats = [
            ("最新日期", latest_date),
            ("快照數量", f"{len(snaps)}"),
            ("宇宙規模", f"{universe_n} 支"),
            ("脈搏更新", updated[11:] if len(updated) > 11 else updated),
        ]
        rows_html = "".join(
            f'<div class="sidebar-stat-row">'
            f'<span class="sidebar-stat-key">{k}</span>'
            f'<span class="sidebar-stat-val">{v}</span>'
            f'</div>'
            for k, v in stats
        )
        st.markdown(rows_html, unsafe_allow_html=True)

        st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

        # ── Dev / Audit ───────────────────────────────────────────────────
        with st.expander("🔧 開發者工具 Dev Tools", expanded=False):
            st.caption("Replay integrity · Provenance · Raw audit events")

            if not snaps or not dates_available:
                st.info("No snapshot data.")
            else:
                snap   = vd.load_snapshot(active_date)
                stocks = snap.get("stocks", [])
                st.markdown(f"**{active_date}** — {len(stocks)} tickers")

                tab_raw, tab_audit, tab_schema = st.tabs(["Raw", "Audit", "Schema"])

                with tab_raw:
                    st.json({
                        "date":           snap.get("date"),
                        "universe_size":  snap.get("universe_size"),
                        "market_regime":  snap.get("market_regime"),
                        "schema_version": snap.get("schema_version"),
                        "generated_at":   snap.get("generated_at"),
                        "provenance":     snap.get("provenance"),
                    })

                with tab_audit:
                    events = snap.get("audit_log", [])
                    if events:
                        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
                    else:
                        st.info("No audit events.")

                with tab_schema:
                    st.json(snap.get("provenance", {}))

    return active_date if active_date != "—" else (latest_date if latest_date != "—" else "")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    global _NAME_MAP
    snaps = _load_all_snapshots()
    _NAME_MAP = build_name_map(snaps)   # populate once; all _name() calls read this

    # ── Sidebar (date selector + dev tools) ──────────────────────────────
    active_date = _render_sidebar(snaps)

    # Filter snapshots up to (and including) selected date for time-travel
    snaps_to_date = [s for s in snaps if s.get("date", "") <= active_date] if active_date else snaps

    # ── Top bar ───────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:22px;font-weight:800;color:#E6EDF3;letter-spacing:-0.02em;">'
        '🪷 Maitreya &nbsp;<span style="color:#6B8EAA;font-size:14px;font-weight:400;">'
        'Taiwan Market Intelligence Terminal &nbsp;·&nbsp; 市場情報終端</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr style="border:none;border-top:1px solid #1F2D3D;margin:10px 0 16px 0;">', unsafe_allow_html=True)

    # ── 大盤脈搏 banner (pinned above all tabs) ───────────────────────────
    _render_market_pulse_banner()

    # ── Tabs（P3.2 定稿 7 tabs,Yonki 2026-07-04:深度數據解散,內容各自歸位 —
    #    故事→市場敘事頂 / Δ+質變事件→潛力區 / 風險警報→出場警示）─
    tab_market, tab_holdings, tab_entry, tab_potential, tab_exit, tab_research, tab_backtest = st.tabs([
        "📰 市場敘事",
        "💼 我的持倉",
        "★ 進場機會",
        "🌱 潛力區",
        "🔻 出場警示",
        "🔬 個股顯微鏡",
        "📈 模擬績效",
    ])

    _SECTION_HR = ('<hr style="border:none;border-top:1px solid #1F2D3D;'
                   'margin:22px 0 18px 0;">')
    _SECTION_TITLE = ('<div style="font-size:13px;font-weight:700;color:#6B8EAA;'
                      'letter-spacing:.06em;text-transform:uppercase;'
                      'margin:0 0 10px 0;">{label}</div>')

    with tab_holdings:
        _render_holdings(snaps_to_date)

    with tab_entry:
        # 進場機會 = 黃金引擎全家:黃金名單(過五門) + 黃金候補(過四門)
        # (P2.8:候補與名單同引擎,按模組歸位 — Yonki 2026-07-04 定案)
        _render_score_glossary()
        st.markdown(_SECTION_TITLE.format(label="★ 黃金名單"), unsafe_allow_html=True)
        _render_golden(snaps_to_date, show_near_miss=False)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_near_miss_table(snaps_to_date)

    with tab_potential:
        # 潛力區 = 多空計分體系(精選觀察) + 今日變化(Δ+質變) + 原始行為數據(轉強全表)
        _render_score_glossary()
        _render_watch_table(active_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_intelligence(active_date, snaps_to_date, part="changes")
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_strengthening(snaps_to_date)

    with tab_exit:
        # 出場警示 = 風險警報(P3.2 歸位) + 轉弱出貨 + 假突破
        _render_intelligence(active_date, snaps_to_date, part="risk")
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="🔻 轉弱出貨"), unsafe_allow_html=True)
        _render_weakening(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="⚠ 假突破"), unsafe_allow_html=True)
        _render_failed_breakouts(snaps_to_date)

    with tab_market:
        # 市場敘事 = 今日綜述(P3.2 歸位,開頁第一眼) + 環境層,順序 Yonki 定案:
        # 綜述 → 體制 → 龍頭雷達 → 主題觀察 → 資金輪動(含族群走勢) → 熱度 → 三觀察點
        _render_intelligence(active_date, snaps_to_date, part="story")
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="📊 市場體制"), unsafe_allow_html=True)
        st.markdown(_EXPLAIN_DIV.format(
            text="用全市場廣度（幾 % 股票在漲）、平均漲跌、量能綜合判定今天屬於哪種環境"
                 "（吸籌期／觀望期／防禦期…），決定今天適不適合出手。"),
            unsafe_allow_html=True)
        _render_regime(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_watchlist_radar(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_narrative(snaps_to_date, part="themes")
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="⟳ 資金輪動"), unsafe_allow_html=True)
        st.markdown(_EXPLAIN_DIV.format(
            text="各板塊的主力資金流向排名與 5 日走勢；偵測到「錢從 A 板塊搬去 B 板塊」時會顯示輪動警報。"),
            unsafe_allow_html=True)
        _render_leadership_rotation(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_heat_radar(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_narrative(snaps_to_date, part="watchpoints")

    with tab_research:
        # 個股顯微鏡 = 多空體檢(先掃描) → 個股時序(再放大),P3.2 改造
        st.markdown(_SECTION_TITLE.format(label="◈ 多空體檢"), unsafe_allow_html=True)
        st.markdown(_EXPLAIN_DIV.format(
            text="獨立於黃金引擎的多空證據計分：多頭分＝多頭證據總量，警訊分＝空頭證據總量。"
                 "先在這裡掃全市場分布，鎖定目標後到下方「個股時序」放大看。"),
            unsafe_allow_html=True)
        _render_confidence(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="⌛ 個股時序"), unsafe_allow_html=True)
        st.markdown(_EXPLAIN_DIV.format(
            text="選一檔股票，看主力行為的完整歷史：連買、累計、速度的逐日演化。"),
            unsafe_allow_html=True)
        _render_temporal_chains(snaps_to_date)

    with tab_backtest:
        _render_backtest(snaps_to_date)


main()
