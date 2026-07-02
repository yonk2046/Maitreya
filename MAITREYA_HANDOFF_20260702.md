# Maitreya 交接文件 — 2026/07/02（change_pct + 分級改名 · 完整整合版）

> 交接對象：任何下一個 AI session（Claude Cowork / Cursor / Claude Code）
> Repo：`yonk2046/Maitreya` · Viewer：Streamlit Cloud 自動部署（`viewer/cockpit.py`）
> 本機路徑：`/Users/yoncky/SCD engine/Ai stock/`
> 作者：Yonki + Claude Cowork · 整理日：2026-07-02
> **這份是「整合版」**——想快速上手只讀這份即可；要細節再回頭讀 `docs/handoffs/MAITREYA_HANDOFF_20260701.md` + `docs/handoffs/MAITREYA_HANDOFF_20260624.md`（2026-07-02 文件整併後歷史 handoff 移至 `docs/handoffs/`）。
> 開工前先跑：`git log --oneline -20` + `make verify-all-replay`（沙箱 linux＝等同 GHA 驗證）。

---

## 0. 系統定位（必讀）

**Maitreya**（彌勒）= TWSE 股票的**決定論狀態偵測引擎**（SCD = Stock Condition Detection）。
一句話：*彌勒觀市，不測，只記。* 同一份輸入（raw + config + lookback）永遠產同一份 snapshot。

**哲學**：籌碼 > 心理 > 消息 > 預測。不預測，只偵測「主力正在做什麼」的客觀狀態。
**紀律**：連買 <3 日不進場；現價 ≤ 主力成本 ×1.05；空手是獲利的一部分；止損/TP 由籌碼定義，價格只是觸發點。

### 架構四層
```
data/adapters/   原始資料 → 標準化 adapter_output（legacy / rollup / tdcc adapter）
core/            純函數：ingest, scoring(golden), state_machine, market_context, paper_trading
viewer/          Streamlit read-only cockpit（不含業務邏輯，只渲染）
tools/           CLI：run_pipeline, daily, fetch_*, run_backtest, scan_params, backfill_range
```

### ⛔ AI_GOVERNANCE 紅線（違反即拒絕）
1. **`viewer/` 不得含業務邏輯**——偵測/計分/分級一律在 `core/` 算，viewer 純渲染。**不得 render-time 重算衍生欄位**，用 helper 讀 snapshot。
2. 新（會進快照的）欄位走 **schema → core → viewer** 順序，且要 **bump schema + 顧 replay-safety**。
3. `core/` 不寫死數字門檻 → 放 `config/scd.example.yaml`（策略參數放 `core/strategies.py` dataclass）。
4. `reports/_raw_archive/<date>/` 是 **WORM，禁改**。`data/` 執行期唯讀，任何寫入會觸發 `WORM_VIOLATION` 中止 pipeline。
5. **NEVER 輸出 GitHub token（`ghp_*`）**。
6. **P3b 已解鎖**（Yonki 2026-06-24 簽核）——可動 scoring / 新增欄位。但改既有快照欄位仍要 bump schema + 顧 replay。
   - ⚠️ 註：`CONTRIBUTING.md`（2026-05-26）still 寫「scoring GATED / tier 只能 IGNORE」，**那段已過時**，以本條為準。

---

## 1. 目前 Phase 狀態（2026-07-02）

