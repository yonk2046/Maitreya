"""viewer/view_params.py — cockpit 顯示門檻的集中命名(單一來源)

cockpit.py 各處寫死的「顯示用門檻/切點」集中於此並命名,讓呈現層的顯示啟發式
可 diff、可查驗。分兩類:

  1. 判斷鏡像(JUDGMENT_MIRRORS)— 與 core/engine_params.py 同語意的值。
     **不得複製數字**,一律 `from core.engine_params import` 正本;若引擎值變,
     此處自動跟隨,永不漂移。tests/test_terms_contract.py 逐一驗證 is/== 正本。
     (2026-07 收案:3094 的 0.4 是對 sponsorship gate 0.45 的漂移 bug — 已改為
      import GOLDEN_GOLD_SPON_MIN 正本,是本輪唯一允許的行為變更。)

  2. 純顯示啟發式 — 只影響顯示分級/版面,不進任何判斷、不入 config_hash、
     不對齊引擎(標註「純顯示,非判斷」)。搬家自 cockpit,值一個不改。

紅線:本檔只 import engine_params 的**常數**(那是參數,不是引擎),不 import
任何 core 引擎模組。
"""
from __future__ import annotations

from core.engine_params import (
    GOLDEN_TIER_PRIME,        # 0.65  conviction ≥ → PRIME
    GOLDEN_TIER_STRONG,       # 0.40  conviction ≥ → STRONG
    GOLDEN_GOLD_SPON_MIN,     # 0.45  G3 閘門:進黃金層最低回頭率
    GOLDEN_SCORE_SPON_HIGH,   # 0.70  回頭率高帶
    GOLDEN_SCORE_STREAK_HIGH, # 5     連買高帶
    SM_ACCEL_DISTRIBUTING,    # -500  加速度低於此視為動能斷裂
)

# ═══════════════════════════════════════════════════════════════════════════
# 1) 判斷鏡像 — 值 = engine_params 正本(禁止複製數字)
# ═══════════════════════════════════════════════════════════════════════════
TIER_PRIME_CUT   = GOLDEN_TIER_PRIME         # 黃金分 → PRIME 切點(_lvl 高帶)
TIER_STRONG_CUT  = GOLDEN_TIER_STRONG        # 黃金分 → STRONG 切點(_lvl 中帶)
SPON_GATE        = GOLDEN_GOLD_SPON_MIN      # 回頭率 G3 閘門 / _lvl 中帶(修正 0.4→0.45 漂移)
SPON_HIGH        = GOLDEN_SCORE_SPON_HIGH    # 回頭率高帶(PRIME/checklist/_lvl 高帶)
STREAK_HIGH      = GOLDEN_SCORE_STREAK_HIGH  # 連買高帶(PRIME/checklist 確認門檻)
MOMENTUM_ACCEL_BREAKDOWN = SM_ACCEL_DISTRIBUTING  # 動能斷裂加速度門檻(momentum/失效訊號)

# 測試逐一驗證:getattr(view_params, k) 必須 is/== getattr(engine_params, v)。
JUDGMENT_MIRRORS: dict[str, str] = {
    "TIER_PRIME_CUT":           "GOLDEN_TIER_PRIME",
    "TIER_STRONG_CUT":          "GOLDEN_TIER_STRONG",
    "SPON_GATE":                "GOLDEN_GOLD_SPON_MIN",
    "SPON_HIGH":                "GOLDEN_SCORE_SPON_HIGH",
    "STREAK_HIGH":              "GOLDEN_SCORE_STREAK_HIGH",
    "MOMENTUM_ACCEL_BREAKDOWN": "SM_ACCEL_DISTRIBUTING",
}

# ═══════════════════════════════════════════════════════════════════════════
# 2) 純顯示啟發式 — 非判斷,不對齊引擎,不入 config_hash
# ═══════════════════════════════════════════════════════════════════════════

# ── 全市場熱度觀察 Heat Radar(display-only,零 impact on composite/tier/gates)──
# 連買積分梯:streak ≥ 門檻 → 加分
HEAT_STREAK_TIERS = [(7, 30), (5, 22), (3, 14), (1, 5)]  # 純顯示,非判斷
HEAT_FII_SAME_DIR = 15   # 外資同向加分
HEAT_FII_OPP_DIR  = -5   # 外資反向扣分
HEAT_TIER_FULL    = 10   # 資料完整加分
HEAT_TIER_PARTIAL = 5    # 資料部分加分
HEAT_WEAK_PENALTY = {"red": -25, "orange": -15, "yellow": -5}  # 轉弱扣分
# 熱度分 → (色類別, 級別);切點沿用舊 _heat_bar
HEAT_LEVEL_CUTS = [(40, "scd-green", "高"), (20, "scd-amber", "中"), (5, "scd-blue", "低")]

# ── 轉強訊號篩網 ─────────────────────────────────────────────────────────
STRENGTHEN_MIN_STREAK    = 2     # 連買 ≥ 此才進轉強潛力篩網(純顯示,最寬篩網)
STRENGTHEN_SPON_MIN      = 0.35  # 「只看持續吸籌」勾選:回頭率 ≥ 此(純顯示篩選)
STRENGTHEN_SPON_MIN_DAYS = 3     # 且分點樣本 ≥ 此天(假訊號防呆)

# ── 動能方向分類(golden card 顯示膠囊;純顯示,非判斷)──────────────────
MOMENTUM_ACCEL_UP   = 500   # 加速度 > 此 → 轉強(純顯示,非判斷)
MOMENTUM_VEL_STRONG = 3000  # 速度 > 此 且 加速 > 0 → 轉強(純顯示,非判斷)
# 動能斷裂用鏡像 MOMENTUM_ACCEL_BREAKDOWN(= -500,同語意於引擎)

# ── velocity 顯示分級(golden card 證據/why-matters;純顯示)──────────────
VELOCITY_STRONG = 5000   # 3日速度 > 此 → 加速顯著
VELOCITY_POS    = 1000   # 3日速度 > 此 → 動能為正
VELOCITY_NEG    = -1000  # 3日速度 < 此 → 明顯轉負

# ── 主力成本安全區(顯示膠囊;純顯示,非黃金 5% 鐵則判斷本身)─────────────
COST_TIGHT_PCT       = 2.0  # |現價距成本| ≤ 此 → 貼近
COST_SAFETY_BAND_PCT = 5.0  # |現價距成本| ≤ 此 → 安全區(5% 鐵則的顯示帶)

# ── _lvl 風險色點(警訊分越高越糟;純顯示)────────────────────────────────
RISK_LEVEL_HI  = 0.5  # 警訊分 ≥ 此 → 🔴高
RISK_LEVEL_MID = 0.3  # 警訊分 ≥ 此 → 🟠中

# ── 資金流泡泡圖(display-only 佈局)──────────────────────────────────────
RISK_RANK = {"low": 0, "medium": 1, "elevated": 2, "critical": 3}  # 風險 → x 軸序位
BUBBLE_FLOW_TOP_N   = 30  # 泡泡宇宙取前 N(顯示用,非評分)
BUBBLE_BASE_SIZE    = 14  # 泡泡基礎大小
BUBBLE_NET_DIVISOR  = 20  # 泡泡大小 = base + sqrt(|net|)/此
