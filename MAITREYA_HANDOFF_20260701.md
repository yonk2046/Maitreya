# Maitreya 交接文件 — 2026/07/01(P2.5 + Schema 1.8.0 · 完整)

> 交接對象:任何下一個 AI session(Claude Cowork / Cursor / Claude Code)
> Repo:`yonk2046/Maitreya` · Viewer:Streamlit Cloud 自動部署(cockpit.py)
> 本機路徑:`/Users/yoncky/SCD engine/Ai stock/`
> 作者:Yonki + Claude Cowork · 整理日:2026-07-01
> 下一個 session 請先讀此文件 + `MAITREYA_HANDOFF_20260624.md` + `git log --oneline -20` + `make verify-all-replay`

---

## 0. 系統定位(必讀,同 6/24 handoff)

**Maitreya** = TWSE 股票的決定論狀態偵測引擎(SCD = Stock Condition Detection)。

哲學:**籌碼 > 心理 > 消息 > 預測**。不預測,只偵測「主力正在做什麼」的客觀狀態。
紀律:連買 <3 日不進場;現價 ≤ 主力成本 ×1.05;空手是獲利的一部分;止損/TP 由籌碼定義。

### 架構四層
```
data/adapters/   原始資料 → 標準化 adapter_output(legacy / rollup / tdcc adapter)
core/            純函數:ingest, scoring(golden), state_machine, market_context, paper_trading
viewer/          Streamlit read-only cockpit(不含業務邏輯)
tools/           CLI:run_pipeline, daily, fetch_*, run_backtest, scan_params, backfill_range
```

### ⛔ AI_GOVERNANCE 紅線(違反即拒絕)
1. `viewer/` 不得含業務邏輯——偵測/計分/分級在 `core/` 計算,viewer 純渲染。**7/1 已強化:viewer 不再 render-time 重算衍生欄位,一律讀 snapshot。**
2. 新欄位走 schema → core → viewer 順序。
3. `core/` 不寫死數字門檻 → 放 `config/scd.example.yaml`。
4. `reports/_raw_archive/<date>/` 是 WORM,禁改。
5. NEVER 輸出 GitHub token(ghp_*)。
6. P3b 已解鎖(2026-06-24)——可動 scoring / 新增欄位。改既有快照欄位仍要 bump schema + 顧 replay。

---

## 1. 目前 Phase 狀態(2026-07-01)

- **Schema 版本:v1.8.0**(6/29 從 1.7.0 bump,前後端衍生欄位一致化)
- **黃金名單引擎**:`core/golden.py` 每天即時算,產出真實 prime/strong/qualified 名單。目前(6/29 snapshot)產出約 30 檔黃金
- **P2.5 tab 重構完成**:12 → 6 tab,心智模型「我有什麼 → 該不該出 → 能不能進 → 為什麼 → 深入 → 驗證」
- **回測引擎每日自動刷新**:daily pipeline 末段跑 4 策略 backtest → `reports/backtest/<strategy>_latest.json`;viewer 讀檔,樣本 <30 顯示進度條
- **資料覆蓋**:快照 2026-05-08 → 2026-06-29(≈35 個);早期稀疏(4-8 檔/日),5/26 後 26-43 檔/日;每日 universe ≈ 榜單+權值 ≈40 檔(非全市場)
- **回測進度**:B 動能 13/30、A 籌碼 6/30、A v2 11/30、B v2 16/30(2026-06-29 快照跑出)

---

## 2. 本 session(2026-07-01)完成的工作

### 2A. P2.5 Tab 重構(12 → 6)· commit 6ebb67a

新分頁結構:
| 新 tab | 合併原本 | 對應問題 |
|--------|----------|----------|
| 💼 我的持倉 | 持倉 | 我有什麼 + 出場警示 |
| ★ 進場機會 | 黃金名單 + 轉強訊號 | 能不能進 |
| 🔻 出場警示 | 轉弱出貨 + 假突破 | 該不該出 |
| 📊 市場全景 | 今日綜述 + 市場體制 + 雷達 + 資金輪動 | 為什麼 |
| 🔬 深度研究 | 持續吸籌 + 時序演化 + 信心風險 | 想深入 |
| 📈 模擬績效 | 新分頁(讀 backtest latest.json) | 驗證 |

