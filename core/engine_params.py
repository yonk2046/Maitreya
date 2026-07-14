"""core/engine_params.py — 存活引擎判斷參數(單一權威來源)

憲法 §7 Phase 1 第 1 線 / NOTES #33(C11 系統性裁定)。

引擎的判斷「門檻/權重」若寫死在 code 內,改一個數字就會**無痕改變歷史意見**
(C11 陽性),且對 replay 不可見。本檔把這些判斷參數從 code 抽出集中於此,讓
「改參數」變成可 diff、可審計的動作。

設計紅線(參照 core/strategies.py 之先例):
  • 純 Python 資料模組 — 零環境依賴、載入確定性(不讀檔、不解析 YAML)。
  • 值一個都不改 — 本輪只搬家(參數外置),不調參。引擎輸出 bit-identical。
  • 每個參數一行語意註解 + 來源引擎行號(config 化當時)。

Phase 2(隨 1.9.0):config_snapshot 入 canonical hash。本輪**不**做 hash 綁定。

存活引擎(§3 所有權表):golden / state_machine / chip_score / market_context。
已判死/降級引擎(confidence / market_state / distribution / resonance)不在此登記。

C11 演示:改本檔任一參數 → importlib.reload(該引擎)→ 輸出改變;還原 → 復原。
見 tests/test_config_extraction.py。
"""
from __future__ import annotations

import copy
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# TIER_A — 永久追蹤名單(市場體制錨)
# ═══════════════════════════════════════════════════════════════════════════
# NOTES #47:TIER_A 名單 = 人工維護的 I 態判斷參數,C11 陽性必留痕。
# golden.py 用 `ticker in TIER_A` 給 +0.10 conviction(見 GOLDEN_W_TIER_A);
# 增刪一檔即無痕改變歷史 conviction → 名單本身就是判斷參數,故外置於此。
# 名稱/群組為附帶的參考中繼資料;core/watchlists.py 由此匯入並再匯出。
# 來源:core/watchlists.py:17-29(config 化前)
TIER_A: dict[str, dict[str, Any]] = {
    # ── Semiconductors 半導體 ──────────────────────────────────────────────
    "2330": {"name": "台積電",  "name_en": "TSMC",       "group": "semiconductor", "group_zh": "半導體"},
    "2454": {"name": "聯發科",  "name_en": "MediaTek",   "group": "semiconductor", "group_zh": "半導體"},
    # ── Electronics / EMS 電子代工 ────────────────────────────────────────
    "2317": {"name": "鴻海",    "name_en": "Hon Hai",    "group": "electronics",   "group_zh": "電子代工"},
    "2382": {"name": "廣達",    "name_en": "Quanta",     "group": "electronics",   "group_zh": "電子代工"},
    "2308": {"name": "台達電",  "name_en": "Delta",      "group": "electronics",   "group_zh": "電子代工"},
    # ── Financials 金融權值 ───────────────────────────────────────────────
    "2881": {"name": "富邦金",  "name_en": "Fubon FHC",  "group": "financials",    "group_zh": "金融"},
    "2882": {"name": "國泰金",  "name_en": "Cathay FHC", "group": "financials",    "group_zh": "金融"},
    "2891": {"name": "中信金",  "name_en": "CTBC FHC",   "group": "financials",    "group_zh": "金融"},
}

# ═══════════════════════════════════════════════════════════════════════════
# GOLDEN LAYER v2 — core/golden.py
# ═══════════════════════════════════════════════════════════════════════════
# ── Gate / tier 切點(來源 golden.py:68-78)──────────────────────────────────
GOLDEN_GOLD_SPON_MIN      = 0.45   # G3 閘門:進入黃金層最低贊助分(golden.py:68)
GOLDEN_SCORE_STREAK_HIGH  = 5      # conviction:streak ≥ 此 → +0.25(golden.py:70)
GOLDEN_SCORE_STREAK_MID   = 3      # conviction:streak ≥ 此 → +0.15(golden.py:71)
GOLDEN_SCORE_SPON_HIGH    = 0.70   # conviction:贊助 ≥ 此 → +0.20(golden.py:72)
GOLDEN_SCORE_SPON_MID     = 0.55   # conviction:贊助 ≥ 此 → +0.10(golden.py:73)
GOLDEN_TIER_PRIME         = 0.65   # conviction ≥ 此 → PRIME(golden.py:75)
GOLDEN_TIER_STRONG        = 0.40   # conviction ≥ 此 → STRONG(golden.py:76)
GOLDEN_SECTOR_TOP_N_TIGHT = 3      # sector 落在前 N → +0.05(比閘門 top-5 更緊,golden.py:78)

