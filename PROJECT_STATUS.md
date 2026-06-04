# PROJECT_STATUS.md
# SCD Engine / Maitreya — 完整專案移交文件

> **最後更新：2026-06-04**
> 本文件假設下一個 Claude 完全不知道此專案。請從頭讀到尾再開始任何工作。

---

## 0. 專案一句話

**Maitreya（彌勒）** 是一個台灣股市「時序智慧終端」——每個交易日自動抓取主力分點＋外資＋投信資料，計算籌碼動能，並以可重現（deterministic replay）的方式存入不可篡改的歷史快照，供波段交易決策參考。

**核心哲學：** 可信賴的歷史記錄 > 即時訊號。先把 archive 做到 provenance 無懈可擊，再做 scoring。

---

## 1. 目前系統架構

### 1.1 目錄結構

```
/Users/yoncky/SCD engine/
├── tools/
│   └── fetch_daily.py          上游抓取（TWSE / Sinotrade / T86 三大法人）
│                                Step 1-9，輸出 data/today.json + data/branches/<ticker>.json
│
└── Ai stock/                   ← 主 repo (git: yonk2046/Maitreya)
    ├── core/
    │   ├── hashing.py          canonical hash 計算（generated_at 排除）
    │   ├── ingest.py           snapshot 寫入 + audit_log
    │   ├── archive.py          raw 資料歸檔到 _raw_archive/
    │   ├── worm_check.py       WORM 自查（raw archive 不可篡改驗證）
    │   ├── watchlists.py       Tier A 8支永久追蹤 + SECTOR_GROUPS
    │   ├── market_context.py   5個純觀察函數（accumulation_velocity、
    │   │                       sponsorship_persistence、regime_shift、
    │   │                       failed_breakout_memory、leadership_rotation）
    │   ├── funnel.py           候選漏斗引擎（5層：DISCOVERY→FAILURE）
    │   ├── state_machine.py    時序狀態機（9態：UNDISCOVERED→EXITED）
    │   ├── golden.py           黃金名單 v2（5道 Gate + 三層 PRIME/STRONG/QUALIFIED）
    │   ├── chip_score.py       籌碼動能評分（40分制：投量比/連買/集中/法人/成本）
    │   ├── resonance.py        法人共振引擎（主力+外資+投信同向偵測）
    │   ├── confidence.py       信心度與風險側寫（2D：confidence × risk）
    │   ├── intelligence_delta.py  日報 delta 計算（輸出 .intelligence.json）
    │   ├── market_state.py     市場狀態統一引擎（MarketState 彙整）
    │   ├── narrative_engine.py 純翻譯層（時序輸出 → 中文敘述）
    │   └── sector_intelligence.py  板塊智慧（sector_summary / sector_strength）
    │
    ├── data/
    │   ├── adapters/
    │   │   ├── legacy.py       歷史快照轉換（含 paths_override + env override）
    │   │   ├── rollup.py       滾動快照
    │   │   └── contract.py     adapter 契約（凍結介面）
    │   ├── branches/<ticker>.json   Sinotrade 分點資料（每日更新，≤30支）
    │   ├── snapshots/          原始快照 rollup
    │   ├── market_pulse.json   大盤脈搏（TAIEX/台指期/三大法人，每日更新）
    │   └── checklist_history.json   SCD 每日檢核清單歷史
    │
    ├── reports/
    │   ├── YYYY-MM-DD.json         每日 canonical snapshot（WORM-protected）
    │   ├── YYYY-MM-DD.json.sha256  SHA-256 sidecar
    │   ├── YYYY-MM-DD.intelligence.json  日報 delta（智慧摘要）
    │   ├── index.json              全部快照索引（含 supersedes 鏈）
    │   ├── _raw_archive/<date>/    每日 raw 輸入（不可篡改，replay 從這裡讀）
    │   └── _daily_logs/<date>.log  每日管道執行 log
    │
    ├── tools/
    │   ├── daily.py            每日自動流水線 orchestrator
    │   ├── run_pipeline.py     手動執行 pipeline
    │   ├── verify_all_replay.py  全量重放驗證
    │   └── temporal/
    │       ├── _loader.py
    │       ├── temporal_metrics.py    純指標函數（velocity/acceleration/streak 等）
    │       ├── streak_analyzer.py
    │       ├── transition_detector.py
    │       ├── persistence_ranker.py
    │       ├── regime_monitor.py
    │       └── market_flow_monitor.py  CLI 市場流動監控
    │
    ├── viewer/
    │   ├── cockpit.py          ★ 主終端（P4，143KB，8502 port）
    │   ├── cockpit_v2.py       舊版（P3c/P3d，8503 port，保留未刪）
    │   ├── app.py              工程診斷界面（8501 port）
    │   ├── data.py             緩存數據讀取（mtime-keyed）
    │   ├── intelligence.py     舊版計算層（P3c 之前，仍存在）
    │   └── metrics.py          觀測指標
    │
    ├── tests/
    │   ├── test_replay.py          replay 驗證
    │   ├── test_worm.py            WORM 自查
    │   ├── test_adapter_contract.py
    │   ├── test_contracts.py
    │   ├── test_temporal_toolkit.py
    │   ├── test_viewer_data.py
    │   └── test_daily.py
    │
    ├── schema/canonical_schema.json
    ├── config/scd.example.yaml
    ├── Makefile                    ← 所有日常操作入口
    ├── deploy/
    │   ├── com.scd.daily.plist.template  macOS launchd 排程
    │   └── install_launchd.sh
    └── .github/workflows/daily.yml      GitHub Actions 每日流水線
```