viewer/cockpit.py 用 `st.markdown('<hr>...')` + 小標題疊在同分頁內。

### 2B. 籌碼動能改「證據列表」+ 移除 Prime 標籤 · commit 6ebb67a

**問題**:原本卡片顯示「籌碼動能 24/24 強」,但分母浮動(缺資料項不計),同分母下數字無比較意義。且 🏛 Institutional Prime / 🔥 Momentum Prime / 🌱 Emerging Prime 三標籤 Yonki 覺得無實質意義。

**修法**:
- 卡片露「強度」標籤(強/中/弱 + 色球),不再露分子/分母
- 展開卡片後有「Chip Momentum Evidence · 籌碼動能證據」區塊,列 6 項 ✓/△/—:
  * ✓ 買超占成交量 14%
  * ✓ 連續買超 7 天(嚴格)
  * ✓ 主力成本 +3%
  * ✓ Velocity ↑
  * △ 法人未同步
  * — TDCC 未接入
- 有窗口鬆語意時多顯示「窗口買超 13/20 天(高頻吸籌)」
- Prime 三標籤刪除

### 2C. 回測接進 daily pipeline + 樣本門檻 gate · commit 6ebb67a

- `tools/run_backtest.py` 新增 `--latest-only`(寫 `<strategy>_latest.json` 固定檔名)+ `--source=backfill`(讀 backfill 沙盒)
- `tools/daily.py` 末段跑 4 策略回測(非阻塞):`chip_anchored_swing` / `momentum_continuation` / `chip_anchored_v2` / `momentum_v2`
- `viewer/cockpit.py` 新增 `_render_backtest()`:讀 latest.json,樣本 <`_BACKTEST_MIN_TRADES=30` 顯示累積進度條;達標顯示 KPI(勝率/平均報酬/Sharpe/最大回撤/平均持有)

### 2D. 歷史回補沙盒 · commit 6ebb67a

**背景**:Yonki 希望回補 2 個月歷史跑完整回測,但 Fubon 分點(主力排名)**無歷史 API**。硬回補會用 T86 自營商代理,污染 A 策略結果。決策:另闢沙盒,不污染主 archive。

- 新增 `tools/backfill_range.py`:讀範圍逐日呼叫 `fetch_history` + 塞 `paths_override` 跑 `adapt_legacy` + `ingest`,寫入 `data/backfill/snapshots/<date>.json`
- 每筆 backfill snapshot 標記 `_provenance: "historical_reconstruction"` + `_backfill_note`
- **絕不寫**:`data/snapshots/`、`reports/<date>.json`、`reports/_raw_archive/`、`reports/index.json`
- **不參與**:`verify_all_replay` 鏈
- `.gitignore` 排除 `data/backfill/staging/`、`data/backfill/history/`、`data/backfill/snapshots/`、`reports/backtest/backfill/`(Yonki 決定要不要 commit)

用法(Mac):
```bash
python -m tools.backfill_range --from 2026-04-01 --to 2026-05-25
python -m tools.run_backtest --strategy momentum_continuation --source=backfill --latest-only
```

### 2E. 前後端衍生欄位不一致 → bump 1.8.0 · commit 56dd4a7 + 3d8898c + 7f8c2af

**Bug**(Yonki 提供的 reports/2026-06-29.json 對比):
- 合庫金 5880 前端顯示「連買 14 日」,JSON `main_force_consecutive_days = 4`
- 精成科 6191 前端 4 日,JSON = 2
- 淨累計:前端有值(+283,698)、JSON 沒欄位
- 違反 AI_GOVERNANCE 紅線 #1

