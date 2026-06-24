# Maitreya 交接文件 — 2026/06/24（P3b 啟動版 · 完整）

> 交接對象：任何下一個 AI session（Claude Cowork / Cursor / Claude Code）
> Repo：`yonk2046/Maitreya` · Viewer：Streamlit Cloud 自動部署（cockpit.py）
> 本機路徑：`/Users/yoncky/SCD engine/Ai stock/`
> 作者：Yonki + Claude Cowork · 整理日：2026-06-24
> 下一個 session 請先讀此文件 + `git log --oneline -15` + `make verify-all-replay`

---

## 0. 系統定位（必讀）

**Maitreya** = TWSE 股票的決定論狀態偵測引擎（SCD = Stock Condition Detection）。

哲學：**籌碼 > 心理 > 消息 > 預測**。不預測，只偵測「主力正在做什麼」的客觀狀態。
紀律：連買 <3 日不進場；現價 ≤ 主力成本 ×1.05；空手是獲利的一部分；止損/TP 由籌碼定義，價格只是觸發點。

### 架構四層
```
data/adapters/   原始資料 → 標準化 adapter_output（legacy / rollup / tdcc adapter）
core/            純函數：ingest, scoring(golden), state_machine, market_context, paper_trading
viewer/          Streamlit read-only cockpit（不含業務邏輯）
tools/           CLI：run_pipeline, daily, fetch_*, run_backtest, scan_params, render_backtest_report
```

### ⛔ AI_GOVERNANCE 紅線（違反即拒絕）
1. `viewer/` 不得含業務邏輯——偵測/計分/分級在 `core/` 計算，viewer 純渲染（heat radar / 泡泡圖代理屬「display-only」例外，不得回饋 tier/score/gate）。
2. 新欄位走 schema → core → viewer 順序。
3. `core/` 不寫死數字門檻 → 放 `config/scd.example.yaml`（策略參數放 `core/strategies.py` dataclass）。
4. `reports/_raw_archive/<date>/` 是 WORM，禁改。
5. NEVER 輸出 GitHub token（ghp_*）。
6. **P3b 已由 Yonki 簽核解鎖（2026-06-24）**——可動 scoring / 新增欄位。但改既有快照欄位仍要 bump schema + 顧 replay。

---

## 1. 目前 Phase 狀態（2026-06-24，重大更新）

- **P3a ingest-only** → 已演進。
- **H3 穩定期時鐘已作廢**：原本要 20 個交易日（~07/01）才解鎖 P3b。Yonki 2026-06-24 **提早簽核解鎖 P3b**，理由：回測引擎價值高、且回測本身就是「籌碼選股賺不賺」的驗證，取代日曆式 H3。**內容凍結已解除。**
- **Schema 版本：v1.7.0**（P5 weakening=1.6.0 → P3b 時序+開盤=1.7.0）。
- **評分引擎狀態**：`core/golden.py` 的評分/gate 引擎**一直都建好**（不是新寫的），先前產出空名單只因歷史不夠（狀態未成熟）。現在累積 ~30 天 → `golden.run` 產出真實黃金名單（2026-06-23 約 prime 6 + strong 1）。
- **注意**：分數目前是 `golden.run` **即時計算**（viewer + 回測都即時跑），**尚未寫回每日快照**（ingest 仍寫 abstained 的 composite/tier）。把真實 tier/分數寫進快照 = 另一個可選步驟（formal ingest-level P3b）。
- **資料覆蓋**：快照 2026-05-08 → 2026-06-24（31 個）。**早期極稀疏**（5/08–5/25 每天僅 4–8 檔；5/26 後才 26–43 檔），且有缺日（5/11、5/12、5/19 開發期未跑；6/19 端午節）。每日 universe ≈ 當日榜單+權值 ~8–43 檔，**非全市場**。

---

## 2. 本 session（2026-06-24 一整天）完成的工作