# ── Conviction 權重(來源 golden.py:_score_conviction 262-292)────────────────
GOLDEN_W_STREAK_HIGH          = 0.25  # streak ≥ HIGH(golden.py:262)
GOLDEN_W_STREAK_MID           = 0.15  # streak ≥ MID(可與 HIGH 疊加,golden.py:263/265)
GOLDEN_W_SPON_HIGH            = 0.20  # 贊助 ≥ HIGH(golden.py:269)
GOLDEN_W_SPON_MID            = 0.10  # 贊助 ≥ MID(可疊加,golden.py:270/272)
GOLDEN_W_STATE_CONFIRMED      = 0.15  # sm_state == confirmed(golden.py:276)
GOLDEN_W_TIER_A               = 0.10  # is_tier_a(golden.py:280)
GOLDEN_W_VELOCITY_POSITIVE    = 0.10  # velocity_3d > 0(golden.py:284)
GOLDEN_W_ACCELERATION_POSITIVE = 0.05  # acceleration > 0(golden.py:288)
GOLDEN_W_SECTOR_TOP3          = 0.05  # sector 在前 SECTOR_TOP_N_TIGHT(golden.py:292)
GOLDEN_CONVICTION_CAP         = 1.0   # conviction 上限(golden.py:294)

# ═══════════════════════════════════════════════════════════════════════════
# TEMPORAL STATE MACHINE — core/state_machine.py
# ═══════════════════════════════════════════════════════════════════════════
# ── 狀態轉移門檻(來源 state_machine.py:81-90)────────────────────────────────
SM_STREAK_ACCUMULATING  = 1      # ACCUMULATING 最低連買(state_machine.py:81)
SM_STREAK_STRENGTHENING = 3      # STRENGTHENING 最低連買(state_machine.py:82)
SM_STREAK_CONFIRMED     = 3      # CONFIRMED 最低連買(state_machine.py:83)
SM_SPON_STRENGTHENING   = 0.40   # STRENGTHENING 最低贊助(state_machine.py:84)
SM_SPON_CONFIRMED       = 0.50   # CONFIRMED 最低贊助(state_machine.py:85)
SM_SECTOR_TOP_N_CONFIRM = 5      # CONFIRMED 要求 sector 前 N(state_machine.py:86)
SM_BREADTH_CONFIRMED    = 0.50   # CONFIRMED 要求市場廣度(state_machine.py:87)
SM_ABSENT_EXITED        = 3      # 連續缺席 N 快照 → EXITED(state_machine.py:88)
SM_COLLAPSE_WINDOW      = 2      # streak 3→0 於 N 日內 → FAILED(state_machine.py:89)
SM_DAYS_SINCE_FAIL_RISK = 10     # 假突破 N 日內 → 風險偏高(state_machine.py:90)

# ── P0.5 反鋸齒常數(來源 state_machine.py:93-96)─────────────────────────────
SM_ACCEL_DISTRIBUTING     = -500  # 加速度低於此視為動能斷裂(state_machine.py:93)
SM_DEBOUNCE_SNAPSHOTS     = 2     # 轉移落定所需連續快照數(state_machine.py:94)
SM_DIST_LOCKOUT_SNAPSHOTS = 5     # 出貨後 N 快照內禁升 CONFIRMED(state_machine.py:95)
SM_FLIPS_UNSTABLE_30D     = 2     # 已落定方向反轉 ≥ 此 → 結構不穩(state_machine.py:96)

# ═══════════════════════════════════════════════════════════════════════════
# CHIP MOMENTUM SCORE — core/chip_score.py
# ═══════════════════════════════════════════════════════════════════════════
# 全部評分門檻的單一來源(來源 chip_score.py:23-64)。結構原封搬移,值不變。
CHIP_SCORE_CONFIG: dict = {
    "vol_ratio": {
        "max": 8,
        "label": "投量比",
        "desc":  "主力買超 ÷ 市場成交量",
        # mfb / market_volume > 12% → 8, 6-12% → 4, <6% → 0
        "thresholds": [0.12, 0.06],
        "scores":     [8,    4,    0],
    },
    "streak": {
        "max": 10,
        "label": "連續買超",
        "desc":  "連續主力淨買超天數",
        # ≥7→10, 5-6→8, 3-4→6, 1-2→3, 0→0
        "thresholds": [7,  5,  3,  1],
        "scores":     [10, 8,  6,  3, 0],
    },
    "concentration": {
        "max": 8,
        "label": "籌碼集中度",
        "desc":  "大戶持股變化(TDCC)",
        # data pending — returns 0 when unavailable
        "thresholds": [],
        "scores":     [0],
    },
    "institutional": {
        "max": 8,
        "label": "法人同向",
        "desc":  "主力/外資/投信同向淨買家數",
        # 3→8, 2→5, 1→2, 0→0
        "thresholds": [3,  2,  1],
        "scores":     [8,  5,  2, 0],
    },
    "cost_support": {
        "max": 6,
        "label": "成本支撐",
        "desc":  "現價距主力成本距離(越近越好)",
        # price/cost ≤ 1.02 → 6, ≤ 1.05 → 3, > 1.05 → 0
        "thresholds": [1.02, 1.05],
        "scores":     [6,    3,    0],
    },
}

