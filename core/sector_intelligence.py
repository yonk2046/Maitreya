"""SCD Engine — Sector & Rotation Intelligence  (P3d)
板塊輪動智慧觀測層

Pure observation module. NO trading signals, NO buy/sell recommendations.
All functions describe the structural flow of capital across sectors — nothing more.

Public API
----------
    build_sector_map(snapshots)          → SectorMap (enriched ticker→sector mapping)
    sector_strength(snapshots)           → dict per sector: breadth / persistence / acceleration
    rotation_analysis(snapshots)         → rotation events, leading/weakening/emerging sectors
    sector_summary(snapshots)            → daily rotation summary (top-level output)
    sector_time_series(snapshots)        → per-sector metric timeseries for charting

Design principles
-----------------
- All inputs are pre-loaded snapshot dicts (same shape as vd.load_snapshot)
- All outputs are plain dicts / lists — no side effects, no I/O
- Sectors are defined in SECTOR_TAXONOMY (extended from watchlists.SECTOR_GROUPS)
- Unknown tickers fall into "other" sector
- Rotation is detected by comparing consecutive snapshot sector rankings
- Acceleration is the second derivative of 3-day velocity (observational only)
"""
from __future__ import annotations

import json
import pathlib
from collections import defaultdict
from typing import Any

# ---------------------------------------------------------------------------
# Extended Sector Taxonomy
# ---------------------------------------------------------------------------
# Extends core.watchlists.SECTOR_GROUPS with additional sub-sectors.
# Ticker→sector assignment: first match wins (most-specific listed first).