### 1.2 資料流

```
fetch_daily.py (SCD engine/)
    └─→ data/today.json + data/branches/<ticker>.json
            ↓
        core/ingest.py
            ↓
        reports/YYYY-MM-DD.json + .sha256
        reports/_raw_archive/<date>/
            ↓
        verify_all_replay.py  (11/11 dates replay-clean)
            ↓
        core/intelligence_delta.py
            ↓
        reports/YYYY-MM-DD.intelligence.json
            ↓
        viewer/cockpit.py (Streamlit, read-only)
```

### 1.3 部署

- **本機：** macOS launchd，每日 19:00 觸發（Fubon ZGK 最終結算約 18:00-18:30）
- **雲端：** GitHub Actions（`.github/workflows/daily.yml`）+ Streamlit Cloud
- **Repo：** `github.com/yonk2046/Maitreya`
- **Streamlit Cloud：** https://share.streamlit.io → Maitreya

### 1.4 路徑注意事項

`_project_root()` 在 `data/adapters/legacy.py` 期望父目錄同時含 `Ai stock` 和 `data` 子目錄（即 `/Users/yoncky/SCD engine/`）。

環境變數覆蓋：`$SCD_PROJECT_ROOT`（Cowork VM 或 CI 環境使用）。

---

## 2. 已完成 Phase

### ✅ P3a — Ingest-Only（2026-05-22）
- 所有 scoring 全部 abstained（tier="IGNORE"，composite_score=0）
- 快照寫入 `reports/<date>.json` + `.sha256`
- Audit log 事件體系（v1.4）

### ✅ P3a-Hardening（2026-05-26，H1–H15）
包含：path resolver + env override；supersedes chain repair；Makefile 入口；CONTRIBUTING.md；WORM 自查；schema validation；sidecar 驗證；index 完整性測試；adapter contract 凍結；raw-data 歸檔；cross-date lookback 連續性測試。

測試：37 tests / 4 files，全綠。`make verify-all-replay`：10/10 dates clean。

### ✅ P3a-Visibility — Streamlit Viewer（2026-05-26）
`viewer/app.py`（port 8501）：7個面板（Snapshot Timeline、Ticker History、Replay Integrity、Temporal Chain DAG、Observation-Only Metrics、Audit Explorer、Replay Status）。

### ✅ P3a-Observation — Temporal Toolkit（2026-05-26）
`tools/temporal/`：6個純函數模組（velocity/acceleration/persistence/transition/streak/regime）。67/67 tests 全綠，含 5 個 byte-identical fingerprint 測試。

### ✅ P3a-Scheduler — Daily Auto-Ingest（2026-05-26）
`tools/daily.py` + launchd plist + `deploy/install_launchd.sh`。

### ✅ DS6 — Replay-from-Archive Fix（2026-05-26）
關鍵修復：replay 改從 `reports/_raw_archive/<date>/` 讀（不可變），不再從會每日變動的 `data/snapshots/` 讀。normalize provenance.url + raw_file 為 canonical 路徑（不洩漏機器絕對路徑）。11/11 dates replay-clean。

### ✅ P3c — Market Context & Permanent Watchlist（2026-05-29）
- `core/watchlists.py`：Tier A 8支永久錨（2330/2454/2317/2382/2308/2881/2882/2891）+ SECTOR_GROUPS
- `core/market_context.py`：5個純觀察函數
- `tools/temporal/market_flow_monitor.py`：CLI 市場流動監控
- `viewer/cockpit.py` 重建為 7-tab Bloomberg+Notion 風格終端（Warm Slate 主題）
- fetch_daily.py Step 6：Tier A 永遠抓進 Sinotrade fetch
- launchd 排程 14:30 → 19:00

