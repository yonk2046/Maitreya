# Maitreya — Architecture Reference（架構參考）

> *彌勒觀市，不測，只記。*
> **Maitreya**（彌勒）= TWSE 股票的決定論狀態偵測引擎（SCD = Stock Condition Detection）。
>
> 最後更新：2026-07-02（合併自舊 ARCHITECTURE.md 2026-05-30 + PROJECT_STATUS.md 2026-06-04）
> ⚠️ **Phase / 進度狀態一律以最新的 `MAITREYA_HANDOFF_*.md` 為準**——本文件只寫「不常變的結構性知識」，避免再次過期。

---

## 0. 系統一句話

每個交易日自動抓取主力分點＋外資＋投信資料，計算籌碼動能，以可重現（deterministic replay）方式存入不可篡改的歷史快照，供波段決策參考。**同一份輸入（raw + config + lookback）永遠產同一份 snapshot。**

**哲學**：籌碼 > 心理 > 消息 > 預測。不預測，只偵測「主力正在做什麼」的客觀狀態。
**紀律**：連買 <3 日不進場；現價 ≤ 主力成本 ×1.05；空手是獲利的一部分；止損/TP 由籌碼定義，價格只是觸發點。

---

## 1. 架構四層

```
data/adapters/   原始資料 → 標準化 adapter_output（legacy / rollup / tdcc adapter）
core/            純函數：ingest, scoring(golden), state_machine, market_context,
                 paper_trading, holdings, confidence, funnel …
viewer/          Streamlit read-only cockpit（不含業務邏輯，只渲染）
tools/           CLI：run_pipeline, daily, fetch_*, run_backtest, scan_params, backfill_range
```

### ⛔ AI_GOVERNANCE 紅線（違反即拒絕）

1. **`viewer/` 不得含業務邏輯**——偵測/計分/分級一律在 `core/` 算，viewer 純渲染。**不得 render-time 重算衍生欄位**，用 helper 讀 snapshot。
2. 新（會進快照的）欄位走 **schema → core → viewer** 順序，且要 **bump schema + 顧 replay-safety**。
3. `core/` 不寫死數字門檻 → 放 `config/scd.example.yaml`（策略參數放 `core/strategies.py` dataclass）。
4. `reports/_raw_archive/<date>/` 是 **WORM，禁改**。`data/` 執行期唯讀，寫入觸發 `WORM_VIOLATION` 中止。
5. **NEVER 輸出 GitHub token（`ghp_*`）**，不 `git remote -v` 印 URL。
6. P3b 已解鎖（Yonki 2026-06-24 簽核）——可動 scoring / 新增欄位；改既有快照欄位仍要 bump schema + 顧 replay。

---

## 2. 目錄結構