### 2A. Replay / pipeline 修復（先滅火，讓驗證可信）
1. **prior_snap_objects（commit a9dabaf）**：`verify_all_replay` full-replay 沒傳 `prior_snap_objects`，導致 weakening 重算成空 → 1.6.0 首個 full-replay 日(6/15) hash 不符。修。
2. **env/mtime/audit_log normalize（e05172b）**：快照含 build 環境指紋（os/python/numpy）+ mtime 衍生 provenance（fetched_at/lag）。Mac 建、GHA(linux)驗 → 必不符。verify 端比 hash 前把 `environment`/`audit_log`/`fetched_at`/`report_date`/`data_lag_days` 用 on-disk 值正規化（如同 generated_at）。
3. **TDCC 漂移 pin（e05172b）**：`adapt_legacy` 的 TDCC 解析每次挑「最新 ≤ 當日」的週檔；新週檔(20260618)出現後，replay 舊日期會漂移挑到它 → 封存沒有 → 崩。修法：`adapt_legacy(tdcc_asof=...)`，verify 傳快照記錄的 `tdcc_weekly.report_date` 當上限（讀 live 目錄保留前一週算 delta，但不漂移）。
4. **GHA Node-24 pin**：`daily.yml` checkout@v4.2.2 + setup-python@v5.6.0。
5. **假日乾淨跳過（739aa71）**：`tools/daily.py` 加 `_trading_day_gate`——resolved date < latest → fail red（stale 回歸）；== latest → 乾淨 skip(exit 0，holiday/週末);> latest → 正常建。

### 2B. 分點抓取優先序（fetch-priority）
`fetch_daily.py` Step 7：加 `MEMORY_ANCHORS=["2344","2408","6239"]`（華邦電/南亞科/力成）+ `build_branch_fetch_list()` 優先序 = 記憶體 anchors → Tier-A → 昨日黃金名單(rankings.golden，P3b 後自動生效) → 昨日高累積買超 → 今日榜，去重取前 40。確保關注標的不會掉出 40 額度。

### 2C. P3b 主體
- **時序層**：`core/market_context.py` 新增 `temporal_enrich()`（重用 `accumulation_velocity`）→ velocity_3d / acceleration / 主力連買 / 外資連買 / volume_5d_avg / volume_ratio / 量增連續 / 主力買超序列。ingest 在 weakening 同迴圈接（同 prior_snap_objects，replay-safe）。schema bump 1.7.0。**只填欄位、不開評分。**
- **開盤價**：`fetch_twse.py` 加抓 STOCK_DAY_ALL → 全市場 `{code:開盤價}`（`_parse_open_map`）→ today.json `openPrices` → legacy 併入 → ingest `open` 欄位。**go-forward**；歷史無開盤 → 回測退回收盤（spec §99）。
- **回測引擎**：`core/paper_trading.py`（純函式 `run_backtest`，kind-aware：momentum / chip_anchored；`snapshots[:i+1]` 切片防前視，D 日決策 D+1 成交；trailing/weakening/fii-reversal/mfb-sell 出場；Trade/BacktestResult + summary 含 per-trade Sharpe）。`core/strategies.py`（STRATEGY_A/B dataclass config）。`tools/run_backtest.py`（寫 reports/backtest/<策略>_<範圍>.json + sha256）。
- **評分引擎啟動**：策略 A 進場用 `golden.run(snapshots[:i+1])` 即時取黃金名單（prime+strong）+ 現價≤成本×1.05。STRATEGY_A.enabled=True。**無需新寫評分**（引擎早在）。
- **參數掃描**：`tools/scan_params.py`（dataclasses.replace 掃 param）。結論：B 連買門檻 **3 > 4 > 5**（初段勝出）。
- **模擬績效報表**：`tools/render_backtest_report.py` → `reports/backtest/report.html`（Chart.js 自包含；KPI/權益曲線/報酬分布/出場原因/逐筆表 + 策略邏輯說明 + 參數掃描對照）。

