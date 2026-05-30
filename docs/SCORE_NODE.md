# SCD Engine — Score Node 規格 (Hierarchical Score Tree)

> Version: v1.0 (2026-05-22) — P2 phase
> Schema: canonical_schema v1.3.0
> 對應 SCORING_RUBRIC.md v1.1（規則不變，只新增可觀察性結構）

---

## 0. 一句話

**每一個 composite_score 必須能展開成一棵可單獨重算的樹；每片葉子記得自己用了哪份原始資料、哪個 config 鍵、哪段公式、哪些 normalization 步驟。**

*Every composite_score must expand into a tree whose every leaf records which raw input, which config key, which formula, and which normalization steps produced its value.*

---

## 1. 為什麼要 Score Tree

對應 AUDIT_v1.0.md §1.3：v1 的 `stage_X_breakdown` 只到 sub-factor 層；讀者無法從快照單獨還原分數。Score Tree 把這層次補完整，使：

1. **任一葉節點可單獨驗算**：拿原始資料 + 公式 + config 重算即可。
2. **任一中間節點可獨立稽核**：weight、formula、inputs 都在節點上。
3. **重構分數規則時影響面可量化**：搜尋 `config_refs` 即知哪些葉節點會變動。
4. **AI 解讀層可引用節點路徑**：例如「3481 在 `composite.chip_score.fii_sub.sync_score` 拿 0 分是因為 sync_count=3 卡在 gate-then-score 下界」。

**不變動規則**：本階段絕不修改 weights、threshold、ranking。Score Tree 只是把現有 v1.1 計算「展開」成可觀察的形式。

---

## 2. 節點型別 (Node Types)

### 2.1 `ScoreNode` (Internal node — 內部節點)

```jsonc
{
  "path":      "composite.chip_score.fii_sub",   // 從 root 開始的點分隔路徑
  "kind":      "internal",
  "value":     "48.0000",                         // Decimal as string, 4 dp
  "formula":   "0.4*sync_score + 0.4*ratio_score + 0.2*trend_score",
  "inputs":    {                                  // 子節點，nested
    "sync_score":  { /* LeafScoreNode */ },
    "ratio_score": { /* LeafScoreNode */ },
    "trend_score": { /* LeafScoreNode */ }
  },
  "config_refs": ["stage_1.fii.sub_weights"],     // 影響本節點的 config 鍵路徑
  "config_values_at_eval": {                       // 評估當下的快照
    "stage_1.fii.sub_weights": { "sync": 0.4, "ratio": 0.4, "trend": 0.2 }
  },
  "normalization": [                               // 此節點輸出前套用的轉換
    { "op": "weighted_sum", "weights": ["0.4","0.4","0.2"] },
    { "op": "quantize",     "dp": 4, "rounding": "ROUND_HALF_EVEN" }
  ],
  "abstained":          false,                     // 是否因子節點全部 abstain → 自身 abstain
  "abstain_propagation": "any_input_abstained_zero_weight_redist"
}
```

### 2.2 `LeafScoreNode` (Leaf — 葉節點)

```jsonc
{
  "path":      "composite.chip_score.fii_sub.sync_score",
  "kind":      "leaf",
  "value":     "0.0000",
  "formula":   "linear_range(x=fii_sync_count, r_min=3, r_max=6, base_min=0, base_max=100)",
  "raw_inputs": {
    "fii_sync_count": 3
  },
  "config_refs": [
    "stage_1.fii.sync_count.linear_range",
    "stage_1.fii.sync_count.base_at_min",
    "stage_1.fii.sync_count.base_at_max"
  ],
  "config_values_at_eval": {
    "stage_1.fii.sync_count.linear_range": [3, 6],
    "stage_1.fii.sync_count.base_at_min": 0,
    "stage_1.fii.sync_count.base_at_max": 100
  },
  "provenance": {                                  // 引用 provenance.field_to_source
    "fii_sync_count": {
      "source_id": "vendor_broker_chip",            // 從 provenance.field_to_source 而來
      "derived":   true,                            // 是 derived 還是直接欄位
      "derivation_step": "core.derivations.fii_sync_count"   // 若 derived
    }
  },
  "normalization": [
    { "op": "linear",   "r_min": 3, "r_max": 6, "base_min": 0, "base_max": 100 },
    { "op": "clamp",    "min": 0, "max": 100 },
    { "op": "quantize", "dp": 4, "rounding": "ROUND_HALF_EVEN" }
  ],
  "evaluated":  "base_min + (base_max - base_min) * clamp((3-3)/(6-3), 0, 1) = 0 + 100*0 = 0.0000",
  "clamped":    false,
  "abstained":  false,
  "abstain_reason": null
}
```