### ✅ P4 — Golden Layer v2 + 法人共振（2026-06-02/03）
新增核心計算模組群：
- `core/funnel.py`：5層候選漏斗
- `core/state_machine.py`：9態時序狀態機
- `core/golden.py`：5道 Gate + PRIME/STRONG/QUALIFIED 三層
- `core/chip_score.py`：40分制籌碼評分
- `core/resonance.py`：法人共振（主力+外資+投信同向）
- `core/confidence.py`：信心×風險 2D 側寫
- `core/intelligence_delta.py`：日報 delta 引擎
- `core/market_state.py`：市場狀態統一彙整
- `core/narrative_engine.py`：時序輸出 → 中文敘述
- T86 三大法人接線：`fii_net_buy`、`dealer_net_buy`（投信）、`fii_sync_count` 寫入快照
- Checklist 內嵌 + 共振徽章 UI
- `viewer/cockpit.py` P4 UX 重構：固定高度卡片、chip score 顯示、resonance badge、volume ratio
- TAIEX 改用 MI_INDEX 表格來源（修正）

---

## 3. 未完成 Phase

### 🔒 P3b — Scoring Layer（等待用戶簽核）
- **狀態：** 明確 gated，不得自行啟動
- **條件：** 需 ≥20 日歷史，用戶明確說「可以開始 P3b」
- **內容：** tier / composite_score 從 IGNORE → 真實值；cockpit 轉強/吸籌標籤顯示實際分數；`intelligence.py` 分類邏輯接真實 composite_score

### ⏳ Intelligence Delta 補跑
- 目前 reports/ 中 2026-06-01~06-03 無 `.intelligence.json`（P4 之後管道沒有補產生）
- 需手動 backfill：`python -m core.intelligence_delta --backfill`

### ⏳ 外資持股趨勢補齊
- `fii_holding_trend_5d` 在多數 snapshot 為 null（資料來源尚未完整接入）
- `fii_net_buy`、`dealer_net_buy` 在共振引擎中部分為 None（graceful degradation 已處理）

---

## 4. 重要設計決策

| # | 決策 | 理由 |
|---|------|------|
| D1 | **Replay first** — 一切以 deterministic replay 為最高優先 | 系統價值是可信賴的歷史記錄，非即時 alpha |
| D2 | **Raw archive WORM** — `_raw_archive/<date>/` 一旦寫入不可改 | 任何 replay 都從 immutable source 重建 |
| D3 | **generated_at 排除於 canonical hash** | 同日重跑不應改變 hash |
| D4 | **Scoring abstained（P3b gated）** — tier="IGNORE", composite_score=0 直到簽核 | 避免不成熟的 scoring 污染歷史記錄 |
| D5 | **UI 不含業務邏輯** — cockpit 只 render，所有 filter/sort 由 core 預算好 | 防止 UI 端偷改排序造成結果不一致（症狀③） |
| D6 | **所有門檻數字在 config** — 不寫死在 prompt 或 core | 防止不同對話偷改門檻（症狀②） |
| D7 | **AI 引用白名單** — CANONICAL_SCHEMA.md §7 的 ai_readable_subset | 防止 AI 幻想未計算的指標（症狀④） |
| D8 | **Tier A 永遠在 fetch** — 8支永久錨每日必抓 | 保持主力成本連續性，即使它不在當日 universe |
| D9 | **Adapter contract 凍結** — `data/adapters/contract.py` | 防止 adapter 介面蔓延 |
| D10 | **Feature flags 全在 config/scd.yaml** — 預設 OFF | 行為可稽核、可重現（F1-F7 規約） |
| D11 | **Cockpit 是 read-only** — 不寫入任何資料 | viewer 不能污染 archive |

---

## 5. 已知 Bug

| # | Bug | 影響 | 狀態 |
|---|-----|------|------|
| B1 | **Replay mismatch（GitHub Actions）** | daily.yml 中設為 `continue-on-error`，不影響資料寫入，橘色 warning 是正常的 | 已知，非阻塞 |
| B2 | **2026-06-01~06-03 無 .intelligence.json** | cockpit 的 intelligence panel 沒有最新 3 天的日報 delta | 待補跑（見§3） |
| B3 | **fii_net_buy / dealer_net_buy 多為 None** | 共振引擎 graceful degrade 到 level 1（單主力），不崩潰 | 資料來源問題，待接 |
| B4 | **merge conflict（git）** | 本機 launchd 和 GitHub Actions 都寫 reports/，偶發 merge conflict；日常用 `--rebase` 已緩解 | 已知 |
| B5 | **Big5 亂碼（部分股名）** | 2353 宏碁已修正；其他 Big5 stock 可能仍有問題 | 已部分修正 |