- **Schema 版本：v1.8.0**（6/29 從 1.7.0 bump，前後端衍生欄位一致化）。
- **黃金名單引擎**：`core/golden.py` 每天**即時算**（viewer + 回測都即時跑），產出真實 prime/strong/qualified 名單（約 30 檔級距）。**尚未寫回快照**（ingest 仍寫 abstained 的 tier=IGNORE / composite=0）——把真實分數寫回快照是可選的 formal step。
- **前端分頁**：P2.5 已從 12 → 6 tab（持倉 / 進場機會 / 出場警示 / 市場全景 / 深度研究 / 模擬績效），心智模型「我有什麼→該不該出→能不能進→為什麼→深入→驗證」。
- **黃金名單分級（NEW 2026-07-02）**：前端顯示已從 PRIME/STRONG/QUALIFIED 改成 **🟢可買進 / ◆增強 / ●中**（見 §2）。
- **回測引擎每日自動刷新**：daily pipeline 末段跑 4 策略 backtest → `reports/backtest/<strategy>_latest.json`；viewer 讀檔，樣本 <30 顯示進度條。
- **資料覆蓋**：快照 2026-05-08 → 最新（每日 +1）；早期稀疏（5/08–5/25 每天 4–8 檔），5/26 後 26–43 檔/日；每日 universe ≈ 榜單+權值 ≈40 檔（**非全市場**），且會有掉榜。
- **replay 狀態**：舊 1.5–1.7.0 快照 legacy-epoch-clean（hash 鎖定）；**1.8.0 的 6/30、7/1 兩天 full-replay 紅字＝已知的 Mac建/linux驗跨平台指紋差異**（`RUNBOOK.md` 明講「忽略，資料正確」）。等 Mac 重跑 pipeline 才會轉綠。

---

## 2. 本 session（2026-07-01 → 07-02）完成的工作 · commit `730fd4d`

**起因**：Yonki 請另一個 AI 檢查 6/30 GitHub 原始資料，對方說「國巨 2327 漲+100%、距成本+17.2%、外資賣，絕不能碰，你的黃金名單列它是 bug」。追查後發現**三個根因疊在一起**，不是單一 bug，也不是名單邏輯壞掉：

### 2A. `change_pct` 貼錯標籤 → 改真百分比 ⭐ 最關鍵
- **Bug**：`tools/fetch_twse.py` 把 TWSE 的 `Change`（**漲跌價差，單位=新台幣元**）直接存成 `chgPct`。國巨 1040→1140 是漲 **100 元（實際 +9.6%）**，被記成「100%」。低價股（中石化 8 元漲 0.25 元）剛好看起來像合理的「0.25%」，所以這 bug 一直沒被抓到——**它是全系統性的**，只在千元股才爆出來。另一個 AI 的「漲100%/減資重設」是被這壞欄位誤導（國巨股價 826→1140 一路緩爬，沒重設）。
- **修法**：`chg_pct = round(chg / (close - chg) * 100, 2)`，並多存原始元數 `chgAmt`。
- ⚠️ **go-forward only**：舊快照維持錯值，**明天新抓的快照才正確**。首次 Mac pipeline 跑完，確認國巨 change_pct 不再是 100。

### 2B. 分點資料陳舊（假新鮮）→ 加 MEMORY_ANCHORS 先止血
- **Bug**（§7A 那個已知問題）：`data/branches/<ticker>.json` **無 fetchDate**。國巨 6/18 後掉出每日分點前 40，ingest 每天重複讀舊檔 → `main_force_buy=8836` 從 6/18 複製到 6/30。這把 golden 算出的 streak 灌成 7、贊助分 1.00、conviction 0.85 → 才擠進 STRONG。資料若新鮮它多半進不了。
- **止血修法（本次）**：`tools/fetch_daily.py` 的 `MEMORY_ANCHORS` 加入 **2327 國巨 / 1314 中石化**（現為 `["2344","2408","6239","2327","1314"]`），強制每日抓這幾檔分點、永不陳舊。
- **治本修法（未做，Yonki 選擇先止血）**：branches 加 `fetchDate` + ingest 讀到過期則 fallback 回 today.json 當日 buyVol。**要 bump schema 1.8→1.9.0 + 顧 replay**。詳見 §7。