### 2.3 共通欄位

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `path` | string | ✅ | 點分隔，從 `composite` 開始；唯一定位節點 |
| `kind` | enum `internal` / `leaf` | ✅ | — |
| `value` | string (Decimal-as-string, 4 dp) | ✅ | 不可為 number/float |
| `formula` | string | ✅ | 人類可讀的算式 |
| `config_refs` | array<string> | ✅ | 影響本節點的 config 鍵；缺 = 違規 |
| `config_values_at_eval` | object | ✅ | 評估當下這些鍵的值；replay 不需查 config 即可重算 |
| `normalization` | array<NormalizationStep> | ✅ | 套用順序 |
| `abstained` | boolean | ✅ | 缺資料時為 true |
| `abstain_reason` | string \| null | leaf only | abstain 時必填 |

### 2.4 NormalizationStep 子型別

```jsonc
// op: "linear"
{ "op": "linear", "r_min": 3, "r_max": 6, "base_min": 0, "base_max": 100 }

// op: "piecewise"
{ "op": "piecewise", "curve": {"130":100, "140":80, "150":50, "160":20} }

// op: "step"
{ "op": "step", "levels": {"5":100, "3":60, "0":0} }

// op: "lookup"
{ "op": "lookup", "table": {"up":100, "flat":50, "down":0} }

// op: "weighted_sum"
{ "op": "weighted_sum", "weights": ["0.4","0.4","0.2"] }

// op: "clamp"
{ "op": "clamp", "min": 0, "max": 100 }

// op: "quantize"
{ "op": "quantize", "dp": 4, "rounding": "ROUND_HALF_EVEN" }

// op: "max_with_retest_bonus"  (Stage 3 PA aggregation)
{ "op": "max_with_retest_bonus", "bonus": 20, "cap": 100 }
```

> 任何 op 之 schema 進入 `schema/canonical_schema.json` 的 `$defs.NormalizationStep` enum。

---

## 3. 樹結構 (Tree Layout)

```
composite                                                    ScoreNode
├── chip_score              [weight 0.40]                     ScoreNode
│   ├── fii_sub             [weight 0.50]                     ScoreNode
│   │   ├── sync_score      [weight 0.40]                     LeafScoreNode
│   │   ├── ratio_score     [weight 0.40]                     LeafScoreNode
│   │   └── trend_score     [weight 0.20]                     LeafScoreNode
│   └── mainforce_sub       [weight 0.50]                     ScoreNode
│       ├── days_score          [weight 0.30]                 LeafScoreNode
│       ├── lock_score          [weight 0.30]                 LeafScoreNode
│       ├── streak_score        [weight 0.20]                 LeafScoreNode
│       └── concentration_score [weight 0.20]                 LeafScoreNode
│
├── behavior_score          [weight 0.35]                     ScoreNode
│   ├── concentration_sub   [weight 0.50]                     ScoreNode
│   │   ├── shareholders_score [weight 0.30]                  LeafScoreNode
│   │   ├── diff_score         [weight 0.20]                  LeafScoreNode
│   │   ├── L400_score         [weight 0.25]                  LeafScoreNode
│   │   └── L1000_score        [weight 0.25]                  LeafScoreNode
│   └── margin_sub          [weight 0.50]                     ScoreNode
│       ├── maintenance_score  [weight 0.50]                  LeafScoreNode
│       ├── wash_score         [weight 0.30]                  LeafScoreNode
│       └── penalty_score      [weight 0.20]                  LeafScoreNode
│
└── structure_score         [weight 0.25]                     ScoreNode
    ├── price_action_score  [weight 0.60]                     LeafScoreNode
    └── trend_2h_score      [weight 0.40]                     LeafScoreNode
```

