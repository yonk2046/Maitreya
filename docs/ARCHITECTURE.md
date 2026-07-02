# SCD Engine — 系統架構 (Architecture)

> Version: 2026.ULTIMATE_DUAL_ENGINE — Architecture Charter v2 (post T-pivot)
> Status: Specification (規格) — 尚未綁定技術棧 (stack-agnostic)
> Last Updated: 2026-05-22
> Owner: yonki

---

## 0. 一句話總綱 (One-line charter)

**SCD Engine 是「決定論市場狀態引擎 + AI 解讀層」的分層、時序系統；同一份輸入 (raw + config + lookback + episodes) 必須永遠產出同一份 snapshot；歷史 snapshot 是活的記憶，不是被動歸檔。**
*SCD Engine is a layered, temporal system: a deterministic market-state engine + AI interpretation. Identical inputs (raw + config + lookback + episodes) MUST always produce the same snapshot. Historical snapshots are active memory, not passive archives.*

> 詳細時序模型見 [TEMPORAL_ARCHITECTURE.md](TEMPORAL_ARCHITECTURE.md)。

---

## 1. 設計原則 (Design Principles)

1. **決定論優先 (Determinism First)**
   核心邏輯（過濾、評分、排名、階段轉換）必須是純函式 (pure function)。輸入 = 輸出。沒有隨機性、沒有時間相依、沒有 AI 主觀判斷。
   *Core logic must be pure functions. No randomness, no wall-clock dependency, no AI subjective judgement.*

2. **單向依賴 (One-way Dependency)**
   `ui → reports → core → data`；`research` 平行於 `ui`，**只讀** `reports`。任何反向呼叫都是違規。
   *Strict one-way dependency. `research` is parallel to `ui` and only reads `reports`. Any reverse call is a violation.*

3. **真理之源 (Single Source of Truth)**
   每日 23:59 凍結一份 `reports/YYYY-MM-DD.json` 為當日不可變快照 (immutable snapshot)。所有 UI、AI、回測、報表都從此檔讀。
   *Each trading day produces an immutable snapshot; UI/AI/backtest/reports all consume from it.*

4. **顯式優於隱式 (Explicit over Implicit)**
   所有門檻數字 (1.8x、≥3 天、前 15 名、5%、140%) 必須來自 `config/scd.yaml`。**禁止在程式碼或 prompt 中寫死數字。**
   *All thresholds live in config. Hardcoding numbers in code or prompts is forbidden.*

5. **資料來源可追溯 (Traceable Provenance)**
   每個欄位的值必須帶 `data_source` 與 `data_timestamp` 元資料。沒有來源 = 不准進核心。
   *Every value must carry source + timestamp metadata. No provenance, no entry.*

---

## 2. 五層架構 (Five-layer Architecture)