```
/Users/yoncky/SCD engine/
├── tools/fetch_daily.py        上游抓取 orchestrator（Step 1-9），在 Ai stock/ 之外
│                                輸出 data/today.json + data/branches/<ticker>.json
│
└── Ai stock/                   ← 主 repo（git: yonk2046/Maitreya）
    ├── core/
    │   ├── ingest.py           snapshot 寫入 + audit_log（SCHEMA_VERSION 在此）
    │   ├── hashing.py          canonical hash（generated_at 排除；規則見 docs/REPLAY.md §4）
    │   ├── archive.py          raw 歸檔到 _raw_archive/（WORM）
    │   ├── worm_check.py       WORM 自查
    │   ├── golden.py           黃金名單：G1-G5 gates + conviction + action_group()
    │   │                       + display_tier()（可買進/增強/中）
    │   ├── market_context.py   時序觀察 + temporal_enrich()（窗口 streak/velocity）
    │   ├── state_machine.py    時序狀態機（P0.5 改革後版本）
    │   ├── funnel.py           候選漏斗
    │   ├── confidence.py       信心×風險 2D 側寫
    │   ├── holdings.py         持倉判斷 evaluate_holdings()（P/L + A/B 出場警示）
    │   ├── paper_trading.py    回測引擎 run_backtest()（純函式、no-lookahead）
    │   ├── strategies.py       策略 A/B v1/v2 參數（dataclass）
    │   ├── distribution.py     Distribution Intelligence Layer（獨立 sidecar）
    │   ├── watchlists.py       Tier A 錨點 + 板塊群組
    │   └── …（narrative_engine, market_state, sector_intelligence, chip_score, resonance）
    │
    ├── data/
    │   ├── adapters/           legacy / rollup / tdcc / contract（介面凍結）
    │   ├── branches/<ticker>.json   Sinotrade 分點（⚠ 無 fetchDate，陳舊問題見 handoff）
    │   ├── snapshots/          原始 rollup 快照
    │   └── market_pulse.json   TAIEX / 台指期 / 三大法人
    │
    ├── reports/
    │   ├── YYYY-MM-DD.json + .sha256    每日 canonical snapshot（WORM）
    │   ├── index.json                   快照索引（supersedes 鏈）
    │   ├── backtest/<strategy>_latest.json   每日自動刷新的回測結果
    │   ├── _raw_archive/<date>/         不可篡改 raw（replay 從這讀）
    │   └── _daily_logs/                 每日 pipeline log
    │
    ├── tools/
    │   ├── daily.py            每日流程：fetch→pipeline→verify→intel→backtest×4→log
    │   │                       含 _trading_day_gate（假日跳過）+ _fii_published()（T86 未出跳過）
    │   ├── run_pipeline.py     單日 ingest
    │   ├── run_backtest.py     回測 CLI（4 策略）
    │   ├── backfill_range.py   歷史回補沙盒
    │   ├── verify_all_replay.py  全量重放驗證（epoch-aware）
    │   ├── fetch_twse.py / fetch_sinotrade.py / fetch_tdcc.py / fetch_market_pulse.py
    │   └── temporal/           read-only 時序工具（_loader.py 不得 import streamlit）
    │
    ├── viewer/
    │   ├── cockpit.py          ★ 主 UI（:8502）——6 tab：持倉 / 進場機會 / 出場警示 /
    │   │                       市場全景 / 深度研究 / 模擬績效
    │   ├── app.py              工程診斷界面（:8501）
    │   ├── data.py             Streamlit 緩存 loader
    │   └── metrics.py / intelligence.py（舊，逐步淘汰）
    │
    ├── schema/canonical_schema.json    ← 版本以檔內為準
    ├── config/scd.example.yaml         全部門檻（cost_safety 1.05、lookback 20 日等）
    ├── deploy/                 launchd plist + daily_and_push.sh（主 pipeline）
    ├── .github/workflows/daily.yml     GHA 備援 pipeline（skip-guard）
    ├── tests/                  pytest 全套
    └── Makefile                所有日常操作入口
```

---

## 3. 資料流

```
上游：TWSE(T86/日成交/TAIEX) · Sinotrade 分點 · Fubon ZGK · TDCC 集保
        │
tools/fetch_daily.py ──► data/today.json + data/branches/<ticker>.json
        │
data/adapters/legacy.py ──► adapter_output（contract 驗證）
        │
core/ingest.py + hashing + archive ──► reports/YYYY-MM-DD.json (+.sha256, WORM raw archive)
        │
core/market_context.temporal_enrich ──► 窗口欄位寫進快照
        │
        ├─► core/golden.run()（viewer/回測即時算，尚未寫回快照）
        ├─► core/paper_trading.run_backtest() ──► reports/backtest/*_latest.json
        └─► viewer/cockpit.py（read-only 渲染）
```

**Key rule**：`tools/temporal/_loader.py` 絕不 import streamlit（CLI-safe 路徑）；`viewer/data.py` 是 Streamlit-cached 路徑。

---

## 4. 黃金名單引擎（core/golden.py）

- **G1-G5 五道 gate** 全過才入名單；**5% 成本鐵則不在 gate 裡**，在 `action_group()` 判（EXECUTABLE vs WAIT_PULLBACK）。
- **conviction** 加權分（0–1）→ 內部 tier：prime ≥0.65 / strong ≥0.40 / qualified。
- **前端顯示用 `display_tier()`**：🟢可買進（PRIME + EXECUTABLE + 未轉弱）/ ◆增強 / ●中。純顯示層，不動快照。
- 門檻數字一律在 `config/scd.example.yaml`，勿信任何文件裡的舊數值（含 docs/SCORING_RUBRIC.md 的 GOLDEN≥85 舊制）。

---