**樹高 = 3 層 (composite → factor → sub → leaf)；葉節點共 16 個。**

> 注意：`chip_score / behavior_score / structure_score` 為 P2 命名 alias，**對映** 至原 v1 的 `stage_1 / stage_2 / stage_3`。Schema 同時保留兩組欄位以兼容。

---

## 4. 不變式 (Tree Invariants)

CI 必須驗證以下任一被破壞 → build fail：

1. **加總一致**：每個 ScoreNode 的 `value` 必須等於用 `normalization` 套用 `inputs.*.value` 後的結果（誤差 < 1e-4）。
2. **路徑唯一**：所有節點的 `path` 在樹內唯一。
3. **value 為字串**：所有 `value` 為 4 dp 字串，不可為 float。
4. **abstain 傳播**：若某 LeafScoreNode 為 abstained，父 ScoreNode 必須在 `abstain_propagation` 紀錄如何處理（重新分配權重 / 整節點 abstain / 視為 0）。**v1.1 規約：weight redistribution within siblings**。
5. **config_refs 完備**：每個節點至少一個 config_ref（葉節點直接引用 linear_range/curve/levels；內部節點引用 sub_weights）。
6. **config_values_at_eval 與 config_refs 對得起來**：`set(config_values_at_eval.keys()) == set(config_refs)`。
7. **與 SCORING_RUBRIC.md v1.1 完全一致**：composite 值必須等於 `stocks[*].composite_score`。

---

## 5. Decimal Policy (重申)

對應 SCORING_RUBRIC.md §0.3。Score Tree 必須遵守：

- 所有 `value` 字串型 Decimal，內部精度 ≥ 28 位
- 寫入 snapshot 時 quantize 至 4 dp (`Decimal("0.0001")`)
- `normalization` 鏈中的 `quantize` 步驟必須明示 `dp` 與 `rounding`
- 不允許 `NaN` / `Inf`；缺資料 → `abstained=true` + `value="0.0000"`（記帳值，不參與加權）

---

## 6. Abstain Propagation 規約

當某 leaf `abstained = true`：

```
parent.inputs = { x: ScoreNode, y: ScoreNode (abstained), z: ScoreNode }
parent.config = { weights: {x: 0.4, y: 0.3, z: 0.3} }
```

**v1.1 規約 (re-normalize active weights)**：

```
active_inputs = [x, z]                    # y abstained 移除
active_weights_sum = 0.4 + 0.3 = 0.7
parent.value = (0.4/0.7) * x.value + (0.3/0.7) * z.value
parent.normalization += [
  { "op": "weight_redistribute", "abstained": ["y"], "active_sum": "0.7" }
]
parent.abstain_propagation = "redistribute_within_siblings"
```

若**全部子節點 abstained** → parent 也 abstain，繼續往上傳。

> 替代規約 "treat_as_zero" 在 audit 上更乾淨但會壓低分數，**v1.1 不採用**。改為 redistribute 以保持分數尺度公平。

---

## 7. Provenance 連結 (Cross-reference to provenance)

Leaf 的 `provenance` 必須引用 snapshot 頂層的 `provenance` 結構：

```jsonc
"provenance": {
  "fii_sync_count": {
    "source_id": "vendor_broker_chip",          // 必須 ∈ provenance.sources keys
    "derived":   true,                          // 是 derived 或直接 fetched
    "derivation_step": "core.derivations.fii_sync_count"
  }
}
```

CI 驗證：
- 每個 leaf 的每個 raw_input → 必須能在 `provenance.field_to_source` **或** `provenance.derived_fields` 中找到對應
- 若 `derived=true` → 必須在 `provenance.derived_fields` 找到 `derivation_step`

---

## 8. 體積估算 (Volume Estimate)

