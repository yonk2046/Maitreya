# SCD Engine — v1.0 規格內部稽核報告 (Internal Audit)

> Auditor: Self-review under quant-architect lens
> Audit date: 2026-05-22
> Subject of audit: `docs/SCORING_RUBRIC.md` v1.0, `docs/CANONICAL_SCHEMA.md` v1.0, `schema/canonical_schema.json`, `config/scd.example.yaml`
> Verdict: **規格通過初版自洽性測試，但有 7 類設計缺陷會在實作後浮現。本文件列出全部缺陷與建議修法。**

---

## 0. Executive Summary

| 嚴重度 | 類別 | 數量 | 簡述 |
|---|---|---|---|
| 🔴 **CRITICAL** | 決定論失敗 | 4 | 浮點/四捨五入策略未定義；同輸入可在 GOLDEN/WATCH 之間翻面 |
| 🔴 **CRITICAL** | 可追溯性缺口 | 3 | breakdown 停在 sub-factor 層，無法從快照單獨還原分數 |
| 🟠 HIGH | 訊號重疊 / 雙重計分 | 5 | FII 連買、主力鎖碼、大戶持股 (400/1000) 等高度相關訊號被重複加權 |
| 🟠 HIGH | 假精度 (fake precision) | 3 | 小數兩位 × 10 餘子因子 ≫ 原始資料解析度 |
| 🟡 MEDIUM | provenance 粒度過粗 | 2 | provenance 以「group」記，非以「欄位」記，cross-source merge 無法稽核 |
| 🟡 MEDIUM | 隱性 AI 介面 | 2 | `pa_signals_30m` 是後處理結果，沒有 raw 30 分 K 留底，無法事後驗證 |
| 🟢 LOW | 命名一致性 | 3 | `stage_X` 不是 quant 命名慣例；`is_day_trader_branch` 未進入評分但已存欄 |

**結論**：可以基於 v1.0 落地 PoC，但在 GO-LIVE 前必須 patch 為 v1.1（本文件 §6 給出最小改動的重構提案）。

---

## 1. Composite Score Integrity 可追溯性檢查

### 1.1 已驗證：規格本身有「啟發性算術錯誤」

**測試**：對 `SCORING_RUBRIC.md §7` 的群創 3481 worked example 用三種精度模式重算。

| 計算方式 | composite_score | tier |
|---|---|---|
| 規格文件公布值 | **72.15** | WATCH |
| 浮點全程不中途四捨五入 | 72.11 | WATCH |
| Decimal + ROUND_HALF_EVEN quantize | 72.11 | WATCH |
| 差值 (drift) | **0.04 點** | — |

> 規格文件把 `FII sync sub` 從 66.6667 寫成 67.0、`stage_1` 從 72.50 寫成 72.6。每一步只差 0.1，但累積後 composite 偏差 0.04 點。**規格文件本身就是 non-determinism 的活案例。**

### 1.2 翻面實驗：跨 85 的 GOLDEN 是否會被誤判？

**測試**：在 (stage_1, stage_2, stage_3) = (84.99, 85.01, 85.00) 與 (84.95, 85.05, 84.99) 兩組邊界輸入下：

| 計算 | composite | tier |
|---|---|---|
| 純 float | 84.999500 / 84.995000 | **WATCH** |
| Decimal HALF_EVEN | 85.000000 / 85.000000 | **GOLDEN** |
| 結果 | ⚠️ **同一輸入翻面** | — |

> 證實：**若不在 spec 中釘死浮點策略，任何在 84.9–85.1 之間的標的，今日 WATCH、明日 GOLDEN，純粹由實作差異決定。** 這是 P0 級 bug。

### 1.3 Breakdown 缺乏「raw_inputs → formula → score」鏈

目前 snapshot 的 `stage_1_breakdown.fii_sub_breakdown` 只給 `{sync: 66.7, ratio: 70.0, trend: 100}`，但沒給：
- 這些 66.7 是怎麼從 `fii_sync_count=3` 算出來的（哪段 linear_range？哪兩個 anchor？）
- 用的是哪個 config_key
- 配套的 config_hash

**結論**：讀者必須同時擁有 snapshot + 同一份 config 才能重算。如果未來改 config，舊 snapshot 的「為什麼是 72.15」就會永遠失傳。