### 2C. 黃金名單 ≠ 可買進 → 分級改名 可買進/增強/中
- **關鍵觀念**：5% 成本鐵則**不在**黃金 5 道 Gate（G1-G5）裡，它在 `core/golden.py:action_group()` 那層判（EXECUTABLE vs WAIT_PULLBACK）。所以國巨（+17% 超成本）會正確地「進名單但被標 wait_pullback + CAP_fii_contra_2d 降級」。系統其實沒判錯，是前端 PRIME/STRONG 字眼看起來像「快買」。
- **修法**：`core/golden.py` 新增 `display_tier(entry, weakening_severity)` → 回 `可買進 / 增強 / 中`。
  - **可買進**：conviction ≥ PRIME(0.65) **AND** action==EXECUTABLE（現價≤成本×1.05）**AND** 未轉弱。→ 價格延伸的股（如國巨）永遠不會顯示可買進。
  - **增強**：其餘 conviction ≥ STRONG(0.40)。
  - **中**：通過門檻但 conviction 較低。
  - 純顯示層、derived from 既有 conviction + action_group，**不動 gate / conviction / 快照 tier / replay hash，不用 bump schema**。
- **viewer 接線**：`viewer/cockpit.py` 黃金卡片 badge、摘要 metric strip、Session Narrative、候補（near-miss）卡都改用新標籤。內部 `e.tier`（prime/strong/qualified）保留不動，只換顯示。
- ⚠️ **可買進門檻偏嚴**（要 PRIME + executable）：6/30 沒人達標是安全的保守結果。若 Yonki 想要更多買點，把 `display_tier` 的 `entry.conviction >= TIER_PRIME` 放寬成 `TIER_STRONG` 即可（一行）。

### 2D. 順帶發現（未修）
- **合庫金 5880**（6/30 的 #1 PRIME，14 日連買）**當天整個掉出 universe**（連價格都沒有 → data_pending）。同一個 universe 不穩定/掉榜問題，根本解是擴大 universe（§4）。

### 2E. 資安：GitHub token 外洩已處理
- 舊的 remote URL 內嵌了 `ghp_*` token，被 `git remote -v` 印出來過。已請 Yonki：**GitHub Regenerate 作廢舊 token** + `git remote set-url` 拿掉 URL 內的 token + 新 token 存進 macOS Keychain（`credential.helper osxkeychain`）。**下個 AI 別再 `git remote -v` 印 URL、別把 token 寫進任何檔案。**

### 驗證
- **243 tests pass**（改了 `tests/test_fetch_priority.py` 讓 anchors 數量 assertion 不寫死）。
- `make verify-all-replay`：34 legacy-epoch-clean + 6/30/7/1 已知紅字（非本次造成——ingest 不 import 任何我改的檔）。
- 已 push GitHub：**commit `730fd4d`**，origin/main 已確認含三修正。

---

## 3. 策略邏輯（同 6/24 handoff，無改動）

**A 籌碼錨定波段（保守）** `chip_anchored_swing` v1/v2 · **B 動能延續（積極）** `momentum_continuation` v1/v2

- **A 進場**：進黃金名單（5 gate 全過）且 現價 ≤ 主力成本×1.05 → 次日開盤買 1 單位。出場：轉弱紅/橙 OR 主力連 2 日淨賣。v2 有加碼/TP1減半/結構止損。
- **B 進場**：連買 ≥3 + velocity_3d>0 + acceleration>0 + 外資同向 → 次日開盤買。出場：移動停利(回落8%) OR 轉弱 OR 外資連2反向。
- 共同：次日開盤結算（歷史無開盤→收盤代理）、固定 1 單位、掉榜不算出場。
- 跑法：`python -m tools.run_backtest --strategy <name> --latest-only`（4 個策略：`chip_anchored_swing`/`momentum_continuation`/`chip_anchored_v2`/`momentum_v2`）。
- 細節見 `docs/handoffs/MAITREYA_HANDOFF_20260624.md` §3。

---

## 4. Roadmap

### 🟢 現在進行中（被動）
- **讓資料自然累積**。每日 pipeline 跑，樣本厚了 backtest 才有意義。B 目前約 13/30，約 7 月中破 30。

### 🔴 主要任務（下一步價值最大）
1. **治本 branches 陳舊**（§2B / §7A）：branches 加 fetchDate + 過期 fallback。要 bump schema 1.8→1.9.0、顧 replay。Yonki 已選「先止血（anchors）」，治本 code 未寫，等他點頭。
2. **擴大每日 universe**（回測樣本瓶頸的根本解，也順帶解掉合庫金那種掉榜）：fetch 只抓榜單+權值 ~40 檔 → 擴到更大範圍/全市場，評估 Fubon/API 負載。
3. **持久化 sponsorship / failed_breakout**：viewer 還剩這 2 個 render-time 重算未寫回快照（同類 AI_GOVERNANCE 問題，比 streak 影響小）。建議跟 1.9.0 一起寫回。