---

## 6. 已知技術債

| # | 技術債 | 優先級 |
|---|--------|--------|
| T1 | **`viewer/cockpit_v2.py` 殘留**（62KB，P3c/P3d 版本）與 `cockpit.py`（P4，143KB）並存，未清理 | 低 |
| T2 | **`viewer/intelligence.py` 舊版計算層**（P3c 前的版本）仍存在，P4 後部分邏輯重複 | 低 |
| T3 | **`viewer/app.py` 工程診斷界面**（30KB）與 cockpit 功能重疊，長期可能合并 | 低 |
| T4 | **`fii_holding_trend_5d` 欄位 null**，外資持股趨勢資料缺失 | 中 |
| T5 | **test suite 未覆蓋 P4 新模組**（golden.py、resonance.py、chip_score.py 等）— 目前 67 tests 為 P3a 前 | 中 |
| T6 | **intelligence_delta backfill 未自動化**，需手動補跑 | 中 |
| T7 | **`data/checklist_history.json` 與 SCD 系統指令的整合**未完整文件化 | 低 |

---

## 7. 下一步 Roadmap

### 立即可做（不需用戶簽核）

1. **補跑 intelligence delta** — `python -m core.intelligence_delta --backfill --force`
2. **P4 test coverage** — 為 golden.py / chip_score.py / resonance.py / confidence.py 補測試
3. **清理殘留** — 移除或封存 cockpit_v2.py / intelligence.py 舊版邏輯

### 需要用戶明確開門

4. **P3b Scoring 啟動** — tier / composite_score 真實化。前提：用戶說 OK + ≥20 日歷史（目前已有 ~18 個交易日）
5. **外資持股趨勢接入** — fii_holding_trend_5d 資料來源（集保、外資揭露）

### 中期

6. **Cockpit P5** — 待 P3b 啟動後，PRIME/STRONG/QUALIFIED 分層在 cockpit 有意義
7. **SCD Checklist 與系統整合** — 每日 SCD 三階段過濾清單與 cockpit 互動

---

## 8. Golden Layer 最新設計方向（P4）

### 核心概念

Golden Layer 是「觀察漏斗的頂端」，不是交易訊號。目的是找出「主力正在持續吸籌且結構穩固」的標的。

### 五道 Gate（全部通過才入 Golden）

| Gate | 條件 |
|------|------|
| G1 | Funnel Layer = "confirmation"（streak ≥ 2，板塊相對強，無假突破） |
| G2 | State Machine ∈ {confirmed, strengthening} |
| G3 | Sponsorship score ≥ 0.45 |
| G4 | Transition risk ≠ "critical" |
| G5 | Net cumulative > 0 |

### Conviction Score（0.0–1.0）

```
+0.25  streak ≥ 5
+0.15  streak ≥ 3  （與上累加）
+0.20  sponsorship ≥ 0.70
+0.10  sponsorship ≥ 0.55  （與上累加）
+0.15  state == confirmed
+0.10  Tier A 標的
+0.10  velocity_3d > 0
+0.05  acceleration > 0
+0.05  sector 在今日 top-3
```

### 三層輸出

- **PRIME** （conviction ≥ 0.65）— 高確信
- **STRONG**（conviction ≥ 0.40）— 結構穩固
- **QUALIFIED**（conviction ≥ 0.0）— 通過門檻，確信度較低

### Chip Score（40分制）

| 項目 | 滿分 | 計算 |
|------|------|------|
| 投量比 | 8 | main_force_buy / market_volume（>12%→8，6-12%→4） |
| 連續買超 | 10 | streak（≥7→10，5-6→8，3-4→6，1-2→3） |
| 籌碼集中度 | 8 | top5 concentration（資料待補） |
| 法人同向 | 8 | 3機構中幾個 net positive |
| 成本支撐 | 6 | 現價 vs 主力均價 |

等級：32+ 強（金）/ 24+ 中（藍）/ <24 弱（灰）

### Resonance Engine（共振）

觀察主力、外資、投信是否同向：
- Level 0：無共振
- Level 1：單方買盤（目前多數因 fii/投信資料待補）
- Level 2：雙方共振 ★
- Level 3：三方共振 ★★

---

