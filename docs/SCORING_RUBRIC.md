# SCD Engine — 量化評分規則 (Scoring Rubric)

> Version: v1.1 (2026-05-22) — superseded v1.0
> 對應 V3 守冊 §二、§三、§四
> Patches applied: AUDIT_v1.0.md P0-1 ~ P0-10
> **本文件是真理之源。任何 prompt 或 UI 顯示的分數必須能在此完全還原。**
> *This document is the source of truth. Any score shown in prompts/UI must be fully reconstructible from these rules.*

---

## 0. 總則 (Overview)

### 0.1 評分結構 (Score Structure)

```
                ┌──────────────── 三道 Hard Gate (任一不過 → 整檔剔除) ──┐
                │  G1: 主力成本 5% 緩衝區                                  │
                │  G2: 外資同步買進 (≥2 家指標分點)                        │
                │  G3: 主力連買 ≥3 天                                      │
                └────────────────────────────────────────────────────────┘
                                       │
                                       ▼ (通過者進入評分)
        ┌────────────────────┬────────────────────┬────────────────────┐
        │ Stage 1 雙引擎     │ Stage 2 行為背離   │ Stage 3 執行觸發   │
        │ 0-100 分           │ 0-100 分           │ 0-100 分           │
        │ 權重 40%           │ 權重 35%           │ 權重 25%           │
        └─────────┬──────────┴─────────┬──────────┴─────────┬──────────┘
                  │                    │                    │
                  └────────────────────┴────────────────────┘
                                       │
                                       ▼
                       Composite Score = Σ(stage × weight)
                                       │
                                       ▼
                ┌─────────────────────────────────────────────┐
                │  Composite ≥ 85  →  🥇 GOLDEN              │
                │  70 ≤ Composite < 85  →  WATCH             │
                │  Composite < 70  →  IGNORE                  │
                └─────────────────────────────────────────────┘
```

### 0.2 通則 (General Rules)

- 所有子分數皆 0-100，採線性內插 (linear interpolation) 計算。
- 所有門檻數字皆來自 `config/scd.yaml`，本文件數字為 **v1 預設值**。
- 「Hard Gate 不過」與「分數低」是兩件事；前者直接剔除，後者進入排名後段。
- 缺資料的子因子採「**abstain**」(棄權) 處理，**不可記 0**；該子因子從加權平均的分母移除，並在 `audit_log` 留痕（避免 fake zero 翻轉排名，詳見 AUDIT_v1.0.md §3 F4）。

---

### 0.3 Numeric Policy — 數值精度政策 (BINDING)

> Patch P0-1 / P0-3 / P0-4. 違反任一條 ⇒ build fail.