**根因**(我實跑 `full_ticker_context` 對 33 個快照確認):
1. **窗口不同**:backend `config: lookback_window_days: 5`(只看最近 5 天);frontend `full_ticker_context` 對全 viewer 載入的 33 個快照跑 `accumulation_velocity`
2. **缺日處理不同**:backend `temporal_enrich` 建 seq 時跳過絕於 universe 的日;frontend 塞 None,而 `accumulation_velocity` 的 streak loop 對 None 是**透明的**(既不算又不破),於是 None-None-(+) 會把後面的正值一併計入 streak → 5880 = 13

**修法**:
- **`core/market_context.py`**:新增 helpers
  * `_strict_tail_streak`:嚴格連續(任何 None 或非正值都中斷)
  * `_positive_count_in_window`:窗口內正值天數(忽略 None,不要求連續)
  * `_window_sum`:窗口內 mf_buy 累計
- `temporal_enrich` 改用 `seq_windowed`(含 None 缺日)算 strict/positive/net_accum;`seq_present`(僅 present 日)算 velocity/acceleration(維持原語意)
- **`core/ingest.py`**:寫入三個新欄位到 snapshot
  * `main_force_strict_streak_days`(嚴格連續)
  * `main_force_positive_days_in_window`(窗口內買超天數)
  * `net_accumulation_in_window`(窗口內累計)
  * 兼容:保留 `main_force_consecutive_days` = strict 語意的別名(paper_trading 等下游無感)
- **`config/scd.example.yaml`**:`lookback_window_days: 5 → 20`(前後端統一)
- **`schema/canonical_schema.json`**:加 3 個新欄位
- **`viewer/cockpit.py`**:
  * 新增 3 個 helper:`_stock_streak` / `_stock_buy_days_in_window` / `_stock_net_accumulation`(+ 帶 `_or_none` 版避免 1.7.0 舊快照顯示 0/20)
  * 6 個 render 站點改讀 snapshot,不再 `full_ticker_context` 重算 streak/net
  * 只剩 sponsorship / failed_breakout 仍走 ctx(那兩個未持久化,屬 P2 後續工作)
- **`SCHEMA_VERSION: 1.7.0 → 1.8.0`**;舊 1.7.0 快照走 `legacy-epoch-clean`(hash 鎖定,不重 replay)

**驗證**:
- 242 tests pass
- `verify_all_replay` 33 dates legacy-epoch-clean(新 1.8.0 等 Mac pipeline 跑出後才有 full-replay-clean)
- 模擬 6/26 ingest:5880 strict=4 / positive_days=13 / net=+276,983,前後端數字對得起來

### 2F. 「窗口買超」鬆語意加入卡片 · commit 3d8898c + 7f8c2af

- 黃金卡「主力連買」格:strict>positive 才顯示「4日 · 窗13」(相等時省略)
- 籌碼證據列表加一行「窗口買超 13/20 天(高頻吸籌/中頻/偶現)」
- 轉強訊號表加「窗口買(日)」欄
- 持續吸籌表「買超(日)」改「13/20」格式
- 時序演化單檔頁 3 metric → 4 metric(strict / window / net / sponsor)
- 1.7.0 舊快照缺欄位 → 顯示「—」不是 0/20

### 2G. 6/30 資料對比別的 AI(未修 bug,只是發現)

Yonki 問另一個 AI 對 6/30 raw 資料的分析和 viewer 有出入,追出 3 層差異:
1. **國巨 2327 我們早就排除了**(tier=IGNORE,不在 golden list)- 不是 bug
2. **時間差**:另一個 AI 看 6/30、我們最新 6/29(今晚 launchd 19:00 才跑 6/30)
3. **真 bug(未修)· 資料陳舊**:
   - `data/branches/<ticker>.json` **沒有 tradingDate/fetchDate 欄位**
   - `fetch_daily.py` 只對「今日分點榜前 40 + Tier-A + 記憶 + 前日黃金」fetch 分點
   - 若某股沒進今日這批清單,branches 檔案不更新,ingest 讀進去當「今日 main_force_buy」用 → 假新鮮
   - 例:國巨 2327 6/18 mf=8836、6/25 mf=8836、6/29 mf=8836(完全相同)
   - 中石化 1314 6/22 mf=21792、6/24 mf=21792(6/23 沒進 universe,6/24 用回 6/22 值)
   - 另一個 AI 看 6/30 中石化 +25,989,我們最新 6/29 是 10,126,除了時間差還有這個 staleness