### 2D. 持倉重點關注 + 轉強搜尋（viewer）
- **`core/holdings.py`**：`load_holdings(data/holdings.json)` + `evaluate_holdings(holdings, snaps)`（純函式,可測）→ 每筆持倉算 P/L + 是否達策略 A/B 出場條件(轉弱orange/red、主力連2日淨賣、外資連2日反向、從近高回落≥8%)→ alert: red/orange/none。
- **`data/holdings.json`**：使用者手填 `{ticker, name, shares, cost}`(編輯後 commit)。
- **cockpit**：新增「💼 持倉」分頁(放第一個)——卡片含現價/成本/股數/市值/損益 + 警示燈(達 A/B 出場條件亮橘/紅、紅燈排頂);「轉強訊號」分頁加搜尋欄(代號/名稱過濾)。viewer 純渲染,判斷在 core。

### 第一份回測結果（小樣本，僅參考）
| 策略 | 交易 | 勝率 | 平均報酬 | 夏普(每筆) | 最大回撤 |
|------|------|------|---------|-----------|---------|
| A 籌碼錨定(保守) | 5 | 80% | +4.2% | 1.37 | −0.2% |
| B 動能延續(積極) | 11 | 73% | +3.9% | 0.87 | −1.8% |
> 5/11 筆是 `end_of_data`（窗口末端強制結算，非真出場）。樣本太小,不能當結論。

---

## 3. 策略邏輯（寫死備忘,日後別忘）

**A 籌碼錨定波段（保守）** `chip_anchored_swing`
- 進場：進黃金名單（5 gate 全過：漏斗=確認層、狀態=confirmed/強化、贊助≥門檻、轉折風險≠critical、淨累計>0）且 現價 ≤ 主力成本×1.05 → 次日開盤買 1 單位。
- 出場（v1）：轉弱紅/橙 OR 主力連 2 日淨賣(翻負) → 全出。
- v2 待補：TP1 部分減碼、加碼 0.5 單位、ATR 結構低點止損。

**B 動能延續（積極）** `momentum_continuation`
- 進場：連買 ≥3 + velocity_3d>0 + acceleration>0 + 外資同向(fii>0) → 次日開盤買 1 單位。
- 出場：移動停利(從高點回落 8%) OR 轉弱紅/橙 OR 外資連 2 日反向 → 全出。
- v2 待補：velocity 創新高加碼 / 轉負減碼（分批）。

共同設定：次日開盤價結算(歷史無開盤→收盤)、固定 1 單位、掉榜不算出場。

---

## 4. Roadmap

### 🟢 現在進行中（被動）
- **讓資料自然累積**（Yonki 已決定）。每天 pipeline 跑，窗口加長、universe 穩定 ~40 檔。樣本厚了夏普/勝率才有意義。想看最新績效：Mac 跑 `python -m tools.run_backtest`(A+B) + `tools.scan_params` + `tools.render_backtest_report`。

### 🔴 主要任務（下一步價值最大）
1. **擴大每日 universe**（讓回測有牛市該有的交易量）：目前 fetch 只抓榜單+權值 ~40 檔。要更多回測候選 → 擴到更大範圍/全市場（fetch 規模放大,評估 API 負載）。**這是「5 筆太少」的根本解。**
2. **策略 A/B v2 部位分批**：加碼/減碼、TP1 部分減碼、ATR 結構止損（讓報酬更貼近真實）。
3. **（可選）把真實分數寫回快照**：ingest 目前寫 abstained composite/tier;改成寫 golden.run 的真實結果 → cockpit 每日快照直接帶 tier/分數。需顧 replay + 可能再 bump schema。

### 🟡 次要任務
- viewer cockpit 加「📈 模擬績效」分頁（目前是 standalone HTML 報表;spec §4 想要 cockpit 內分頁,但 Streamlit 無法在沙箱目視驗證）。
- 原油 × 航運 context overlay（Yonki 提過的想法;消息/總經層,做成警示旗標非預測訊號;需新資料源 adapter）。