---

## 2. Hidden Drift Risks 漂移風險清單

### 2.1 規則模糊處（未來會成為實作分歧點）

| # | 規則模糊點 | 兩種合理實作 | 後果 |
|---|---|---|---|
| D1 | `linear_range: [0.0, -0.05]` 方向 | (a) 0→0, -0.05→100；(b) 0→100, -0.05→0 | 「股東人數延漲」記為 0 還是 100 分？翻面 |
| D2 | `maintenance_curve: {130:100, 140:80, ...}` 中間值 | (a) piecewise linear；(b) step function；(c) cubic spline | 138% 可能 = 84、80、或其他 |
| D3 | `levels: {5:100, 3:60, 0:0}` 中間值 | (a) 階梯函數取≤；(b) 線性內插 | 4 連負日 = 60 或 80？ |
| D4 | `volume_increasing_streak` 「segment」定義 | (a) 上升次數總和；(b) 最長連續段 | F=[1,2,1,2,3] 是 2 段或 1 段？ |
| D5 | `pa_signals_30m` 多訊號同時觸發 | spec 說「取最高分不疊加 + retest 可加 20」，但程式碼可能誤實作為「全部加總」 | 100 vs 70 vs 50 |
| D6 | TDCC 集保週報的 delta 用「上一次」還是「7 天前」 | 若週報空窗，可能持續引用同一份 → 同一份 delta 出現多日 | 訊號跨日重複計分 |

> 修法見 §6.5。

### 2.2 訊號重疊與相關性（雙重計分）

| 訊號 A | 訊號 B | 重疊原因 |
|---|---|---|
| Gate G2 (`fii_sync ≥ 2`) | Stage1.FII.sync (linear [2,5]) | 通過 G2 的下界已經被 G2 認證，又在 sub-score 重新計分 |
| Gate G3 (`mf_consec ≥ 3`) | Stage1.MF.consecutive_days (linear [3,7]) | 同上 |
| `large_holder_400_pct` | `large_holder_1000_pct` | 集合包含 (1000-lot ⊂ 400-lot)；相關性極高 |
| `fii_holding_trend_5d` | `fii_consecutive_buy_days` | 連買勢必造成持股上升 |
| `main_force_consecutive_days` | `volume_increasing_streak` | 都從同一條買超時序提取 |
| `main_force_buy` (絕對量) | `top5_concentration` (相對佔比) | 強者通常兩者都高 |

**經驗法則**：若兩子因子的 Pearson r > 0.7，等同把同一訊號重複加權，**實質權重 ≈ nominal × (1 + r)**。

### 2.3 Day-trader 污染未處理

`is_day_trader_branch` 已存欄但**從未進入評分**。然而 `top5_concentration = 70%` 可能來自隔日沖分點（如凱基-台北）的盤中拉抬。這會把短線沖洗誤判為「主力鎖碼」。

**修法**：先排除日沖名單後再算 top5_concentration（見 §6.2.3）。

---

## 3. Determinism Failure Points 決定論失敗點

| # | 失敗點 | 影響 | 修法 |
|---|---|---|---|
| F1 | 全程未指定 float vs Decimal | 翻面（§1.2 已證） | 全程 `Decimal(str(x)).quantize("0.01", ROUND_HALF_EVEN)` |
| F2 | 中途四捨五入（規格文件即如此） | 累積偏差 ≥ 0.04 點 | 子分數不四捨五入，只在 snapshot 寫入時 quantize 一次 |
| F3 | tie-breaker 在 raw composite_score desc 上排 | 87.0000001 vs 87.0000002 視為不同 | 先 quantize 至 2 dp 再排序 |
| F4 | `on_missing_field: zero_with_warning` | 隨意把缺資料記 0，導致同檔在不同跑次因網路抖動而排名不同 | 改為 `fail_fast` 或 `nullable_subfactor` 模式（後者讓子因子直接 abstain） |
| F5 | `dict` 迭代順序 (Python 3.7+ 有序，但 YAML loader 不保證) | 影響 `config_hash` | YAML 載入後強制 `sort_keys=True` 序列化再 hash |
| F6 | 時區 / 系統時鐘 | `generated_at` 不影響邏輯但會打斷 hash | hash 不可包含 `generated_at`；改用 `data_window` 區間描述 |
| F7 | NumPy/Pandas 版本差異 | 統計函式 (`mean`, `corr`) 在不同版本給不同小數位 | `requirements.txt` 鎖版本；CI 加 hash test |

