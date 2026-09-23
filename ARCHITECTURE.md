# Maitreya — Architecture Reference（架構參考）

> *彌勒觀市，不測，只記。*
> **Maitreya**（彌勒）= TWSE 股票的決定論狀態偵測引擎（SCD = Stock Condition Detection）。
>
> 最後更新：2026-09-15（§5 觸發器表改為實測版：雲端 18:05 為事實主力、原生 cron 落地時間、測試排在 commit 後、憑證依賴、混日警告。前版 2026-07-10）
> ⚠️ **Phase / 進度狀態一律以最新的 `MAITREYA_HANDOFF_*.md` 為準**——本文件只寫「不常變的結構性知識」，避免再次過期。
> 🏛️ **架構規範正本＝`docs/ARCHITECTURE_BLUEPRINT.md`（憲法，2026-07-10 立）**——本文件描述現狀怎麼跑；目標架構、遷移路線、契約法以憲法為準。

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

## 5. 部署與三條 pipeline 觸發器（OPS-1，唯一正本——README/RUNBOOK 只指到這裡，不重寫細節）

> ⚠️ **2026-09-15 改為實測版。** 7/10 版的設計描述(launchd 為主、雲端抓不到當日 T86、原生 cron 只遲到 1–3h)已不符現況。
> 以下「實際落地時間」取自 2026-08 ~ 09 Actions run 紀錄;事故經過見 `docs/handoffs/MAITREYA_HANDOFF_20260915.md`。

| 觸發器 | 設定時間(台北) | **實際落地** | 實際角色 | 依賴的憑證 |
|---|---|---|---|---|
| cron-job.org → `workflow_dispatch`(job 1) | **18:05** | 準時 | **事實上的主力**。8/17–8/28 快照幾乎全由此建成,且為完整快照(`fii_pending=false`)—— 雲端 IP 目前**抓得到**當日 T86 | cron-job.org 內的 PAT(2026-09-15 起為 classic)|
| cron-job.org → `workflow_dispatch`(job 2) | **08:35** | 準時 | T+1 補建昨日快照(唯一能準時落在盤前的補班) | 同上 |
| 本機 launchd `com.maitreya.daily` | **19:00** | 準時(Mac 需開機未睡眠) | 備援:雲端 18:05 已 commit 則「nothing to do」;雲端漏掉時補建 | Mac 的 `gh` OAuth(無強制到期)|
| GHA `daily.yml` schedule `0 12 * * 1-5` | 20:00 | **00:00–02:00(隔日)** | 名義備援。**過午夜後日期解析會錯**(9/7 晚班建成 9/4),不可信賴 | GITHUB_TOKEN |
| GHA `daily.yml` schedule `35 0 * * 2-6` | 08:35 | **~13:00(盤中)** | 名義 T+1 補班。**幾乎必落在盤中 → intraday guard 擋掉**,實際上不起作用 | GITHUB_TOKEN |
| GHA `canary.yml` | 21:30 | 延遲可至午夜 | 快照缺席即開 issue。**跑在 GHA 上 —— GHA 本身出事時會一起沉默** | GITHUB_TOKEN |

**workflow 步驟順序(2026-09-15 起,`tests/test_workflow_commit_order.py` 守門)**:
fetch market pulse → `make daily` → `make verify-index` → **commit + push** → `make test-fast`。
測試必須排在 commit 之後:`continue-on-error` 管不到 job 層 `timeout-minutes`,排在前面時測試逾時會連帶 skip 掉 commit(9 月 7 個交易日的資料就是這樣丟的)。

- **兩條真正準時的路都依賴會過期的憑證。** cron-job.org 的 PAT **2026-12-14(一)到期**,必須在到期前換發(FORWARD-RISK-REGISTER R2 已實際發生於 2026-09-04)。
- **pipeline 內回測步驟成本立方成長**(chip_anchored 每支 9/4 已達 ~85 秒),且排在 commit 之前 —— 推估 2026-12 ~ 2027-01 撐破 job 30 分鐘上限。見 FORWARD-RISK-REGISTER R13。
- **1.8.1 兩段式快照**：晚班（20:00）T86 不可得時不再整段跳過，改建 `fii_pending=true` 的 partial 快照（價格+分點齊全，外資待補）；隔晨 08:35 班次偵測到 partial + 新鮮 T86 到手 → 自動重建、透過 supersede 鏈補完為完整快照。viewer 顯示待補橫幅（`fii_pending` 為 true 時）。
- **排程變更記錄**：2026-07-10 Yonki 把 cron-job.org dispatch 由 ~19:05 移前到 18:05（launchd 主排程維持 19:00 未動，plist 為準）。~~18:05 dispatch 在雲端因當日 T86 被 CDN 擋、必被 fii gate 跳過~~(2026-09-15 更正:8 月起雲端 18:05 可建完整快照)。仍有效的警告:Fubon ZGK 結算窗口約 18:00–18:30,**任何在此之前抓富邦的執行,拿到的可能是前一交易日的主力榜**。
- **「只給最新一天」的來源(富邦 ZGK_D/ZGK_F、Sinotrade 分點、TWSE STOCK_DAY_ALL OpenAPI)與「按日期查詢」的來源(T86、MI_MARGN、MI_INDEX)混用時,晚建或補建必然混日。** 快照的 `tradingDate` 由 `derive_trading_date` 標記,ingest 日期守門員無法察覺這種混日(9/4 事故)。STOCK_DAY_ALL 在 18–19 點建置時 95% 仍是前一日 → 快照 `open` 普遍落後一天(見 EXEC-PLAN §七)。
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
| Fubon ZGK | 外資分點最終結算 | ~18:00-18:30 | `fetch_daily.py`（launchd 19:00 刻意設在此結算之後） |
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
