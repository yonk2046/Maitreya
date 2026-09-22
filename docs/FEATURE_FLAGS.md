# SCD Engine — Feature Flags 治理規約

> Version: v1.0 (2026-05-22) — P2 phase
> 對應 SCORING_RUBRIC.md v1.1（規則不變）+ REPLAY.md（replay 必匹配）

---

## 0. 為何需要 Feature Flags

某些「想試但還沒驗證」的行為（如 day-trader exclusion）需要：
1. 旁路存在，不立刻啟用 → **預設 OFF**
2. 一旦啟用，行為差異可稽核 → **每次 resolve 都 emit `FEATURE_FLAG_RESOLVED`**
3. 啟用後的結果可重現 → **flag 值進入 `config_hash`**
4. 不可偷偷改變既有 snapshot 的分數 → **任何 flag 設定改變必須觸發新 snapshot**

---

## 1. 規約 (Binding Rules)

| # | 規則 |
|---|---|
| F1 | 所有 feature flag 集中於 `config/scd.yaml` 的 `feature_flags:` 區段 |
| F2 | Flag 預設值 **必須為 OFF**（false / 空清單），新行為要明示開啟 |
| F3 | Flag 值參與 `config_hash` 計算（同 N8）；改 flag = 新 config_hash = 新 snapshot |
| F4 | Core 讀取 flag 時必 emit `FEATURE_FLAG_RESOLVED` 事件，含 `{flag, value, default, took_effect_at, downstream_paths}` |
| F5 | Flag 不可在執行期改變（runtime mutation forbidden）。改值需重啟 pipeline |
| F6 | 每個 flag 必須有對應的 `docs/FEATURE_FLAGS.md` 條目，含：用途、影響的 score_tree paths、replay 含義 |
| F7 | Flag 移除（轉正或廢棄）需 schema 升版且保留向後相容讀取舊 snapshot |

---

## 2. 既有 Feature Flags

### 2.2 `engine_correction_v1`(2026-09-22 新增;**第一個實際生效的旗標**)

| 欄位 | 值 |
|---|---|
| 預設 | `false`(上線:2026-10-02 收盤後改 `true`,10/5 起生效) |
| 依據 | `docs/migration/AUDIT-golden-list-20260922.md` G1/G3/G9;執行正本 `EXEC-PLAN-engine-correction-20260922.md` |
| 讀取點 | `core/ingest.py`(唯一讀取者;以參數 `correction` 傳入 `temporal_enrich`/`weakening_profile`/`obs_landing`→`state_machine.run_all`/`golden.run`/`funnel.run`,引擎預設 False) |
| 影響欄位 | `stocks[].weakening`、`velocity_3d`、`acceleration`、`fii_consecutive_buy_days`、`obs_sm_*`、`obs_golden_*`、`obs_chip_grade`、`obs_market_temperature`(讀當日 obs_sm);sidecar `reports/strategy_tags/<date>.json`(讀該快照記錄的旗標) |
| 行為 | ① 缺席不透明:掉出主力榜的日子以主力買超 0 計,中斷連買/速度(G3)。但**缺席不觸發當日定案的「連買崩塌→FAILED」**(1 日缺席多為輪動,交給 W3/EXITED);外資連買改嚴格計算,缺席日視為中斷(缺席日外資實為未知,**刻意保守**);② 快照轉弱用「前序 + 當天」判斷(G1,W3 不再亮在回榜日);③ 狀態機 CONFIRMED 廣度閘讀全市場 `market_pulse`,缺值不放行(G9) |
| Replay 含義 | 旗標存在 yaml → 進 `config_snapshot.yaml` 與 `config_hash`;replay 用快照**記錄的** yaml,旗標出現前的快照自動走舊邏輯。**不可改用 engine_params 當開關**(`as_config_dict()` 會把新鍵帶進所有舊快照的 replay) |
| 稽核 | 每次 ingest emit `FEATURE_FLAG_RESOLVED`(F4) |
| 守門員 | `tests/test_engine_correction_v1.py` |

### 2.1 `day_trader_exclusion`