SECTOR_TAXONOMY: dict[str, dict[str, Any]] = {
    # ── AI / Server Infrastructure ────────────────────────────────────────
    "ai_server": {
        "zh": "AI伺服器", "en": "AI / Server",
        "color": "#7EB8D4", "icon": "🤖",
        "tickers": [
            "2382",  # 廣達
            "2356",  # 英業達
            "3231",  # 緯創
            "2324",  # 仁寶
            "6669",  # 緯穎
            "3017",  # 奇鋐
            "6273",  # 台燿
            "4958",  # 臻鼎-KY
            "3443",  # 創意
        ],
    },
    # ── Semiconductors (foundry / fabless / design) ───────────────────────
    "semiconductor": {
        "zh": "半導體", "en": "Semiconductor",
        "color": "#52B788", "icon": "⬡",
        "tickers": [
            "2330",  # 台積電
            "2454",  # 聯發科
            "2303",  # 聯電
            "2408",  # 南亞科
            "2344",  # 華邦電
            "2337",  # 旺宏
            "6770",  # 力積電
            "3711",  # 日月光投控
            "2449",  # 京元電子
            "3034",  # 聯詠
            "3006",  # 晶豪科
            # 2385 群光 removed 2026-06-12 — 電腦及週邊, resolves via official map (25)
            "3697",  # 晨星半導體 (delisted, kept for history)
        ],
    },
    # ── Memory ────────────────────────────────────────────────────────────
    "memory": {
        "zh": "記憶體", "en": "Memory",
        "color": "#9E8AC8", "icon": "◫",
        "tickers": [
            "2344",  # 華邦電
            "2408",  # 南亞科
            "3260",  # 威剛
            "4863",  # 新鉅科
            "6770",  # 力積電
            "2337",  # 旺宏
        ],
    },
    # ── Networking / PCB / Connectivity ───────────────────────────────────
    "networking": {
        "zh": "網路通訊", "en": "Networking / PCB",
        "color": "#4AB0B8", "icon": "⬡",
        "tickers": [
            "2345",  # 智邦
            "2367",  # 燿華
            "3037",  # 欣興
            "2316",  # 楠梓電
            # 6505 台塑化 removed 2026-06-12 — 油電燃氣, resolves via official map (23)
            "2379",  # 瑞昱半導體
            "3105",  # 穩懋
        ],
    },
    # ── Electronics / EMS (contract manufacturing) ────────────────────────
    "electronics": {
        "zh": "電子代工", "en": "Electronics / EMS",
        "color": "#7EB8D4", "icon": "⬢",
        "tickers": [
            "2317",  # 鴻海
            "2354",  # 鴻準
            "2308",  # 台達電
            "2353",  # 宏碁
            "2312",  # 金寶
        ],
    },
    # ── Financials ────────────────────────────────────────────────────────
    "financials": {
        "zh": "金融", "en": "Financials",
        "color": "#D4A84B", "icon": "⬡",
        "tickers": [
            "2881",  # 富邦金
            "2882",  # 國泰金
            "2891",  # 中信金
            "2883",  # 開發金
            "2884",  # 玉山金
            "2885",  # 元大金
            "2886",  # 兆豐金
            "2887",  # 台新金
            "2892",  # 第一金
            "2801",  # 彰銀
            "2834",  # 臺企銀
        ],
    },
    # ── Shipping ──────────────────────────────────────────────────────────
    "shipping": {
        "zh": "航運", "en": "Shipping",
        "color": "#6B9AAA", "icon": "⛵",
        "tickers": [
            "2609",  # 陽明海運
            "2610",  # 華航
            "2603",  # 長榮
            "2615",  # 萬海
            # 5880 合庫金 removed 2026-06-12 — financial, resolves via official map (17)
        ],
    },
    # ── Heavy Industry / Steel ────────────────────────────────────────────
    "heavy_industry": {
        "zh": "重工/鋼鐵", "en": "Heavy Industry / Steel",
        "color": "#8A7A6A", "icon": "⚙",
        "tickers": [
            "2002",  # 中鋼
            "2008",  # 高興昌鋼鐵
            "2015",  # 豐興鋼鐵
            "2017",  # 官田鋼
            "1503",  # 士電
            "1504",  # 東元
            "1507",  # 永大
        ],
    },
    # ── Energy / Power / Green ────────────────────────────────────────────
    "energy_power": {
        "zh": "能源/電力", "en": "Energy / Power",
        "color": "#B8A052", "icon": "⚡",
        "tickers": [
            "6505",  # 台塑化
            # 2026-06-12 cleanup: 1301/1303/1326 belong to materials (curated below);
            # 9945 潤泰全 → consumer via official map (18); 5347 世界先進 → semiconductor
            # via official map (24). Removed from this list.
        ],
    },
    # ── Materials / Chemicals ─────────────────────────────────────────────
    "materials": {
        "zh": "材料/化工", "en": "Materials / Chemicals",
        "color": "#7A8A6A", "icon": "◎",
        "tickers": [
            "1301",  # 台塑
            "1303",  # 南亞塑膠
            "1326",  # 台化
            "1802",  # 台玻
        ],
    },
    # ── ETFs / Index Proxies ──────────────────────────────────────────────
    "etf_index": {
        "zh": "ETF/指數", "en": "ETFs / Index Proxies",
        "color": "#5A7A8A", "icon": "▣",
        "tickers": [
            "0050",  # 元大台灣50
            "0051",  # 元大中型100
            "0052",  # 富邦科技
            "00632R", # 元大台灣50反1
            "006208", # 富邦台50
        ],
    },
    # ── Optoelectronics (panels / lenses / LED) ───────────────────────────
    "optoelectronics": {
        "zh": "光電", "en": "Optoelectronics",
        "color": "#C88A5A", "icon": "◐",
        "tickers": [],
    },
    # ── Electronic Components (passive / connectors / batteries) ─────────
    "components": {
        "zh": "電子零組件", "en": "Components",
        "color": "#8AA86A", "icon": "▫",
        "tickers": [],
    },
    # ── Tech Services / Distribution / Cloud ─────────────────────────────
    "tech_services": {
        "zh": "資訊服務/通路", "en": "Tech Services",
        "color": "#5A8AC8", "icon": "☁",
        "tickers": [],
    },
    # ── Machinery / Electrical Equipment ──────────────────────────────────
    "machinery": {
        "zh": "電機機械", "en": "Machinery / Electrical",
        "color": "#A8825A", "icon": "⚙",
        "tickers": [],
    },
    # ── Automotive / Parts ────────────────────────────────────────────────
    "automotive": {
        "zh": "汽車", "en": "Automotive",
        "color": "#7A6A9A", "icon": "◈",
        "tickers": [],
    },
    # ── Textiles ──────────────────────────────────────────────────────────
    "textiles": {
        "zh": "紡織", "en": "Textiles",
        "color": "#B87A8A", "icon": "✂",
        "tickers": [],
    },
    # ── Food / Agriculture ────────────────────────────────────────────────
    "food_agri": {
        "zh": "食品/農業", "en": "Food / Agri",
        "color": "#9AA85A", "icon": "☘",
        "tickers": [],
    },
    # ── Biotech / Healthcare ──────────────────────────────────────────────
    "biotech": {
        "zh": "生技醫療", "en": "Biotech / Healthcare",
        "color": "#5AB89A", "icon": "✚",
        "tickers": [],
    },
    # ── Consumer / Retail / Tourism / Lifestyle ───────────────────────────
    "consumer": {
        "zh": "消費/觀光", "en": "Consumer / Tourism",
        "color": "#C8A06A", "icon": "◍",
        "tickers": [],
    },
    # ── Construction / Cement ─────────────────────────────────────────────
    "construction": {
        "zh": "營建/水泥", "en": "Construction / Cement",
        "color": "#8A8A7A", "icon": "▤",
        "tickers": [],
    },
    # ── Conglomerates / Misc ──────────────────────────────────────────────
    "conglomerate": {
        "zh": "綜合/其他", "en": "Conglomerate / Misc",
        "color": "#6A7A8A", "icon": "◌",
        "tickers": [],
    },
    # ── Catch-all ─────────────────────────────────────────────────────────
    "other": {
        "zh": "其他", "en": "Other",
        "color": "#3A4A5A", "icon": "○",
        "tickers": [],
    },
}

# ---------------------------------------------------------------------------
# Official TWSE/TPEx industry code → sector group (mid-granularity)
# ---------------------------------------------------------------------------
# Both exchanges share one code family. Source: TWSE/TPEx company-basics
# open data, cached at data/industry/industry_map.json by tools/fetch_industry.
# Curated SECTOR_TAXONOMY ticker lists act as a thematic OVERLAY (e.g.
# ai_server, memory) and always win over the official code.

INDUSTRY_CODE_TO_SECTOR: dict[str, str] = {
    "01": "construction",    # 水泥
    "02": "food_agri",       # 食品
    "03": "materials",       # 塑膠
    "04": "textiles",        # 紡織纖維
    "05": "machinery",       # 電機機械
    "06": "machinery",       # 電器電纜
    "08": "materials",       # 玻璃陶瓷
    "09": "materials",       # 造紙
    "10": "heavy_industry",  # 鋼鐵
    "11": "materials",       # 橡膠
    "12": "automotive",      # 汽車
    "14": "construction",    # 建材營造
    "15": "shipping",        # 航運
    "16": "consumer",        # 觀光餐旅
    "17": "financials",      # 金融保險
    "18": "consumer",        # 貿易百貨
    "19": "conglomerate",    # 綜合
    "20": "conglomerate",    # 其他
    "21": "materials",       # 化學
    "22": "biotech",         # 生技醫療
    "23": "energy_power",    # 油電燃氣
    "24": "semiconductor",   # 半導體
    "25": "electronics",     # 電腦及週邊設備
    "26": "optoelectronics", # 光電
    "27": "networking",      # 通信網路
    "28": "components",      # 電子零組件
    "29": "tech_services",   # 電子通路
    "30": "tech_services",   # 資訊服務
    "31": "electronics",     # 其他電子
    "32": "consumer",        # 文化創意
    "33": "food_agri",       # 農業科技
    "34": "tech_services",   # 電子商務
    "35": "energy_power",    # 綠能環保
    "36": "tech_services",   # 數位雲端
    "37": "consumer",        # 運動休閒
    "38": "consumer",        # 居家生活
}