**未修**——等 Yonki 決策。3 個修法選項見 §7。

---

## 3. 策略邏輯(同 6/24 handoff,無改動)

**A 籌碼錨定波段** `chip_anchored_swing` v1/v2 · **B 動能延續** `momentum_continuation` v1/v2

進場/出場邏輯見 20260624 handoff §3。

---

## 4. Roadmap

### 🟢 現在進行中(被動)
- **讓資料自然累積**。每日 pipeline 跑,樣本厚了 backtest 才有意義。B 目前 13/30,約 7 月中破 30。
- 明日(2026-07-02)首個 1.8.0 snapshot 產生 → viewer 顯示「4 日 · 窗13」等新窗口語意生效。

### 🔴 主要任務(下一步)
1. **修 branches 陳舊問題**(§7 詳述,3 個修法選項待 Yonki 拍板)
2. **擴大每日 universe**(仍是 backtest 樣本瓶頸的根本解)
3. **持久化 sponsorship / failed_breakout**(viewer 剩 2 個 render-time 重算,同類 AI_GOVERNANCE 問題)

### 🟡 次要任務
- 「📈 模擬績效」再放權益曲線和分批 breakdown(目前只 KPI + 進度條)
- P2.5 tab 分組看膩了想調就調(結構已可用)

### ⬜ 遠期
- **Phase 2:observation-hash 契約**(H3/replay 穩定一個月後)—— 6/24 handoff 說明
- 諧波(YHAF/Gartley…)—— 範圍外,`paper_trading` 有 `entry_filter_hook` 備用

---

## 5. 重要指令 / 工作流程(同 6/24)

### 常用指令
```bash
make daily               # 完整每日流程(fetch → ingest → verify → backtest → log,不 auto push)
make daily-skip-fetch    # 用現有 data/ 重建
make verify-all-replay   # 全 archive replay
make test                # pytest 全套
make cockpit             # Streamlit :8502
python -m tools.run_backtest --strategy chip_anchored_swing --latest-only
python -m tools.run_backtest --strategy momentum_continuation --source=backfill --latest-only
python -m tools.backfill_range --from 2026-04-01 --to 2026-05-25
python -m tools.scan_params --param entry_streak_min --values 3,4,5
python -m tools.render_backtest_report        # 刷新 report.html
```

### ⚠️ 環境限制(給 AI:很重要)
- **沙箱(Cowork/Claude Code)不能 push、不能寫 git**(`.git/*.lock` unlink 失敗)。所有 git 操作在 Yonki 的 Mac Terminal 跑
- 沙箱 bash 跑在 **Linux** → 正好可重現 GHA 的 replay
- 沙箱**連不到 TWSE/Sinotrade/TDCC** → fetch 只能在 Mac 跑
- 沙箱**刪不掉已追蹤檔** → 要刪用 `git rm`(Mac)
- 沙箱寫檔到 workspace 沒問題(改 viewer/cockpit.py 這類)

### ⚠️ Git 工作流教訓
1. **先 commit 程式碼,再 restore/clean**(否則洗掉未 commit 改動)
2. push 常被擋(non-fast-forward)因為兩條 pipeline 自動 commit → `git fetch` + `git merge origin/main` 再 push
3. 別清 `reports/backtest/` 和根目錄 `.md`
4. 若 `.git/index.lock: File exists` → 檢查 `ps aux | grep git` 確認沒真的在跑,再 `rm -f .git/index.lock`(本 session 遇過)