---

## 4. Score Semantics Audit 評分語意稽核

### 4.1 假精度 (Fake Precision)

| 原始資料 | 解析度 | 進入評分後 | 假精度倍率 |
|---|---|---|---|
| `fii_buy_ratio` | TWSE 報張數整數 | linear [0.05, 0.15] → 0.01% 解析度 | × 100 |
| `margin_maintenance_ratio` | TWSE 公布到 1% | piecewise curve → 2 dp | × 100 |
| `top5_concentration` | 張數比 | 2 dp | × 10 ~ 100 |

**這意味著**：composite score 寫到 72.15 是「**6 位有效數字的假精度**」，原始資料只支持 2 位。

> 量化金融慣例：**呈現分數到 1 dp**（最多）；超過 1 dp 應視為內部 audit 用，不可顯示給人類做交易決策。

### 4.2 過擬合風險 (Overfitting Risk)

- 10+ 子因子 × 12+ 權重旋鈕 = **22 個自由參數**。
- 樣本：台股 ~1800 檔 × 252 交易日 = ~45 萬筆，看似夠用。但籌碼+融資資料只回溯 10 年 → 樣本 SNR 低。
- v1 所有門檻來自「個人經驗 (V3 守冊)」未做 walk-forward 驗證。
- 風險：**過擬合到 2020-2025 的多頭環境，2026 熊市必失靈**。

> 應對：每次 config 改動前必須跑 walk-forward backtest（train: 2015-2020；validate: 2021-2023；test: 2024+）。

### 4.3 不公平的分數天花板

| 子因子 | 達到 100 分容易度 | 觀察 |
|---|---|---|
| `trend_2h` | 易 (站上 20EMA 且斜率正) | 多頭日約 50% 個股達標 |
| `fii_holding_trend_5d` | 易 | 趨勢明確即可 |
| `price_action_30m` | 難 (需 engulfing + retest 雙條件) | 約 5% 個股有此 combo |
| `top5_concentration` | 中 | 中等流動性股容易、權值股困難 |

**後果**：composite 天花板被「易達」子因子拉高，但人工挑出來的好股反而被「難達」子因子壓低。

---

## 5. Provenance & Replay 稽核

### 5.1 Provenance 粒度過粗

目前 `provenance.fii_data.source = "TWSE_OpenAPI"`，但實際上：
- `fii_net_buy` 來自 TWSE「三大法人買賣超日報」
- `fii_holding_pct` 來自 TWSE「外資持股比例」(不同 endpoint)
- `fii_brokers_buying` 來自第三方券商分點供應商 (TWSE 不公開)

混為一談 = 出問題時無法定位污染源。

### 5.2 衍生欄位未標 derived_from

`main_force_buy` 是 `sum(top5_branches.net)` 還是另一個資料源？  spec 未說。若兩者不一致（會發生：因為「主力買超」可能定義為前 5 名買、前 10 名買、或所有買超分點淨額），會永遠對不起來。

**修法**：所有 derived 欄位加 `derived_from: ["top5_branches[*].net"]` 或 `derived_from: ["dataset:broker_chip.daily_buy"]`。

### 5.3 「Replay」實際做不到

要 replay 2026-05-22 的 snapshot，需要：
- ✅ snapshot 自身 (有)
- ✅ config (有，已 inline)
- ❌ `/core` 程式碼版本 — spec 未 pin git SHA
- ❌ raw data — spec 未說 `data/raw/2026-05-22/` 是否保留
- ❌ Python / NumPy 版本

**結論：目前的 spec 寫成「我們會 replay」但實作上做不到。**

---

## 6. 重構建議 — 邁向 Quant 級結構 (v1.1 提案)

### 6.1 命名升級