## 9. 重要資料來源

| 來源 | 資料 | 更新時間 | 入口 |
|------|------|---------|------|
| **TWSE（twse.com.tw）** | 個股日成交、TAIEX（MI_INDEX 表格） | 每日收盤後 | `fetch_daily.py` Step 1-3 |
| **Sinotrade 永豐金** | 主力分點買超（`data/branches/<ticker>.json`） | 每日 T+1 | `fetch_daily.py` Step 6 |
| **T86 三大法人揭露（TWSE）** | fii_net_buy（外資）、dealer_net_buy（投信）、fii_sync_count | 每日收盤後 | `fetch_daily.py`（db87181 commit） |
| **Fubon ZGK** | 最終外資分點（launchd 改 19:00 原因） | ~18:00-18:30 | `fetch_daily.py` |
| **市場脈搏（market_pulse.json）** | TAIEX 指數 + 台指期 + 三大法人淨買賣 | 每日更新 | `tools/fetch_market_pulse.py` |
| **TDCC 集保** | 股東人數（週報，有 lag） | 每週 | 暫無自動抓取，手動 |
| **reports/index.json** | 所有快照索引（supersedes 鏈） | 每次 ingest | 自動 |

### Tier A 永久追蹤清單（8支）

```
2330 台積電  2454 聯發科  2317 鴻海   2382 廣達
2308 台達電  2881 富邦金  2882 國泰金  2891 中信金
```

---

## 10. 如何從零接手此專案

### Step 1 — 環境確認

```bash
cd "/Users/yoncky/SCD engine/Ai stock"
python3 --version              # 需 3.10+
pip install -r requirements.txt --break-system-packages
```

### Step 2 — 確認 Repo 狀態

```bash
git log --oneline -10          # 最近提交
git status                     # 有無未提交的本機改動
cat reports/index.json | python3 -m json.tool | head -20
```

### Step 3 — 跑全量重放驗證

```bash
make verify-all-replay         # 全部 dates 應 replay-clean
```

### Step 4 — 跑測試

```bash
make test                      # 預期 67+ tests 全綠
```

### Step 5 — 看 Cockpit

```bash
make cockpit                   # 開 viewer/cockpit.py，port 8502
```

### Step 6 — 查最新每日狀態

```bash
make daily-status              # launchd 排程狀態
make daily-tail                # 最新 daily log tail
cat reports/_daily_logs/$(ls reports/_daily_logs/ | grep -v launchd | sort | tail -1)
```

### Step 7 — 手動補執行（如果某天沒跑）

```bash
# 19:00 之後（Fubon ZGK 已結算）
cd "/Users/yoncky/SCD engine"
python3 tools/fetch_daily.py   # 抓資料

cd "Ai stock"
make daily-skip-fetch          # 跑 ingest + verify + log（不重抓）
```

### 重要禁止事項

- ❌ 不得在 P3b 未被用戶簽核前啟動 scoring（tier / composite_score）
- ❌ 不得修改 `reports/_raw_archive/<date>/` 任何檔案（WORM）
- ❌ 不得在 viewer/ 加業務邏輯（filter/sort 必須在 core 計算好）
- ❌ 不得在 core/ 寫死數字門檻（必須放 config/scd.yaml）
- ❌ 不得讓 AI 引用未在 CANONICAL_SCHEMA.md ai_readable_subset 的欄位

### 關鍵文件索引

| 文件 | 說明 |
|------|------|
| `CONTEXT_HANDOFF.md` | P3c 交付時的手動摘要（2026-05-29，有點舊） |
| `ARCHITECTURE.md` / `docs/ARCHITECTURE.md` | 系統架構設計 |
| `docs/CANONICAL_SCHEMA.md` | snapshot 欄位定義 + AI 可讀白名單 |
| `docs/AUDIT_LOG_EVENTS.md` | 所有 audit 事件（v1.4） |
| `docs/SCORING_RUBRIC.md` | 評分規則（P3b 啟動後才正式用） |
| `docs/REPLAY.md` | Replay 機制詳細說明 |
| `docs/FEATURE_FLAGS.md` | Feature flag 治理規約 |
| `docs/AUDIT_FINDINGS.md` | 7個已知不穩定症狀與修法 |
| `RUNBOOK.md` | 日常操作手冊（GitHub Actions / Streamlit Cloud） |
| `CONTRIBUTING.md` | 開發規範 |
| `Makefile` | 所有日常操作入口 |

---

*本文件由 Claude (Cowork) 於 2026-06-04 根據 git history、記憶檔案、原始碼掃描自動生成。*