### 兩條 pipeline(OPS-1)
- **主**:本機 launchd 每交易日 19:00(Mac,darwin 建檔)
- **備**:GHA `daily.yml` 週一~五 20:00(linux),有 skip-guard

---

## 6. 關鍵檔案速查

| 功能 | 檔案 | 重點 |
|------|------|------|
| 時序衍生 | `core/market_context.py` | `temporal_enrich()`(1.8.0:seq_windowed 含缺日算 strict/positive/net_accum;seq_present 算 velocity)+ `_strict_tail_streak` / `_positive_count_in_window` / `_window_sum` helpers |
| 每股 ingest | `core/ingest.py` | SCHEMA_VERSION="1.8.0";寫入 main_force_strict_streak_days / main_force_positive_days_in_window / net_accumulation_in_window;`main_force_consecutive_days` 保留為 strict 別名 |
| 評分/黃金名單 | `core/golden.py` | `run()` / `_evaluate_gates`(G1-G5) / `_score_conviction` / `_tier_from_score` |
| 回測引擎 | `core/paper_trading.py` | `run_backtest(snaps, strategy)` 純函式,kind-aware,no-lookahead |
| 策略 config | `core/strategies.py` | STRATEGY_A / STRATEGY_B v1/v2(dataclass) |
| replay 驗證 | `tools/verify_all_replay.py` | 1.8.0 epoch:舊 1.7.0 快照 legacy-epoch-clean(hash 鎖定) |
| legacy adapter | `data/adapters/legacy.py` | today.json+branches+tdcc → raw;⚠ branches 檔案無 fetchDate 是資料陳舊根源 |
| 每日排程 | `tools/daily.py` | fetch→pipeline→verify→intel→**backtest×4**→log;`_trading_day_gate`(假日跳過);`_fii_published()`(T86 未公布跳過) |
| fetch 主流程 | `tools/fetch_daily.py` | Step7 分點只對前 40 fetch → 是 staleness bug 的源頭 |
| TWSE 抓取 | `tools/fetch_twse.py` | MI_INDEX20(close)+MI_MARGN+STOCK_DAY_ALL(open) |
| 歷史回補 | `tools/backfill_range.py`(NEW) | 沙盒模式,寫入 data/backfill/snapshots/;不動 main archive |
| 回測 CLI | `tools/run_backtest.py` | `--latest-only`(寫 <strategy>_latest.json)+ `--source=backfill` |
| 績效顯示 | `viewer/cockpit.py` `_render_backtest()` | 讀 reports/backtest/*_latest.json,min_trades=30 gate |
| 持倉判斷 | `core/holdings.py` | `evaluate_holdings()` — P/L + A/B 出場警示 |
| 持倉資料 | `data/holdings.json` | 使用者手填 {ticker,name,shares,cost} |
| canonical schema | `schema/canonical_schema.json` | 1.8.0 新增 3 個欄位 |
| 設定門檻 | `config/scd.example.yaml` | `lookback_window_days: 20`(1.8.0 從 5 bump)|

### 1.8.0 新的 viewer 讀資料契約
```python
# viewer/cockpit.py 頂端 helpers
_stock_streak(stock)                       # main_force_strict_streak_days,回 int
_stock_buy_days_in_window(stock)           # main_force_positive_days_in_window,回 int(缺=0)
_stock_buy_days_in_window_or_none(stock)   # 同上但缺=None(給表格顯示「—」)
_stock_net_accumulation(stock)             # net_accumulation_in_window,fallback 到 weakening.net_cumulative
```
**新規範**:任何要在 viewer 顯示 streak/net_accum 的地方,一律用這幾個 helper,不再 `full_ticker_context()`。

---

## 7. 已知限制 / 待釐清

### ★ 高優先(下一個 session 值得處理)

**A. Branches 資料陳舊 bug**(2G 節詳述)
- 症狀:國巨 6/18/6/25/6/29 mf 都是 8836,中石化 6/22 和 6/24 都是 21792
- 根因:branches JSON 無 fetchDate,fetch_daily 只對前 40 名 fetch → 沒進榜的股用舊值
- 3 個修法選項:
  * **A(短期,建議先做)**:branches JSON 加 `fetchDate`,ingest 讀時若 fetchDate ≠ 當日則 fallback 到 today.json 的 buyVol。**要 bump schema 1.8.0 → 1.9.0**(main_force_buy 值會變)
  * **B(中期)**:改 `main_force_buy` 定義優先用 today.json 的當日 buyVol,分點 totalBuyVol 當補充
  * **C(長期)**:fetch 範圍擴大到「今日所有 universe」;要評估 Fubon API 額度

**B. 剩 2 個 viewer render-time 重算未持久化**
- `sponsorship`(用於贊助分)、`failed_breakout`(假突破)還在 `full_ticker_context` 裡算
- 影響比 streak 小(它們不隨 viewer window 大小變),但同類 AI_GOVERNANCE 問題
- 建議一併寫回 snapshot(schema 1.9.0 順便一起)

### 其他限制(已知,不急)

- **回測樣本仍小(6-16 筆)**:根本解是 universe 擴大 + 時間累積
- 多數回測交易是 `end_of_data`(窗口末端結算)非真出場 → 窗口加長改善
- Sharpe 是「每筆交易」版、非年化;小樣本噪音大
- 開盤價只 go-forward;歷史用收盤代理
- 力成/華邦電等記憶體股每日進出榜 → 已用 `MEMORY_ANCHORS` 抓分點
- **`signal_age_days` vs 「成熟確認 N 天」看起來衝突,但實際是不同狀態機**(前者=信心 tier 維持;後者=state machine state 維持)—— 命名混淆,不是 bug。要改善需 viewer 標籤區分清楚

---

## 8. 給下一個 AI 的 instructions(精簡)

1. 先讀此文件 + `MAITREYA_HANDOFF_20260624.md` + 記憶(`MEMORY.md`) + `git log --oneline -20` + 跑 `make verify-all-replay`(沙箱 linux,等同 GHA)
2. 所有 git/fetch 在 Yonki Mac 跑;你給指令,他貼
3. 動 core 前確認沒違反 §0 紅線;新欄位要 bump schema + 顧 replay-safety(見 §2E 案例)
4. **viewer 新代碼不得 render-time 重算衍生欄位**;用 `_stock_streak` 等 helper 讀 snapshot
5. 高風險決定(schema bump / 換 fetch 策略等)先攤給 Yonki 選
6. 回測/績效:改完跑 `run_backtest`(4 個策略 `--latest-only`)刷新
7. Yonki 有時會請另一個 AI 對比 raw 資料,若不一致先確認**時間差(對比日期是否同一天)**再懷疑 bug

---

## 附:本 session commit 歷史

```
7f8c2af  fix(viewer): 1.7.0 舊快照「窗口買超」顯示「—」避免假 0/20
3d8898c  feat(viewer): 黃金卡/表格/時序頁加上「窗口買超」鬆語意輔助
ab1ee00  merge before 1.8.0 ship
56dd4a7  fix(data): 前後端衍生欄位一致化 + bump schema 1.7.0→1.8.0
83ed784  data: daily pipeline 2026-06-29 [skip ci]
0bc65cf  data: daily pipeline 2026-06-28 [skip ci]
704d4fe  data: daily pipeline 2026-06-27 [skip ci]
6f1014b  merge before P2.5 ship
6ebb67a  feat(viewer): P2.5 tab 重構 12→6 + chip momentum 改證據列表 + 移除 Prime 分類
```

*文件由 Claude Cowork 於 2026-07-01 session 整理。涵蓋:P2.5 tab 重構 + chip evidence + backtest 自動化 + backfill 沙盒 + schema 1.8.0(前後端一致化)+ 窗口鬆語意 + branches staleness bug 發現(未修)。*