| v1 (現) | v1.1 (建議) | 理由 |
|---|---|---|
| `stage_1` | `chip_score` | 對應業界 chip-flow analysis |
| `stage_2` | `behavior_score` | 對應 behavioral / sentiment factor |
| `stage_3` | `structure_score` 或 `microstructure_score` | 對應 market microstructure (PA + trend) |
| `composite_score` | `scd_score` | 系統命名前綴 |
| Tier `GOLDEN/WATCH/...` | 保留 (內部口語) + 增加 `signal_grade: A/B/C/D` 對外 | A 級對應 GOLDEN |

### 6.2 評分節點統一格式 (Score Node)

每個分數節點（無論 sub-factor 或 factor 或 composite）必須採用以下結構：

```jsonc
{
  "value": "72.55",                   // 字串表示 Decimal，避免 FP
  "formula": "0.4*sync_score + 0.4*ratio_score + 0.2*trend_score",
  "inputs": {                         // 上游 score node 的引用
    "sync_score":  { "$ref": "#/breakdown/chip/fii/sync_score" },
    "ratio_score": { "$ref": "#/breakdown/chip/fii/ratio_score" },
    "trend_score": { "$ref": "#/breakdown/chip/fii/trend_score" }
  },
  "config_refs": ["stage_1.fii.sub_weights"],
  "config_hash":  "sha256:ab12..."
}
```

**葉節點** (subfactor) 還須包含：

```jsonc
{
  "value": "66.67",
  "formula": "base_at_min + (base_at_max - base_at_min) * (raw - r_min) / (r_max - r_min)",
  "raw_inputs":  { "fii_sync_count": 3 },
  "config_refs": [
    "stage_1.fii.sync_count.linear_range",
    "stage_1.fii.sync_count.base_at_min",
    "stage_1.fii.sync_count.base_at_max"
  ],
  "clamped":  false,
  "abstained": false               // raw 缺值時 = true，分數不入加權平均
}
```

### 6.3 三層分解圖

```
┌─────────────────────────────────────┐
│  GATES (boolean, pass/fail only)   │
│   G1 cost_safety                    │
│   G2 fii_sync                       │
│   G3 main_force_consec              │
└──────────────┬──────────────────────┘
               │ (eliminate non-passers)
               ▼
┌─────────────────────────────────────┐
│  FACTORS (3 × 0-100)                │
│   chip_score                        │
│   behavior_score                    │
│   structure_score                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  SUBFACTORS                         │
│   chip:    fii_*, mainforce_*       │
│   behav:   concentration_*, margin_*│
│   struct:  pa_*, trend_2h_*         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  COMPOSITE (scd_score)              │
│   weighted sum, Decimal-quantized   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  TIER (A/B/C/D + GOLDEN/WATCH/...)  │
└─────────────────────────────────────┘
```

### 6.4 去除雙重計分 — Gate-then-Score 規約

新規則：**Gate 用於剔除，score 只衡量「超出 gate 下界多少」。**

| 子因子 | Gate 門檻 | Sub-score linear_range (建議改為) |
|---|---|---|
| `fii_sync_count` | ≥ 2 (gate G2) | **[3, 6]** ← 從 gate 下界 +1 開始 |
| `mainforce_consec_days` | ≥ 3 (gate G3) | **[4, 8]** ← 同上 |
| `cost_safety_pct` | ≥ -5% (gate G1) | **[-4%, +1%]** ← gate 通過後再衡量便宜程度 |

**好處**：sub-score 不會「獎勵剛好擦邊通過」；獎勵「明顯優於門檻」。

### 6.5 模糊規則的明文化（修補 §2.1 的 D1-D6）

寫入 `config/scd.example.yaml` 的 schema 註解：

```yaml
# === Convention rules (binding) ===
#
# linear_range:
#   value = base_at_min + (base_at_max - base_at_min) * (x - r_min) / (r_max - r_min)
#   clamped to [base_at_min, base_at_max]
#   r_min may be > r_max (descending), formula still works
#
# *_curve:  piecewise linear between adjacent keys, clamped at endpoints
# *_levels: step function (pick largest key <= input)
# *_streak: longest CONSECUTIVE run, NOT total count
```

### 6.6 移除相關性高的雙因子

