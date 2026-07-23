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
import os
import pathlib
import subprocess
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
from viewer import terms as _terms
from viewer import view_params as _vp
from viewer.terms import label as _L, defn as _D, col as _C
from core.narrative_engine import generate as _narrative_generate
from core.market_context import (
    accumulation_velocity,
    sponsorship_persistence,
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
/* 進場機會 tab 金色由標籤上的原生 ⭐ emoji 提供(取代脆弱的 nth-of-type CSS,Yonki 2026-07-13) */

/* ══════════════════════════════════════════════════════════════════════
   SCD_STATUS 呈現層 tokens — 進場機會 tab「一家人」視覺語言
   單一「狀態→顏色」事實來源;C12 呈現映射表雛形 (Yonki 2026-07-13, fable 裁定)。
   金 tier/黃金身分(呼應 tab ⭐) · 綠 可執行 · 琥珀 等回檔 · 藍 資料待補
   · 紅 動能轉弱/風險 · 中性 差一步/次要。emoji 圓點 🟢🟡🔵🔻🟠 於本 tab 全數退場。
   組件:.scd-dot(8px 色點)＋.scd-pill(色點+標籤+1px 同色細邊框膠囊)。
   ════════════════════════════════════════════════════════════════════ */
:root {
    --scd-gold:    #EBC92F;
    --scd-green:   #52B788;
    --scd-amber:   #E8A93C;
    --scd-blue:    #7EB8D4;
    --scd-red:     #E4626F;
    --scd-neutral: #8B949E;
}
.scd-dot { display:inline-block;width:8px;height:8px;border-radius:50%;flex-shrink:0;vertical-align:middle; }
.scd-dot.scd-gold    { background:var(--scd-gold); }
.scd-dot.scd-green   { background:var(--scd-green); }
.scd-dot.scd-amber   { background:var(--scd-amber); }
.scd-dot.scd-blue    { background:var(--scd-blue); }
.scd-dot.scd-red     { background:var(--scd-red); }
.scd-dot.scd-neutral { background:var(--scd-neutral); }
.scd-pill { display:inline-flex;align-items:center;gap:6px;font-size:12px !important;font-weight:600;padding:3px 10px;border-radius:999px;white-space:nowrap;line-height:1.4;border:1px solid; }
.scd-pill.scd-gold    { color:var(--scd-gold);    border-color:#EBC92F55; }
.scd-pill.scd-green   { color:var(--scd-green);   border-color:#52B78855; }
.scd-pill.scd-amber   { color:var(--scd-amber);   border-color:#E8A93C55; }
.scd-pill.scd-blue    { color:var(--scd-blue);    border-color:#7EB8D455; }
.scd-pill.scd-red     { color:var(--scd-red);     border-color:#E4626F55; }
.scd-pill.scd-neutral { color:var(--scd-neutral); border-color:#8B949E55; }
.scd-star { color:var(--scd-gold);font-weight:700; }

/* ── P4.1 密度表 Density tables — 四訊號區塊統一設計(Yonki 2026-07-15)
   小字表頭 · ~30px 行高 · SCD 色點 · 標籤小膠囊 · 原始值無綜合分數 ── */
.dt-table { width:100%;border-collapse:collapse;margin:2px 0 6px 0; }
.dt-table th { font-size:10px !important;color:#6B8EAA;text-transform:uppercase;letter-spacing:.06em;text-align:left;padding:4px 10px;border-bottom:1px solid #253A52;font-weight:700;white-space:nowrap; }
.dt-table td { font-size:13px !important;color:#CDD5E0;padding:4px 10px;border-bottom:1px solid #1A2030;line-height:1.5;vertical-align:middle;height:30px; }
.dt-table tr:hover td { background:#131B26; }
.dt-ticker { color:#7EB8D4;font-weight:700;font-family:'SF Mono','Fira Code',monospace; }
.dt-name  { color:#8B949E;font-size:12px !important; }
.dt-num   { font-family:monospace; }
.dt-note  { font-size:10px !important;color:#4A6A8A;text-align:right;margin:0 0 2px 0; }
.dt-empty { font-size:12px !important;color:#52B788;margin:4px 0 8px 0; }
.scd-pill.dt-sm { font-size:11px !important;padding:1px 8px;gap:5px;margin:1px 3px 1px 0; }

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
.gc-strat-badge { display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:800;letter-spacing:.02em;background:#101A22;color:var(--scd-gold,#EBC92F);border:1px solid #EBC92F55;margin-left:4px;cursor:help; }
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


@st.cache_data(ttl=120, show_spinner=False)
def _strategy_tags_load(date: str) -> dict:
    """讀 reports/strategy_tags/<date>.json 的 tags(Part 1 sidecar,R1)。

    viewer 只讀落地 sidecar 檔渲染徽章 —— 不新增 core 引擎 import、不算不裝
    (viewer 三紅線)。回傳 {ticker: {"tags": [...], "rejections": {...}}}。
    """
    if not date:
        return {}
    p = _AI_STOCK / "reports" / "strategy_tags" / f"{date}.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("tags", {})
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _strategy_health_load() -> dict:
    """讀四策略 <name>_latest.json 的 summary(策略健康度標頭用)。純讀檔。

    回傳 {strategy_name: summary};summary 可能含 net(成本模型完成後,A2)或
    只有毛報酬(未扣成本)。呈現由 viewer 決定。
    """
    out: dict[str, dict] = {}
    for name in ("chip_anchored_swing", "momentum_continuation"):
        p = _AI_STOCK / "reports" / "backtest" / f"{name}_latest.json"
        if p.is_file():
            try:
                out[name] = json.loads(p.read_text(encoding="utf-8")).get("summary", {})
            except Exception:
                pass
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _load_tdcc_file(fname: str) -> dict:
    """讀單一 data/tdcc/YYYYMMDD.json 週快取(fetch_daily 每日維護)。
    interim:viewer 直讀原始快取,正式落地待 2.0 schema(Q5.1 放行,Yonki 2026-07-15)。"""
    import json as _json
    path = _AI_STOCK / "data" / "tdcc" / fname
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tdcc_lookup(ticker: str, on_or_before: str) -> dict | None:
    """取 tdcc_date ≤ on_or_before(YYYY-MM-DD)的最近一週該股 TDCC 原始值。
    回傳 {week:'MM/DD', large_holder_400_pct, large_holder_1000_pct,
    shareholder_count, delta_1000(前一週千張大戶 pt 差,無前週為 None)};缺料回 None。
    時間旅行安全:選過去日期時只用該日以前的週檔。"""
    tdcc_dir = _AI_STOCK / "data" / "tdcc"
    try:
        fnames = sorted(
            f.name for f in tdcc_dir.iterdir()
            if f.suffix == ".json" and len(f.stem) == 8 and f.stem.isdigit()
        )
    except OSError:
        return None
    cutoff = (on_or_before or "").replace("-", "") or "99999999"
    usable = [f for f in fnames if f[:8] <= cutoff]
    if not usable:
        return None
    cur = _load_tdcc_file(usable[-1])
    rec = (cur.get("stocks") or {}).get(ticker)
    if not rec:
        return None
    d = cur.get("tdcc_date", usable[-1][:8])
    out = {
        "week": f"{d[4:6]}/{d[6:8]}",
        "large_holder_400_pct":  rec.get("large_holder_400_pct"),
        "large_holder_1000_pct": rec.get("large_holder_1000_pct"),
        "shareholder_count":     rec.get("shareholder_count"),
        "delta_1000": None,
    }
    if len(usable) >= 2:
        prev_rec = (_load_tdcc_file(usable[-2]).get("stocks") or {}).get(ticker)
        if prev_rec and rec.get("large_holder_1000_pct") is not None \
                and prev_rec.get("large_holder_1000_pct") is not None:
            out["delta_1000"] = round(
                rec["large_holder_1000_pct"] - prev_rec["large_holder_1000_pct"], 2)
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _deployed_commit_hash() -> str:
    """短 commit hash，用來一眼比對「雲端部署版本 vs main HEAD」(R12/補充裁定 D)。

    優先讀環境變數(部署時注入，例如 Streamlit Cloud secrets/env)，
    fallback 到本機 `git rev-parse --short HEAD`。任何一步失敗都回傳 "unknown"，
    絕不讓 viewer crash。
    """
    env_hash = os.environ.get("STREAMLIT_COMMIT") or os.environ.get("COMMIT_HASH")
    if env_hash:
        return env_hash.strip()[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_AI_STOCK),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out:
                return out
    except Exception:
        pass
    return "unknown"


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


def _sponsorship(ticker: str, snaps: list[dict]) -> dict:
    """sponsorship 單一取值來源(漂移第11例收案,Yonki 2026-07-15)。
    全 viewer render-time 的主力回頭率一律走本函式 → full_ticker_context["sponsorship"]
    → market_context.sponsorship_persistence,與 golden 引擎 funnel 的 sponsorship_score
    (funnel.py:460 = 同一 persistence_score)同源,不再各處各算。
    註:黃金名單/候補的 e.sponsorship_score 與 intel 的 w.sponsorship 皆為上游已落地
    產物(非 viewer render-time 計算),其計算函式即本函式對齊的 sponsorship_persistence。"""
    return full_ticker_context(ticker, snaps)["sponsorship"]


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


def _density_table(headers: list[str], rows: list[str], sort_note: str = "",
                   max_rows: int = 10) -> None:
    """P4.1 密度表(Yonki 2026-07-15,四訊號區塊統一):小字表頭、~30px 行高、
    SCD 色點/小膠囊、原始值。rows 為 <tr>…</tr> HTML 字串;預設最多 max_rows 列,
    超過收 st.expander「展開全部 (N)」。sort_note 顯示於表頭右側小字(排序鍵標註)。"""
    head = "".join(f"<th>{h}</th>" for h in headers)

    def _tbl(rs: list[str]) -> str:
        return (f'<table class="dt-table"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(rs)}</tbody></table>')

    if sort_note:
        st.markdown(f'<div class="dt-note">{sort_note}</div>', unsafe_allow_html=True)
    st.markdown(_tbl(rows[:max_rows]), unsafe_allow_html=True)
    if len(rows) > max_rows:
        with st.expander(f"展開全部 ({len(rows)})"):
            st.markdown(_tbl(rows[max_rows:]), unsafe_allow_html=True)


def _dt_empty(text: str) -> None:
    """密度表空狀態:綠字小 caption 一行帶過,不畫空表格。"""
    st.markdown(f'<div class="dt-empty">{text}</div>', unsafe_allow_html=True)


def _dt_pill(cls: str, text: str, title: str = "") -> str:
    """小膠囊(密度表尺寸):cls ∈ scd-gold/green/amber/blue/red/neutral。"""
    t = f' title="{title}"' if title else ""
    return (f'<span class="scd-pill {cls} dt-sm"{t}>'
            f'<span class="scd-dot {cls}"></span>{text}</span>')


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
        f'大盤脈搏  MARKET PULSE &nbsp;·&nbsp; 資料日期 {date} &nbsp;·&nbsp; 更新 {fat}</div>'
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;">{cells}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 1 — Market Regime  市場體制
# ─────────────────────────────────────────────────────────────────────────────

# temperature_level → 呈現色類別(C12:viewer 單一擁有映射;溫度真值 obs_market_temperature)
_TEMP_LEVEL_VAL_CLS = {
    "cool": "val-cyan", "stable": "val-green", "warm": "val-amber",
    "hot": "val-red", "extreme": "val-red",
}


def _render_regime_alert(snaps: list[dict]) -> None:
    """⚡警訊 — 體制轉換的低調單行提示(A:從大黃條降級為小字,置於龍頭雷達下、綜述上)。
    讀當日落地 obs_market_regime.transition_detected/transition_note(B:真值母體)。"""
    if not snaps:
        return
    reg = snaps[-1].get("obs_market_regime")
    if not reg or not reg.get("transition_detected"):
        return
    st.markdown(
        f'<div style="font-size:12px;color:#D4A84B;margin:2px 0 10px 0;letter-spacing:.02em;">'
        f'⚡ {reg.get("transition_note", "體制轉換")}</div>',
        unsafe_allow_html=True,
    )


def _render_regime(snaps: list[dict]) -> None:
    if not snaps:
        st.info("尚無快照資料 No snapshot data available.")
        return

    # B:改讀當日落地真值(obs_market_regime/breadth/temperature),render-time
    # regime_shift 的舊廣度(買超榜母體恆≈100%)退場。缺欄(7/13 前舊快照)誠實佔位。
    snap = snaps[-1]
    reg  = snap.get("obs_market_regime")
    brd  = snap.get("obs_market_breadth") or {}
    tmp  = snap.get("obs_market_temperature") or {}

    if not reg:
        st.markdown(
            '<div class="data-gap-notice">該日無落地市場觀測（obs_market_* 欄位缺，'
            '此日快照早於 2026-07-13 母體修正上線）。</div>',
            unsafe_allow_html=True,
        )
        return

    # Colour scheme
    color = reg.get("regime_color", "#6B8EAA")
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
        f'<div class="regime-label-zh" style="color:{color};">{reg.get("regime_label_zh","—")}</div>'
        f'<div class="regime-label-en" style="color:{color};">{reg.get("regime_label_en","")}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Metrics — 廣度(真原始家數) ｜ 均漲 ｜ 風險溫度 ｜ 快照數。廣度趨勢 Trend 已刪(無資訊量)。
    b_frac = reg.get("latest_breadth")
    if b_frac is not None:
        b_pct = b_frac * 100
        b_cls = "val-green" if b_pct >= 60 else ("val-amber" if b_pct >= 30 else "val-red")
        adv, dec, unch = brd.get("advancers"), brd.get("decliners"), brd.get("unchanged")
        if adv is not None and dec is not None:
            b_sub = f"{adv}漲/{dec}跌/{unch if unch is not None else 0}平"
        else:
            b_sub = "全市場漲跌家數"
        b_val = f"{b_pct:.1f}%"
    else:
        b_cls, b_sub, b_val = "val-dim", "該日無落地廣度", "—"

    c_val = reg.get("latest_avg_chg", 0.0)
    c_cls = "val-green" if c_val > 0 else "val-red"

    if tmp:
        t_cls = _TEMP_LEVEL_VAL_CLS.get(tmp.get("temperature_level"), "val-dim")
        t_val = tmp.get("temperature_zh", "—")
        t_sub = f"{tmp.get('temperature_level','')} · {int((tmp.get('temperature') or 0) * 100)}%"
    else:
        t_cls, t_val, t_sub = "val-dim", "—", "該日無落地溫度"

    _metric_strip([
        ("廣度 Breadth", b_val,           b_sub,         b_cls),
        ("均漲 Avg Chg", f"{c_val:+.2f}%", "全宇宙均值",   c_cls),
        ("風險溫度 Risk Temp", t_val,       t_sub,         t_cls),
        ("快照數 Dates",  str(len(reg.get("dates", []))), "歷史紀錄", "val-dim"),
    ])

    st.markdown("<br>", unsafe_allow_html=True)

    # 廣度歷史圖 + 均漲：改用落地序列。breadth_series 僅含有 market_pulse 的日期
    # (breadth_dates);avg_chg_series 覆蓋全窗(dates)。誠實各用各的 x 軸。
    b_dates  = reg.get("breadth_dates", [])
    b_series = reg.get("breadth_series", [])
    a_dates  = reg.get("dates", [])
    a_series = reg.get("avg_chg_series", [])
    v_series = reg.get("vol_series", [])
    if len(a_dates) >= 2:
        col1, col2 = st.columns(2)
        with col1:
            if len(b_series) >= 2:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=b_dates, y=[v * 100 for v in b_series],
                    mode="lines+markers", name="廣度%",
                    line=dict(color="#7EB8D4", width=2.5),
                    marker=dict(size=6),
                    fill="tozeroy", fillcolor="rgba(126,184,212,0.08)",
                ))
                fig.add_hline(y=50, line_dash="dot", line_color="#2A3A4A", line_width=1)
                fig.update_layout(**_plotly_layout("全市場廣度 Breadth %（落地真值）", 240))
                fig.update_yaxes(ticksuffix="%", range=[0, 105])
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("廣度歷史需 ≥2 個有落地母體的交易日（market_pulse 上線後累積中）")
        with col2:
            colors = [("#52B788" if v >= 0 else "#E05C7A") for v in a_series]
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=a_dates, y=a_series,
                marker_color=colors, name="均漲%",
            ))
            fig2.add_hline(y=0, line_color="#3A4A5A", line_width=1)
            fig2.update_layout(**_plotly_layout("宇宙均漲 Avg Change %", 240))
            fig2.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

        # 歷史體制紀錄表：以落地廣度序列(breadth_dates)為主，avg_chg/vol 依日期對齊。
        st.markdown("<br>", unsafe_allow_html=True)
        _section_header("📋", "歷史體制紀錄", "Regime History", len(b_dates))
        _achg_by_date = dict(zip(a_dates, a_series))
        _vol_by_date  = dict(zip(a_dates, v_series))
        rows = []
        for i, d in enumerate(b_dates):
            b = b_series[i] * 100
            c = _achg_by_date.get(d)
            v = _vol_by_date.get(d)
            rows.append({
                "日期 Date": d,
                "廣度% Breadth": f"{b:.1f}%",
                "均漲% Avg Chg": f"{c:+.2f}%" if c is not None else "—",
                "量能指數 Vol": f"{v:.2f}×" if v is not None else "—",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("尚無落地廣度序列可製表（market_pulse 上線後累積中）")


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
    for thr, pts in _vp.HEAT_STREAK_TIERS:
        if streak >= thr:
            s += pts
            break

    if fii is not None:
        if fii > 0:   s += _vp.HEAT_FII_SAME_DIR
        elif fii < 0: s += _vp.HEAT_FII_OPP_DIR

    if conf_tier == "FULL":    s += _vp.HEAT_TIER_FULL
    elif conf_tier == "PARTIAL": s += _vp.HEAT_TIER_PARTIAL

    s += _vp.HEAT_WEAK_PENALTY.get(weak_sev, 0)

    return s


def _heat_level(score: int) -> tuple[str, str]:
    """熱度分 → (SCD 色類別, 中文級別)。切點集中於 view_params.HEAT_LEVEL_CUTS。"""
    for thr, cls, zh in _vp.HEAT_LEVEL_CUTS:
        if score >= thr:
            return cls, zh
    return "scd-neutral", "冷"


def _render_heat_radar(snaps: list[dict]) -> None:
    """P3: additive heat-score ranking for all tracked stocks.

    P4.1(Yonki 2026-07-15):卡片牆 → 密度表(代號｜名稱｜熱度色點+級別｜連買｜
    外資方向｜觀察標籤小膠囊)。Display-only — zero impact on composite/tier/gates。
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
    st.markdown(_EXPLAIN_DIV.format(
        text="熱度＝連買積分＋外資對齊＋資料品質－轉弱扣分的觀察級別。"
             "純觀察層，不影響黃金名單評分／閘門／Tier。"),
        unsafe_allow_html=True)

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
        name   = stock.get("name", "") or _short_name(ticker)
        rows.append({
            "ticker": ticker, "name": name, "score": score,
            "streak": streak, "fii": fii, "tier": tier, "weak": weak,
        })

    rows.sort(key=lambda r: (-r["score"], -r["streak"]))

    html_rows = []
    for r in rows:
        lvl_cls, lvl_zh = _heat_level(r["score"])
        heat_cell = f'<span class="scd-dot {lvl_cls}"></span> {lvl_zh}'
        fii = r["fii"]
        if fii is None:
            fii_cell = '<span style="color:#4A5A6A;">—</span>'
        elif fii > 0:
            fii_cell = '<span style="color:#52B788;">同向</span>'
        elif fii < 0:
            fii_cell = '<span style="color:#E05C7A;">反向</span>'
        else:
            fii_cell = '<span style="color:#4A5A6A;">持平</span>'
        tags = []
        if r["tier"] == "FULL":
            tags.append(_dt_pill("scd-blue", "資料完整"))
        elif r["tier"] == "SKELETON":
            tags.append(_dt_pill("scd-amber", "資料偏薄"))
        weak = r["weak"]
        if weak.get("severity", "none") != "none":
            flag_codes = "+".join(f["code"] for f in weak.get("flags", []))
            tags.append(_dt_pill("scd-red", f'🔻 {weak.get("label_zh", "轉弱")}', title=flag_codes))
        html_rows.append(
            f'<tr><td class="dt-ticker">{r["ticker"]}</td>'
            f'<td class="dt-name">{r["name"]}</td>'
            f'<td>{heat_cell}</td>'
            f'<td class="dt-num">{r["streak"]}</td>'
            f'<td>{fii_cell}</td>'
            f'<td>{"".join(tags)}</td></tr>'
        )

    if not html_rows:
        _dt_empty("今日無追蹤標的 ✓")
        return
    _density_table(
        ["代號", "名稱", "熱度", _C("streak_strict"), _L("fii_sync"), "觀察標籤"],
        html_rows, sort_note="熱度排序",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 2 — Watchlist Radar  雷達觀察
# ─────────────────────────────────────────────────────────────────────────────

def _render_watchlist_radar(snaps: list[dict]) -> None:
    # A(Yonki 2026-07-15):刪 _section_header 與說明段,只留 5 張卡(標題由 main 的
    # _SECTION_TITLE 統一提供,與其餘環境層區塊一致)。
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
        spon = _sponsorship(ticker, snaps)   # D1:sponsorship 單一取值來源(漂移第11例收案)
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
            _L("momentum_glyph"): mom_txt,
            "現價": f"NT${price:,.2f}" if price else "—",
            "漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            _C("streak_strict"): streak,
            _C("window_buy_days"): _stock_buy_days_in_window_or_none(stock),  # 1.7.0 缺欄位顯示「—」
            _C("net_window"): net,
            _C("velocity_3d"): round(vel) if vel is not None else None,
            _L("sponsorship"): f"{spon_score:.0%}" if spon_days and spon_days >= 3 else "樣本不足",
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
        .sort_values(["_mom", "_fresh", _C("net_window")], ascending=[True, True, False])
        .drop(columns=["_mom", "_fresh", "_spon", "_spon_days"])
    )
    st.caption("排序：動能方向 → 資料新鮮度 → 20日累計買超 ｜ ▼ 減速中的標的代表動能衰竭，連買天數高也應降權看待")
    st.dataframe(
        _style_signal_df(
            df,
            color_cols=["漲跌", _C("velocity_3d")],
            text_cols=[_L("momentum_glyph"), "資料"],
            fmt={_C("net_window"): "{:+,.0f}", _C("velocity_3d"): "{:+,.0f}",
                 _C("streak_strict"): "{:d} 日", _C("window_buy_days"): "{:d}/20"},
        ),
        use_container_width=True,
        hide_index=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 3b — Weakening / Distribution Signals  轉弱出貨
# ─────────────────────────────────────────────────────────────────────────────

# W1–W5 旗標定義(密度表 hover title 用;文案沿用原 gc-tooltip 圖例字典)
_W_FLAG_DEFS = {
    "W1": "W1 動能衰竭 — 連買≥3日但速度轉負、買量遞減",
    "W2": "W2 雙引擎分歧 — 主力買超但外資賣超達主力買量30%",
    "W3": "W3 主力消失 — 曾連買≥3日，從買超榜缺席（≠賣出；缺席1日可能只是輪動，缺席≥2日才可合成紅燈）",
    "W4": "W4 散戶接盤 — 券商家數差轉正，或價跌融資增≥3日/10日",
    "W5": "W5 分點賣壓 — 分點總賣>總買，或前三買點邊買邊倒（賣出自身買量≥60%）",
}

# severity → (SCD 色類別, 高/中/低)。C12 呈現映射 viewer 單一擁有。
_SEV_DT = {
    "red":    ("scd-red",     "高"),
    "orange": ("scd-amber",   "中"),
    "yellow": ("scd-neutral", "低"),
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

    if not results:
        _dt_empty("今日無轉弱訊號 ✓")
        return

    # P4.1(Yonki 2026-07-15):警示卡牆 → 密度表。旗標膠囊 hover title 顯示定義全文。
    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    html_rows = []
    for w in results:
        ticker = w["ticker"]
        stock  = latest_stocks.get(ticker, {})
        name   = stock.get("name") or _short_name(ticker)
        sev_cls, sev_zh = _SEV_DT.get(w["severity"], ("scd-neutral", "低"))
        sev_cell = (f'<span title="{w.get("label_zh", "")}">'
                    f'<span class="scd-dot {sev_cls}"></span> {sev_zh}</span>')
        net = w.get("net_cumulative", 0) or 0
        net_color = "#E05C7A" if net < 0 else "#52B788"
        pills = "".join(
            _dt_pill("scd-amber", f'{f["code"]} {f["zh"]}',
                     title=_W_FLAG_DEFS.get(f["code"], f.get("detail", "")))
            for f in w["flags"]
        )
        if not w.get("present_latest", True):
            pills += _dt_pill("scd-neutral", f'缺席 {w.get("snaps_since_seen", "?")} 快照',
                              title="缺席 >3 個快照的標的自動移出（陳舊訊號）")
        html_rows.append(
            f'<tr><td class="dt-ticker">{ticker}</td>'
            f'<td class="dt-name">{name}</td>'
            f'<td>{sev_cell}</td>'
            f'<td class="dt-num" style="color:{net_color};">{net:+,}</td>'
            f'<td>{pills}</td></tr>'
        )

    _density_table(
        ["代號", "名稱", "嚴重度", _C("weak_net_window"), "轉弱旗標"],
        html_rows, sort_note="嚴重度排序 · 旗標滑鼠停留看定義",
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
        _dt_empty("今日無假突破 ✓")
        return

    # P4.1(Yonki 2026-07-15):警報卡 → 密度表,回落天數排序。
    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    warnings.sort(key=lambda tc: -(tc[1]["failed_breakout"].get("retreat_days") or 0))

    html_rows = []
    for ticker, ctx in warnings:
        fb    = ctx["failed_breakout"]
        stock = latest_stocks.get(ticker, {})
        name  = stock.get("name") or _short_name(ticker)
        bdate = str(fb.get("breakout_date", ""))
        bdate_s = bdate[5:].replace("-", "/") if len(bdate) >= 10 else bdate
        high_risk = "高風險" in fb.get("label_zh", "")
        sev_cls = "scd-red" if high_risk else "scd-amber"
        retreat_cell = (f'<span title="{fb.get("label_zh", "")}">'
                        f'<span class="scd-dot {sev_cls}"></span> {fb["retreat_days"]} 日</span>')
        html_rows.append(
            f'<tr><td class="dt-ticker">{ticker}</td>'
            f'<td class="dt-name">{name}</td>'
            f'<td class="dt-num">{bdate_s}</td>'
            f'<td class="dt-num" style="color:#52B788;">+{fb["breakout_chg"]:.1f}%</td>'
            f'<td class="dt-num">{fb["vol_ratio"]:.1f}×</td>'
            f'<td>{retreat_cell}</td></tr>'
        )

    _density_table(
        ["代號", "名稱", "突破日", "當日", "量比", "回落"],
        html_rows, sort_note="回落天數排序 · 回落欄滑鼠停留看風險級別",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PANEL 5 — Persistent Accumulation  持續吸籌
# D4(Yonki 2026-07-15):_render_persistent_accumulation 死碼刪除(無任何 tab 佈線呼叫,
# 刪前已 grep 確認無呼叫者)。持續吸籌資訊由「轉強訊號」的「只看持續吸籌」勾選與
# 「精選觀察」涵蓋。
# ─────────────────────────────────────────────────────────────────────────────


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
        spon = _sponsorship(ticker, snaps)   # D1:sponsorship 單一取值來源(漂移第11例收案)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(_L("streak_strict"),  f"{_stock_streak(stock_latest)}日",
                    help=_D("streak_strict"))
        _win_v = _stock_buy_days_in_window_or_none(stock_latest)
        col2.metric(_L("window_buy_days"),
                    f"{_win_v}/20" if _win_v is not None else "—",
                    help=_D("window_buy_days") +
                         "舊 1.7.0 快照無此欄位,顯示「—」;pipeline 1.8.0 起生效。")
        col3.metric(_L("net_window"),      f"{_stock_net_accumulation(stock_latest):+,}張",
                    help=_D("net_window"))
        col4.metric(_L("sponsorship"), f"{spon['persistence_score']:.0%}", help=_D("sponsorship"))

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
        # n_dates = 敘事窗口日數(持續出現表把覆蓋率%換算回原始出現日數用)
        _render_narrative_watchpoints(report, n_dates=len(snaps))


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
    # D3(Yonki 2026-07-15):刪「板塊輪動」卡——與下方「資金輪動」區重複判斷,留其餘主題。
    st.markdown(_EXPLAIN_DIV.format(
        text="從近幾日快照歸納的市場主題：資金方向（整體進或出）、強弱對比（誰在領漲誰在破位）。"
             "（板塊輪動請看下方「資金輪動」區。）"),
        unsafe_allow_html=True)
    themes = report.get("key_themes", {})
    theme_defs = [
        ("capital_flow",         "◉", "資金方向", "Capital Flow"),
        ("strength_vs_weakness", "↕", "強弱對比", "Strength vs Weakness"),
    ]
    cols = st.columns(2, gap="small")
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


def _render_narrative_watchpoints(report: dict, n_dates: int = 10) -> None:
    # ── Section C: Notable Entities ──────────────────────────────────────
    # D2(Yonki 2026-07-15):刪「可能假突破」欄——出場警示的 failed_breakouts 是唯一 SoT,
    # 此處重複判斷退場。三欄改兩欄。
    st.markdown(_EXPLAIN_DIV.format(
        text="持續出現＝在每日買超榜反覆現身的個股（主力沒走）；重要轉換＝首次上榜或消失後重現。"
             "（假突破訊號請看「🔻 出場警示」分頁，該處為唯一資料來源。）"),
        unsafe_allow_html=True)
    ent = report.get("notable_entities", {})
    col_left, col_mid = st.columns(2, gap="small")

    # Persistent tickers — P4.1(Yonki 2026-07-15):長條列 → 密度表。
    # 覆蓋率%換算回原始出現日數(X / N 日),窗口 N = 敘事實際窗口(n_dates)。
    with col_left:
        pers = ent.get("persistent_tickers", [])
        _section_header("◈", "持續出現個股", "Persistent Tickers")
        if not pers:
            _dt_empty("無持續出現個股")
        else:
            win = max(1, n_dates)
            html_rows = []
            for e in pers:
                streak = e.get("current_streak", 0)
                days   = round((e.get("coverage_pct", 0) / 100) * win)
                # 最近動向:note_zh 去掉「名稱（代號）：覆蓋率 X%，」前綴,縮成一句
                note = (e.get("note_zh") or "").split("，", 1)[-1].rstrip("。") or "—"
                s_cls = "scd-green" if streak >= 3 else ("scd-blue" if streak >= 1 else "scd-neutral")
                html_rows.append(
                    f'<tr><td class="dt-ticker">{e["ticker"]}</td>'
                    f'<td class="dt-name">{_short_name(e["ticker"])}</td>'
                    f'<td><span class="scd-dot {s_cls}"></span> <span class="dt-num">{streak}</span></td>'
                    f'<td class="dt-num">{days} / {win} 快照</td>'
                    f'<td class="dt-name">{note}</td></tr>'
                )
            _density_table(
                ["代號", "名稱", _C("presence_streak"), _L("appearance"), "最近動向"],
                html_rows, sort_note="持續度排序",
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


def _render_strategy_health(health: dict, a_n: int, b_n: int, consensus_n: int) -> None:
    """Part 1:策略健康度標頭(誠實性要求)+ 共識計數。

    讓徽章保持『描述性』而非『指示性』:標頭露各策略最新回測報酬與成本檢驗狀態。
    淨報酬(summary.net,成本模型完成後)優先;未完成前顯示毛報酬並標注「未扣成本」。
    純呈現 — 讀 _strategy_health_load 的 summary,不算不裝。
    """
    _META = [   # (glyph, term-key, strategy_name)
        ("Ⓐ", "strat_chip", "chip_anchored_swing"),
        ("Ⓑ", "strat_momentum", "momentum_continuation"),
    ]
    rows = []
    for glyph, tkey, sname in _META:
        s = health.get(sname, {})
        net = (s.get("net") or {}).get("avg_return")
        gross = s.get("avg_return")
        if net is not None:
            ret_txt = f"淨 {net*100:+.2f}%"
            if net >= 0:
                status, col = "✓ 通過成本檢驗", "#52B788"
            else:
                status, col = "⚠️ 研究中(未通過成本檢驗)", "#E8A838"
        elif gross is not None:
            ret_txt = f"毛 {gross*100:+.2f}% · 未扣成本"
            status, col = "研究中(成本模型未完成)", "#7EB8D4"
        else:
            ret_txt, status, col = "無回測樣本", "—", "#6B8EAA"
        rows.append(
            f'<div style="display:flex;gap:10px;align-items:baseline;padding:2px 0;">'
            f'<span style="color:var(--scd-gold,#EBC92F);font-weight:800;min-width:110px;">{glyph} {_L(tkey)}</span>'
            f'<span style="font-family:monospace;color:#CDD5E0;min-width:150px;">{ret_txt}</span>'
            f'<span style="color:{col};font-weight:600;">{status}</span>'
            f'</div>'
        )
    consensus_line = (
        f'<div style="margin-top:8px;font-size:13px;color:#9FB2C4;">'
        f'Ⓐ {a_n} 檔 &nbsp;｜&nbsp; Ⓑ {b_n} 檔 &nbsp;｜&nbsp; '
        f'{_L("strat_consensus")} <b style="color:var(--scd-gold,#EBC92F);">{consensus_n}</b> 檔</div>'
    )
    st.markdown(
        f'<div style="background:#111820;border:1px solid #1F2D3D;border-left:4px solid #EBC92F;'
        f'border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
        f'<div style="font-size:12px;color:#6B8EAA;letter-spacing:.08em;margin-bottom:6px;">'
        f'策略健康度 STRATEGY HEALTH · 描述性標示,非投資建議</div>'
        f'{"".join(rows)}{consensus_line}</div>',
        unsafe_allow_html=True,
    )


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

    # ── Part 1: strategy tags (Ⓐ 籌碼錨定 / Ⓑ 動能延續) — sidecar, display-only ──
    # 讀 reports/strategy_tags/<date>.json(R1);決定論、來源＝共用 would_enter。
    # viewer 只渲染,不算/不裝、不影響 tier/score/gates。
    strategy_tag_map = _strategy_tags_load(active_date)   # {ticker: {tags, rejections}}
    _TAG_META = {   # label → (glyph, term-key)
        "A": ("Ⓐ", "strat_chip"),
        "B": ("Ⓑ", "strat_momentum"),
    }

    def _strategy_badges_html(ticker: str) -> str:
        """卡片策略徽章 HTML(tier 徽章之後、轉弱 pill 之前)。未符合任何策略者回空字串
        (不顯示灰色空徽章)。滑鼠懸停顯示未取得策略的未通過原因。"""
        info = strategy_tag_map.get(ticker)
        if not info or not info.get("tags"):
            return ""
        rej = info.get("rejections", {})
        spans = []
        for lab in info["tags"]:
            glyph, tkey = _TAG_META.get(lab, ("", None))
            name = _L(tkey) if tkey else lab
            # tooltip: this ticker's rejection reasons for the OTHER strategy
            other_tips = "；".join(
                f'{_TAG_META.get(k, ("", None))[0]} ✗ {"、".join(v)}'
                for k, v in sorted(rej.items()) if v
            )
            title = f' title="{other_tips}"' if other_tips else ""
            spans.append(
                f'<span class="gc-strat-badge"{title}>{glyph} {name}</span>')
        return "".join(spans)

    def _tag_count(ticker: str) -> int:
        info = strategy_tag_map.get(ticker)
        return len(info["tags"]) if info and info.get("tags") else 0

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
        if acc > _vp.MOMENTUM_ACCEL_UP or (acc > 0 and vel > _vp.MOMENTUM_VEL_STRONG):
            return "strengthening"
        if acc < _vp.MOMENTUM_ACCEL_BREAKDOWN or (acc < 0 and vel < 0):
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
        if (e.streak or 0) >= _vp.STREAK_HIGH and e.sponsorship_score >= _vp.SPON_HIGH and (e.net_cumulative or 0) > 0:
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
        # e.streak = accumulation_velocity streak(缺席不中斷)= 榜上連買,非落地嚴格連買
        streak_n = e.streak or 0
        if streak_n >= _vp.STREAK_HIGH:
            items.append(("✓", _L("streak_on_board"), f"{streak_n} 日榜上連續買超", True))
        elif streak_n >= 1:
            items.append(("△", _L("streak_on_board"), f"榜上連買 {streak_n} 日（≥{_vp.STREAK_HIGH}日視為確認）", None))
        else:
            items.append(("✗", _L("streak_on_board"), "無持續買超紀錄", False))

        # 2. Sponsorship strength
        spon = e.sponsorship_score
        if spon >= _vp.SPON_HIGH:
            items.append(("✓", _L("sponsorship"), f"回頭率 {spon:.0%}（≥{_vp.SPON_HIGH:.0%},同一主力鎖碼）", True))
        elif spon >= _vp.SPON_GATE:
            items.append(("△", _L("sponsorship"), f"回頭率 {spon:.0%}（≥{_vp.SPON_HIGH:.0%} 視為強）", None))
        else:
            items.append(("✗", _L("sponsorship"), f"回頭率 {spon:.0%}，偏低（買盤分散）", False))

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
            if abs(dist) <= _vp.COST_SAFETY_BAND_PCT:
                items.append(("✓", "主力成本支撐", f"現價距成本 {dist:+.1f}%，在安全區間 ±{_vp.COST_SAFETY_BAND_PCT:.0f}% 內", True))
            elif dist > _vp.COST_SAFETY_BAND_PCT:
                items.append(("△", "主力成本支撐", f"現價高於成本 {dist:.1f}%（偏離安全區）", None))
            else:
                items.append(("✗", "主力成本支撐", f"現價低於成本 {abs(dist):.1f}%", False))
        else:
            items.append(("—", "主力成本支撐", "無主力成本資料", None))

        # 5. Concentration — interim:viewer 直讀 data/tdcc/ 週快取原始值(Q5.1 放行,
        #    Yonki 2026-07-15),正式落地待 2.0 schema。僅呈現原始值(TDCC 為週頻,標資料週);
        #    不做通過判定(ok 維持 None,passed/total 語意一個字不動)。
        _td = _tdcc_lookup(e.ticker, active_date)
        if _td and _td.get("large_holder_1000_pct") is not None:
            _d1000 = f"，週變化 {_td['delta_1000']:+.2f}pt" if _td.get("delta_1000") is not None else ""
            items.append(("—", "籌碼集中度",
                          f"千張大戶 {_td['large_holder_1000_pct']:.2f}%{_d1000}"
                          f"（資料週：{_td['week']}）", None))
        else:
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
            parts.append(f"榜上連續 {e.streak} 日主力買超")
        elif e.streak >= 3:
            parts.append(f"榜上連買 {e.streak} 日呈現持續吸籌")
        if e.sponsorship_score >= 0.8:
            parts.append(f"{_L('sponsorship')}達 {e.sponsorship_score:.0%}，法人高度集中")
        elif e.sponsorship_score >= 0.5:
            parts.append(f"{_L('sponsorship')} {e.sponsorship_score:.0%}")
        if (e.velocity_3d or 0) > _vp.VELOCITY_STRONG:
            parts.append("近三日動能加速顯著")
        elif (e.velocity_3d or 0) > _vp.VELOCITY_POS:
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
        if (e.acceleration or 0) < _vp.MOMENTUM_ACCEL_BREAKDOWN:
            tags.append("動能快速衰退")
        if e.sponsorship_score < 0.3:
            tags.append(f"{_L('sponsorship')}顯著下滑")
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
        "G3": f"G3 {_L('sponsorship')}≥{_vp.SPON_GATE:.0%}", "G4": "G4 風險<臨界",
        "G5": f"G5 {_L('net_alltime')}>0",
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
            # 紅橙一律收斂為紅 token pill(取代 🔴/🟠 emoji;例:「轉弱 W3」)
            weak_html = (
                f'<div class="scd-pill scd-red" style="background:#E4626F18;font-weight:700;">'
                f'<span class="scd-dot scd-red"></span>'
                f'{_wk["label_zh"]} {_wcodes}{_w_tip}'
                f'</div>'
            )
            if _wk["severity"] == "red":
                card_style = ' style="border-color:#E4626F;"'

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
                f'<span class="scd-star">{res_stars}</span> {res_label}'
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
            # Part 1: 策略徽章(tier 徽章之後、轉弱 pill 之前)
            + _strategy_badges_html(e.ticker)
            + f'<span class="gc-state" style="background:{state_col}20;color:{state_col};border:1px solid {state_col}50;">'
            f'{e.sm_state_zh}{days_txt}</span>'
            + (f'<span style="margin-left:2px;">{cat_html}</span>' if cat_html else "")
            + f'<span class="gc-price" style="color:{chg_col};">{price_s} <span style="font-size:12px;">{chg_s}</span></span>'
            f'</div>'
            # Divider
            f'<hr class="gc-divider">'
            # Row 2: key metrics grid (3-column, 6 items)
            + f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 8px;margin:6px 0;">'
            f'<div class="gc-metric"><span class="gc-metric-label">{_L("streak_on_board")}</span><span class="gc-metric-val" style="color:#7EB8D4;">{streak_n}日{(" · " + _L("window_buy_days") + str(_stock_buy_days_in_window(stock))) if _stock_buy_days_in_window(stock) > streak_n else ""}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">{_L("sponsorship")}</span><span class="gc-metric-val" style="color:#D4A84B;">{e.sponsorship_score:.0%}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">主力成本</span><span class="gc-metric-val">{cost_s}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">{_L("velocity_3d")}</span><span class="gc-metric-val">{f"{e.velocity_3d:+,.0f}" if e.velocity_3d is not None else "—"}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">加速度</span><span class="gc-metric-val">{f"{e.acceleration:+,.0f}" if e.acceleration is not None else "—"}</span></div>'
            f'<div class="gc-metric"><span class="gc-metric-label">{_L("net_alltime")}</span><span class="gc-metric-val">{f"{e.net_cumulative:+,}" if e.net_cumulative else "—"}張</span></div>'
            f'</div>'
            # Divider
            f'<hr class="gc-divider">'
            # Row 3: signals
            f'<div class="gc-signals">'
            f'{res_html}'
            f'<div class="gc-signal-pill" style="background:#161B26;color:{cs.grade_color};border:1px solid {cs.grade_color}40;">'
            f'{_L("chip_grade")}&nbsp;{chip_bar}'
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

            # 2) 連續買超(嚴格) + 20日內買超(鬆語意)
            if streak_n >= 7:
                _ev_row("✓", f"連續買超 {streak_n} 天")
            elif streak_n >= 3:
                _ev_row("△", f"連續買超 {streak_n} 天（≥7天為強）")
            elif streak_n >= 1:
                _ev_row("△", f"連續買超 {streak_n} 天（≥3天為基本）")
            else:
                _ev_row("—", "無連續買超")

            # 2b) 20日內買超 — 20 天內主力買超天數(鬆語意,輔助參考)
            _pos_days = _stock_buy_days_in_window(stock)
            _wlbl = _L("window_buy_days")
            if _pos_days > streak_n:  # 只有當 20 日內買超天數大於榜上連買時才有額外資訊量
                if _pos_days >= 12:
                    _ev_row("✓", f"{_wlbl} {_pos_days}/20 天（高頻吸籌）")
                elif _pos_days >= 7:
                    _ev_row("△", f"{_wlbl} {_pos_days}/20 天（中頻）")
                else:
                    _ev_row("△", f"{_wlbl} {_pos_days}/20 天（偶現）")

            # 3) 主力成本支撐
            if mf_cost and mf_cost > 0 and cur_price and cur_price > 0:
                dist = (cur_price - mf_cost) / mf_cost * 100
                if abs(dist) <= _vp.COST_TIGHT_PCT:
                    _ev_row("✓", f"主力成本 {dist:+.1f}%（貼近）")
                elif dist <= _vp.COST_SAFETY_BAND_PCT:
                    _ev_row("✓", f"主力成本 {dist:+.1f}%（安全區）")
                elif dist > _vp.COST_SAFETY_BAND_PCT:
                    _ev_row("△", f"主力成本 {dist:+.1f}%（偏離安全區）")
                else:
                    _ev_row("△", f"主力成本 {dist:+.1f}%（低於成本）")
            else:
                _ev_row("—", "主力成本資料待補")

            # 4) Velocity(3日速度)
            vel = e.velocity_3d
            _vlbl = _L("velocity_3d")
            if vel is None:
                _ev_row("—", f"{_vlbl}資料待補")
            elif vel > _vp.VELOCITY_POS:
                _ev_row("✓", f"Velocity ↑（{_vlbl} +{vel:,.0f}）")
            elif vel > 0:
                _ev_row("△", f"Velocity ↑（{_vlbl} +{vel:,.0f},力道有限）")
            elif vel < _vp.VELOCITY_NEG:
                _ev_row("△", f"Velocity ↓（{_vlbl} {vel:,.0f}）")
            else:
                _ev_row("△", f"Velocity 持平（{_vlbl} {vel:,.0f}）")

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

            # 6) TDCC 集中度 — interim:viewer 直讀 data/tdcc/ 週快取原始值(Q5.1 放行,
            #    Yonki 2026-07-15),正式落地待 2.0 schema。TDCC 為週頻,標資料週;僅呈現不判定。
            _td_ev = _tdcc_lookup(e.ticker, active_date)
            if _td_ev and _td_ev.get("large_holder_1000_pct") is not None:
                _d_ev = (f"，週變化 {_td_ev['delta_1000']:+.2f}pt"
                         if _td_ev.get("delta_1000") is not None else "")
                _ev_row("—", f"千張大戶 {_td_ev['large_holder_1000_pct']:.2f}%{_d_ev}"
                             f"（資料週：{_td_ev['week']}）")
            else:
                _ev_row("—", "TDCC 籌碼集中度資料待補")

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
                f'Chip Momentum Evidence · {_L("chip_grade")}證據</div>'
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
                f' ≥65% 為最高級（搭配價格條件才會顯示 <span class="scd-dot scd-green"></span>可買進），40–64% 增強，&lt;40% 中。'
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
        # Within group (structure unchanged): Part 1 排序 — 雙策略共識置頂 → 單策略
        # → 無標示,再依既有 conviction;轉弱組仍紅燈優先。策略共識為主鍵,不破壞分組。
        if k == _golden_mod.ACTION_WEAKENING:
            action_groups[k].sort(key=lambda e: (e.ticker not in _red, -_tag_count(e.ticker), -e.conviction))
        else:
            action_groups[k].sort(key=lambda e: (-_tag_count(e.ticker), -e.conviction))

    _n_of = {k: len(v) for k, v in action_groups.items()}

    # ── Part 1: strategy health header + consensus counts ────────────────
    _strat_a_n = sum(1 for e in all_entries if "A" in strategy_tag_map.get(e.ticker, {}).get("tags", []))
    _strat_b_n = sum(1 for e in all_entries if "B" in strategy_tag_map.get(e.ticker, {}).get("tags", []))
    _consensus_n = sum(1 for e in all_entries
                       if {"A", "B"} <= set(strategy_tag_map.get(e.ticker, {}).get("tags", [])))
    _render_strategy_health(_strategy_health_load(), _strat_a_n, _strat_b_n, _consensus_n)

    # ── Summary metric strip — action-first (P2) ─────────────────────────
    _metric_strip([
        ("黃金總覽 Total", str(prime_n + strong_n + qual_n),
         f"⭐⭐⭐可買進{_buy_n} ⭐⭐增強{_str_n} ⭐中{_mid_n}", "val-cyan"),
        ('<span class="scd-dot scd-green"></span> 可執行',   str(_n_of[_golden_mod.ACTION_EXECUTABLE]),    "價格在保守錨容忍內", "val-green"),
        ('<span class="scd-dot scd-amber"></span> 等回檔',   str(_n_of[_golden_mod.ACTION_WAIT_PULLBACK]), "結構好、價格延伸",   "val-amber"),
        ('<span class="scd-dot scd-blue"></span> 資料待補', str(_n_of[_golden_mod.ACTION_DATA_PENDING]),  "SKELETON/缺錨點",   "val-cyan"),
        ('<span class="scd-dot scd-red"></span> 動能轉弱', str(_n_of[_golden_mod.ACTION_WEAKENING]),
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
        bullets.append(f'<span class="scd-dot scd-green"></span> 可執行：{tickers_s}{"等" if len(_exec_list) > 3 else ""}。')
    _weak_list = action_groups[_golden_mod.ACTION_WEAKENING]
    if _weak_list:
        tickers_s = "、".join(f"{e.ticker} {e.name}" for e in _weak_list[:2])
        bullets.append(f'<span class="scd-dot scd-red"></span> 需注意動能轉弱：{tickers_s}。')
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
    # SCD_STATUS token 對映(呈現層,覆寫 core 的 emoji icon;分組語意/順序不動)
    _ACTION_TOKEN = {
        _golden_mod.ACTION_EXECUTABLE:    ("scd-green", "#52B788"),
        _golden_mod.ACTION_WAIT_PULLBACK: ("scd-amber", "#E8A93C"),
        _golden_mod.ACTION_DATA_PENDING:  ("scd-blue",  "#7EB8D4"),
        _golden_mod.ACTION_WEAKENING:     ("scd-red",   "#E4626F"),
    }
    for _ak in _golden_mod.ACTION_ORDER:
        _meta = _golden_mod.ACTION_META[_ak]
        _dot_cls, _tok_col = _ACTION_TOKEN.get(_ak, ("scd-neutral", "#8B949E"))
        _legend = _W_LEGEND if _ak == _golden_mod.ACTION_WEAKENING else ""
        _render_section(
            action_groups[_ak],
            f'<div class="g5-momentum-head" style="border-left-color:{_tok_col};">'
            f'<span class="scd-dot {_dot_cls}" style="margin-right:2px;"></span>'
            f'<span class="g5-momentum-label" style="color:{_tok_col};">'
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
                "G1": "漏斗確認", "G2": "狀態強勢", "G3": f"{_L('sponsorship')}≥{_vp.SPON_GATE:.0%}",
                "G4": "風險<臨界", "G5": f"{_L('net_alltime')}>0",
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
                f'&nbsp;·&nbsp; {_L("streak_on_board")} {e.streak}日 &nbsp;·&nbsp; {_L("sponsorship")} {e.sponsorship_score:.0%}</div>'
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
    return "🔴高" if score >= _vp.RISK_LEVEL_HI else ("🟠中" if score >= _vp.RISK_LEVEL_MID else "🟢低")


def _lvl_sponsor(score, days) -> str:
    """主力回頭率;分點樣本 <3 天 → 樣本不足(1/1=100% 假訊號防呆)。"""
    if not days or days < 3:
        return "⚪樣本不足"
    return _lvl(score, _vp.SPON_HIGH, _vp.SPON_GATE)


def _render_score_glossary() -> None:
    """📖 邏輯說明 — 折疊區(P2.9:無粗體、灰字、無 code block —
    fenced block 會觸發 Streamlit SyntaxHighlighter 動態載入,雲端曾 TypeError)。"""
    with st.expander("📖 邏輯說明", expanded=False):
        st.markdown(
            '<div style="font-size:11px;color:#969696;line-height:1.9;">'
            '兩套獨立的計分系統，互相對照用:'
            '<br><br>'
            '① 黃金引擎（⭐進場機會）— 五道門檻＋加分賽，用星級表示:'
            '<br>⭐ 進黃金名單 ＝ 過五道門（G1 有在持續吃貨／G2 行為已成型／G3 主力有回頭／G4 無出貨嫌疑／G5 整體淨買）'
            '<br>⭐⭐ 增強 ＝ 黃金分高（過門後的加分賽:連買越久、回頭率越高、動能越正，分越高）'
            '<br>⭐⭐⭐ 可買進 ＝ 再加價格條件（現價 ≤ 主力成本×1.05 且未轉弱 — 5% 鐵則）'
            '<br><br>'
            '② 多空計分（⭐進場機會的精選觀察）— 獨立的證據天平:'
            '<br>多頭分 ＝ 多頭證據總量:連買＋回頭率＋動能＋黃金身分加權（🟢高≥60%｜🟡中≥40%）'
            '<br>警訊分 ＝ 空頭證據總量:疑似出貨+25%、假突破+20%、速度轉負+15% 等（🔴高≥50%｜🟠中≥30%）'
            '<br>兩者獨立計算，可能同時高——代表多空證據並存，要特別小心'
            '<br><br>'
            '共用的基礎指標:'
            '<br>主力回頭率 ＝ 同一家分點回頭買的頻率（🟢高≥70%:同一主力鎖碼｜🟡中≥40%｜⚪低:每天換人像散戶追價｜樣本不足:分點資料未滿 3 天不評分）'
            '<br>連買(日) ＝ 主力連續淨買超天數 ｜ 20日累計買超(張) ＝ 20 日內主力總買超 ｜ 3日速度 ＝ 近 3 日平均每天買幾張'
            '<br>疑似出貨 ＝ 之前強勢吸籌但買超動能連續轉負——主力可能在倒貨的「嫌疑」狀態（未定罪:缺席買超榜 ≠ 一定在賣）'
            '</div>',
            unsafe_allow_html=True,
        )


def _strip_score_fragments(reason: str) -> str:
    """入選理由去分數化(收尾輪,Yonki 2026-07-15):intel 落地 reason 內含
    「贊助 X%」「信心 Y%」片段——渲染端濾掉,原始片段(連買 N 日等)保留。
    不改上游 intelligence_delta(sidecar 判死停產在即)。"""
    import re as _re
    parts = [p.strip() for p in (reason or "").split("·")]
    kept = [p for p in parts if p and not _re.match(r"^(贊助|信心)\s*\d+(\.\d+)?\s*%$", p)]
    return "  ·  ".join(kept)


def _render_watch_table(active_date: str, snaps: list[dict]) -> None:
    """精選觀察 — intelligence report watch_list rendered as a sortable table.

    C(Yonki 2026-07-15)去分數化:刪「多頭分/警訊分/主力回頭率(高/中/低)」三欄,
    改原始數據——榜上連買日數、主力回頭率(%)、20日累計買超張數;
    #排名 按 20日累計買超張數排。"""
    report = _intel_load(active_date) if active_date else None
    _section_header("◉", "精選觀察", "Top Watch (next 3–5 sessions)",
                    len(report.watch_list) if report else 0)
    st.markdown(_EXPLAIN_DIV.format(
        text="狀態機已達 吸籌中/轉強/已確認 的股票。原始數據優先：榜上連買日數、主力回頭率、"
             "20日累計買超張數，依 20日累計買超張數排名。主力回頭率＝同一家分點回頭買的頻率"
             "（越頻繁越高）。只有 10 秒的話，看這張表就夠。"),
        unsafe_allow_html=True)
    if not report or not report.watch_list:
        st.markdown('<div class="data-gap-notice">無觀察名單資料（今日情報尚未生成）</div>',
                    unsafe_allow_html=True)
        return
    latest_stocks = {s["ticker"]: s for s in (snaps[-1].get("stocks", []) if snaps else [])}
    import pandas as _pd
    tmp = []
    for w in report.watch_list:
        net = _stock_net_accumulation(latest_stocks.get(w.ticker, {}))
        tmp.append((net, w))
    tmp.sort(key=lambda t: -t[0])   # 按 20日累計買超張數排
    rows = []
    for rank, (net, w) in enumerate(tmp, 1):
        rows.append({
            "#排名": rank,
            "代號": w.ticker,
            "名稱": w.name,
            "狀態": w.sm_state_zh,
            _C("streak_on_board"): w.streak,
            _L("sponsorship"): f"{(w.sponsorship or 0):.0%}",
            _C("net_window"): f"{net:+,}",
            "在此狀態(天)": w.days_in_state,
            "入選理由": _strip_score_fragments(w.reason_zh),
        })
    st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_near_miss_table(snaps: list[dict]) -> None:
    """黃金候補 — near-miss entries as a table (moved out of the golden tab)."""
    key = _snaps_key(snaps)
    result = _run_golden(key, snaps)
    near = sorted(result.near_miss, key=lambda e: e.conviction, reverse=True)
    _section_header("△", "黃金候補", "Near-Miss Watchzone", len(near))
    st.markdown(_EXPLAIN_DIV.format(
        text=f"黃金名單 5 道門檻（G1 漏斗確認／G2 狀態強勢／G3 {_L('sponsorship')}≥{_vp.SPON_GATE:.0%}／"
             f"G4 無疑似出貨等臨界風險／G5 {_L('net_alltime')}>0）"
             "剛好通過 4 道的股票——距離升級黃金最近的預備隊。「缺門檻」欄標出還差哪一道。"
             "黃金分＝過門後的加分賽總分（連買越久、回頭率越高、動能越正分數越高）。"),
        unsafe_allow_html=True)
    if not near:
        st.markdown('<div class="data-gap-notice">今日無候補標的（沒有剛好過 4 道門檻的股票）</div>',
                    unsafe_allow_html=True)
        return
    latest_stocks = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}
    _gate_zh = {"G1": "漏斗確認", "G2": "狀態強勢", "G3": f"{_L('sponsorship')}≥{_vp.SPON_GATE:.0%}",
                "G4": "風險<臨界", "G5": f"{_L('net_alltime')}>0"}
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
            "黃金分": _lvl(e.conviction, _vp.TIER_PRIME_CUT, _vp.TIER_STRONG_CUT),
            "缺門檻": "、".join(_gate_zh.get(g, g) for g in failed) or "—",
            "狀態": e.sm_state_zh,
            _C("streak_on_board"): e.streak or 0,
            _L("sponsorship"): _lvl(e.sponsorship_score, _vp.SPON_HIGH, _vp.SPON_GATE),
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

    # profiles is a dict; use the pre-sorted lists
    profs = result.ideal + result.watch + result.deteriorating + result.weak

    # ── Temperature banner ── C(Yonki 2026-07-15):改讀當日落地 obs_market_temperature
    #    (與市場體制區同源);缺欄(舊快照)誠實佔位,不 fallback 回已判死的 confidence 引擎。
    obs_temp = (snaps[-1].get("obs_market_temperature") if snaps else None) or {}
    temp_color_map = {
        "cool":    ("#7EB8D4", "#0A1520", "冷靜"),
        "stable":  ("#52B788", "#0A1F12", "穩定"),
        "warm":    ("#D4A84B", "#1F1508", "偏熱"),
        "hot":     ("#E05C7A", "#1F0A10", "過熱"),
        "extreme": ("#FF6B9D", "#2A0818", "極端"),
    }
    if obs_temp:
        t_level = obs_temp.get("temperature_level", "")
        tc, tbg, _tzh = temp_color_map.get(t_level, ("#8B949E", "#111820", "—"))
        tzh = obs_temp.get("temperature_zh", _tzh)
        t_pct = int((obs_temp.get("temperature") or 0) * 100)
        st.markdown(
            f'<div class="temp-strip" style="background:{tbg};border-left-color:{tc};">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;">'
            f'<div>'
            f'<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">市場風險溫度 MARKET RISK TEMPERATURE</div>'
            f'<div style="font-size:28px;font-weight:800;color:{tc};line-height:1.2;">{tzh} · {t_level.upper()}</div>'
            f'<div style="font-size:13px;color:#8B949E;margin-top:4px;">{obs_temp.get("temperature_zh","")}</div>'
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
    else:
        st.markdown(
            '<div class="data-gap-notice">該日無落地市場溫度（obs_market_temperature 欄缺，'
            '此日快照早於 2026-07-13 母體修正上線）。</div>',
            unsafe_allow_html=True,
        )

    # ── 數字條已刪(P3.2:與下方表格重複);溫度橫幅補說明 ─────────────────────
    st.markdown(_EXPLAIN_DIV.format(
        text="市場風險溫度＝全市場警訊訊號的加權濃度（高風險股佔比＋出貨中佔比＋廣度風險）。"
             "溫度越高，越該收手觀望。"),
        unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── 三維泡泡圖 D5(Yonki 2026-07-15 誠實化):軸全部換落地原始觀測值 ──────────
    #   X = 轉弱證據(weakening 旗標數 + obs_sm_transition_risk 層級,離散+jitter 防重疊)
    #   Y = 連買日數(原始)   大小 = 累計淨買張數   顏色 = obs_sm_state 的 SCD_STATUS token
    #   金框 = 持股。刪 _conf_proxy/_risk_proxy 與「(代理)」警語(不再有代理軸)。
    if profs:
        _section_header("◉", "轉弱證據 × 連買動能 × 籌碼 泡泡圖", "Weakening × Streak × Flow Bubble Map")
        st.markdown(_EXPLAIN_DIV.format(
            text="全落地原始觀測值：X＝轉弱證據（W1-W5 旗標數＋狀態轉換風險層級，越右越危險），"
                 "Y＝主力連買日數（越上動能越強），泡泡大小＝20 日累計淨買張數，顏色＝sm 生命週期狀態，"
                 "金框＝持股中。滑鼠停在泡泡上看原始值（無任何百分比）。"),
            unsafe_allow_html=True)
        latest_ls = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

        # obs_sm_state → SCD_STATUS token 色(C12:呈現映射 viewer 單一擁有)
        _SM_TOKEN = {
            "strengthening": "#52B788",  # green 轉強
            "confirmed":     "#EBC92F",  # gold  成熟確認
            "accumulating":  "#7EB8D4",  # blue  吸籌
            "decelerating":  "#E8A93C",  # amber 減速
            "distributing":  "#E4626F",  # red   疑似出貨
            "failed":        "#E4626F",  # red
            "exited":        "#8B949E",  # neutral 已退出
        }
        _SM_ZH = {
            "strengthening": "轉強中", "confirmed": "成熟確認", "accumulating": "吸籌中",
            "decelerating": "減速中", "distributing": "疑似出貨", "failed": "訊號失敗",
            "exited": "已退出",
        }
        _RISK_RANK = _vp.RISK_RANK

        # 持股集合(金框);holdings.json 目前可能為空。
        try:
            _hold = json.loads((_AI_STOCK / "data" / "holdings.json").read_text(encoding="utf-8"))
            held = {h.get("ticker") for h in _hold.get("holdings", [])}
        except Exception:
            held = set()

        # flow 宇宙:20 日累計淨買 ≠ 0,最大者優先,取前 N(顯示用,非評分)
        flow = sorted(
            [p for p in profs if _stock_net_accumulation(latest_ls.get(p.ticker, {}))],
            key=lambda p: abs(_stock_net_accumulation(latest_ls.get(p.ticker, {}))),
            reverse=True,
        )[:_vp.BUBBLE_FLOW_TOP_N] or profs[:_vp.BUBBLE_FLOW_TOP_N]

        import random as _rnd
        _rnd.seed(42)  # jitter 確定性:同一輸入 → 同一圖
        xs, ys, sizes, colors, line_w, line_c, labels, hover = [], [], [], [], [], [], [], []
        for p in flow:
            stk    = latest_ls.get(p.ticker, {})
            flags  = (stk.get("weakening") or {}).get("flags", [])
            risk_lv = _RISK_RANK.get(stk.get("obs_sm_transition_risk"), 0)
            x_pos  = len(flags) + risk_lv + _rnd.uniform(-0.15, 0.15)
            streak = _stock_streak(stk)
            net    = _stock_net_accumulation(stk)
            sm     = stk.get("obs_sm_state") or "exited"
            price  = stk.get("current_price")
            chg    = stk.get("change_pct")
            is_held = p.ticker in held
            flag_codes = "、".join(f'{f.get("code","")}{f.get("zh","")}' for f in flags) if flags else "無"
            xs.append(x_pos)
            ys.append(streak)
            sizes.append(_vp.BUBBLE_BASE_SIZE + (abs(net) ** 0.5) / _vp.BUBBLE_NET_DIVISOR)
            colors.append(_SM_TOKEN.get(sm, "#8B949E"))
            line_w.append(3 if is_held else 1.5)
            line_c.append("#EBC92F" if is_held else _SM_TOKEN.get(sm, "#8B949E"))
            labels.append(stk.get("name") or p.ticker)
            hover.append(
                f"<b>{p.ticker} {p.name}</b><br>"
                f"現價 {('NT$%.2f' % price) if price else '—'} "
                f"({('%+.2f%%' % chg) if chg is not None else '—'})<br>"
                f"連買 {streak} 日<br>"
                f"累計淨買 {net:+,} 張<br>"
                f"狀態 {_SM_ZH.get(sm, sm)}<br>"
                f"轉弱旗標 {flag_codes}（轉換風險 {stk.get('obs_sm_transition_risk','—')}）"
            )

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            text=labels, textposition="middle center",
            textfont=dict(size=9, color="#E8E4D8"),
            marker=dict(size=sizes, color=colors, opacity=0.5,
                        line=dict(width=line_w, color=line_c), sizemode="diameter"),
            hovertext=hover, hoverinfo="text",
        ))
        _max_x = max(xs, default=4)
        layout = _plotly_layout("轉弱證據 × 連買動能 × 籌碼 泡泡圖", 460)
        layout["xaxis"].update(dict(title="轉弱證據 →", range=[-0.6, max(4.0, _max_x + 0.7)], dtick=1))
        layout["yaxis"].update(dict(title="← 連買動能", rangemode="tozero"))
        fig.update_layout(**layout)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            '<div style="font-size:11px;color:#7A8070;margin-top:-6px;line-height:1.7;">'
            '顏色＝sm 狀態：'
            '<span style="color:#52B788;">●</span>轉強　'
            '<span style="color:#EBC92F;">●</span>成熟確認　'
            '<span style="color:#7EB8D4;">●</span>吸籌　'
            '<span style="color:#E8A93C;">●</span>減速　'
            '<span style="color:#E4626F;">●</span>出貨/失敗　'
            '<span style="color:#8B949E;">●</span>已退出'
            '　·　泡泡大小＝累計淨買張數　·　金框＝持股中'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 全市場體檢表(P3.2:側寫卡片牆 → 一張表格,舊詞全換新) ────────────────
    latest_stocks_ls = {s["ticker"]: s for s in snaps[-1].get("stocks", [])}

    _section_header("☑", "全市場體檢表", "All Profiles", len(profs))
    st.markdown(_EXPLAIN_DIV.format(
        text="原始數據優先：sm 狀態（白話生命週期）、榜上連買日數、20日累計買超張數、"
             "轉弱旗標（W1-W5，無則空）。多頭分/警訊分（高/中/低）已去分數化移除。"
             "排序：狀態較強者在前。搜尋用表格右上角 🔍。"),
        unsafe_allow_html=True)

    mid_low   = [p for p in result.profiles.values() if p.profile_code == "mid_low"]
    watch_all = result.watch + result.deteriorating + result.weak
    ordered = result.ideal + mid_low + [p for p in watch_all if p.ticker not in
                                        {q.ticker for q in result.ideal} | {q.ticker for q in mid_low}]
    import pandas as _pd
    prof_rows = []
    for p in ordered:
        stock = latest_stocks_ls.get(p.ticker, {})
        price = stock.get("current_price")
        chg   = stock.get("change_pct")
        flags = (stock.get("weakening") or {}).get("flags", [])
        flag_str = "、".join(f'{f.get("code","")}{f.get("zh","")}' for f in flags) if flags else ""
        prof_rows.append({
            "代號": p.ticker,
            "名稱": p.name,
            "現價": f"NT${price:,.2f}" if price else "—",
            "漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            "sm 狀態": p.sm_state_zh,
            _C("streak_on_board"): p.streak,
            _C("net_window"): f"{_stock_net_accumulation(stock):+,}",
            "轉弱旗標": flag_str,
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


def _delta_table(changes: list[BiggestChange], mode: str = "pct") -> str:
    """mode: 'pct'（0-1→%,主力回頭率Δ 用）｜ 'raw'（原始張數,速度Δ 用）。
    C(術語契約):刪回頭率×20 假日數 'days' 模式,回頭率Δ 一律顯 %。"""
    if not changes:
        return '<div class="data-gap-notice">無顯著變化</div>'
    rows = ""
    for c in changes:
        color = "#52B788" if c.direction == "up" else "#E05C7A"
        arrow = "↑" if c.direction == "up" else "↓"
        if mode == "raw":
            fv = f"{c.from_value:+,.0f}"
            tv = f"{c.to_value:+,.0f}"
            dv = f"{c.delta:+,.0f}"
        else:  # pct
            fv = f"{c.from_value:.0%}"
            tv = f"{c.to_value:.0%}"
            dv = f"{c.delta:+.0%}"
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


def _optimism_table(changes: list[BiggestChange], latest_map: dict, prev_map: dict) -> str:
    """C(Yonki 2026-07-15):「樂觀分數」欄——內部仍按 confidenceΔ 排序（排名合法），
    但每列版面顯示該股「最主要變化」的原始值（連買日數差 或 累計張數差，取幅度大者），
    完整明細（連買/累計/速度）放 HTML title hover tooltip。不顯示任何 %。"""
    if not changes:
        return '<div class="data-gap-notice">無顯著變化</div>'
    rows = ""
    for c in changes:
        now  = latest_map.get(c.ticker, {})
        prev = prev_map.get(c.ticker, {})
        s_now, s_prev = _stock_streak(now), _stock_streak(prev)
        n_now, n_prev = _stock_net_accumulation(now), _stock_net_accumulation(prev)
        d_streak, d_net = s_now - s_prev, n_now - n_prev
        if d_streak != 0:
            main = f"連買 {d_streak:+d}日"
        elif d_net != 0:
            main = f"累計 {d_net:+,}張"
        else:
            main = "—"
        color = "#52B788" if c.direction == "up" else "#E05C7A"
        vel = now.get("velocity_3d")
        tip = (f"連買 {s_prev}→{s_now}日 ｜ 累計 {n_prev:+,}→{n_now:+,}張"
               + (f" ｜ 速度 {round(vel):+,}張/日" if vel is not None else ""))
        rows += (
            f'<div class="delta-row" title="{tip}">'
            f'<span class="delta-ticker">{c.ticker}</span>'
            f'<span class="delta-name">{c.name}</span>'
            f'<span class="delta-to" style="color:{color};">{main}</span>'
            f'</div>'
        )
    return rows


def _render_intelligence(active_date: str, snaps: list[dict], part: str = "story") -> None:
    """P3.2 拆件:深度數據 tab 解散(Yonki 2026-07-04),三個部分各自歸位 —
    part='story'   今日綜述(市場故事)      → 市場敘事 tab 頂部
    part='changes' Δ排行 + 今日事件(質變)  → 進場機會(潛力區併入)
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
                 "量化明細在「⭐ 進場機會→今日變化」與「🔻 出場警示→風險警報」。"),
            unsafe_allow_html=True)
        # A(Yonki 2026-07-15):渲染端過濾「市場廣度」與「風險溫度」兩類 bullet——真值
        # 已由市場體制區呈現;不改上游 intelligence_delta(sidecar 判死停產在即)。
        _story = [
            s for s in (report.market_story or [])
            if not (s.startswith("市場廣度") or "風險溫度" in s)
        ]
        if _story:
            for s in _story:
                st.markdown(f'<div class="intel-story-item">• {s}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="data-gap-notice">無市場故事資料</div>', unsafe_allow_html=True)
        return

    # ═══ part: changes — Δ排行 + 今日事件(質變) ═════════════════════════════
    if part == "changes":
        _section_header("△", "最大變化排行", "Biggest Changes (last 24h)")
        st.markdown(_EXPLAIN_DIV.format(
            text="原始數據優先：主力回頭率變化（%）、主力速度（張/日）變化、以及「樂觀分數」欄"
                 "（內部按綜合多頭證據排序，版面顯示各股最主要的原始變化——連買日數或累計張數；"
                 "滑鼠停在該列看完整明細，該欄不顯示百分比）。"),
            unsafe_allow_html=True)
        _latest_map = {s["ticker"]: s for s in (snaps[-1].get("stocks", []) if snaps else [])}
        _prev_map   = {s["ticker"]: s for s in (snaps[-2].get("stocks", []) if len(snaps) >= 2 else [])}
        col_s, col_v, col_c = st.columns(3, gap="small")
        with col_s:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                f'letter-spacing:.08em;margin-bottom:8px;">{_L("sponsorship")} Δ (%)</div>',
                unsafe_allow_html=True)
            st.markdown(_delta_table(report.biggest_sponsorship_changes, mode="pct"),
                        unsafe_allow_html=True)
        with col_v:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                'letter-spacing:.08em;margin-bottom:8px;">速度 Velocity Δ (張/日)</div>',
                unsafe_allow_html=True)
            st.markdown(_delta_table(report.biggest_velocity_changes, mode="raw"),
                        unsafe_allow_html=True)
        with col_c:
            st.markdown(
                '<div style="font-size:11px;color:#6B8EAA;text-transform:uppercase;'
                'letter-spacing:.08em;margin-bottom:8px;">樂觀分數（主要變化）</div>',
                unsafe_allow_html=True)
            st.markdown(_optimism_table(report.biggest_confidence_changes, _latest_map, _prev_map),
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

def _freshness_status(latest_date: str) -> tuple[str, str, str]:
    """6.1 資料新鮮度:回 (顯示文字, 顏色, 警示文字或空)。

    以最新快照日到今天的『交易日(週一~週五)』距離衡量。盤後 pipeline 讓最新快照通常
    是前一交易日 → 0~1 交易日為正常;≥2 視為可能斷更並跳過期警示。純呈現、無外部依賴。
    """
    if not latest_date:
        return "—", "#6B8EAA", ""
    try:
        d0 = dt.date.fromisoformat(latest_date)
    except ValueError:
        return "—", "#6B8EAA", ""
    today = dt.date.today()
    if today <= d0:
        return "當日最新", "#52B788", ""
    # count trading days (Mon–Fri) strictly after d0, up to and including today
    n = 0
    cur = d0
    while cur < today:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    if n <= 1:
        return f"距今 {n} 交易日", "#52B788", ""
    if n == 2:
        return f"距今 {n} 交易日", "#E8A838", ""
    return (f"距今 {n} 交易日", "#E4626F",
            f"最新快照距今 {n} 交易日,可能斷更 — 請查證 pipeline / 資料來源。")


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

        # ── 6.1 資料新鮮度:距今 N 交易日 + 過期警示 ─────────────────────────
        fresh_txt, fresh_col, fresh_warn = _freshness_status(latest_date)
        st.markdown(
            f'<div class="sidebar-stat-row">'
            f'<span class="sidebar-stat-key">資料新鮮度</span>'
            f'<span class="sidebar-stat-val" style="color:{fresh_col};">{fresh_txt}</span>'
            f'</div>'
            + (f'<div class="data-gap-notice" style="margin:6px 0 0 0;padding:6px 10px;font-size:12px !important;">'
               f'⚠️ {fresh_warn}</div>' if fresh_warn else ""),
            unsafe_allow_html=True,
        )
        st.caption(f"commit `{_deployed_commit_hash()}`")

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

    # ── 兩段式快照:外資待補橫幅(fii_pending 由 pipeline 寫入,純渲染)──
    if snaps_to_date and snaps_to_date[-1].get("fii_pending"):
        st.markdown(
            '<div style="background:#2A230D;border:1px solid #8A6D1A;border-radius:8px;'
            'padding:10px 14px;margin:0 0 14px 0;color:#E8C55A;font-size:13px;">'
            '⏳ <b>部分快照</b> — 今日外資(三大法人)數據尚未取得,'
            '外資相關欄位暫缺;明晨引擎自動補完後即顯示完整數據。</div>',
            unsafe_allow_html=True,
        )

    # ── Tabs（Yonki 2026-07-11:潛力區併入進場機會,6 tabs —
    #    故事→市場敘事頂 / Δ+質變事件+轉強+多空計分→進場機會 / 風險警報→出場警示）─
    tab_market, tab_holdings, tab_entry, tab_exit, tab_research, tab_backtest = st.tabs([
        "📰 市場敘事",
        "💼 我的持倉",
        "⭐ 進場機會",
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
        # 進場機會 = 黃金引擎全家 + 潛力區併入(Yonki 2026-07-11):
        #   黃金名單(過五門) → 黃金候補(過四門)
        #   → 轉強訊號(潛力區拉上,緊接黃金候補)
        #   → 潛力區其餘訊號表(維持原相對順序:多空計分精選觀察 → 今日變化Δ+質變)
        _render_score_glossary()
        st.markdown(_SECTION_TITLE.format(label="★ 黃金名單"), unsafe_allow_html=True)
        _render_golden(snaps_to_date, show_near_miss=False)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_near_miss_table(snaps_to_date)
        # ── 潛力區併入 ──
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_strengthening(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_watch_table(active_date, snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_intelligence(active_date, snaps_to_date, part="changes")

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
        # 市場敘事(A, Yonki 2026-07-15 定案順序):
        # 市場體制(頂) → 龍頭雷達 → ⚡警訊(小字) → 今日綜述 → 主題觀察
        # → 資金輪動(含族群走勢) → 熱度 → 三觀察點
        st.markdown(_SECTION_TITLE.format(label="📊 市場體制"), unsafe_allow_html=True)
        st.markdown(_EXPLAIN_DIV.format(
            text="用全市場廣度（幾 % 股票在漲）、平均漲跌、量能綜合判定今天屬於哪種環境"
                 "（吸籌期／觀望期／防禦期…），決定今天適不適合出手。"),
            unsafe_allow_html=True)
        _render_regime(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        st.markdown(_SECTION_TITLE.format(label="🎯 龍頭雷達"), unsafe_allow_html=True)
        _render_watchlist_radar(snaps_to_date)
        _render_regime_alert(snaps_to_date)
        st.markdown(_SECTION_HR, unsafe_allow_html=True)
        _render_intelligence(active_date, snaps_to_date, part="story")
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
            text="獨立於黃金引擎的全市場掃描，原始觀測值優先、無綜合評分："
                 "先看泡泡圖分布（轉弱證據 × 連買動能 × 累計買超）鎖定目標，"
                 "再到下方「個股時序」放大看逐日演化。"),
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