| 項目 | 大小 |
|---|---|
| 一檔的 score_tree | ~6 KB (16 leaves + 7 internal nodes, JSON minified) |
| 1800 檔 × 6 KB | ~11 MB / 日 |
| 壓縮後 (gzip ~10x) | ~1.1 MB / 日 |
| 一年 (252 日) | ~280 MB / 年 |

**對策**：
- snapshot 主檔包含 score_tree（不可省略，否則違反「可單獨重算」）
- 若 ranked NEUTRAL 且 composite < 30 → score_tree 可只存 leaves + 公式，省去 normalization 細節（待 P3 決定）
- 整年資料可冷儲（S3 IA / 本地壓縮歸檔）

---

## 9. Snapshot 結構升級 (Schema 1.3.0)

`StockRecord` 新增可選欄位（向後相容）：

```jsonc
{
  "ticker": "3481",
  /* ... existing v1.2 fields ... */

  "score_tree": {                       // NEW in 1.3.0
    "root_path": "composite",
    "root":      { /* ScoreNode for composite */ }
  }
}
```

舊的 `stage_1_breakdown / stage_2_breakdown / stage_3_breakdown` **保留** 作為向後相容的「簡化視圖」；新工具應讀 `score_tree`。

---

## 10. Replay 安全性 (Replay Safety)

對應 REPLAY.md：

- `value` 為字串 → JSON 序列化不會有 float drift
- `config_values_at_eval` 內嵌 → replay 不依賴外部 config 檔
- `normalization` 是 op-list，每個 op 都是純函式 → 同輸入產同輸出
- canonical hashing (sort_keys + NFC + UTF-8) 涵蓋整棵樹

**CI 必跑**：把 `score_tree` 從零重新計算（從 raw_inputs + config_values_at_eval + normalization 鏈），確認 `value` 完全相同。

---

## 11. AI 可讀性 (AI Readability)

對應 AI_GOVERNANCE.md：

AI 可以**讀**整棵 score_tree（用於敘事），但**禁止**：
- 修改任何節點的 `value`
- 重排 `inputs` 順序（會影響 canonical hash）
- 新增/刪除節點
- 引用 `score_tree` 結構外的「虛擬節點」

AI 應該說：
> 「3481 在 `composite.chip_score.fii_sub.sync_score` 為 0.0000，因為 `fii_sync_count = 3` 卡在 `linear_range [3, 6]` 下界（見 SCORING_RUBRIC.md §0.5 Gate-then-Score）」

不應該說：
> 「3481 應該加 X 分，因為它有 momentum」

---

## 12. 相關文件

- [SCORING_RUBRIC.md](SCORING_RUBRIC.md) §0.3 §0.5 — Decimal Policy 與 Gate-then-Score
- [CANONICAL_SCHEMA.md](CANONICAL_SCHEMA.md) — 完整 schema 說明
- [REPLAY.md](REPLAY.md) — 重現性規約
- [AUDIT_LOG_EVENTS.md](AUDIT_LOG_EVENTS.md) — `SUBFACTOR_COMPUTED` 等 P2 事件
- [CORRELATION_REPORT.md](CORRELATION_REPORT.md) — 哪些 leaves 之間高度相關（觀察用，不修改規則）
- [FEATURE_FLAGS.md](FEATURE_FLAGS.md) — 如 day-trader exclusion 的旁路 flag

---

## 13. Temporal Extension (新增 by T-pivot)

> 對應 TEMPORAL_ARCHITECTURE.md §9。本節擴充 ScoreNode 結構以支援時序維度，但**本階段不啟用任何 node 的 temporal block**——只預留 slot 以避免未來 retrofit。

### 13.1 何時 ScoreNode 需要 `temporal`

當某節點的「軌跡形狀」本身可能成為訊號時：
- composite 的 5 日加速度
- chip_score 的衰退率
- pa_signals_30m 的命中頻率

> 本文件**不主張**這些就是 alpha。只是說「如果未來想用，結構是這個」。

### 13.2 ScoreNode.temporal 結構