### 🟡 次要任務
- 「可買進」門檻若太嚴 → 放寬成 STRONG（§2C 一行）。
- 「📈 模擬績效」再放權益曲線和分批 breakdown（目前只 KPI + 進度條）。
- （可選）把 golden.run 真實 tier/分數寫回每日快照（formal ingest-level P3b）。

### ⬜ 遠期
- **Phase 2：observation-hash 契約**（H3/replay 穩定一個月後）：快照拆 observation + provenance，只 hash observation，根除「metadata 破壞 replay」。這也會根治 §1 的 6/30/7/1 跨平台紅字。見記憶 `scd_observation_hash_contract`。
- 諧波（YHAF/Gartley…）：**明確範圍外**；`paper_trading` 進場留了 `entry_filter_hook` 備用。

---

## 5. 重要指令 / 環境限制 / Git 教訓

### 常用指令（在 `Ai stock/` 下）
```bash
make daily               # 完整每日流程 fetch→ingest→verify→backtest→log（不 auto push）
make daily-skip-fetch    # 用現有 data/ 重建（繞過交易日 gate，可重跑特定日）
make verify-all-replay   # 全 archive replay（沙箱 linux 等同 GHA）
make test                # pytest 全套（沙箱缺 streamlit → 加 --ignore=tests/test_viewer_data.py）
make cockpit             # Streamlit :8502（沙箱無法目視，改在 Mac 開）
python -m tools.run_backtest --strategy momentum_continuation --latest-only
python -m tools.run_backtest --strategy chip_anchored_swing --source=backfill --latest-only
python -m tools.backfill_range --from 2026-04-01 --to 2026-05-25    # 歷史回補沙盒
```

### ⚠️ 環境限制（給 AI：很重要）
- **沙箱（Cowork/Claude Code）不能 push、不能寫 git**（`.git/*.lock` unlink = Operation not permitted）。**所有 git / fetch 在 Yonki 的 Mac Terminal 跑**；AI 給指令、Yonki 貼。
- 沙箱跑 pytest / verify 前要 `export SCD_PROJECT_ROOT="/path/to/SCD engine"`（雙掛載環境 path resolver 需要，見 `CONTRIBUTING.md`）。
- 沙箱 bash 跑在 **Linux** → 正好重現 GHA 的 replay。
- 沙箱**連不到 TWSE/Sinotrade/TDCC** → fetch 只能在 Mac 跑；AI 只能驗邏輯/解析。
- 沙箱**刪不掉已追蹤檔** → 要刪用 `git rm`（Mac）。
- **GitHub 是 source of truth**（Yonki 明確要求）。沙箱看到的是 Mac 資料夾快照，可能比 GitHub 舊（兩條 pipeline 會自動 push 資料 commit）。要 push 我的改動前，Mac 先 `git pull --rebase` 再疊。

### ⚠️ Git 工作流教訓（踩過的雷）
1. **先 commit 程式碼，再 restore/clean**（否則洗掉未 commit 改動）。
2. **push 前一定要先 commit**——本 session 踩過：Yonki 一直 `git push` 沒反應，因為改動只是工作區 modified、從沒 commit，push 當然 "Everything up-to-date"。順序：`git add <檔> && git commit -m "..." && git push`。
3. **HTTPS 認證**：GitHub 不收密碼，密碼欄要貼 **token**（終端機貼上不顯示是正常的）。最穩：用 `git credential-osxkeychain store` 先把 token 存進 Keychain。
4. push 被擋（non-fast-forward）→ `git fetch` + `git merge/rebase origin/main` 再 push（兩條 pipeline 會自動 commit）。
5. `index.lock exists` → 確認沒真的在跑，`rm -f .git/index.lock`。
6. 清理只限 `reports/ data/`，**別清 `reports/backtest/` 和根目錄 `.md`**。

