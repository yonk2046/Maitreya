# P3a — Legacy Bridge & Gap Analysis

> Status: 2026-05-25
> Purpose: 把既有 SCD engine v1 (JS 前端 + python fetcher) 的資料橋接進 v1.4 canonical snapshot，**不破壞既有 pipeline**。

---

## 0. 既有專案盤點 (P3a-S0)

```
/Users/yoncky/SCD engine/
├── data/
│   ├── today.json                ← 當日 ingested 主檔 (29 個 mainForceBuy 籌碼)
│   ├── snapshots/<date>.json     ← 多日 rollup (schemaVersion 2; days {date:{...}})
│   ├── history/<date>.json       ← 歷史片段
│   └── branches/<ticker>.json    ← per-ticker 分點明細 (15 檔; 無日期欄位)
├── tools/                        ← Python fetchers (twse / fubon / sinotrade / tdcc / wantgoo)
├── scripts/                      ← JS 前端 (stage1.js ~ stage5.js, dashboard, history, state)
├── styles/                       ← CSS
├── SCD_Engine_v2.html            ← 2012 行單檔前端
├── SCD_ENGINE_PROJECT_BRIEF.md
├── PLAN.md                       ← v2 gap analysis
└── Ai stock/                     ← 新 spec + canonical schema (P0-P2 + T-pivot)
```

**結論**：既有系統有完整工作流程，但是 JS state-localStorage based、schema 不固定、無 replay。新 v1.4 是純後端 Python + canonical schema + replay-safe，**互不相容但可並行**。

---

## 1. 差距分析 (P3a-S1)

| 項目 | 舊 (data/snapshots/v2) | 新 (Ai stock/reports/v1.4) | 對應策略 |
|---|---|---|---|
| 檔案結構 | 多日 rollup 單檔 | 每日一檔 immutable | bridge 產出新檔，舊檔不動 |
| schema 版本宣告 | `schemaVersion: 2` (數字) | `schema_version: "1.4.0"` (SemVer 字串) | 新 schema 嚴格驗證 |
| 日期欄位 | `days{}` 的 key | `date` 頂層 + `generated_at` UTC | 直接對映 |
| 個股結構 | `buyList[].{code,name,buyVol,close,...}` | `stocks[].{ticker,name,current_price,volume,...}` | rename mapping |
| 分點資料 | `data/branches/<ticker>.json`（無日期） | `top5_branches[].{branch,buy,sell,net}` | 取 buyBranches[:5]；mtime 當 fetched_at |
| 主力成本 | `avgBuyCost`（已算好） | `main_force_cost`（VWAP top5） | 直接搬 + 標示 derived |
| 評分 | `stage2Verdict: pass/fail/...` | `stage_1/2/3 + tier (GOLDEN/...)` | **本階段全 abstain** (ingest-only) |
| Hash / Sidecar | 無 | sha256 sidecar + canonical | 新增 |
| Lookback | 無概念 | environment.lookback_snapshots | 第 2 個 snapshot 起填 |
| Provenance | `sources: [fubon-zgk-d, twse-mi20, ...]` 一行 | per-source dict with raw_sha256 | 擴充 |
| 決定論 | 不保證 | sha256 雙跑必一致 | CI 守門 |

---

## 2. Bridge 設計 (P3a-S2)

### 2.1 不動的部分
- 既有 `tools/fetch_*.py` 一律不改（生產中）
- 既有 `data/today.json / data/snapshots/* / data/branches/*` 一律不改（既有前端讀）
- 既有 JS 前端 + serve.py 不動

### 2.2 新增的部分（全在 `Ai stock/` 之下）
```
Ai stock/
├── core/
│   ├── __init__.py
│   ├── canonical.py        # data shapes
│   ├── hashing.py          # canonical_bytes + sha256 sidecar
│   └── ingest.py           # raw → v1.4 snapshot (scores abstain)
├── data/
│   └── adapters/
│       ├── __init__.py
│       └── legacy.py       # 讀 ../../data/today.json + ../../data/branches/
├── tools/
│   └── run_pipeline.py     # CLI: python -m tools.run_pipeline --date 2026-05-25
├── tests/
│   └── test_replay.py      # 同 raw 跑兩次 → byte-identical
└── reports/
    └── <date>.json + .sha256   # 真實 v1.4 snapshot
```

### 2.3 資料流
```
../data/today.json  (29 stocks mainForceBuy)
../data/branches/<ticker>.json (15 stocks 分點細節)
       ↓
  legacy adapter
       ↓
  canonical raw_inputs dict (per ticker)
       ↓
  core/ingest.py
       ↓
  Ai stock/reports/<date>.json   ← v1.4 schema-conform
  Ai stock/reports/<date>.json.sha256
  Ai stock/reports/index.json    ← 累積真實 history
```

### 2.4 分點檔的時序問題

**問題**：`data/branches/<ticker>.json` 沒有日期欄位，且 15 個檔的 mtime 跨 4 日（5/18, 5/19, 5/21, 5/24）。

**規約**：
- 用檔案 `mtime` 當 `fetched_at`
- 若 mtime 與 snapshot date 差距 > 1 個交易日 → emit `DATA_WARNING { lag_days: N }`
- raw_sha256 仍用檔案實際內容計算
- 等真實「每日一次」抓檔機制建好（P3a-S6 後續），這個 lag 問題就消失

### 2.5 缺資料的處理
- `mainForceBuy[]` 有 29 檔，但只有 15 檔有 `branches/<ticker>.json`
- 對缺分點的 14 檔：`top5_branches: []`、`top5_concentration: null`、`abstained.reason: "no branches file"`
- 既然 ingest-only，全部 scoring 欄位 abstain，所以缺資料不影響

---

## 3. 第一個真實 snapshot 的形狀預期

```jsonc
{
  "schema_version": "1.4.0",
  "date": "2026-05-25",
  "generated_at": "2026-05-25T<UTC>Z",
  "config_hash": "sha256:<hash of frozen scd.example.yaml>",
  "core_version": "core@0.1.0-p3a",
  "environment": { /* real Python/numpy versions */ },
  "provenance": {
    "sources": {
      "legacy_today_json":  { raw_file: "../data/today.json", raw_sha256, fetched_at: 2026-05-25T... },
      "legacy_branches":    { raw_file: "../data/branches/", raw_sha256: hash of dir manifest, fetched_at: latest mtime }
    },
    "field_to_source": { ... },
    "derived_fields":   { ... }
  },
  "universe_size": 29,
  "eligible_count": 0,           // 全 abstain
  "stocks": [
    { "ticker": "2409", "name": "友達", "current_price": 22.2, /* scoring 全 abstain */ ... },
    /* 28 more */
  ],
  "rankings": {
    "golden": [], "watch": [], "neutral": [], "ignored": [],
    "sort_keys_used": ["abstained — scoring not yet activated"]
  },
  "audit_log": [
    { event: "BOOTSTRAP_SNAPSHOT", reason: "P3a first ingest; all scoring abstained" },
    { event: "DATA_WARNING", ticker: "<x>", reason: "no branches file" } * 14
  ]
}
```

---

## 4. 後續

S3-S7 (本 PR 範圍)：寫 adapter + ingest + run_pipeline + test_replay + 跑出真實 snapshot + 驗證 replay。**完全不啟用任何 scoring 規則。**

S8+ (未來)：等累積到 5 日 v1.4 snapshot，啟用 lookback chain，emit LOOKBACK_VERIFIED；temporal_state 開始填值。