## 5. 部署與兩條 pipeline（OPS-1）

- **主**：本機 launchd 每交易日 **19:00**（Fubon ZGK ~18:00-18:30 結算後）。
- **備**：GitHub Actions `daily.yml` 週一~五 **20:00**，含 skip-guard（主已 commit 當日快照則跳過）。
- **原則：同一時間只有一個來源在 push。** 改 code 後 commit+push，等排程自動跑，別手動觸發 Actions。
- Viewer 部署：Streamlit Community Cloud，讀 GitHub repo，日常操作見 `RUNBOOK.md`。
- **GitHub 是 source of truth**；本機/沙箱可能落後，push 前先 `git pull --rebase`。

---

## 6. 重要設計決策

| # | 決策 | 理由 |
|---|------|------|
| D1 | **Replay first** — deterministic replay 最高優先 | 系統價值是可信賴的歷史記錄，非即時 alpha |
| D2 | **Raw archive WORM** | 任何 replay 都從 immutable source 重建 |
| D3 | **generated_at 排除於 canonical hash** | 同日重跑不應改變 hash |
| D4 | **Scoring 演進走簽核制**（P3b 已於 2026-06-24 解鎖） | 避免不成熟 scoring 污染歷史記錄 |
| D5 | **UI 不含業務邏輯** — cockpit 只 render | 防止 UI 端偷改造成結果不一致 |
| D6 | **所有門檻在 config** | 防止不同對話偷改門檻 |
| D7 | **AI 引用白名單** — CANONICAL_SCHEMA §7 ai_readable_subset | 防止 AI 幻想未計算的指標 |
| D8 | **MEMORY_ANCHORS 永遠在 fetch** — 常追個股每日必抓分點 | 保持主力成本連續性、防 branches 陳舊 |
| D9 | **Adapter contract 凍結** | 防止 adapter 介面蔓延 |
| D10 | **Feature flags 全在 config，預設 OFF** | 行為可稽核、可重現 |
| D11 | **Cockpit read-only** | viewer 不能污染 archive |
| D12 | **回測 no-lookahead、次日開盤結算、固定 1 單位** | 解耦選股與下注，杜絕前視偏誤 |

---

## 7. 資料來源

| 來源 | 資料 | 時間 | 入口 |
|------|------|------|------|
| TWSE | 個股日成交、TAIEX（MI_INDEX）、T86 三大法人 | 收盤後 ~14:30 | `fetch_twse.py` / `fetch_daily.py` |
| Sinotrade | 主力分點買超（branches/） | T+1 | `fetch_daily.py`（前 40 + MEMORY_ANCHORS） |
| Fubon ZGK | 外資分點最終結算 | ~18:00-18:30 | `fetch_daily.py`（19:00 排程原因） |
| TDCC 集保 | 股東人數（週報，有 lag） | 每週 | `fetch_tdcc.py` |

板塊分類：21 群，基於官方 TWSE/TPEx 產業代碼（sector taxonomy v2）。

---

## 8. 如何從零接手

```bash
cd "/Users/yoncky/SCD engine/Ai stock"
git log --oneline -20                # 最近提交
make verify-all-replay               # 全量重放（沙箱 linux = 等同 GHA）
make test                            # pytest（沙箱缺 streamlit → --ignore=tests/test_viewer_data.py）
make cockpit                         # UI :8502（沙箱看不到，在 Mac 開）
```

閱讀順序：**最新 `MAITREYA_HANDOFF_*.md`** → 本文件 → `RUNBOOK.md` → `CONTRIBUTING.md` → docs/ 各規格。
歷史 handoff 與已完成的一次性規格在 `docs/handoffs/`、`docs/archive/`。

### 環境限制（AI session 必讀）

- 沙箱**不能 push / 寫 git**；所有 git、fetch 在 Yonki 的 Mac Terminal 跑。
- 沙箱跑 pytest / verify 前 `export SCD_PROJECT_ROOT="/path/to/SCD engine"`（雙掛載，見 CONTRIBUTING.md）。
- 沙箱連不到 TWSE / Sinotrade / TDCC。
- 沙箱刪不掉已追蹤檔 → 用 `git rm`（Mac）。

---

*本文件為結構性參考。最新進度、已知 bug、待辦一律看最新 handoff。*