### 兩條 pipeline（OPS-1）
- **主**：本機 launchd 每交易日 19:00（Mac，darwin 建檔）。
- **備**：GHA `daily.yml` 週一~五 20:00（linux），有 skip-guard。
- RUNBOOK 原則：**同一時間只有一個來源在 push**；改 code 後 commit+push，別手動觸發 Actions（等 19:00 自動跑）。

---

## 6. 關鍵檔案速查

| 功能 | 檔案 | 重點 |
|------|------|------|
| TWSE 抓取 | `tools/fetch_twse.py` | **NEW 730fd4d：`chgPct` 改真百分比 `chg/(close-chg)*100`；多存 `chgAmt`** |
| fetch 主流程 | `tools/fetch_daily.py` | Step7 分點優先序；`MEMORY_ANCHORS=["2344","2408","6239","2327","1314"]`（NEW 加國巨/中石化）；staleness 源頭：只對前 40 fetch |
| 評分/黃金名單 | `core/golden.py` | `run()` / `_evaluate_gates`(G1-G5) / `_score_conviction` / `_tier_from_score` / `action_group()`（EXECUTABLE 判5%成本）/ **NEW `display_tier()`→可買進/增強/中** |
| 時序衍生 | `core/market_context.py` | `temporal_enrich()`（seq_windowed 含缺日算 strict/positive/net_accum；seq_present 算 velocity）+ `_strict_tail_streak`/`_positive_count_in_window`/`_window_sum` |
| 每股 ingest | `core/ingest.py` | SCHEMA_VERSION="1.8.0"；寫 main_force_strict_streak_days / positive_days_in_window / net_accumulation_in_window；scoring 仍 abstained。**不 import golden/fetch，故 golden/fetch 改動 replay 中立** |
| legacy adapter | `data/adapters/legacy.py` | today.json+branches+tdcc → raw；`change_pct` 讀 `row.chgPct`；⚠ branches 無 fetchDate 是陳舊根源 |
| 回測引擎 | `core/paper_trading.py` | `run_backtest(snaps, strategy)` 純函式，kind-aware，no-lookahead |
| 策略 config | `core/strategies.py` | STRATEGY_A/B v1/v2（dataclass，參數不寫死） |
| replay 驗證 | `tools/verify_all_replay.py` | epoch-aware：舊快照 legacy-epoch-clean（hash 鎖定） |
| 每日排程 | `tools/daily.py` | fetch→pipeline→verify→intel→backtest×4→log；`_trading_day_gate`（假日跳過）；`_fii_published()`（T86 未公布跳過） |
| 持倉判斷 | `core/holdings.py` | `evaluate_holdings()` — P/L + A/B 出場警示；viewer「💼 持倉」讀它 |
| 主 UI | `viewer/cockpit.py` | read-only 6-tab；黃金 badge/摘要/候補改用 `display_tier`；action 分組（可執行/等回檔/資料待補/動能轉弱）已存在 |
| canonical schema | `schema/canonical_schema.json` | 1.8.0（含 3 個窗口欄位） |
| 設定門檻 | `config/scd.example.yaml` | gates（含 cost_safety.max_premium_ratio=1.05、fii_alignment.contra_days_cap=2）；`lookback_window_days: 20` |

### 1.8.0 viewer 讀資料契約（沿用）
```python
_stock_streak(stock)                       # main_force_strict_streak_days
_stock_buy_days_in_window(stock)           # main_force_positive_days_in_window（缺=0）
_stock_buy_days_in_window_or_none(stock)   # 缺=None（表格顯示「—」）
_stock_net_accumulation(stock)             # net_accumulation_in_window，fallback weakening.net_cumulative
```
**規範**：任何要顯示 streak/net_accum 的地方用這幾個 helper，不再 `full_ticker_context()`。

---

## 7. 已知限制 / 待修