```jsonc
{
  "path": "composite",
  "value": "63.4766",
  /* ... existing fields ... */

  "temporal": {
    "lookback_window_days":   5,
    "values_series":          ["72.11","70.20","68.10","65.00","63.48"],
    "series_dates":           ["2026-05-16","2026-05-19","2026-05-20","2026-05-21","2026-05-22"],
                                                       // 已排除非交易日
    "velocity":               "-2.1575",                // (today - T-1)
    "acceleration":           "-0.4750",                // 二階差分平均
    "ema_3":                  "65.66",
    "ema_5":                  "67.78",
    "lookback_snapshot_hashes": {
      "2026-05-21": "sha256:...",
      "2026-05-20": "sha256:..."
    },
    "abstained":     false,
    "abstain_reason": null
  }
}
```

### 13.3 計算規約

- 全部走 §5 Decimal Policy（4 dp）
- 不足 `lookback_window_days` → `abstained=true`，`reason="insufficient_lookback (have=3 need=5)"`
- `velocity = quantize(values_series[-1] - values_series[-2], 4dp, HALF_EVEN)`
- `acceleration = quantize(mean(second_diff(values_series)), 4dp, HALF_EVEN)`
- EMA 計算式必須完整定義（避免 EMA 初值約定差異破壞 replay）：
  - `ema_n[0] = values_series[0]`
  - `ema_n[i] = α * values_series[i] + (1-α) * ema_n[i-1]`, `α = 2/(n+1)`
  - 全程 Decimal；最終 quantize 4 dp

### 13.4 Provenance 與 lookback_snapshot_hashes

`temporal.lookback_snapshot_hashes` 必須 **subset of** snapshot 頂層的 `environment.lookback_snapshots`。
CI 驗證：每個 temporal block 的所有 hash 都已在 environment 內登記過。

對應 `provenance.derived_fields` 條目：

```jsonc
"composite.temporal.velocity": {
  "derived_from": ["composite_score@T-1", "composite_score@T-0"],
  "formula":      "today - yesterday",
  "step":         "core.temporal.score_velocity",
  "temporal":     true,
  "lookback":     { "T-1": "sha256:..." }
}
```

### 13.5 何時某 node 該啟用 temporal block

| 條件 | 是否啟用 |
|---|---|
| node 是 composite (root) | 建議啟用 (highest level) |
| node 是 factor (chip/behavior/structure) | 可選 |
| node 是 sub-factor | 通常**不啟用**（太細，雜訊大） |
| node 是 leaf | **禁止啟用**（leaves 已有自己的 raw_inputs；temporal 應該疊在 normalized score 之上） |

config 規約：

```yaml
score_tree:
  temporal_enabled_paths: []        # default empty; P4 backtest 決定加哪些
```

### 13.6 與 StockRecord.temporal_state 的關係

| 結構 | 範圍 | 何時讀 |
|---|---|---|
| `StockRecord.temporal_state` | 整檔層級 (tier history, episode ids) | UI / AI 解讀 / 排名邏輯 |
| `ScoreNode.temporal` | 單一節點 (composite velocity) | backtest 用 / 因子診斷 |

兩者不重疊：`temporal_state.score_velocity` ⊆ `score_tree.root.temporal.velocity`（若啟用），且必須一致。CI 驗證一致性。

### 13.7 Replay 含義

對應 REPLAY.md §17：

- 每個帶 `temporal` 的 node 引入 lookback dependency
- canonical hash 涵蓋整個 `temporal` 區塊
- replay 時必須重現 EMA、velocity、acceleration 至 4 dp

### 13.8 抽象寫法 — 未來 P4 落地時的擴充槽位

ScoreNode 已預留以下 slot 給更複雜的 temporal 運算：

- 滑動視窗統計 (mean, stdev, max, min over N days)
- 趨勢分類 (regression slope sign + significance)
- Regime-conditional scoring (score 在不同 market_regime 下調整)
- Cross-factor lag (composite[T] vs FII@T-3)

**所有這些都不在本階段啟用**。Schema 與計算管線已 ready。