# Grade by percentage of available max(來源 chip_score.py:68-72)
# ≥80% → 強, ≥60% → 中, <60% → 弱
GRADE_PCT_MAP = [
    (0.80, "強", "#D4A84B"),
    (0.60, "中", "#7EB8D4"),
    (0.0,  "弱", "#8B949E"),
]

# ═══════════════════════════════════════════════════════════════════════════
# MARKET CONTEXT — core/market_context.py
# ═══════════════════════════════════════════════════════════════════════════
# ── 假突破偵測門檻(來源 market_context.py:458-502)───────────────────────────
MC_BREAKOUT_LOOKBACK       = 10   # 回看窗(failed_breakout_memory lookback 預設,:461)
MC_BREAKOUT_VOL_MULT       = 1.8  # 量 > 均量 × 此 才算突破(market_context.py:485)
MC_BREAKOUT_CHG_MIN        = 2.0  # 突破日漲幅門檻 %(market_context.py:485)
MC_BREAKOUT_RETREAT_MIN    = 2    # 後續 N 日回落 → 判定假突破(market_context.py:491)
MC_BREAKOUT_HIGHRISK_RETREAT = 3  # 回落 ≥ 此 → 高風險假突破(market_context.py:501)

# ── 市場體制 breadth trend 斜率(來源 market_context.py:389-398)───────────────
MC_BREADTH_TREND_FAST = 0.1   # |Δbreadth| > 此 → rising/falling_fast(market_context.py:389/393)
MC_BREADTH_TREND_SLOW = 0.02  # |Δbreadth| > 此 → rising/falling(market_context.py:391/394/398)

# ── 市場體制分類切點(來源 market_context.py:401-412)─────────────────────────
MC_REGIME_OFFENSIVE_BREADTH   = 0.75  # 強勢進攻:breadth ≥(market_context.py:401)
MC_REGIME_OFFENSIVE_CHG       = 3.0   # 強勢進攻:avg_chg >(market_context.py:401)
MC_REGIME_MILD_RISKON_BREADTH = 0.6   # 溫和偏多:breadth ≥(market_context.py:403)
MC_REGIME_MILD_RISKON_CHG     = 1.0   # 溫和偏多:avg_chg >(market_context.py:403)
MC_REGIME_RETREAT_BREADTH     = 0.25  # 全面撤退:breadth <(market_context.py:405)
MC_REGIME_RETREAT_CHG         = -2.0  # 全面撤退:avg_chg <(market_context.py:405)
MC_REGIME_WAITING_BREADTH     = 0.35  # 資金觀望:breadth <(market_context.py:407)

# ── 市場體制轉換偵測(來源 market_context.py:419)─────────────────────────────
MC_TRANSITION_BREADTH_DELTA = 0.25  # |Δbreadth| ≥ 此 → 體制轉換(market_context.py:419)
MC_TRANSITION_CHG_DELTA     = 3.0   # |Δavg_chg| ≥ 此 → 體制轉換(market_context.py:419)

# ── 轉弱/出貨偵測門檻(來源 market_context.py:651-653, 694, 772)───────────────
MC_W2_FII_RATIO           = 0.30  # 外資賣 ≥ 主力買 × 此 才記 W2(market_context.py:651)
MC_W5_SELL_RATIO          = 1.00  # 分點 totalSellVol > totalBuyVol × 此(market_context.py:652)
MC_W5_CHURN_RATIO         = 0.60  # 前三買點賣/買 ≥ 此 → 邊買邊倒(market_context.py:653)
MC_WEAKENING_RECENCY_MAX  = 3     # 缺席 > N 快照 → 過期非活躍轉弱訊號(market_context.py:694)
MC_W3_SOLID_MIN_ABSENCE   = 2     # W3 缺席 ≥ 此才算 solid(可併紅,market_context.py:772)