_INDUSTRY_MAP_FILE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "data" / "industry" / "industry_map.json"
)
_industry_sector_cache: dict[str, str] | None = None


def _industry_map() -> dict[str, str]:
    """Lazy-loaded {ticker: sector_key} from the official industry cache.

    Reference-data load (same nature as the static taxonomy above) — read
    once per process, deterministic given the cache file. Returns {} when
    the cache is absent so the curated taxonomy remains the sole source.
    """
    global _industry_sector_cache
    if _industry_sector_cache is None:
        try:
            raw = json.loads(_INDUSTRY_MAP_FILE.read_text(encoding="utf-8"))
            _industry_sector_cache = {
                t: INDUSTRY_CODE_TO_SECTOR.get(str(code), "other")
                for t, code in raw.get("tickers", {}).items()
            }
        except (OSError, json.JSONDecodeError):
            _industry_sector_cache = {}
    return _industry_sector_cache


def _reset_industry_cache() -> None:
    """Test hook — force re-read of the industry cache file."""
    global _industry_sector_cache
    _industry_sector_cache = None

# Build ticker → sector lookup (first assignment wins, most-specific sector listed first)
_TICKER_TO_SECTOR: dict[str, str] = {}
for _sector, _smeta in SECTOR_TAXONOMY.items():
    for _t in _smeta.get("tickers", []):
        if _t not in _TICKER_TO_SECTOR:
            _TICKER_TO_SECTOR[_t] = _sector


def ticker_sector(ticker: str) -> str:
    """Return the primary sector key for a ticker.

    Resolution order:
      1. Curated SECTOR_TAXONOMY overlay (thematic groups like ai_server win)
      2. Official TWSE/TPEx industry code via data/industry/industry_map.json
      3. "other"
    """
    explicit = _TICKER_TO_SECTOR.get(ticker)
    if explicit is not None:
        return explicit
    return _industry_map().get(ticker, "other")


def sector_meta(sector: str) -> dict[str, Any]:
    """Return metadata dict for a sector key."""
    return SECTOR_TAXONOMY.get(sector, SECTOR_TAXONOMY["other"])


# ---------------------------------------------------------------------------
# SectorMap — enriched per-snapshot view
# ---------------------------------------------------------------------------

class SectorMap:
    """Lightweight result container from build_sector_map()."""

    def __init__(self, mapping: dict[str, str], universe: set[str]) -> None:
        self._map    = mapping        # ticker → sector
        self.universe = universe      # all tickers seen across snapshots

    def sector_of(self, ticker: str) -> str:
        return self._map.get(ticker, "other")

    def tickers_in(self, sector: str) -> list[str]:
        return [t for t, s in self._map.items() if s == sector]

    def sectors_present(self) -> list[str]:
        return sorted(set(self._map.values()))

    def as_dict(self) -> dict[str, str]:
        return dict(self._map)


def build_sector_map(snapshots: list[dict[str, Any]]) -> SectorMap:
    """
    Build a SectorMap from all tickers seen across snapshots.

    Priority:
      1. SECTOR_TAXONOMY explicit assignment (first-match)
      2. Falls back to "other"

    Returns a SectorMap with ticker → sector string for every observed ticker.
    """
    all_tickers: set[str] = set()
    for snap in snapshots:
        for s in snap.get("stocks", []):
            t = s.get("ticker", "")
            if t:
                all_tickers.add(t)

    mapping = {t: ticker_sector(t) for t in all_tickers}
    return SectorMap(mapping, all_tickers)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_per_snap(
    snapshots: list[dict[str, Any]],
    sector_map: SectorMap | None = None,
) -> list[dict[str, Any]]:
    """
    For each snapshot produce:
        date, sector_data: {sector: {tickers, mfb_vals, chg_vals, vol_vals}}
    """
    sm = sector_map or build_sector_map(snapshots)
    result = []

    for snap in snapshots:
        date   = snap.get("date", "?")
        stocks = snap.get("stocks", [])

        sector_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "tickers":   [],
            "mfb_vals":  [],   # main_force_buy
            "chg_vals":  [],   # change_pct
            "vol_vals":  [],   # volume
        })

        for s in stocks:
            ticker = s.get("ticker", "")
            sector = sm.sector_of(ticker)
            sd     = sector_data[sector]
            sd["tickers"].append(ticker)

            mfb = s.get("main_force_buy")
            chg = s.get("change_pct")
            vol = s.get("volume")
            if mfb is not None: sd["mfb_vals"].append(mfb)
            if chg is not None: sd["chg_vals"].append(chg)
            if vol is not None: sd["vol_vals"].append(vol)

        result.append({"date": date, "sector_data": dict(sector_data)})

    return result


# ---------------------------------------------------------------------------
# Sector Strength Scores
# ---------------------------------------------------------------------------