### ⬜ 遠期
- **Phase 2：observation-hash 契約**（H3/replay 穩定一個月後）：快照拆 observation + provenance，只 hash observation，根除「metadata 破壞 replay」。見記憶 `scd_observation_hash_contract`。
- 諧波(YHAF/Gartley…)：**明確範圍外**;`paper_trading` 進場已留 `entry_filter_hook` 接口備用。

---

## 5. 重要指令 / 工作流程（含血淚教訓）

### 常用指令
```bash
make daily               # 完整每日流程：fetch → ingest+archive → verify → log（不自動 push）
make daily-skip-fetch    # 用現有 data/ 重建（繞過交易日 gate,可重跑特定日）
make verify-all-replay   # 全archive重播驗證
make test                # pytest 全套
make cockpit             # Streamlit viewer :8502
python -m tools.run_backtest --strategy chip_anchored_swing   # 回測 A
python -m tools.run_backtest --strategy momentum_continuation # 回測 B
python -m tools.scan_params --param entry_streak_min --values 3,4,5
python -m tools.render_backtest_report                        # 刷新 report.html
```

### ⚠️ 環境限制（給 AI：很重要）
- **沙箱(Cowork/Claude Code)不能 push、不能寫 git**（`.git/*.lock` unlink = Operation not permitted）。**所有 git 操作在 Yonki 的 Mac Terminal 跑**;AI 給指令、Yonki 貼。
- 沙箱 bash 跑在 **Linux** → 正好可重現 GHA 的 replay（linux 驗 Mac 建的快照）。
- 沙箱**連不到 TWSE/Sinotrade/TDCC** → 所有 fetch 只能在 Mac 跑;AI 只能驗證「邏輯/解析」(對真實快照)，實際抓取要 Yonki 本機驗。
- 沙箱**刪不掉已追蹤檔**（rm Operation not permitted）→ 要刪 committed 檔用 `git rm`(Mac)。

### ⚠️ Git 工作流教訓（踩過的雷,務必遵守）
1. **`git restore .` 會洗掉「已追蹤檔」的未提交修改**。若 AI 改的是既有檔(非新檔) + 工作區又有 fetch 殘留要清 → **務必「先 commit 程式碼,再 restore/clean」**。安全順序：
   ```bash
   git add <你改的具體檔案>
   git commit -m "..."          # 程式碼先安全進 commit
   git restore .                # 這時才清未提交的 fetch 殘留(動不到已 commit 的)
   git clean -fd reports/_raw_archive data/branches data/tdcc data/snapshots   # 注意:別清到 reports/backtest/!
   git fetch origin && git merge origin/main -m "..."
   git push
   ```
2. **push 常被擋(non-fast-forward)**：因為有兩條 pipeline(launchd 19:00 + GHA 20:00)會自動 commit 資料到 origin。被擋就 `git fetch` + `git merge origin/main` 再 push。
3. **merge 被 fetch 殘留擋(Aborting)**：工作區的 `data/branches/*`、`.taiex_cache.json`、未追蹤的 `reports/_raw_archive/<date>/` 會擋。清理範圍限 `reports/ data/`(`git restore .` + `git clean -fd ...`)，**保住根目錄 .md** 和 `reports/backtest/`。
4. 早期出現過「網頁直接編輯 daily.yml 把中文混進 `uses:`」→ 壞掉。workflow 改動走本機 commit。

### 兩條 pipeline（OPS-1）
- **主**：本機 launchd 每交易日 19:00（Mac，darwin 建檔）。
- **備**：GHA `daily.yml` 週一~五 20:00（linux），有 skip-guard（當日已有 commit 就跳）。
- 因為快照是 Mac 建、GHA 是 linux 驗 → replay 靠 §2A 的 env/mtime normalize 才跨平台過。

---

## 6. 關鍵檔案速查