# ── 雙錨主力成本背離門檻(來源 market_context.py:822)─────────────────────────
MC_COST_DIVERGENCE_PCT = 5.0  # 近/episode 錨背離 > 此 % → ⚠ 成本背離(market_context.py:822)

# ═══════════════════════════════════════════════════════════════════════════
# DISTRIBUTION — core/distribution.py(obs_dist_consistency,NOTES #38)
# ═══════════════════════════════════════════════════════════════════════════
# 1.9.0(P2-W3):obs_dist_consistency 落地為 canonical O 欄(唯一賣方證據源)。
# 賣方一致性/安全邊際/自動過濾的判斷門檻改一個值即無痕改變歷史賣方判斷,故隨
# obs 落地一併外置入 config_snapshot(C11,任務#5「safety band 參數入 engine_params」)。
# 值一個都不改,僅搬家(對齊 chip_score/golden 的 config 化先例)。
# 註:安全邊際最後一段上界原為 float("inf");canonical hash 拒 Inf(allow_nan=False),
#     故以 None 表「無上界」,distribution._safety_margin 視 None 為 +∞(行為 bit-identical)。
DIST_CONSISTENCY_CONFIG: dict = {
    "strong_rank_max":  15,      # 前 15 名視為強力訊號(distribution.py:107)
    "strong_vol_min":   8000,    # 買/賣超 > 8,000 張視為強力訊號(distribution.py:108)
    "scores": {
        "both_strong_buy":   (+5, "最高共振"),
        "both_buy":          (+3, "一般共振"),
        "foreign_lead":      (+3, "外資主導"),
        "main_lead":         (+3, "主力主導"),
        "either_sell":       (-3, "扣分"),
        "both_sell":         (-5, "強烈賣超"),
        "neutral":           ( 0, "中性 / 分歧"),
    },
}

DIST_GRADE_BANDS = [
    (4,   "強", "#52B788"),   # green
    (1,   "中", "#D4A84B"),   # yellow/gold
    (-99, "弱", "#E05C7A"),   # red — catches everything ≤ 0
]

DIST_SAFETY_MARGIN_BANDS = [
    # (upper_bound_exclusive | None=+∞, label, color, hint)
    (1.03, "綠", "#52B788", "安全，可積極布局"),
    (1.08, "黃", "#D4A84B", "中等，小心 / 分批"),
    (1.15, "橙", "#C47A5A", "偏高，建議減碼"),
    (None, "紅", "#E05C7A", "高風險，強烈建議減碼或移除"),
]

DIST_AUTO_FILTER_MARGIN_MIN  = 1.12   # 安全邊際 > 此 且 一致性弱 → flagged_for_removal
DIST_AUTO_FILTER_CONSISTENCY = "弱"   # 觸發自動過濾的一致性等級


# ═══════════════════════════════════════════════════════════════════════════
# as_config_dict — 判斷參數的確定性序列化(P2-W2:config_snapshot 雙來源之一)
# ═══════════════════════════════════════════════════════════════════════════
def as_config_dict() -> dict[str, Any]:
    """回傳「本檔所有 public UPPERCASE 判斷參數 → 值」的確定性有序 dict。

    P2 §4b:1.9.0 起 config_snapshot 從單一 yaml 升為 {yaml, engine_params}
    雙來源,兩者皆凍結、皆入 canonical config_hash。本函式產出 engine_params
    來源。設計紅線(對齊 core/engine_params.py 檔頭):

      • 純函式 — 零環境依賴、零 I/O(不讀檔、不解析 YAML)。同一份 code 恆回相同
        內容 → 入 config_hash 具確定性(改本檔任一參數 → dict 變 → hash 變,
        C11 對 replay 可見)。
      • 鍵排序(sorted)— 頂層鍵序穩定;canonical_bytes 另以 sort_keys=True 遞迴
        正規化,故巢狀鍵序不影響 hash,此處排序僅為快照可讀性的穩定輸出。
      • 深拷貝 — 回傳全新物件,呼叫端(或其後續變更)絕不會回頭 desync 存活引擎
        正在使用的同一份 config dict(CHIP_SCORE_CONFIG / TIER_A 等為共享參照)。

    收錄準則:module 層級名稱為 public UPPERCASE(全大寫、非 `_` 開頭)者全收,
    含 TIER_A / GOLDEN_* / SM_* / CHIP_SCORE_CONFIG / GRADE_PCT_MAP / MC_*。
    """
    g = globals()
    out = {
        name: copy.deepcopy(value)
        for name, value in g.items()
        if name.isupper() and not name.startswith("_")
    }
    return dict(sorted(out.items()))