def sector_strength(
    snapshots: list[dict[str, Any]],
    sector_map: SectorMap | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Compute observational strength metrics for each sector in the latest snapshot.

    Returns
    -------
    dict keyed by sector with:
        breadth              — fraction of tickers with positive mfb (0–1)
        net_mfb              — total main_force_buy across sector tickers
        avg_mfb              — net_mfb / ticker_count
        avg_chg              — average change_pct
        persistence_score    — fraction of tickers with mfb > 0 AND seen in prior day
        acceleration         — net_mfb change vs prior day (+/- / None)
        ticker_count         — tickers observed
        ticker_list          — list of ticker strings
        label_zh / label_en  — qualitative description
        meta                 — {zh, en, color, icon}
    """
    if not snapshots:
        return {}

    sm   = sector_map or build_sector_map(snapshots)
    per  = _collect_per_snap(snapshots, sm)

    if not per:
        return {}

    latest = per[-1]["sector_data"]
    prior  = per[-2]["sector_data"] if len(per) >= 2 else {}

    out: dict[str, dict[str, Any]] = {}

    for sector, sd in latest.items():
        mfb_vals = sd["mfb_vals"]
        chg_vals = sd["chg_vals"]
        n        = len(sd["tickers"])

        net_mfb  = int(sum(mfb_vals)) if mfb_vals else 0
        avg_mfb  = round(net_mfb / max(n, 1))
        avg_chg  = round(sum(chg_vals) / len(chg_vals), 3) if chg_vals else 0.0
        breadth  = sum(1 for v in mfb_vals if v > 0) / max(len(mfb_vals), 1) if mfb_vals else 0.0

        # Persistence: tickers also present yesterday with mfb > 0
        prior_sd       = prior.get(sector, {})
        prior_tickers  = set(prior_sd.get("tickers", []))
        persisting     = sum(
            1 for t, v in zip(sd["tickers"], [None] * n)
            if t in prior_tickers
        )
        persistence    = persisting / max(n, 1)

        # Acceleration: Δnet_mfb vs prior day
        prior_net  = int(sum(prior_sd.get("mfb_vals", []))) if prior_sd.get("mfb_vals") else None
        accel      = (net_mfb - prior_net) if prior_net is not None else None

        # Qualitative label
        if breadth >= 0.7 and net_mfb > 0:
            lzh, len_ = "板塊全面進場", "Broad Sector Inflow"
        elif breadth >= 0.5 and net_mfb > 0:
            lzh, len_ = "板塊偏多佈局", "Sector Accumulating"
        elif breadth >= 0.5 and net_mfb <= 0:
            lzh, len_ = "板塊分散整理", "Sector Consolidating"
        elif breadth < 0.3 and net_mfb < 0:
            lzh, len_ = "板塊資金撤出", "Sector Outflow"
        else:
            lzh, len_ = "板塊觀望", "Sector Neutral"

        out[sector] = {
            "breadth":           round(breadth, 3),
            "net_mfb":           net_mfb,
            "avg_mfb":           avg_mfb,
            "avg_chg":           avg_chg,
            "persistence_score": round(persistence, 3),
            "acceleration":      accel,
            "ticker_count":      n,
            "ticker_list":       list(sd["tickers"]),
            "label_zh":          lzh,
            "label_en":          len_,
            "meta":              sector_meta(sector),
        }

    return out


# ---------------------------------------------------------------------------
# Rotation Analysis
# ---------------------------------------------------------------------------

_ROTATION_PAIRS: list[tuple[str, str, str, str]] = [
    # (from_sector, to_sector, zh_label, en_label)
    ("semiconductor", "financials",    "半導體→金融",        "Semis → Financials"),
    ("ai_server",     "financials",    "AI伺服器→金融",      "AI/Server → Financials"),
    ("ai_server",     "semiconductor", "AI伺服器→半導體",    "AI/Server → Semis"),
    ("semiconductor", "shipping",      "半導體→航運",        "Semis → Shipping"),
    ("electronics",   "financials",    "電子代工→金融",      "EMS → Financials"),
    ("financials",    "semiconductor", "金融→半導體",        "Financials → Semis"),
    ("financials",    "ai_server",     "金融→AI伺服器",      "Financials → AI/Server"),
    ("shipping",      "semiconductor", "航運→半導體",        "Shipping → Semis"),
    ("memory",        "ai_server",     "記憶體→AI伺服器",    "Memory → AI/Server"),
]

_PATTERN_LABELS: dict[str, tuple[str, str]] = {
    k: (zh, en) for k, zh, en in [
        ("large_to_small",  "大型股→小型股輪動",   "Large Cap → Small Cap Rotation"),
        ("small_to_large",  "小型股→大型股輪動",   "Small Cap → Large Cap Rotation"),
        ("defensive_entry", "防禦性資金進場",       "Defensive Capital Entry"),
        ("risk_on",         "風險偏好提升",         "Risk-On Rotation"),
    ]
}


def rotation_analysis(
    snapshots: list[dict[str, Any]],
    sector_map: SectorMap | None = None,
) -> dict[str, Any]:
    """
    Detect sector rotation across consecutive snapshots.

    Algorithm
    ---------
    1. Per snapshot, rank sectors by net_mfb.
    2. Compare rank-1 (leading) across adjacent days.
    3. Any change in top-3 composition → rotation event.
    4. Named pattern matching for known rotation pairs.

    Returns
    -------
    leading_sector        — sector with highest net_mfb today
    weakening_sector      — sector with largest negative acceleration
    emerging_sector       — sector with positive acceleration not previously leading
    rotation_events       — list of detected rotation events
    named_rotations       — matched named patterns (from _ROTATION_PAIRS)
    sector_rank_series    — per-date ordered sector list by net_mfb
    momentum_map          — {sector: momentum_direction} (+1 / -1 / 0)
    """
    if len(snapshots) < 2:
        return _empty_rotation()

    sm  = sector_map or build_sector_map(snapshots)
    per = _collect_per_snap(snapshots, sm)

    # Build per-date sector net_mfb ranking
    rank_series: list[dict[str, Any]] = []
    for ps in per:
        date = ps["date"]
        sd   = ps["sector_data"]
        ranked = sorted(
            ((sec, int(sum(data.get("mfb_vals", [])))) for sec, data in sd.items()),
            key=lambda x: -x[1],
        )
        rank_series.append({"date": date, "ranked": ranked})

    # Detect rotation events (consecutive day top-3 set change)
    rotation_events: list[dict[str, Any]] = []
    for i in range(1, len(rank_series)):
        prev_top3 = {r[0] for r in rank_series[i - 1]["ranked"][:3]}
        curr_top3 = {r[0] for r in rank_series[i]["ranked"][:3]}
        entered   = curr_top3 - prev_top3
        exited    = prev_top3 - curr_top3

        if entered or exited:
            rotation_events.append({
                "date":          rank_series[i]["date"],
                "from_date":     rank_series[i - 1]["date"],
                "sectors_entered": list(entered),
                "sectors_exited":  list(exited),
                "description_zh":  _rotation_description_zh(entered, exited),
                "description_en":  _rotation_description_en(entered, exited),
            })

    # Latest snapshot analysis
    latest_ranked = rank_series[-1]["ranked"] if rank_series else []
    prior_ranked  = rank_series[-2]["ranked"] if len(rank_series) >= 2 else []

    latest_net = {sec: val for sec, val in latest_ranked}
    prior_net  = {sec: val for sec, val in prior_ranked}

    # Leading = highest net_mfb today
    leading_sector = latest_ranked[0][0] if latest_ranked else None

    # Acceleration per sector
    accel_map: dict[str, int] = {}
    for sec, val in latest_net.items():
        prior = prior_net.get(sec, 0)
        accel_map[sec] = val - prior

    # Weakening = largest negative acceleration (was strong, now weaker)
    weakening_sector = None
    worst_accel = 0
    for sec, ac in accel_map.items():
        if ac < worst_accel and prior_net.get(sec, 0) > 0:
            worst_accel = ac
            weakening_sector = sec

    # Emerging = positive acceleration + not #1 yesterday
    prior_lead = prior_ranked[0][0] if prior_ranked else None
    emerging_sector = None
    best_pos_accel = 0
    for sec, ac in accel_map.items():
        if ac > best_pos_accel and sec != prior_lead and latest_net.get(sec, 0) > 0:
            best_pos_accel = ac
            emerging_sector = sec

    # Named rotation patterns
    named: list[dict[str, Any]] = []
    if len(rank_series) >= 2:
        prev_lead = prior_ranked[0][0] if prior_ranked else None
        curr_lead = latest_ranked[0][0] if latest_ranked else None
        if prev_lead and curr_lead and prev_lead != curr_lead:
            for from_s, to_s, zh, en in _ROTATION_PAIRS:
                if from_s == prev_lead and to_s == curr_lead:
                    named.append({
                        "pattern_zh": zh,
                        "pattern_en": en,
                        "from_sector": from_s,
                        "to_sector":   to_s,
                        "date":        rank_series[-1]["date"],
                    })

    # Large-cap ↔ small-cap proxy (semiconductors+electronics = large)
    _large_cap = {"semiconductor", "electronics", "financials", "ai_server"}
    _small_cap = {"memory", "networking", "shipping", "heavy_industry"}
    prev_top = {r[0] for r in prior_ranked[:3]} if prior_ranked else set()
    curr_top = {r[0] for r in latest_ranked[:3]}
    if (_large_cap & prev_top) and (_small_cap & curr_top) and not (_large_cap & curr_top):
        named.append({"pattern_zh": "大型股→小型股輪動", "pattern_en": "Large Cap → Small Cap Rotation",
                      "from_sector": "large_cap_proxy", "to_sector": "small_cap_proxy",
                      "date": rank_series[-1]["date"]})
    elif (_small_cap & prev_top) and (_large_cap & curr_top) and not (_small_cap & curr_top):
        named.append({"pattern_zh": "小型股→大型股輪動", "pattern_en": "Small Cap → Large Cap Rotation",
                      "from_sector": "small_cap_proxy", "to_sector": "large_cap_proxy",
                      "date": rank_series[-1]["date"]})

    # Momentum map
    momentum_map: dict[str, int] = {
        sec: (1 if ac > 0 else (-1 if ac < 0 else 0))
        for sec, ac in accel_map.items()
    }

    return {
        "leading_sector":      leading_sector,
        "leading_meta":        sector_meta(leading_sector) if leading_sector else {},
        "weakening_sector":    weakening_sector,
        "weakening_meta":      sector_meta(weakening_sector) if weakening_sector else {},
        "emerging_sector":     emerging_sector,
        "emerging_meta":       sector_meta(emerging_sector) if emerging_sector else {},
        "rotation_events":     rotation_events,
        "named_rotations":     named,
        "sector_rank_series":  rank_series,
        "momentum_map":        momentum_map,
        "accel_map":           accel_map,
        "latest_net_mfb":      latest_net,
        "prior_net_mfb":       prior_net,
    }


def _rotation_description_zh(entered: set[str], exited: set[str]) -> str:
    parts = []
    if exited:
        labels = "、".join(sector_meta(s).get("zh", s) for s in exited)
        parts.append(f"{labels} 退出前三強")
    if entered:
        labels = "、".join(sector_meta(s).get("zh", s) for s in entered)
        parts.append(f"{labels} 進入前三強")
    return "  ·  ".join(parts) if parts else "板塊排名變動"


def _rotation_description_en(entered: set[str], exited: set[str]) -> str:
    parts = []
    if exited:
        labels = ", ".join(sector_meta(s).get("en", s) for s in exited)
        parts.append(f"{labels} exited top-3")
    if entered:
        labels = ", ".join(sector_meta(s).get("en", s) for s in entered)
        parts.append(f"{labels} entered top-3")
    return " · ".join(parts) if parts else "Sector rank shift"


def _empty_rotation() -> dict[str, Any]:
    return dict(
        leading_sector=None, leading_meta={},
        weakening_sector=None, weakening_meta={},
        emerging_sector=None, emerging_meta={},
        rotation_events=[], named_rotations=[],
        sector_rank_series=[], momentum_map={}, accel_map={},
        latest_net_mfb={}, prior_net_mfb={},
    )


# ---------------------------------------------------------------------------
# Sector Time Series  (for charting)
# ---------------------------------------------------------------------------

def sector_time_series(
    snapshots: list[dict[str, Any]],
    sector_map: SectorMap | None = None,
) -> dict[str, Any]:
    """
    Build per-sector metric timeseries across all snapshots.

    Returns
    -------
    dates            — list[str]  (YYYY-MM-DD)
    series           — dict[sector → {net_mfb: list, breadth: list, avg_chg: list}]

    Suitable input for Plotly line / area charts.
    """
    if not snapshots:
        return {"dates": [], "series": {}}

    sm  = sector_map or build_sector_map(snapshots)
    per = _collect_per_snap(snapshots, sm)

    all_sectors: set[str] = set()
    for ps in per:
        all_sectors.update(ps["sector_data"].keys())

    dates  = [ps["date"] for ps in per]
    series: dict[str, dict[str, list]] = {
        sec: {"net_mfb": [], "breadth": [], "avg_chg": []}
        for sec in all_sectors
    }

    for ps in per:
        sd = ps["sector_data"]
        for sec in all_sectors:
            data = sd.get(sec, {})
            mfb_vals = data.get("mfb_vals", [])
            chg_vals = data.get("chg_vals", [])
            net_mfb  = int(sum(mfb_vals)) if mfb_vals else 0
            breadth  = sum(1 for v in mfb_vals if v > 0) / max(len(mfb_vals), 1) if mfb_vals else 0.0
            avg_chg  = sum(chg_vals) / len(chg_vals) if chg_vals else 0.0
            series[sec]["net_mfb"].append(net_mfb)
            series[sec]["breadth"].append(round(breadth, 3))
            series[sec]["avg_chg"].append(round(avg_chg, 3))

    return {"dates": dates, "series": series}


# ---------------------------------------------------------------------------
# Daily Sector Rotation Summary  (top-level output)
# ---------------------------------------------------------------------------

def sector_summary(
    snapshots: list[dict[str, Any]],
    sector_map: SectorMap | None = None,
) -> dict[str, Any]:
    """
    Produce the complete daily sector rotation observation summary.

    This is the primary output function of this module.

    Returns
    -------
    date                 — latest snapshot date
    leading_sector       — sector key
    leading_zh/en        — labels
    weakening_sector     — sector key
    emerging_sector      — sector key
    rotation_detected    — bool
    named_rotations      — list of named patterns
    rotation_events      — raw events from rotation_analysis
    sector_strength      — {sector: {breadth, net_mfb, avg_chg, acceleration, label_zh/en, meta}}
    sector_rank          — sectors ordered by net_mfb descending (today)
    sector_rank_series   — per-date ranked lists for timeline
    momentum_map         — {sector: +1/-1/0}
    narrative_zh         — one-paragraph Chinese description
    narrative_en         — one-paragraph English description
    """
    if not snapshots:
        return _empty_summary()

    sm       = sector_map or build_sector_map(snapshots)
    strength = sector_strength(snapshots, sm)
    rotation = rotation_analysis(snapshots, sm)

    date = snapshots[-1].get("date", "?")

    # Sector rank (today, by net_mfb)
    sector_rank = sorted(
        strength.keys(),
        key=lambda s: -(strength[s]["net_mfb"]),
    )

    leading   = rotation["leading_sector"]
    weakening = rotation["weakening_sector"]
    emerging  = rotation["emerging_sector"]

    lead_meta = sector_meta(leading) if leading else {}
    weak_meta = sector_meta(weakening) if weakening else {}
    emrg_meta = sector_meta(emerging) if emerging else {}

    # Narrative generation
    narrative_zh = _build_narrative_zh(
        date, leading, weakening, emerging, rotation, strength, sector_rank)
    narrative_en = _build_narrative_en(
        date, leading, weakening, emerging, rotation, strength, sector_rank)

    return {
        "date":                date,
        "leading_sector":      leading,
        "leading_zh":          lead_meta.get("zh", "—"),
        "leading_en":          lead_meta.get("en", "—"),
        "weakening_sector":    weakening,
        "weakening_zh":        weak_meta.get("zh", "—"),
        "weakening_en":        weak_meta.get("en", "—"),
        "emerging_sector":     emerging,
        "emerging_zh":         emrg_meta.get("zh", "—"),
        "emerging_en":         emrg_meta.get("en", "—"),
        "rotation_detected":   bool(rotation["rotation_events"]),
        "named_rotations":     rotation["named_rotations"],
        "rotation_events":     rotation["rotation_events"],
        "sector_strength":     strength,
        "sector_rank":         sector_rank,
        "sector_rank_series":  rotation["sector_rank_series"],
        "momentum_map":        rotation["momentum_map"],
        "accel_map":           rotation["accel_map"],
        "narrative_zh":        narrative_zh,
        "narrative_en":        narrative_en,
    }


def _build_narrative_zh(
    date: str,
    leading: str | None,
    weakening: str | None,
    emerging: str | None,
    rotation: dict,
    strength: dict,
    sector_rank: list[str],
) -> str:
    parts: list[str] = []

    # Leading sector
    if leading:
        lm  = sector_meta(leading)
        lst = strength.get(leading, {})
        parts.append(
            f"{date} 板塊資金由【{lm.get('zh', leading)}】主導，"
            f"淨主力買超 {lst.get('net_mfb', 0):+,} 張，"
            f"廣度 {lst.get('breadth', 0)*100:.0f}%。"
        )
    else:
        parts.append(f"{date} 板塊資金分散，無明顯主導板塊。")

    # Named rotation
    for nr in rotation.get("named_rotations", [])[:2]:
        parts.append(f"偵測到 {nr['pattern_zh']} 輪動跡象。")

    # Weakening
    if weakening and weakening != leading:
        wm  = sector_meta(weakening)
        wst = strength.get(weakening, {})
        ac  = rotation["accel_map"].get(weakening)
        ac_str = f"加速度 {ac:+,} 張" if ac is not None else ""
        parts.append(
            f"【{wm.get('zh', weakening)}】資金動能轉弱{('，' + ac_str) if ac_str else ''}。"
        )

    # Emerging
    if emerging and emerging != leading:
        em  = sector_meta(emerging)
        est = strength.get(emerging, {})
        ac  = rotation["accel_map"].get(emerging)
        ac_str = f"+{ac:,} 張加速流入" if (ac is not None and ac > 0) else ""
        parts.append(
            f"【{em.get('zh', emerging)}】出現新興動能{('，' + ac_str) if ac_str else ''}，值得觀察。"
        )

    # Top 3 sector list
    top3 = sector_rank[:3]
    if top3:
        labels = "、".join(sector_meta(s).get("zh", s) for s in top3)
        parts.append(f"板塊強弱前三名：{labels}。")

    return "".join(parts)


def _build_narrative_en(
    date: str,
    leading: str | None,
    weakening: str | None,
    emerging: str | None,
    rotation: dict,
    strength: dict,
    sector_rank: list[str],
) -> str:
    parts: list[str] = []

    if leading:
        lm  = sector_meta(leading)
        lst = strength.get(leading, {})
        parts.append(
            f"On {date}, capital flow was led by {lm.get('en', leading)} "
            f"(net MFB {lst.get('net_mfb', 0):+,}, breadth {lst.get('breadth', 0)*100:.0f}%). "
        )
    else:
        parts.append(f"On {date}, capital flow was broadly distributed with no dominant sector. ")

    for nr in rotation.get("named_rotations", [])[:2]:
        parts.append(f"Detected rotation pattern: {nr['pattern_en']}. ")

    if weakening and weakening != leading:
        wm = sector_meta(weakening)
        ac = rotation["accel_map"].get(weakening)
        ac_str = f" (acceleration: {ac:+,})" if ac is not None else ""
        parts.append(f"{wm.get('en', weakening)} showed weakening momentum{ac_str}. ")

    if emerging and emerging != leading:
        em = sector_meta(emerging)
        ac = rotation["accel_map"].get(emerging)
        ac_str = f" (+{ac:,} acceleration)" if (ac is not None and ac > 0) else ""
        parts.append(f"{em.get('en', emerging)} displayed emerging momentum{ac_str}, worth monitoring. ")

    top3 = sector_rank[:3]
    if top3:
        labels = ", ".join(sector_meta(s).get("en", s) for s in top3)
        parts.append(f"Top 3 sectors by capital flow: {labels}.")

    return "".join(parts)


def _empty_summary() -> dict[str, Any]:
    return dict(
        date="—", leading_sector=None, leading_zh="—", leading_en="—",
        weakening_sector=None, weakening_zh="—", weakening_en="—",
        emerging_sector=None, emerging_zh="—", emerging_en="—",
        rotation_detected=False, named_rotations=[], rotation_events=[],
        sector_strength={}, sector_rank=[], sector_rank_series=[],
        momentum_map={}, accel_map={},
        narrative_zh="尚無足夠快照資料。", narrative_en="Insufficient snapshot data.",
    )


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import pathlib
    import sys

    _HERE = pathlib.Path(__file__).resolve().parent
    _AI_STOCK = _HERE.parent
    if str(_AI_STOCK) not in sys.path:
        sys.path.insert(0, str(_AI_STOCK))

    from viewer import data as vd

    index  = vd.load_index()
    dates  = sorted(
        k for k in index.get("snapshots", {}).keys()
        if len(k) == 10 and k.replace("-", "").isdigit()
    )
    snaps  = []
    for d in dates:
        try:
            snaps.append(vd.load_snapshot(d))
        except Exception:
            pass

    if not snaps:
        print("No snapshots found.")
        sys.exit(1)

    summary = sector_summary(snaps)

    print(f"\n{'='*60}")
    print(f"  板塊輪動日報  SECTOR ROTATION SUMMARY  {summary['date']}")
    print(f"{'='*60}")
    print(f"\n📍 主導板塊  Leading : {summary['leading_zh']} / {summary['leading_en']}")
    print(f"📉 轉弱板塊  Weakening: {summary['weakening_zh']} / {summary['weakening_en']}")
    print(f"🌱 新興板塊  Emerging : {summary['emerging_zh']} / {summary['emerging_en']}")

    if summary["named_rotations"]:
        print(f"\n⟳ 輪動模式 Rotation patterns:")
        for nr in summary["named_rotations"]:
            print(f"   • {nr['pattern_zh']}  /  {nr['pattern_en']}")

    if summary["rotation_events"]:
        print(f"\n📅 輪動事件 Rotation events ({len(summary['rotation_events'])}):")
        for ev in summary["rotation_events"][-3:]:
            print(f"   {ev['date']}: {ev['description_zh']}")

    print(f"\n板塊強弱排名 Sector Rank:")
    for i, sec in enumerate(summary["sector_rank"], 1):
        st   = summary["sector_strength"].get(sec, {})
        meta = sector_meta(sec)
        mom  = summary["momentum_map"].get(sec, 0)
        arr  = "↑" if mom > 0 else ("↓" if mom < 0 else "→")
        print(
            f"  {i:2}. {arr} {meta.get('zh',sec):10s} / {meta.get('en',sec):20s}  "
            f"net_mfb {st.get('net_mfb',0):+8,}  breadth {st.get('breadth',0)*100:5.1f}%  "
            f"{st.get('label_zh','')}"
        )

    print(f"\n敘事 Narrative (ZH):\n{summary['narrative_zh']}")
    print(f"\nNarrative (EN):\n{summary['narrative_en']}")


# ---------------------------------------------------------------------------
# P4 — Sector flow profile (板塊輪動強化: 聚合轉強/轉弱/W3 集中度)
# ---------------------------------------------------------------------------
# Aggregates per-sector capital flow + lifecycle states + weakening flags.
# Built to answer "is a sector-wide W3 cluster a rotation-out event?" —
# e.g. the 2026-06-10 financials case (2887/2890/2884/2867/3033 all W3).
# Observation layer only: no impact on score/tier/gates.

_W3_ALERT_MIN_TICKERS   = 3     # ≥N W3 tickers in one sector …
_W3_ALERT_CONCENTRATION = 0.5   # … AND ≥50% of its w3-eligible tickers → alert
                                # (config candidates for P3b SCORING_RUBRIC)


def sector_flow_profile(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-sector aggregation over the snapshot window. Pure function.

    Returns:
      {
        "date": str,
        "sectors": [ {sector, zh, en, active_tickers, net_mfb_latest,
                      net_mfb_3d, states: {state: [tickers]},
                      weakening: {red/orange/yellow: [tickers]},
                      w3_tickers, w3_eligible, w3_concentration,
                      rotation_out_alert: bool} ...sorted by net_mfb_latest desc ],
        "alerts": [ {sector, zh, type, detail_zh} ... ],
      }
    """
    # Lazy imports — state_machine imports this module at top level
    from core.state_machine import run_all as _sm_run_all, S_EXITED, S_UNDISCOVERED
    from core.market_context import weakening_profile as _weakening

    if not snapshots:
        return {"date": "—", "sectors": [], "alerts": []}

    date = snapshots[-1].get("date", "?")
    smap = build_sector_map(snapshots)
    states = _sm_run_all(snapshots)

    # Latest + 3-day mfb sums per ticker
    def _mfb_sum(snaps_slice: list[dict]) -> dict[str, float]:
        out: dict[str, float] = {}
        for snap in snaps_slice:
            for s in snap.get("stocks", []):
                t = s.get("ticker", "")
                v = s.get("main_force_buy")
                if t and v is not None:
                    out[t] = out.get(t, 0) + v
        return out

    mfb_latest = _mfb_sum(snapshots[-1:])
    mfb_3d     = _mfb_sum(snapshots[-3:])

    # Group tickers by sector
    by_sector: dict[str, list[str]] = defaultdict(list)
    for t in states.keys():
        by_sector[smap.sector_of(t)].append(t)

    sectors_out: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for sector, tickers in by_sector.items():
        meta = sector_meta(sector)
        state_groups: dict[str, list[str]] = defaultdict(list)
        weak_groups: dict[str, list[str]] = defaultdict(list)
        w3_tickers: list[str] = []
        w3_eligible = 0
        active: list[str] = []

        for t in sorted(tickers):
            ts = states[t]
            if ts.state not in (S_EXITED, S_UNDISCOVERED):
                active.append(t)
            state_groups[ts.state].append(t)

            weak = _weakening(t, snapshots)
            if weak["max_streak"] >= 3:
                w3_eligible += 1
            sev = weak["severity"]
            if sev != "none":
                weak_groups[sev].append(t)
            if any(f.get("code") == "W3" for f in weak["flags"]):
                w3_tickers.append(t)

        concentration = (len(w3_tickers) / w3_eligible) if w3_eligible else 0.0
        rotation_out = (len(w3_tickers) >= _W3_ALERT_MIN_TICKERS
                        and concentration >= _W3_ALERT_CONCENTRATION)

        sectors_out.append({
            "sector": sector,
            "zh": meta["zh"], "en": meta["en"],
            "active_tickers": active,
            "net_mfb_latest": sum(mfb_latest.get(t, 0) for t in tickers),
            "net_mfb_3d":     sum(mfb_3d.get(t, 0) for t in tickers),
            "states":    {k: v for k, v in state_groups.items()},
            "weakening": {k: v for k, v in weak_groups.items()},
            "w3_tickers": w3_tickers,
            "w3_eligible": w3_eligible,
            "w3_concentration": round(concentration, 2),
            "rotation_out_alert": rotation_out,
        })

        if rotation_out:
            alerts.append({
                "sector": sector, "zh": meta["zh"],
                "type": "rotation_out",
                "detail_zh": (
                    f"{meta['zh']}板塊 {len(w3_tickers)}/{w3_eligible} 檔曾連買≥3日"
                    f"後集體缺席（{ '、'.join(w3_tickers) }）— 疑似板塊資金輪出"
                ),
            })

    sectors_out.sort(key=lambda s: -s["net_mfb_latest"])
    return {"date": date, "sectors": sectors_out, "alerts": alerts}
