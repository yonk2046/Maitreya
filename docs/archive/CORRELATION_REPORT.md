# SCD Engine — Factor Correlation Observability Report

> Version: v1.0 (2026-05-22) — P2 phase
> 對應 AUDIT_v1.0.md §2.2 (訊號重疊與相關性)
> **本文件是 observability framework，不變動任何因子或權重**。實際相關性數值需要回填資料後才能計算；本文件提供假設清單與分析方法。

---

## 0. 為什麼需要這份報告

如果兩個子因子的 Pearson r > 0.7，相當於把同一份訊號重複加權，**實質權重 ≈ nominal × (1 + r)**。
但我們現在沒有歷史資料；移除任何因子都是基於直覺，違反「P4 才決定因子有用」的約束。
所以本階段只做：**列出假設、提供分析腳本、產出觀察報告**；不做移除。

---

## 1. 已假設高相關的因子對 (Hypothesized High-Correlation Pairs)

來源：AUDIT_v1.0.md §2.2 觀察 + 公開文獻常識。

| # | Factor A | Factor B | 預期 r | 機制假設 (Mechanism Hypothesis) | 目前處理 |
|---|---|---|---|---|---|
| C1 | `large_holder_400_pct` | `large_holder_1000_pct` | **0.85 ~ 0.95** | 集合包含：1000-lot 持股是 400-lot 的子集；若大戶增持，兩者必同向 | **保留兩者**，加入 observability |
| C2 | `fii_holding_trend_5d` | `fii_consecutive_buy_days` | 0.6 ~ 0.8 | 連買 N 日勢必造成持股趨勢上升 | 保留 |
| C3 | `main_force_consecutive_days` | `volume_increasing_streak` | 0.5 ~ 0.7 | 都從同一條買超時序提取的形狀特徵 | 保留 |
| C4 | `main_force_buy` (絕對量) | `top5_concentration` (相對佔比) | 0.4 ~ 0.7 | 強鎖碼股通常兩者都高，但流動性低股的絕對量小、相對佔比卻可能高 | 保留 |
| C5 | `fii_buy_ratio` | `volume_ratio` | 0.3 ~ 0.5 | 大買進日通常量也放大 | 保留 |
| C6 | `margin_maintenance_ratio` | `margin_change` | -0.4 ~ -0.6 | 維持率高（無壓力）日，融資傾向增加；負相關 | 保留 |
| C7 | `pa_signals_30m` "engulfing" | `trend_2h` "up" | 0.3 ~ 0.5 | 漲勢中 30 分線易出現吞噬陽 | 保留 |
| C8 | `broker_count_diff_negative_streak` | `shareholder_count_delta_pct` (越負) | 0.4 ~ 0.6 | 籌碼集中時兩者方向一致 | 保留 |

**所有對先保留**；P4 backtest 時再決定哪些有資訊重複問題。

---

## 2. 分析方法 (Methodology)

### 2.1 資料準備
- 取 **N ≥ 60 個歷史 snapshot**（約 3 個月交易日）
- 將每檔每日的 raw_inputs 拍平 (one row per ticker-day)
- 缺資料的列棄置（不可用 0 填補，會稀釋相關性）

### 2.2 計算
- **Pearson r**: 線性相關，最直觀
- **Spearman ρ**: 對 outlier 與非線性穩健
- **Mutual Information**: 偵測非線性依賴
- 報表呈現三者 + p-value

### 2.3 視覺化
- 17 × 17 相關矩陣 (leaves) 熱力圖
- 階層式聚類 (hierarchical clustering) 揭示自然分群
- 對於 |r| > 0.7 的對給紅框，|r| > 0.5 給黃框

### 2.4 解讀規約
- |r| > 0.7：**疑似冗餘**，需 P4 backtest 確認移除一者後 IC 是否下降
- 0.5 < |r| ≤ 0.7：**中度重複**，可考慮正交化 (Gram-Schmidt) 但保留兩者
- |r| ≤ 0.5：視為獨立

> **重要**：高相關 ≠ 該砍。若兩者對 forward return 都有獨立解釋力，保留是對的。決策必須由 P4 backtest 提供 IC 證據。

---

## 3. 分析腳本 (Tools)

見 [tools/correlation_analyzer.py](../tools/correlation_analyzer.py)。

執行方式（資料就緒後）：
```bash
python -m tools.correlation_analyzer \
    --snapshots reports/*.json \
    --leaves chip.fii.sync_score,chip.fii.ratio_score,... \
    --output reports/correlation_2026-Q2.html
```

輸出：
- `reports/correlation_<period>.html` — 互動式熱力圖
- `reports/correlation_<period>.json` — 機器可讀矩陣
- `reports/correlation_<period>.md` — 高 |r| 對清單與建議

---

## 4. 目前觀察 (Empirical Findings — placeholder)

> **本表為 placeholder。** 等真實資料回填後，由 `correlation_analyzer.py` 自動更新本節。

| Pair | Pearson r | Spearman ρ | n | 95% CI | 判定 |
|---|---|---|---|---|---|
| C1 large_holder_400_pct × large_holder_1000_pct | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| C2 fii_holding_trend_5d × fii_consecutive_buy_days | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| C3 main_force_consecutive_days × volume_increasing_streak | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| ... | | | | | |

---

## 5. 與 score_tree 的關係

當 P4 backtest 確認某對因子應該被處理：

| 處理方式 | 對 score_tree 的影響 |
|---|---|
| **保留兩者，加 normalization** | 父節點新增 `weight_redistribute` 步驟，但 leaves 不變 |
| **正交化** | 新增一個 derived field（如 `L1000_residual = L1000 - β*L400`），原 leaf 換成 residual |
| **合併** | leaf 從 2 變 1，schema 升版；舊欄位保留向後相容 |
| **刪除一者** | leaf 從 2 變 1；schema 升版 |

**所有變更必須先過 IC 驗證**（P4 walk-forward）。不可僅憑相關性高就動。

---

## 6. 觀察事項清單 (Watch List)

不立即動手，但持續觀察：

1. **`fii_holding_trend_5d`** 是 5 日斜率，可能與 `fii_consecutive_buy_days` 高度重疊；P4 應比較兩者單獨的 IC。
2. **`large_holder_400_pct`** 包含 `large_holder_1000_pct`；考慮改用 `mid_holder_400_to_1000_pct = 400_pct - 1000_pct` 製造正交特徵。
3. **`top5_concentration`** 對短線分點敏感；day-trader exclusion flag（見 FEATURE_FLAGS.md）即為應對策略，但目前 OFF。
4. **Stage 3 `pa_signals_30m`** 與 `trend_2h` 都關注短期動能；P4 應確認是否 redundant。

---

## 7. 致 P4 的訊息

P4 backtest 開始時，本文件提供：
- 假設清單（§1）作為 hypothesis space
- 計算腳本（§3）作為工具
- 判定規約（§2.4）作為決策框架

**P2 不做任何因子變動**，P4 開展時再回頭看本文件，決定哪些假設成立、哪些該動手。

---

## 8. 相關文件

- [AUDIT_v1.0.md](AUDIT_v1.0.md) §2.2 — 訊號重疊原始觀察
- [SCORE_NODE.md](SCORE_NODE.md) — 因子結構（如何加 normalization 步驟）
- [SCORING_RUBRIC.md](SCORING_RUBRIC.md) — 各因子定義與權重
- tools/correlation_analyzer.py — 分析腳本