| # | 規則 | 為何 |
|---|---|---|
| N1 | 所有子因子內部以 `Decimal` 計算，內部精度 ≥ 6 dp (`getcontext().prec >= 28`) | 杜絕 IEEE 754 漂移 |
| N2 | 子因子寫入 snapshot 時 `quantize(Decimal("0.0001"), ROUND_HALF_EVEN)` (4 dp 內部 audit) | 精度足夠且可重現 |
| N3 | Factor / Composite quantize 同 4 dp | 加總後 quantize 一次，**禁止對中間結果再次四捨五入** |
| N4 | UI / 報表顯示 quantize 至 `Decimal("0.1")` (1 dp) | 對應原始資料解析度，避免假精度 |
| N5 | 全域 rounding mode = `ROUND_HALF_EVEN` (banker's rounding) | Python `round()` 也用此模式，但 floats 之上不穩定，故必須走 Decimal |
| N6 | tie-breaker 排序前先把 `composite_score` quantize 至 4 dp | 避免 84.9995 vs 85.0000 之類的 FP 翻面 |
| N7 | 缺資料子因子 = abstain，從加權平均的分母移除；不可用 0 補洞 | fake 0 會擠掉真實低分股的排名 |
| N8 | `config_hash` = SHA-256 of YAML dumped with `sort_keys=True, default_flow_style=False, indent=2` | 同份 config 跨機器必同 hash |

#### N1 ~ N6 的 Python 參考實作 (此段為 spec，非程式碼)

```python
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
getcontext().prec = 28
Q4 = Decimal("0.0001")   # 內部 / snapshot 精度
Q1 = Decimal("0.1")      # 顯示精度

def to_score(x) -> Decimal:
    return Decimal(str(x)).quantize(Q4, rounding=ROUND_HALF_EVEN)

def weighted_sum(pairs):
    # pairs: List[(weight_str, score_decimal)]
    total = sum(Decimal(w) * s for w, s in pairs)
    return total.quantize(Q4, rounding=ROUND_HALF_EVEN)
```

#### 翻面實證 (來自 AUDIT_v1.0.md §1.2)

> 給定 `(stage_1, stage_2, stage_3) = (84.99, 85.01, 85.00)`：
> - 純 float → composite = 84.9995 → **WATCH**
> - Decimal HALF_EVEN → composite = 85.0000 → **GOLDEN**
>
> **本政策強制 Decimal 路徑，使結果唯一。**

---

### 0.4 Convention Rules — 模糊規則明文化 (BINDING)

> Patch P0-5. 凡 config 出現以下結構，必須按本節定義詮釋。

| 結構 | 解讀 |
|---|---|
| `linear_range: [r_min, r_max]` | `score = base_at_min + (base_at_max − base_at_min) × clamp((x − r_min)/(r_max − r_min), 0, 1)`。若未指定 `base_at_*`，預設 `base_at_min = 0`、`base_at_max = 100`。**`r_min` 可大於 `r_max` (descending)，公式自洽。** |
| `*_curve: {k1:v1, k2:v2, ...}` | **Piecewise linear interpolation** between adjacent keys (sorted by key)。範圍外 clamp 到 endpoint。Keys 為 input；values 為 score。 |
| `*_levels: {k1:v1, k2:v2, ...}` | **Step function**: `score = v[largest_k_le_x]`。x 小於最小 key → 0。Keys 為閾值；values 為達標分數。 |
| `*_streak` | 「最長連續上升段」(longest consecutive run)，**非**「上升次數總和」。 |
| 多訊號 `pa_signals_30m` 聚合 | `max_with_retest_bonus`：取最高訊號分（pin_bar/engulfing/terminal 之最大），若同時含 `retest` 則 + 20，最終 clamp 至 100。**禁止把多個非 retest 訊號分數疊加。** |
| `forbid_segment` 不一致 | TDCC 週報的 delta 必須對 TDCC **自己** 的上一份 report 計算；同一份 TDCC report 跨多日使用時，`shareholder_*_delta_*` 在這幾日**回傳相同值**，並在 audit_log 記 `data_window` 區間。 |

---

### 0.5 Gate-then-Score 規約 — 去除雙重計分 (BINDING)

> Patch P0-1 derived rule. 對應 AUDIT_v1.0.md §2.2「訊號重疊」。

**規則**：當一個子因子的 raw input 也被 hard gate 使用時，sub-score 的 `linear_range` 下界 **必須嚴格大於** gate 下界。

| 子因子 | Gate 下界 | v1.1 sub-score `linear_range` (新) | v1 (舊) |
|---|---|---|---|
| `fii_sync_count` | G2: ≥ 2 | **[3, 6]** | [2, 5] |
| `mainforce_consecutive_days` | G3: ≥ 3 | **[4, 8]** | [3, 7] |
| `cost_safety_pct` (新) | G1: price ≤ cost × 1.05 | **[-0.04, +0.01]** (gate 通過後再衡量便宜程度) | — |

**直覺**：通過 gate 已經是「達標」；sub-score 衡量「**超出多少**」。剛擦邊通過的標的拿 0 分，明顯優於門檻者才往上加。

> v1.1 config keys 同步更新（見 P0-5 patch 後的 `config/scd.example.yaml`）。

---

## 1. Hard Gates — 三道硬性門檻

### G1. 主力成本 5% 緩衝區 (Cost Safety Gate)

| 變數 | 定義 | v1 門檻 |
|---|---|---|
| `main_force_cost` | 主力分點近 N 日買進均價 | N = 5 |
| `current_price` | 當日收盤價 | — |
| 通過條件 | `current_price ≤ main_force_cost × 1.05` | 倍率 = 1.05 |

> 來源：V3 守冊 §二.2 「5% 緩衝區：現價 P ≤ Price_Avg × 1.05。超過則嚴禁追高。」

### G2. 外資同步買進 (FII Synchronization Gate)

| 變數 | 定義 | v1 門檻 |
|---|---|---|
| `fii_brokers_buying` | 當日有買超的指標外資分點清單 | 指標清單：JPM、UBS、GS、ML、Citi |
| 通過條件 | `len(fii_brokers_buying) ≥ 2` 且「近 3 個交易日」皆成立 | ≥ 2 家、連續 3 日 |

> 來源：V3 守冊 §二.1 「2 家以上同時連續買進」。

### G3. 主力分點連買 (Main Force Consecutive Buy Gate)

| 變數 | 定義 | v1 門檻 |
|---|---|---|
| `main_force_consecutive_days` | 買超前 5 名分點，累計買超天數 | ≥ 3 天 |
| `main_force_volume_trend` | 連續日的買超張數應遞增 F(n) > F(n-1) | 至少 2 段遞增 |

> 來源：V3 守冊 §二.2 「買進張數須逐日放大」。

**任一 Gate 不過 → `stage = 0, composite_score = 0`，並在 snapshot 內標記 `eliminated_by = "G1"|"G2"|"G3"`。**

---

## 2. Stage 1 — 雙引擎籌碼分數 (Dual Engine, 0–100, weight 40%)

由 **FII 子分 (FII sub-score)** 與 **主力子分 (Main-Force sub-score)** 各 50% 組成。

### 2.1 FII Sub-score (0–100)

| 指標 | 計分方式 | v1.1 標準 |
|---|---|---|
| 同步外資家數 (`fii_sync_count`) | 線性：3 家 → 0 分，6 家 → 100 分 (Gate-then-Score) | 線性區間 [3, 6] |
| 外資買超佔成交量比 (`fii_buy_ratio`) | 線性：5% → 0 分，15% → 100 分 | 線性區間 [5%, 15%] |
| 外資持股趨勢 (`fii_holding_trend`) | up = 100；flat = 50；down = 0 | step levels |
| **加權** | FII sub = 0.4 × sync + 0.4 × ratio + 0.2 × trend | — |

### 2.2 Main-Force Sub-score (0–100)

| 指標 | 計分方式 | v1.1 標準 |
|---|---|---|
| 連買天數 (`main_force_consecutive_days`) | 線性：4 天 → 0 分，8 天 → 100 分 (Gate-then-Score) | 線性區間 [4, 8] |
| 鎖碼強度 (`main_force_buy / total_volume`) | 線性：10% → 0 分，30% → 100 分 | 線性區間 [10%, 30%] |
| 量遞增驗證 (`volume_increasing_streak`) | 每段遞增 +25 分，上限 100 | 加成型 |
| 分點集中度 (`top5_concentration`) | 前 5 分點買超 / 總買超；50% → 0 分，80% → 100 分 | 線性區間 [50%, 80%] |
| **加權** | Main = 0.3×days + 0.3×lock + 0.2×streak + 0.2×concentration | — |

### 2.3 Stage 1 Composite

```
stage_1 = 0.5 × FII_sub + 0.5 × MainForce_sub
```

---

## 3. Stage 2 — 行為背離分數 (Behavioral Divergence, 0–100, weight 35%)

由 **籌碼集中子分** 與 **融資心理子分** 各 50% 組成。

### 3.1 籌碼集中子分 (Concentration Sub-score, 0–100)

| 指標 | 計分方式 | v1 標準 |
|---|---|---|
| 股東總人數變化 (`shareholder_count_delta_pct`) | 線性：0% → 0 分，−5% → 100 分（負值越多越好） | 區間 [0, −5%] |
| 買賣家數差 (`broker_count_diff`) | 連 5 日為負 = 100；3 日 = 60；< 3 日 = 0 | 3 級離散 |
| 400 張大戶持股比例變化 (`large_holder_400_delta`) | +0% → 0 分，+3% → 100 分 | 區間 [0, +3%] |
| 1000 張大戶持股比例變化 (`large_holder_1000_delta`) | +0% → 0 分，+2% → 100 分 | 區間 [0, +2%] |
| **加權** | 0.3×shareholders + 0.2×diff + 0.25×L400 + 0.25×L1000 | — |

### 3.2 融資心理子分 (Margin Psychology Sub-score, 0–100)

| 指標 | 計分方式 | v1 標準 |
|---|---|---|
| 融資維持率 (`margin_maintenance_ratio`) | 130% → 100 分；140% → 80 分；150% → 50 分；≥160% → 20 分 | 反向曲線 |
| 價跌融資減 (`price_down_margin_down_days`) | 過去 10 日符合的天數，每天 +10 分上限 100 | 累加 |
| 價跌融資增 (`price_down_margin_up_days`) | 過去 10 日符合的天數，每天 −15 分（可為負，下限 0） | 扣分項 |
| **加權** | 0.5×maintenance + 0.3×healthy_wash + 0.2×unhealthy_penalty | — |

> 「140% 絕望買點」=（融資維持率 ≤ 142% 且 量縮不跌 ≥ 3 日 且 利空止步）三條件同時成立時，snapshot 內 `margin_panic_signal = true`，做為加分線索（非 gate）。

### 3.3 Stage 2 Composite

```
stage_2 = 0.5 × Concentration_sub + 0.5 × Margin_sub
```

---

## 4. Stage 3 — 執行觸發分數 (Execution Trigger, 0–100, weight 25%)

### 4.1 30 分鐘線價格行為 (Price Action Sub-score, 0–100)

| 訊號 | 給分 | 備註 |
|---|---|---|
| Pin Bar（長下影線） | +40 | 下影 ≥ 2 × 實體 |
| Bullish Engulfing | +50 | 完全吞噬前一根陰線 |
| Terminal Bar | +30 | 出現在區間下緣 |
| 同根 K 同時符合多訊號 | 取最高分，不疊加 | — |
| 二次回測成功 (Type 2) | +20 | 接近支撐反彈 |
| **上限** | 100 | 超過則截斷 |

### 4.2 2H 線趨勢確認 (2H Trend Confirmation Sub-score, 0–100)

| 條件 | 給分 |
|---|---|
| 站上 20EMA 且斜率為正 | 100 |
| 站上 20EMA 但斜率走平 | 60 |
| 跌破 20EMA | 0 |

### 4.3 交易型態分類 (Trade Type Classification)

| 型態 | 觸發條件 | 標記欄位 |
|---|---|---|
| Type 1（反應型） | 融資維持率 < 140% 且籌碼洗淨後反彈 | `trade_type = "T1"` |
| Type 2（趨勢型） | 外資+主力持續鎖碼 + 突破盤整區後二次回測 | `trade_type = "T2"` |

### 4.4 Stage 3 Composite

```
stage_3 = 0.6 × PriceAction_sub + 0.4 × Trend2H_sub
```

---

## 5. Composite Score & Tier 判定

```
composite_score = 0.40 × stage_1
                + 0.35 × stage_2
                + 0.25 × stage_3
```

| Tier | 條件 | 動作 |
|---|---|---|
| 🥇 **GOLDEN** | `composite ≥ 85` AND `G1 ∧ G2 ∧ G3` 全過 | 進「主力鎖碼名單」，AI 強制產出戰術解讀 |
| 🥈 **WATCH** | `70 ≤ composite < 85` | 進觀察清單，每日盤後重評 |
| 🥉 **NEUTRAL** | `50 ≤ composite < 70` | 暫不動作 |
| ❌ **IGNORE** | `composite < 50` 或任一 gate 不過 | 從清單剔除 |

### 並列時的 tie-breaker 順序

1. `stage_1` 較高者勝
2. `main_force_consecutive_days` 較多者勝
3. `fii_sync_count` 較多者勝
4. `ticker` 字典序較小者勝（最終 fallback，保證決定論）

---

## 6. 全部 v1 門檻參數對照表 (Threshold Reference)

> 將下表完整寫入 `config/scd.example.yaml`。修改門檻只能改 config，不能改程式碼。

| Key | v1 值 | 出處 |
|---|---|---|
| `gates.cost_safety.lookback_days` | 5 | V3 §二.2 |
| `gates.cost_safety.max_premium_ratio` | 1.05 | V3 §二.2 |
| `gates.fii_sync.indicator_brokers` | [JPM, UBS, GS, ML, Citi] | V3 §二.1 |
| `gates.fii_sync.min_brokers` | 2 | V3 §二.1 |
| `gates.fii_sync.min_consecutive_days` | 3 | V3 §二.1 |
| `gates.main_force.min_consecutive_days` | 3 | V3 §二.2 |
| `gates.main_force.volume_increasing_min_streaks` | 2 | V3 §二.2 |
| `stage_1.weights.fii` | 0.5 | 本文件 §2.3 |
| `stage_1.weights.main_force` | 0.5 | 本文件 §2.3 |
| `stage_1.fii.sync_count.linear_range` | **[3, 6]** (v1.1 Gate-then-Score) | 本文件 §2.1 |
| `stage_1.fii.buy_ratio.linear_range` | [0.05, 0.15] | 本文件 §2.1 |
| `stage_1.main_force.consecutive_days.linear_range` | **[4, 8]** (v1.1 Gate-then-Score) | 本文件 §2.2 |
| `stage_1.main_force.lock_strength.linear_range` | [0.10, 0.30] | 本文件 §2.2 |
| `stage_1.main_force.top5_concentration.linear_range` | [0.50, 0.80] | 本文件 §2.2 |
| `stage_2.weights.concentration` | 0.5 | 本文件 §3.3 |
| `stage_2.weights.margin` | 0.5 | 本文件 §3.3 |
| `stage_2.concentration.shareholder_delta.linear_range` | [0.0, -0.05] | 本文件 §3.1 |
| `stage_2.concentration.large_holder_400.linear_range` | [0.0, 0.03] | 本文件 §3.1 |
| `stage_2.concentration.large_holder_1000.linear_range` | [0.0, 0.02] | 本文件 §3.1 |
| `stage_2.margin.maintenance_curve` | {130: 100, 140: 80, 150: 50, 160: 20} | 本文件 §3.2 |
| `stage_2.margin.panic_threshold` | 142 | V3 §三.2 |
| `stage_3.weights.price_action` | 0.6 | 本文件 §4.4 |
| `stage_3.weights.trend_2h` | 0.4 | 本文件 §4.4 |
| `stage_3.price_action.scores` | {pin_bar: 40, engulfing: 50, terminal: 30, retest: 20} | 本文件 §4.1 |
| `composite.weights` | [0.40, 0.35, 0.25] | 本文件 §5 |
| `tiers.golden_min` | 85 | 使用者規範 |
| `tiers.watch_min` | 70 | 本文件 §5 |
| `tiers.neutral_min` | 50 | 本文件 §5 |

---

## 7. 範例計算 (Worked Example) — decimal-verified

> 假設個股 **3481 群創**, 2026-05-22 收盤後（**示範用假資料，非真實**）。
> 計算依 §0.3 Numeric Policy（Decimal + ROUND_HALF_EVEN, 4 dp 內部精度）與 §0.5 Gate-then-Score（linear_range 下界移至 gate 之上）。

### 7.1 v1.1 試算（採新規約）

| 變數 | 值 | 公式 / Config | 子分 |
|---|---|---|---|
| **Gates** | G1 ✓ G2 ✓ G3 ✓ | 19.75 ≤ 18.85×1.05；sync=3 ≥ 2 且連 3 日；mf=5 ≥ 3 | 通過 |
| FII sync count | 3 | linear [**3, 6**] → (3−3)/(6−3) = 0 | **0.0000** |
| FII buy ratio | 12% | linear [0.05, 0.15] → (0.12−0.05)/0.10 = 70% | **70.0000** |
| FII holding trend | up | levels {up:100, flat:50, down:0} | **100** |
| **FII sub** | | 0.4×0 + 0.4×70 + 0.2×100 = 0 + 28 + 20 | **48.0000** |
| MF consec days | 5 | linear [**4, 8**] → (5−4)/(8−4) = 25% | **25.0000** |
| MF lock strength | 22% | linear [0.10, 0.30] → 60% | **60.0000** |
| MF streak | 3 段 | min(25×3, 100) | **75** |
| MF concentration | 70% | linear [0.50, 0.80] → 66.67% | **66.6667** |
| **MF sub** | | 0.3×25 + 0.3×60 + 0.2×75 + 0.2×66.6667 = 7.5+18+15+13.3333 | **53.8333** |
| **chip_score (s1)** | | 0.5×48 + 0.5×53.8333 | **50.9166** |
| Shareholder Δ | −3.2% | linear descending [0, −0.05] → 64% | **64.0000** |
| Broker diff days | 5 連負 | step levels {5:100, 3:60, 0:0} → 100 | **100** |
| L400 Δ | +1.8% | linear [0, 0.03] → 60% | **60.0000** |
| L1000 Δ | +1.2% | linear [0, 0.02] → 60% | **60.0000** |
| Concentration sub | | 0.3×64 + 0.2×100 + 0.25×60 + 0.25×60 | **69.2000** |
| Margin ratio | 138% | piecewise {130:100, 140:80, ...} → 100 − 20×0.8 | **84.0000** |
| Healthy wash days | 6 | min(10×6, 100) | **60** |
| Unhealthy days | 0 | max(0, −15×0) | **0** |
| Margin sub | | 0.5×84 + 0.3×60 + 0.2×0 | **60.0000** |
| **behavior_score (s2)** | | 0.5×69.2 + 0.5×60 | **64.6000** |
| Price action | engulfing + retest | max(50) + 20 = 70 | **70** |
| 2H trend | 站上 20EMA 正斜率 | lookup | **100** |
| **structure_score (s3)** | | 0.6×70 + 0.4×100 = 42 + 40 | **82.0000** |
| **composite** | | 0.40×50.9166 + 0.35×64.6 + 0.25×82.0 = 20.3666 + 22.61 + 20.5 | **63.4766** |
| Display (1 dp) | | quantize(0.1) | **63.5** |
| Tier | 63.48 落於 [50, 70) | | **NEUTRAL** |

### 7.2 v1.0 vs v1.1 對照（同一份輸入）

| 計算路徑 | chip | behavior | structure | composite | tier |
|---|---|---|---|---|---|
| v1.0 文件公布 (含 rounding drift) | 72.6 | 64.6 | 82.0 | **72.15** | WATCH |
| v1.0 decimal-verified (無 drift) | 72.5 | 64.6 | 82.0 | **72.11** | WATCH |
| **v1.1** (Gate-then-Score + Decimal) | 50.92 | 64.6 | 82.0 | **63.48** | **NEUTRAL** |

> **正確的結論**：3481 的 chip 強度是「剛擦邊通過 gate」（sync=3 與 mf_consec=5 都僅略高於門檻），v1.1 規則正確地把它判為 NEUTRAL 而非 WATCH。
> 若要升至 WATCH 需要：FII sync count ≥ 5 或 MF consec days ≥ 7。
> 若要升至 GOLDEN 需要：chip + behavior + structure 三邊同步走強。

### 7.3 程式重現 (reference implementation, 非規範實作)

```python
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
getcontext().prec = 28
Q4 = Decimal("0.0001")

def D(x): return Decimal(str(x))
def lin(x, r_min, r_max, b_min=0, b_max=100):
    t = (D(x)-D(r_min))/(D(r_max)-D(r_min))
    t = max(D(0), min(D(1), t))
    return (D(b_min) + (D(b_max)-D(b_min))*t).quantize(Q4, ROUND_HALF_EVEN)

# Chip
fii_sub = (D("0.4")*lin(3,3,6) + D("0.4")*lin("0.12","0.05","0.15") + D("0.2")*D(100)).quantize(Q4, ROUND_HALF_EVEN)
mf_sub  = (D("0.3")*lin(5,4,8) + D("0.3")*lin("0.22","0.10","0.30")
         + D("0.2")*D(75) + D("0.2")*lin("0.70","0.50","0.80")).quantize(Q4, ROUND_HALF_EVEN)
chip    = (D("0.5")*fii_sub + D("0.5")*mf_sub).quantize(Q4, ROUND_HALF_EVEN)
# Behavior / Structure 同理（略），composite:
composite = (D("0.40")*chip + D("0.35")*D("64.6") + D("0.25")*D("82.0")).quantize(Q4, ROUND_HALF_EVEN)
assert composite == Decimal("63.4766")        # CI 鎖在這個值上
```

---

## 8. 驗收測試 (Acceptance Tests)

CI 應在 `tests/test_scoring.py` 寫死下列案例：

1. **Determinism** — 同樣輸入跑 100 次，composite 必相同（誤差 < 1e-9）。
2. **Boundary**
   - `main_force_consecutive_days = 3`（最小通過）→ MF days 子項 = 60
   - `main_force_consecutive_days = 7`（飽和）→ MF days 子項 = 100
   - `main_force_consecutive_days = 10`（超出）→ 截斷 100
3. **Gate eviction** — `current_price = main_force_cost × 1.06` → `eliminated_by = "G1"`, `composite = 0`
4. **Tie-breaker** — 兩檔 composite 都是 87.000，stage_1 高者排前。
5. **NaN handling** — 缺 `fii_buy_ratio` → FII sub 對該項記 0 並在 `audit_log` 添加警告。

---

## 9. 與 V3 守冊對照 (Cross-reference to V3 Charter)

| V3 §段落 | 本文對應 |
|---|---|
| §二.1 外資動態 | §1 G2 + §2.1 FII sub |
| §二.2 主力分點 | §1 G1 + G3 + §2.2 MF sub |
| §三.1 股權分散 | §3.1 Concentration sub |
| §三.2 融資心理 / 140% | §3.2 Margin sub |
| §四.1 PA 訊號 | §4.1 PA sub |
| §四.2 Type 1 / Type 2 | §4.3 trade_type |
| §六 每日檢核清單 | snapshot.checklist 欄位 (見 schema) |
