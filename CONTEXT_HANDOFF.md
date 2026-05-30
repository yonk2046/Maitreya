# SCD Engine — 工作狀態移交文件
## Context Handoff for New Conversation

**日期 / Date:** 2026-05-29  
**階段 / Phase:** P3c Market Context Layer（已交付）；P3b 等待用戶簽核後啟動

---

## 專案位置 / Project Location

- **主目錄:** `/Users/yoncky/SCD engine/Ai stock/`
- **知識來源:** Claude 知識庫 "Ai stock"（掛載為 read-only）
- **記憶檔案:** `~/.../spaces/.../memory/MEMORY.md`

---

## 系統核心哲學 (SCD System)

外資大趨勢 × 主力分點鎖碼交叉過濾，獵殺高勝率波段標的。

**三階段過濾：**
1. **雙引擎籌碼** — 外資（摩根士丹利/摩根大通/瑞銀/高盛/美林/花旗）+ 主力分點
2. **行為背離** — 股東人數下降、融資140%絕望點、買賣家數差為負
3. **執行觸發** — 30分鐘PA訊號（Pin Bar/吞噬）+ 主力成本5%以內

---

## 本次對話完成的工作

### ✅ P3c — Market Context & Permanent Watchlist Layer（2026-05-29）

**核心設計哲學：** Temporal intelligence > static ranking.  
SCD的核心價值不是「今天誰分數最高」，而是「哪些股票正在進入狀態改變」。

#### 新建 `core/watchlists.py`
Tier A 永久追蹤清單（8個體制錨點）：
- 2330 台積電, 2454 聯發科, 2317 鴻海, 2382 廣達
- 2308 台達電, 2881 富邦金, 2882 國泰金, 2891 中信金
- 輔助：`SECTOR_GROUPS`（8個板塊含ticker列表）、`tier_a_tickers()`、`stock_group()`

#### 新建 `core/market_context.py`
五個純觀察函數（無I/O、無副作用、可測試）：
1. `accumulation_velocity(ticker, records)` — 累積速度：連續streak、淨累積張數、3日速度
2. `sponsorship_persistence(ticker, records)` — 贊助持續性：分點出現頻率、persistence_score (0-1)
3. `regime_shift(snapshots)` — 市場體制：廣度/均漲/量能時序、體制標籤、轉換偵測
4. `failed_breakout_memory(ticker, records)` — 假突破記憶：量>1.8×均 AND 漲>2% 後≥2日退卻
5. `leadership_rotation(snapshots)` — 資金輪動：板塊資金流向排名、輪動偵測
- 批量輔助：`full_ticker_context(ticker, snapshots)`

#### 新建 `tools/temporal/market_flow_monitor.py`
CLI市場流動監控工具：
```bash
make market-flow          # 完整市場報告
make market-flow ARGS="--ticker 2317"   # 單股模式
make market-flow ARGS="--dates 20 --json"
```

#### 改版 `fetch_daily.py` — 新增Step 6（Sinotrade分點擴充）
- 固定抓取：cross[:10] + FII top10 + MF top10 + **TIER_A_ANCHORS（永遠）**
- 上限30支，寫入 `data/branches/<ticker>.json`
- 確保 Tier A 始終有最新主力成本

#### 更改 `deploy/com.scd.daily.plist.template` — 排程修正
- 14:30 → **19:00**（Fubon ZGK 最終結算約18:00-18:30）

#### 完全重建 `viewer/cockpit.py` — 7個面板
Bloomberg+Notion+Trading Desk 風格，Warm Slate色調：

| Tab | 圖示 | 功能 |
|-----|------|------|
| 1 | 📊市場體制 | Regime banner、廣度/均漲Plotly圖、時序表格 |
| 2 | 🎯雷達觀察 | Tier A 8股4列網格卡片、主力成本、streak徽章 |
| 3 | ↑轉強訊號 | streak≥2 全標的，速度/贊助/成本標籤 |
| 4 | ⚠假突破 | 假突破偵測，突破日/量比/退卻天數 |
| 5 | ◉持續吸籌 | persistence_score≥0.35，進度條，主力分點 |
| 6 | ⟳資金輪動 | 板塊橫條圖、輪動警報、5日走勢 |
| 7 | ⌛時序演化 | 單股詳細鏈視圖 OR 多股熱力矩陣 |
| Dev | 折疊 | 原始快照/Audit Log/Schema（工程面板保留） |