### ★ 高優先
**A. Branches 陳舊 bug（已止血、未治本）**
- 症狀：沒進當日分點前 40 的股，`branches/<ticker>.json` 沿用舊值假新鮮（國巨曾 6/18–6/30 mf 都 8836）。
- 已止血：國巨/中石化加進 MEMORY_ANCHORS。其他常追的股（記憶體族群等）若也會掉榜，同法加入。
- 治本 3 選項（待 Yonki 拍板）：
  * **A（建議）**：branches 加 `fetchDate`，ingest 讀到 ≠ 當日則 fallback 到 today.json 當日 buyVol。**bump schema 1.9.0**。
  * B：`main_force_buy` 定義改優先用 today.json 當日 buyVol，分點當補充。
  * C：fetch 範圍擴大到全 universe（評估 API 額度）。

**B. 剩 2 個 viewer render-time 重算未持久化**：`sponsorship` / `failed_breakout` 仍在 `full_ticker_context` 算。建議跟 1.9.0 一起寫回快照。

### 其他（已知，不急）
- **回測樣本仍小（6–16 筆）**：根本解是 universe 擴大 + 時間累積，不是策略問題。
- 多數回測交易是 `end_of_data`（窗口末端結算）非真出場 → 窗口加長改善。
- Sharpe 是「每筆交易」版、非年化；小樣本噪音大。
- 開盤價只 go-forward；歷史用收盤代理。
- **6/30、7/1 replay 紅字**：Mac建/linux驗跨平台指紋差異，RUNBOOK 說忽略、資料正確；observation-hash 契約會根治。
- `signal_age_days` vs「成熟確認 N 天」看似衝突，實為不同狀態機（前者=信心 tier 維持；後者=state machine state 維持），命名混淆非 bug。

---

## 8. 給下一個 AI 的 instructions（精簡）
1. 先讀本文件 + `docs/handoffs/` 內的 0701/0624 handoff + 記憶（`MEMORY.md`，特別是 `scd_changepct_tier_fixes_20260701`）+ `git log --oneline -20` + 跑 `make verify-all-replay`。
2. **所有 git / fetch 在 Yonki Mac 跑**；你給指令、他貼。**push 前先 commit**；改既有檔要「先 commit 再 restore/clean」。
3. 動 core 前確認沒違反 §0 紅線；新（進快照的）欄位要 bump schema + 顧 replay-safety（build 兩次 hash 要一致）。
4. viewer 新代碼**不得 render-time 重算衍生欄位**；分級用 `golden.display_tier`、streak/net 用 `_stock_*` helper。
5. 高風險決定（schema bump / 換 fetch 策略 / 放寬買點門檻）先攤給 Yonki 選。
6. 回測/績效：改完跑 `run_backtest`（4 策略 `--latest-only`）刷新。
7. Yonki 常請另一個 AI 對比 raw 資料——若不一致，**先確認時間差（是否同一天）+ 資料欄位定義（如 change_pct 曾是漲跌價差不是%）**，再懷疑 bug。
8. **絕不 `git remote -v` 印 token、絕不把 token 寫進檔案。**

---

## 附：閱讀順序 & 本 session commit
**閱讀順序**：本文件 → `docs/handoffs/MAITREYA_HANDOFF_20260701.md` → `docs/handoffs/MAITREYA_HANDOFF_20260624.md` → `ARCHITECTURE.md` → `RUNBOOK.md` → `CONTRIBUTING.md`。
（2026-07-02 文件整併：PROJECT_STATUS/CONTEXT_HANDOFF 已併入 ARCHITECTURE.md 後刪除；歷史 handoff 在 `docs/handoffs/`；歷史稽核規格在 `docs/archive/`。）

**本 session commit**：
```
730fd4d  fix: change_pct 真百分比 + 黃金分級改可買進/增強/中 + 國巨/中石化 anchors
```

*文件由 Claude Cowork 於 2026-07-02 session 整理。涵蓋：國巨黃金名單三根因診斷（change_pct 漲跌價差貼錯標籤 / branches 陳舊灌水 / 名單≠可買進）+ 分級改名 可買進/增強/中（action-aware）+ 國巨/中石化 anchors 止血 + token 資安處理 + 全 handoff/ARCHITECTURE/RUNBOOK/CONTRIBUTING 核心知識整合。*