```
┌──────────────────────────────────────────────────────────────┐
│  /ui            ── HTML/dashboard 純呈現層 (presentation)    │
│                    禁止任何 if-score-then-rank 之類業務邏輯  │
├──────────────────────────────────────────────────────────────┤
│  /research      ── AI 敘事/戰術解讀層 (narrative)            │
│                    只讀 reports；寫入 research/*.md           │
├──────────────────────────────────────────────────────────────┤
│  /reports       ── 每日不可變 JSON snapshot (immutable)      │
│                    reports/YYYY-MM-DD.json 為當日真理之源   │
├──────────────────────────────────────────────────────────────┤
│  /core          ── 決定論引擎 (deterministic engine)         │
│                    stages, scoring, ranking, filters         │
├──────────────────────────────────────────────────────────────┤
│  /data          ── 原始資料 + adapter (raw + adapter)        │
│                    券商分點、外資、融資、量價、股權分散      │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 `/data` — 資料層 (Data Layer)

**職責 (Responsibilities)**
- 從外部來源（TEJ / FinMind / 證交所 OpenAPI / 券商分點）抓取原始資料
- 將不同來源的欄位「正規化」(normalize) 成 canonical schema (見 `CANONICAL_SCHEMA.md`)
- 每筆資料必須附 `{data_source, data_timestamp, fetched_at}` 三元組

**輸出 (Output)** — `data/raw/YYYY-MM-DD/*.parquet` 或 `*.csv`
**禁止 (Forbidden)** — 過濾、評分、任何 if-then 邏輯。Adapter 只做欄位對映 + 型別轉換。

### 2.2 `/core` — 決定論核心 (Deterministic Core)

**職責**
- `core/filters.py`：硬性 gate (hard gate)，未通過即剔除
- `core/scoring.py`：三階段 0-100 子分數計算
- `core/stages.py`：階段轉換邏輯 (Stage 1 → 2 → 3)
- `core/ranking.py`：依 `composite_score` 排序，並列時依 tie-breaker 規則

**契約 (Contracts)**
- 所有函式為 pure：`f(canonical_data, config) → canonical_state`
- 不讀環境變數、不讀時間、不呼叫網路
- 必須有 100% 單元測試覆蓋率，含「同一輸入兩次呼叫產出 byte-identical」的測試

### 2.3 `/reports` — 每日快照 (Daily Snapshots)

**職責**
- 將 `/core` 產出寫成 `reports/YYYY-MM-DD.json`
- 同檔同日 SHA-256 必須一致；若不一致 = 上游有非決定論污染
- 歷史檔永不修改 (write-once, read-many)

**檔案組織**
```
reports/
  2026-05-21.json
  2026-05-22.json
  index.json         # 所有快照的索引 (date → hash → record count)
```

### 2.4 `/research` — AI 解讀層 (AI Interpretation)

**職責**
- 讀取 `reports/<date>.json`
- 產出 markdown 敘事：戰術解釋、和諧波形分析、行為分析、操作建議
- 寫入 `research/<date>/<ticker>.md`

**禁止 (Hard Rules)** — 詳見 `AI_GOVERNANCE.md`
- 不准改分數、不准重排、不准覆寫 filter、不准幻想新指標

### 2.5 `/ui` — 呈現層 (Presentation)

**職責**
- 讀取 `reports/<date>.json` 與 `research/<date>/*.md`
- 純呈現：表格、K 線、籌碼疊圖
- 排序與篩選的「結果」由 core 算好，UI 只負責「顯示」與「使用者互動選擇要看哪一頁」

**禁止**
- 不准在 JS 內做 `if (score > X)` 判斷
- 不准在 HTML/JS 內重算分數
- 不准對著 reports 做反查補資料

---

## 3. 資料流 (Data Flow)

```
盤後 (after-hours)
  │
  ▼
[/data adapter] ──► raw/YYYY-MM-DD/*  (canonical schema)
  │
  ▼
[/core pipeline]
  step 1: hard gates       → 通過清單 (eligible set)
  step 2: stage scoring    → stage_1, stage_2, stage_3 sub-scores
  step 3: composite score  → 0-100 加權合分
  step 4: ranking          → sorted by composite desc
  │
  ▼
[reports writer] ──► reports/YYYY-MM-DD.json  (immutable, hashed)
  │
  ├──► [/ui] 純呈現
  └──► [/research] AI 敘事 → research/YYYY-MM-DD/<ticker>.md
```

---

## 4. 模組間契約 (Inter-module Contracts)

| 邊界 (Boundary) | 形式 (Form) | 違反偵測 (Violation Detection) |
|---|---|---|
| data → core | canonical schema JSON | schema validation (jsonschema) |
| core → reports | composite state object | SHA-256 雙跑比對 (double-run hash check) |
| reports → ui | read-only JSON | UI 端禁用所有寫入 API |
| reports → research | read-only JSON | AI prompt 內顯式要求「禁止修改分數」 |

---

## 5. 決定論保證 (Determinism Guarantees)

每次 build 必跑以下 CI 檢查：

1. **Hash-equality test**：同一份 `data/raw/<date>/` 跑兩次 core pipeline，`reports/<date>.json` 的 SHA-256 必須完全相同。
2. **Config drift test**：所有門檻數字必須能在 `config/scd.yaml` 找到對應 key；用 AST 掃描 `core/*.py` 不得出現裸數字常數（白名單除外：0, 1, -1）。
3. **AI quarantine test**：`grep -r "openai\|anthropic\|llm" core/` 必須回傳 0 行。AI client 只能存在於 `/research`。

---

## 6. 從 V3 守冊到此架構的對應 (Mapping V3 Charter → Architecture)

| V3 守冊段落 | 落地位置 |
|---|---|
| 第一階段 雙引擎籌碼過濾 | `core/scoring.py::stage_1_dual_engine()` |
| 第二階段 行為背離過濾 | `core/scoring.py::stage_2_divergence()` |
| 第三階段 執行與觸發 | `core/scoring.py::stage_3_execution()` |
| 5% 緩衝區 hard gate | `core/filters.py::cost_safety_gate()` |
| 140% 絕望買點 監控 | `core/scoring.py::margin_psychology_score()` |
| 每日實戰檢核清單 | `reports/<date>.json` 內 `checklist` 欄位 |

---

## 7. 後續路線 (Roadmap)

- **v1 (本文件)**：規格凍結；無程式碼。
- **v1.1**：`config/scd.yaml` 與 `canonical_schema.json` 完整定義（已在本批次交付）。
- **v2**：`/core` Python 骨架 + 單元測試。
- **v3**：`/data` adapter 接 FinMind 或 TEJ。
- **v4**：`/research` AI 敘事自動化。
- **v5**：回測引擎 (`backtest/`) 讀歷史 snapshot。

---

## 11. Replay & Immutability — 重現性與不可變性 (P1 新增)

> 詳細規格見 [REPLAY.md](REPLAY.md)。此處只列架構含義。

### 11.1 Three Pillars of Replayability

```
┌─────────────────────────────────────────────────────────────┐
│ Snapshot Immutability   reports/<date>.json 寫入後不可動    │
│                          + sidecar <date>.json.sha256        │
│                          + reports/index.json 記錄 history   │
├─────────────────────────────────────────────────────────────┤
│ Raw Data WORM           data/raw/<date>/ chmod 444           │
│                          corrections/ 子目錄寫修正           │
│                          _hashes.json 凍結每檔 SHA-256       │
├─────────────────────────────────────────────────────────────┤
│ Environment Lock        environment.{core_commit_sha,        │
│                          python, numpy, pandas, ...}         │
│                          進入 snapshot；replay 必須匹配      │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 資料修正流程 (Data Correction Workflow)

```
T+0  原始 snapshot           reports/2026-05-22.json          hash: sha256:111...
                              reports/2026-05-22.json.sha256

T+1  TWSE 修正前日 FII 資料
     新 raw data 進           data/raw/2026-05-22/corrections/2026-05-23T03:00:00Z/
     重生 snapshot            reports/2026-05-22.v2.json       hash: sha256:222...
                              reports/2026-05-22.v2.json.sha256
     更新 index               reports/index.json
                                "2026-05-22": {
                                  "current": "2026-05-22.v2.json",
                                  "history": [
                                    { file: "2026-05-22.json",    superseded_by: "2026-05-22.v2.json" },
                                    { file: "2026-05-22.v2.json", supersedes:    "2026-05-22.json"    }
                                  ]
                                }
```

**原檔不動。** 過去任一時點的決策都能對應到當時看到的 snapshot 版本。

### 11.3 Timezone 政策

- **所有 snapshot 內部時間戳一律 UTC ISO 8601 `Z`**
- UI 顯示時可轉 Asia/Taipei（呈現層職責）
- CI: `grep -E '\+[0-9]{2}:[0-9]{2}' reports/*.json` 必為空輸出

### 11.4 CI 必跑 Replay 檢查

```bash
# Per-push: 最近 5 個 snapshot replay
python -m tools.replay --recent 5 --check-only --strict

# Weekly: 全歷史
python -m tools.replay --all --check-only --parallel 4
```

任一份失敗 = build break = ship 阻擋。

---

## 12. 相關文件 (Related Documents)

- [SCORING_RUBRIC.md](SCORING_RUBRIC.md) — 量化評分細則 (v1.1)
- [CANONICAL_SCHEMA.md](CANONICAL_SCHEMA.md) — 統一資料結構 (v1.2 schema 由 P1 升級)
- [REPLAY.md](REPLAY.md) — Replay 與重現性規格 (P1 新增)
- [AI_GOVERNANCE.md](AI_GOVERNANCE.md) — AI 紅線
- [AUDIT_FINDINGS.md](archive/AUDIT_FINDINGS.md) — 現況不穩定點稽核
- [AUDIT_v1.0.md](archive/AUDIT_v1.0.md) — v1.0 內部稽核