| 原配置 | 新配置 |
|---|---|
| `large_holder_400_pct` + `large_holder_1000_pct` | 只保留 `large_holder_1000_pct`（更稀有的訊號）+ 加 `tail_holder_pct`（< 1 張小戶比例下降） |
| `fii_holding_trend_5d` + `fii_consecutive_buy_days` | 二選一；建議保留 `fii_consecutive_buy_days`（直接事件） |
| `main_force_consecutive_days` + `volume_increasing_streak` | 合併為 `mainforce_momentum_index = consecutive_days × log(1 + streak_count)` |

### 6.7 Day-trader exclusion

```yaml
main_force:
  exclude_branches: ["凱基-台北", "元大-總公司", ...]  # 已知日沖大本營
  top5_concentration:
    computed_after_excluding_day_traders: true
```

### 6.8 浮點/精度政策（最重要的單一修法）

新增章節寫入 SCORING_RUBRIC.md：

```
所有分數計算規約 (Numeric Policy)
1. 所有子因子計算使用 Decimal("0.000001") 精度
2. 子因子寫入 snapshot 時 quantize 至 "0.0001"（4 dp，內部 audit）
3. 顯示 (UI / 報表) quantize 至 "0.1"（1 dp）
4. Composite 加總 quantize 至 "0.0001"，tier 判定使用 4 dp 值
5. 所有 quantize 模式為 ROUND_HALF_EVEN（banker's rounding）
6. tie-breaker 使用 4 dp quantize 後的值
```

### 6.9 Audit log 升級

每個子因子計算必須寫一筆 INFO log：

```jsonc
{
  "ticker": "3481",
  "event":  "SUBFACTOR_COMPUTED",
  "path":   "chip.fii.sync_score",
  "formula": "linear[2,5] -> base[50,100]",
  "raw":     { "fii_sync_count": 3 },
  "value":   "66.6667",
  "config_keys": ["stage_1.fii.sync_count.linear_range",
                  "stage_1.fii.sync_count.base_at_min",
                  "stage_1.fii.sync_count.base_at_max"],
  "step":   "scoring.chip.fii.sync_score"
}
```

> 體積估計：1800 檔 × ~20 個 sub-factor = 36k 筆 / 日。可拆獨立檔 `reports/2026-05-22.audit.jsonl`。

---

## 7. Replay & Provenance — 必補項

### 7.1 Per-field provenance

把 `provenance` 從「group→source」改為「field→source」：

```jsonc
"provenance": {
  "fii_net_buy":       { "dataset": "TWSE.three_institutional.daily", "fetched_at": "...", "etag": "..." },
  "fii_holding_pct":   { "dataset": "TWSE.foreign_holding.daily", "fetched_at": "...", "etag": "..." },
  "top5_branches":     { "dataset": "VendorX.broker_chip.daily", "vendor_id": "VendorX_v3" },
  "main_force_buy":    { "derived_from": ["top5_branches[*].net"], "step": "core.derivations.main_force_buy" },
  "shareholder_count": { "dataset": "TDCC.weekly_distribution", "report_date": "2026-05-17", "data_lag_days": 5 }
}
```

### 7.2 環境鎖定

snapshot 頂層新增：

```jsonc
"environment": {
  "core_commit_sha": "abc1234",
  "python":          "3.11.7",
  "numpy":           "1.26.4",
  "pandas":          "2.2.0",
  "decimal_context": { "prec": 28, "rounding": "ROUND_HALF_EVEN" }
}
```

### 7.3 Raw data retention policy

寫入 ARCHITECTURE.md：

```
- /data/raw/<date>/ 保留 ≥ 3 年（壓縮歸檔）
- /data/raw/ 為「不可變區」(WORM)；TWSE 若修正資料 → 新增 /data/raw/<date>/corrections/<timestamp>/，舊資料不動
- 若需要用「修正後資料」重生 snapshot → 新檔名 reports/<date>.v2.json，並在 reports/index.json 標註 supersedes
```

### 7.4 Backtest hooks

snapshot 內保留：

```jsonc
"forward_returns": {
  "r_1d":  null,    // 由 backfill job 在 +1 個交易日後填入
  "r_5d":  null,
  "r_20d": null,
  "filled_at": null
}
```

這樣 backtest 可以直接掃 `reports/*.json` 用 `composite_score` 與 `r_5d` 跑 IC (Information Coefficient)。

---