| 功能 | 檔案 | 重點 |
|------|------|------|
| 時序衍生 | `core/market_context.py` | `temporal_enrich()` / `accumulation_velocity()` / `weakening_profile()` |
| 每股 ingest | `core/ingest.py` | SCHEMA_VERSION="1.7.0";接 weakening+temporal;`open` 欄位;scoring 仍 abstained |
| 評分/黃金名單 | `core/golden.py` | `run()` / `_evaluate_gates`(G1-G5) / `_score_conviction` / `_tier_from_score`——**即時計算,引擎已全建** |
| 回測引擎 | `core/paper_trading.py` | `run_backtest(snaps, strategy)` 純函式,kind-aware,no-lookahead |
| 策略 config | `core/strategies.py` | STRATEGY_A / STRATEGY_B（dataclass,參數不寫死) |
| replay 驗證 | `tools/verify_all_replay.py` | prior_snap_objects + env/mtime/audit normalize + tdcc_asof |
| legacy adapter | `data/adapters/legacy.py` | today.json+branches+tdcc → raw;`open`、`tdcc_asof` |
| 每日排程 | `tools/daily.py` | fetch→pipeline→verify→log;`_trading_day_gate`(假日跳過) |
| fetch 主流程 | `tools/fetch_daily.py` | Step7 分點優先序;`openPrices`;MEMORY_ANCHORS |
| TWSE 抓取 | `tools/fetch_twse.py` | MI_INDEX20(close)+MI_MARGN+STOCK_DAY_ALL(open) |
| 回測 CLI | `tools/run_backtest.py` / `tools/scan_params.py` / `tools/render_backtest_report.py` | |
| 績效報表 | `reports/backtest/report.html` | 自包含 Chart.js;含策略邏輯說明 |
| 持倉判斷 | `core/holdings.py` | `evaluate_holdings()` — P/L + A/B 出場警示;viewer 「💼 持倉」分頁讀它 |
| 持倉資料 | `data/holdings.json` | 使用者手填 {ticker,name,shares,cost} |
| canonical schema | `schema/canonical_schema.json` | `volume_5d_avg` 已放寬 integer→number |
| 設定門檻 | `config/scd.example.yaml` | gates / stage_1-3 / composite 權重 / tiers |

---

## 7. 已知限制 / 待釐清

- **回測樣本太小(5–14 筆)**：根因是早期資料稀疏(4-8 檔/日)+ universe 小(非全市場)+ 黃金名單需歷史成熟。**不是策略問題**。解法:累積資料 + 擴大 universe。
- 多數回測交易是 `end_of_data`(窗口末端結算)非真出場 → 窗口加長後改善。
- 夏普是「每筆交易」版、非年化;小樣本噪音大。
- 開盤價只 go-forward;歷史用收盤代理。第一次 Mac 跑 pipeline 後**確認新快照 `open` 有值**(若空,代表 STOCK_DAY_ALL 欄位名跟 `OpeningPrice` 假設不同,把該 API 一筆回傳給 AI 調 `_parse_open_map`)。
- 力成 6239、華邦電 2344 等記憶體股**會在每日榜進進出出** → 已用 MEMORY_ANCHORS 保證抓分點。

## 8. 給下一個 AI 的 instructions（精簡）
1. 先讀此文件 + 記憶(`MEMORY.md`) + `git log --oneline -15` + 跑 `make verify-all-replay`(沙箱 linux,等同 GHA)。
2. 所有 git/fetch 在 Yonki Mac 跑;你給指令。**改既有檔要 commit 後才 restore/clean**(見 §5)。
3. 動 core/scoring 前確認沒違反 §0.5 紅線;新欄位要 bump schema + 顧 replay-safety(用 prior_snap_objects 模式,build 兩次 hash 要一致)。
4. 回測/績效:改完跑 run_backtest(A+B)+scan_params+render_backtest_report 刷新報表。
5. 高風險或牽涉整體方向的決定,先攤給 Yonki 選(他是 owner,有簽核權)。

*文件由 Claude Cowork 於 2026-06-24 session 整理。涵蓋：replay 三修 + 假日 gate + 分點優先 + P3b(時序/開盤/回測 A·B/掃描/報表)。*