| 欄位 | 值 |
|---|---|
| 預設 | `false` |
| 引入版本 | v1.3.0 (P2) |
| 影響 score_tree paths | `composite.chip_score.mainforce_sub.concentration_score` |
| 影響欄位 | `top5_branches` (filtering)、`top5_concentration` (recomputation) |
| Replay 含義 | 同份 snapshot 必用同一個 flag 設定才能重現 |

**配置位置**：

```yaml
feature_flags:
  day_trader_exclusion: false        # default OFF
  day_trader_exclusion_branches:     # 已知日沖大本營（待擴充）
    - "凱基-台北"
    - "元大-總公司"
    - "永豐金-台北"
```

**啟用行為**（當 `day_trader_exclusion: true`）：

1. `top5_branches` 計算前先過濾掉 `branch ∈ day_trader_exclusion_branches`
2. `top5_concentration` 重新以**過濾後**的 top5 計算
3. emit `FACTOR_LINEAGE` 事件，data 含：
   ```json
   {
     "branches_excluded": ["凱基-台北"],
     "original_top5_concentration": "0.7000",
     "filtered_top5_concentration": "0.6200"
   }
   ```
4. score_tree 的 `concentration_score` leaf 在 `normalization` 鏈中**新增一步**：
   ```json
   { "op": "filter_branches", "excluded": ["凱基-台北"] }
   ```

**未啟用行為**（預設）：
- 行為與 v1.1 完全相同
- 仍 emit `FEATURE_FLAG_RESOLVED { flag: "day_trader_exclusion", value: false }` 紀錄此次 resolve

---

## 3. Flag Resolution Flow

```
┌──────────────────────────────────────────────────────────────┐
│ core.startup                                                  │
│   1. Load config/scd.yaml                                     │
│   2. Compute config_hash (includes feature_flags)             │
│   3. For each flag in feature_flags:                          │
│        emit FEATURE_FLAG_RESOLVED                             │
│        register downstream_paths for later auditing           │
└────────────────────┬─────────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ scoring.<path> evaluation                                     │
│   if path ∈ flag.downstream_paths:                            │
│     consult flag value, branch behavior                       │
│     emit FACTOR_LINEAGE with flag-attributed delta            │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Replay 含義

對應 REPLAY.md：

- snapshot 的 `config_snapshot.feature_flags` 必須完整內嵌
- Replay 時用同份 `config_snapshot.feature_flags` → 同份 `config_hash` → 同份結果
- 若 runtime 強制改 flag → emit `CONFIG_HASH_MISMATCH`，replay 視為失敗

---

## 5. 新增 Flag 的程序

加入新 flag 時必跑以下檢查清單：

- [ ] 在 `config/scd.example.yaml` 的 `feature_flags:` 加 key + 預設 `false`/`[]`
- [ ] 在 `docs/FEATURE_FLAGS.md` §2.x 新增條目，說明影響 paths
- [ ] 在 `docs/AUDIT_LOG_EVENTS.md` 確認 `FEATURE_FLAG_RESOLVED` 已涵蓋
- [ ] 在 `schema/canonical_schema.json` 的 `config_snapshot` 區段補 `feature_flags` 子結構（可選）
- [ ] 在 `core` 對應 path 加 `if flag: ...` 旁路，不可改變 default 行為
- [ ] 加單元測試：flag OFF 時行為與舊版 byte-identical；flag ON 時行為可重現

---

## 6. 反規約 (Anti-patterns to avoid)

- ❌ 把 flag 預設改為 ON 而不升 schema_version
- ❌ 在 prompt 或 UI 端讀 flag（業務邏輯必在 `/core`）
- ❌ 「臨時」實驗用環境變數做開關（必須走 config）
- ❌ 用 flag 來修補 bug；bug 該改 core，不該被「flag 包裝」

---

## 7. 相關文件

- [SCORING_RUBRIC.md](SCORING_RUBRIC.md) §0.5 Gate-then-Score
- [SCORE_NODE.md](SCORE_NODE.md) §2.4 NormalizationStep（含 `filter_branches` op）
- [REPLAY.md](REPLAY.md) §3 Snapshot Integrity
- [AUDIT_LOG_EVENTS.md](AUDIT_LOG_EVENTS.md) `FEATURE_FLAG_RESOLVED` 規格