## 8. 立即可動工的 patch list (P0)

> 按執行優先序，每項都是「改一處就堵一個漏」。

| # | 動作 | 改哪個檔 | 大約工時 |
|---|---|---|---|
| P0-1 | 寫入 Numeric Policy（§6.8） | `docs/SCORING_RUBRIC.md` 新增 §0.3 | 30 min |
| P0-2 | 把 §1 worked example 的算術改正並標「decimal-verified」 | `docs/SCORING_RUBRIC.md` §7 | 30 min |
| P0-3 | 移除中途四捨五入，所有子因子用 Decimal | `core/scoring.py` (尚未寫) | 1 hour |
| P0-4 | tie-breaker 前先 quantize 到 4 dp | `core/ranking.py` (尚未寫) | 15 min |
| P0-5 | 把 §6.5 規約寫進 `config/scd.example.yaml` 註解區 | `config/scd.example.yaml` | 15 min |
| P0-6 | snapshot 加 `environment` 區塊 | `schema/canonical_schema.json` + 範例 | 30 min |
| P0-7 | `provenance` 改 per-field（§7.1） | schema + 範例 | 1 hour |
| P0-8 | sub-factor 採用 Score Node 結構（§6.2） | schema + scoring spec | 2 hour |
| P0-9 | 加入 SUBFACTOR_COMPUTED audit log | spec + ranking design | 30 min |
| P0-10 | day-trader exclusion 在 main_force 計算前 | config + spec | 30 min |

**總計約 7-8 小時 → 即可把 v1 升到 v1.1（仍未動程式碼，全部在 spec 層）。**

---

## 9. 中期建議 (v2+)

1. **Walk-forward backtest infrastructure**：所有 config 改動必須通過 IC ≥ 0.05 (5d) 且 sharpe ≥ 0.5。
2. **Drift monitor**：每日跑「同樣 raw_data 重跑 snapshot」與當日 snapshot SHA-256 比對，紅燈即停。
3. **Cross-validation against 主觀盤手清單**：每週把 Golden 名單與你主觀挑出的清單對照，計 precision/recall。若 precision < 0.5 表示模型發散。
4. **Factor neutralization**：對相關性 > 0.7 的子因子做 Gram-Schmidt 正交化，避免重複加權。
5. **時序穩定性**：composite_score 的 day-over-day 變化應有上限（e.g., ≤ 15 點）。若某檔一夕之間從 60 跳到 90，必有 bug 或資料污染。

---

## 10. 對話留底 — 給將來自己

寫 SCD 規格時最常犯的錯：
1. **「規格自己驗證自己」** — 規格文件的 worked example 必須由程式自動生成，不可手寫。
2. **過早 quantize** — float 比想像中脆，能用 Decimal 就用。
3. **「現價」這種看起來精確的詞** — TWSE 收盤、收盤試撮、最後一盤、零股，差別在 cents，但跨 5% gate 時會翻面。
4. **以為自己沒有用 prompt 做業務邏輯** — 任何「你覺得這檔好嗎」對話都已經繞過 deterministic core。CI 必須跑 hash-equality。
5. **以為「沒寫進 spec」= 「不會發生」** — 模糊處 100% 會被未來的自己 / AI / 同事各自詮釋出三個版本。

---

## 附錄 A — 引用實證

§1.2 翻面實驗的 Python 重現：

```python
from decimal import Decimal, ROUND_HALF_EVEN

def composite_float(s1,s2,s3):
    return 0.40*s1 + 0.35*s2 + 0.25*s3

def composite_decimal(s1,s2,s3):
    Q = lambda x: Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    s1d, s2d, s3d = Q(s1), Q(s2), Q(s3)
    return (Decimal("0.40")*s1d + Decimal("0.35")*s2d + Decimal("0.25")*s3d
           ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

# 邊界案例：(84.99, 85.01, 85.00)
print(composite_float(84.99, 85.01, 85.00))    # 84.9995 → WATCH
print(composite_decimal(84.99, 85.01, 85.00))  # 85.00  → GOLDEN
```

> 同樣輸入，純 Python float 給 WATCH，Decimal+HALF_EVEN 給 GOLDEN。
> **這是 v1 spec 必須在實作前釘死的決定論裂縫。**
