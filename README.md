# Maitreya — 台股主力行為觀測引擎

> *彌勒觀市，不測，只記。*

> Version: 2026.ULTIMATE_DUAL_ENGINE
> Status: 規格凍結 v1.0 (Specification Frozen v1.0)
> Stack: 尚未綁定 (stack-agnostic)
> 對應守冊: V3 全能雙引擎版 (見 Claude 專案自訂指令)

---

## 一句話 (TL;DR)

**SCD 是「決定論市場狀態引擎 + AI 解讀層」的時序系統。snapshot 不是被動歸檔，是會記憶、會傳遞狀態的時序節點。同一份輸入（raw + config + lookback + episodes）永遠產同一份 snapshot。**

---

## 為什麼有這個 repo

過去的工作流程是：在對話中讓 AI 一邊抓資料、一邊評分、一邊排名。
問題：**同樣的資料、不同對話，會選出不同股票。**
原因：分數規則寫在 prompt 而非程式碼裡、UI 偷做業務邏輯、AI 主觀介入排序。

這份規格把上述問題「拆乾淨」：
資料、評分、排名 → 決定論核心；解讀、敘事、戰術建議 → AI；展示 → UI。三者各司其職，互不越界。

---

## 檔案地圖 (File Map)

```
ai_stock/
├── README.md                          ← 你現在讀的這份
├── docs/
│   ├── ARCHITECTURE.md                ← 五層架構（state engine 化）+ §11 Replay & Immutability
│   ├── TEMPORAL_ARCHITECTURE.md       ← T-pivot 主規格：8 個 temporal primitives
│   ├── EPISODE.md                     ← 跨日事件實體規格 (accumulation / breakout / ...)
│   ├── STORAGE_LAYOUT.md              ← reports / episodes / state / parquet 目錄結構
│   ├── SCORING_RUBRIC.md              ← v1.1：0-100 量化評分、Numeric Policy、Gate-then-Score
│   ├── SCORE_NODE.md                  ← v1.0 + §13 Temporal Extension
│   ├── CANONICAL_SCHEMA.md            ← 統一資料結構 + 中英欄位說明
│   ├── REPLAY.md                      ← v1.0 + §17 Window Replay (lookback chain)
│   ├── AUDIT_LOG_EVENTS.md            ← 27 個 audit events 統一登記
│   ├── CORRELATION_REPORT.md          ← 觀察用 (P4 才決定移除)
│   ├── FEATURE_FLAGS.md               ← 旁路 flag 治理 (day_trader_exclusion 等)
│   ├── AI_GOVERNANCE.md               ← AI 紅線：不准改分、不准重排、不准幻想
│   ├── AUDIT_FINDINGS.md              ← 現況七大不穩定症狀 + 重構優先序
│   └── AUDIT_v1.0.md                  ← 自查報告 + v1.1 patch list
├── schema/
│   └── canonical_schema.json          ← v1.4 含 ScoreNode / temporal_state / episodes
├── config/
│   └── scd.example.yaml               ← v1.3 含 temporal + episodes + storage（皆 OFF）
├── reports/
│   ├── 2026-05-22.example.json        ← daily snapshot 範例 (schema 1.4.0, bootstrap)
│   ├── 2026-05-22.example.json.sha256 ← canonical hash sidecar
│   ├── index.json                     ← snapshot 歷史索引 (含 supersedes 範例)
│   └── score_breakdown.v1_1.proposal.json ← P2 提案結構樣本
└── tools/
    └── correlation_analyzer.py        ← 因子相關性觀察工具
```

---

## 30 秒導覽：盤後一個交易日的生命週期

```
1. /data adapter 抓資料 ─────► raw/2026-05-22/*  (canonical schema)
                                  │
2. /core pipeline 跑完 ──────► reports/2026-05-22.json  (immutable, hashed)
                                  │
3. /research AI 解讀 ─────────► research/2026-05-22/<ticker>.md
                                  │
4. /ui 純呈現 ──────────────► dashboard
```

每一步只能讀「前一步的輸出」；不准跨層回呼。

---

## 評分規則 (核心數字)

| 階段 | 權重 | 內容 |
|---|---|---|
| **Hard Gate** | 一票否決 | G1 主力成本 5% 緩衝、G2 外資 ≥2 家同步買 ≥3 日、G3 主力連買 ≥3 日 |
| Stage 1 雙引擎 | 40% | FII sub + Main-Force sub |
| Stage 2 行為背離 | 35% | 籌碼集中 sub + 融資心理 sub |
| Stage 3 執行觸發 | 25% | 30分 PA + 2H 趨勢 |
| **Composite** | — | 加權合分 0-100 |
| Tier 判定 | — | GOLDEN ≥85、WATCH ≥70、NEUTRAL ≥50、IGNORE < 50 |

詳見 `docs/SCORING_RUBRIC.md`。

---

## AI 三條鐵則

1. 永遠引用 snapshot 路徑與 config_hash。
2. 不准改寫 `composite_score`、`tier`、`rankings`、`gates`。
3. 不准提出 schema 未定義的指標（例如 RSI）。

詳見 `docs/AI_GOVERNANCE.md`。

---

## 後續路線 (Roadmap)

| Phase | 內容 | 狀態 |
|---|---|---|
| P0 spec determinism | Numeric Policy + Convention Rules + Gate-then-Score | ✅ 已完成 |
| P1 replay engine | environment + per-source provenance + UTC + hash sidecar + index | ✅ 已完成 |
| P2 scoring decomposition | Score Node 結構 + SUBFACTOR_COMPUTED audit + day-trader 處理 | ⏳ 下一輪 |
| P3 historical snapshots | reports 歸檔策略、data correction 流程實際落地 | ⏳ |
| P4 walk-forward backtest | IC 計算、訓練/驗證/測試、config 變更必驗 | ⏳ |
| P5 AI research layer | `/research/<date>/<ticker>.md` 自動產出 + log | ⏳ |

---

## 給未來自己的提醒 (Letter to Future Me)

- 想加新指標 → 先進 schema → 再進 core → 再進 AI prompt 白名單。**不可跳關。**
- 想調門檻 → 改 `config/scd.yaml`，commit message 寫理由。不要改程式碼。
- 想讓某檔進 Golden → 看 audit_log 看它卡在哪道 gate，是該檔不適合，還是規則該調。
- 系統開始不穩 → 第一步永遠是 `sha256sum reports/<date>.json`，跑兩次比對。