**CSS Warm Slate主題：** `#0D1117` 底色、`#7EB8D4` 鋼藍、`#52B788` 正極、`#E05C7A` 負極

### ✅ 舊版 `viewer/cockpit.py` — 已被上述重建取代
（舊版為L1-L5五層架構，intelligence.py依賴版本）

---

## 目前數據狀態

reports/ 中已有日期：2026-05-08, 05-13~05-15, 05-17~05-18, 05-20~05-22, 05-25~05-29（每日新增）

- **2026-05-26 重要:** Universe 從 8 擴張至 30，9支股票出現外資聯合掃貨
- **P3a 現況:** 所有 tier=IGNORE，composite_score=0，temporal scoring 全部 abstained
- **每日排程:** launchd 19:00 觸發，fetch → ingest → verify-all-replay → log
- **data/branches/:** 每日新增 ≤30個 `<ticker>.json`（Tier A永遠在列）

---

## 目前架構狀態

```
SCD engine/
├── tools/fetch_daily.py      — 上游抓取（Step1-9），寫 data/today.json + data/branches/
└── Ai stock/
    ├── core/
    │   ├── hashing.py, ingest.py, archive.py, worm_check.py
    │   ├── watchlists.py     — ✨ P3c: Tier A + SECTOR_GROUPS
    │   └── market_context.py — ✨ P3c: 5個時序智慧函數
    ├── data/
    │   ├── adapters/         — legacy, rollup, contract adapters
    │   ├── branches/<ticker>.json  — Sinotrade 分點資料（每日更新）
    │   └── snapshots/        — 原始快照（rollup）
    ├── reports/              — JSON snapshots + SHA256 sidecars + index.json
    │   └── _raw_archive/<date>/   — WORM-protected raw provenance
    ├── schema/               — canonical_schema.json
    ├── tools/
    │   ├── daily.py          — 每日自動流水線 orchestrator
    │   ├── run_pipeline.py
    │   └── temporal/         — streak_analyzer, persistence_ranker,
    │                           market_flow_monitor (✨ P3c CLI)
    ├── viewer/
    │   ├── app.py            — 工程診斷界面 :8501
    │   ├── cockpit.py        — ✨ P3c 7-tab 市場智慧終端 :8502
    │   ├── data.py           — 緩存數據讀取
    │   ├── intelligence.py   — 舊版計算層（仍存在，P3c後未刪）
    │   └── metrics.py        — 觀測指標
    └── Makefile              — make cockpit / make market-flow / make daily / etc.
```

---

## Memory 檔案

| 檔案 | 內容 |
|------|------|
| `scd_priority_replay_first.md` | 當前優先順序：replay/temporal/provenance > scoring |
| `scd_engine_phase_state.md` | P3a 已交付；P3a-Hardening 中；P3b 等待 Hardening 簽核 |

---

## 待辦 / 下一步可能方向

**P3c 收尾（可選）：**
- 跑 `make market-flow` 驗證 CLI 正確輸出
- 跑 `make cockpit` 驗證7個Tab全部渲染
- 考慮將 `intelligence.py` 舊版函數遷移至 `market_context.py` 接口

**P3b（評分層）— 仍在等待用戶簽核：**
- 需要足夠歷史天數（建議 ≥20日）
- 啟動後：tier / composite_score 從 IGNORE→真實值；cockpit 轉強/吸籌標籤可顯示分數
- `intelligence.py` 的分類邏輯接入真實 composite_score

**資料補充：**
- 外資持股趨勢（fii_holding_trend_5d）目前多為 null，待數據源補齊
- Tier A 中未進入 buy list 的標的（台積電等）暫無 snapshot stocks，只有 branches 成本

---

*本文件由對話摘要自動生成。請將此內容貼入新對話開頭以延續工作。*
