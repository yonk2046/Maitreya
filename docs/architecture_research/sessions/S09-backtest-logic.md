# Session 09 — Backtest / 績效驗證層

> 證據蒐集：opus，2026-07-10。§0–§4 證據草稿；§5 裁定留給 fable。
> 鐵律：先分析、後才談改；本報告不含任何 code 改動；證據一律附 `檔案:行號`。
> 本 session 是 9 個 session 的最後一個——**回測是全部落地欄位的最終消費者**，故消費一切在最後。

## §0 範圍與輸入

### 本 session 只看
- 引擎：`core/paper_trading.py`（385 行，確定性回測引擎，v1+v2）、`core/strategies.py`（策略 config）、`core/holdings.py`（持倉即時評估）
- CLI/工具：`tools/run_backtest.py`、`tools/scan_params.py`、`tools/render_backtest_report.py`
- 消費面：`viewer/cockpit.py` 模擬績效 tab（`_render_backtest` 3507-3658）、持倉 tab（`_render_holdings` 3434-3505）
- 排程：`tools/daily.py:396-411`（每日 backtest refresh）
- 測試：`tests/test_paper_trading.py`、`tests/test_holdings.py`、`tests/test_backtest_report.py`

### 讀過的證據來源（file:line / 實跑）
- `core/paper_trading.py:1-469` 全文（v1 引擎 108-282、v2 分批 319-469）
- `core/strategies.py:1-107`、`core/holdings.py:1-124`
- `tools/run_backtest.py:34-106`、`tools/scan_params.py:30-84`、`tools/render_backtest_report.py:24-234`
- `viewer/cockpit.py:3507-3658`（backtest tab）、`3434-3505`（holdings tab）、`3282-3349`（intelligence tab，屬 sidecar 稽核對照組）
- `tools/daily.py:396-411`
- 實跑 1：`python -m tools.run_backtest --strategy momentum_continuation --no-write` → 8 筆、勝率 50%、avg 2.3%、範圍 2026-05-08→2026-07-09
- 實跑 2：`python -m tools.run_backtest --strategy chip_anchored_swing --no-write` → 7 筆、勝率 71%、avg 3.2%
- 實跑 3（C11 測試）：`scan_params entry_streak_min 3,4,5` → 歷史交易數 8→4→3；`trailing_stop_pct 0.05,0.08,0.12` → 9→8→7
- 實跑 4：磁碟 42 份 dated snapshot；`reports/backtest/` 有 4 策略 `*_latest.json`＋舊 4M 報告；真快照 stock record 42 欄含 `open`（實值 50.5）、`fii_net_buy`、`main_force_buy`、`main_force_cost`、`weakening`（dict）、`tier`/`composite_score`（stub）
- grep 稽核：backtest 全鏈（paper_trading/holdings/run_backtest/scan_params）**零 `intelligence.json` / 零 sidecar import**

### 明確不看（留給哪個 session）
- golden 引擎內部門檻與 gate 語意 → S01（本 session 只看回測如何**消費/重算** golden）
- temporal_enrich / weakening 生產邏輯 → S02/S04（本 session 只看回測如何消費）
- intelligence.json 本體存廢 → 已由 S08 #46 判死；本 session 僅稽核 backtest 有無斷炊
- replay 等級定義本體 → S06（本 session 指出 backtest 產物落在 replay 之外）

---

## §1 這個模組真正要回答什麼問題？

回測層要回答一個而且只有一個問題：**「這套判斷（golden 名單 / 動能訊號 / 轉弱出場）如果在過去真的照做，會賺會賠？」**——把 SCD 的 Observation（資格/行動判斷）接上未來價格，量化成勝率/報酬/回撤/夏普，讓使用者**在改變策略參數或信任某條 gate 之前，先有歷史證據**。

它是整個系統的「判斷驗證回路」：Observation 層天天生產判斷，但判斷對不對，唯一的裁判是「照著做的損益」。因此回測是全部落地欄位的**下游總消費者**——理論上它該吃 snapshot 裡「當日認定」的判斷（as-was），把它接到次日成交價，算損益。

實際上（§3 詳述）它做的事更多也更雜：它**不只消費、還在回測當下重新生產**了一部分判斷（golden 名單、temporal 動能），因此同時是「消費者」與「第三個判斷計算點」（前兩個＝viewer render-time、pipeline 引擎；NOTES #2）。

下游決策：使用者在績效 tab 看勝率/回撤決定信不信某策略；用 `scan_params` 掃參數挑「甜點」（entry_streak 連 3 vs 連 5）；持倉 tab 用同一套出場邏輯對真實部位亮警示燈。

---

## §2 它屬於哪一層？（Raw / Observation / Derived / Classification / Presentation / Metadata；I/O/M）

回測層**跨了四層**，這正是 §3 的病灶所在：

| 部件 | 層 | I/O/M | 證據 |
|---|---|---|---|
| **回測結果本身**（trades/summary/勝率/回撤/夏普） | **Derived-O** | O（派生觀察，grain=strategy×window） | `paper_trading.py:54-70` `BacktestResult`；`_summarize` 242-274 |
| **成交價** current_price/open（次日 fill） | **Raw-I** | I（原始價格輸入） | `_fill_price` 82-87；快照 `open`/`current_price` |
| **chip 流入** fii_net_buy/main_force_buy/main_force_cost（進出場條件的原料） | **Raw-I** | I | `paper_trading.py:97,158,160,197` 直讀 rec |
| **weakening 出場訊號** | **Classification-O（已落地）** | O（as-was 消費，正確） | `_weakening_sev` 102-104 讀 `rec["weakening"]`；快照確有 weakening dict |
| **golden 名單**（chip 策略進場資格） | **Classification-O，但回測當下重算** ← 越層 | O，但非 as-was | `paper_trading.py:186,423` `_golden.run(snaps[:i+1])` |
| **temporal 動能**（velocity/acceleration/consecutive，動能策略進場） | **Derived-O，但回測當下重算** ← 越層 | O，但非 as-was | `paper_trading.py:202,439` `temporal_enrich(...)` |
| **策略規則**（門檻/權重） | **Config-M** | M（規則資料，正確外置） | `strategies.py:22-107`（規則在 config，非埋引擎——治理紅線遵守） |
| **回測 JSON 產物**（`*_latest.json`＋`.sha256`） | **Derived artifact，但落在 replay 契約之外** | O 產物，M 保證僅防竄改 | `run_backtest.py:97-105`；覆寫式、無版本維度 |

**跨層病根一句話**：回測該是「純消費 as-was 落地判斷 → 接價格 → 算損益」的 Derived-O 消費者；但因為判斷層未落地（NOTES #2：tier 全 IGNORE、composite_score 全 0、golden 不落 snapshot），回測被迫在消費時**用今天的 code + 今天的門檻重新生產歷史判斷**，於是把 Classification-O 的生產責任又扛了一份。

---

## §3 目前有哪些設計混亂或責任重疊？

### F1 🔴 **回測用「今天的 golden.py + 今天的門檻」重算歷史名單 = C11 陽性（參數 look-ahead）**
`paper_trading.py:186`（v1）與 `:423`（v2）對每個決策日 i 呼叫 `_golden.run(snaps[:i+1])`，即時重算「第 i 天誰在黃金名單」。引擎檔頭（`:9-13`）自稱「No look-ahead: decisions for day D use ONLY snapshots[:D+1]」——**資料切片確實無 look-ahead，但門檻與 code 有**。golden 門檻寫死在 golden.py（NOTES #26：conviction 權重 / tier 切點寫死 68-78），今天改了門檻，2026-05-08 的歷史名單、乃至整份回測損益會**無痕改變**。
- **實測 C11 測試**（改參數→歷史意見變否）：`scan_params entry_streak_min 3→4→5` 使歷史交易數 **8→4→3**、勝率 50%→50%→67%；`trailing_stop_pct 0.05→0.08→0.12` 使 **9→8→7**。歷史「照這套做會怎樣」隨參數整段位移，且產物只覆寫 `_latest.json`（`run_backtest.py:97-105`），改動無版本、無訊號。這正是 NOTES #29 C10 要治的「history 由落地序列派生」的反面：回測未讀落地序列，而是拿今日引擎回放歷史。

### F2 🔴 **混合出處回測：一半判斷 as-was 落地讀、一半回測當下重算**
同一次回測裡，**出場**訊號 weakening 讀的是 snapshot 落地的 as-was 值（`:164` `_weakening_sev(rec)`，正確）；但**進場**資格 golden（`:186`）與動能 temporal（`:202`）是回測當下重算。於是損益歸因建立在「當日真實看到的轉弱」＋「今日回算的進場名單」兩種時間基準的混血上。哪些判斷可信、哪些會隨門檻漂移，使用者無從分辨。根因同 §2：落地不齊全，能讀的讀、不能讀的只好算。

### F3 🔴 **universe = 買超榜 → 持股跌出榜即「隱形凍結」（survivorship / 覆蓋缺口）**
snapshot.stocks 只含當日買超 top-N 榜的股票。管理持倉時 `paper_trading.py:153-154`（v1）、`:343-344`（v2）：`price = rec.get("current_price") if rec else None; if price is None: continue`——一旦持股跌出榜，`_rec_for` 回 None，該部位**既不更新 peak、也不評估出場、也不 MTM**，靜默凍結直到它重新上榜或走到 `end_of_data`。真實世界「主力棄守、跌出榜」往往正是最該停損的時刻，回測卻在此刻失明。這是 NOTES #41「母體＝榜非市場」的病在回測層的爆發：跌出榜的下跌段被系統性排除在損益之外，勝率/回撤偏樂觀。`holdings.py:50-57` `_seq` 同構（只收 ticker 在場的 record）。

### F4 🟡 **出場判斷有三個實作，且未共用 config（雙實作漂移第 10 例，NOTES #36 pattern）**
同一套「轉弱 orange/red 出、主力連 2 賣、外資連 2 反向、回落 8%」出場邏輯被寫三遍：
1. `paper_trading.py:164-174`（v1 回測引擎）
2. `paper_trading.py:363-381`（v2 引擎，又一份）
3. `holdings.py:82-96`（真實持倉即時警示）——**硬編碼** `len(fii)>=2 ... <0 and <0`（連 2），未讀 `strategy.fii_reversal_days`；只借用 `STRATEGY_B.trailing_stop_pct`（`:92`）一個常數。
若改 `fii_reversal_days`，回測會變、持倉警示不會變——同一「出場」概念三處各活，config 化只覆蓋了一部分。

### F5 🟡 **回測產物落在 replay 契約之外：夜夜重算、覆寫、無版本維度**
`daily.py:396-411` 每晚重跑 backtest，`run_backtest.py:97-105` 覆寫 `<strategy>_latest.json`＋寫 `.sha256`。但這個 sha256 只是**單檔防竄改**，不進 `canonical_sha256` 主快照、不進 archive、無版本維度。後果：schema bump（NOTES #17：每 bump full-replay 歸零）或門檻改動時，`_latest.json` **靜默變一份新的**，昨天給使用者看的績效與今天不同、無 diff、無留檔。以 NOTES #21「Replay Guarantee Strength」軸衡量，回測產物是「不可驗」級——卻是使用者拿來做策略決策的東西。

### F6 🟡 **出貨中的 `limitations` 字串是假的(stale falsehood)**
`paper_trading.py:120` 硬寫 `"settlement uses next-day close as open-price proxy (snapshots carry no open)"`，實跑 `momentum_continuation_latest.json` 的 limitations 也照登此句。但快照**現在確有 `open`**（實測 open=50.5），`_fill_price:87` 也已 `rec.get("open") or rec.get("current_price")` 優先用 open。於是報告向使用者宣告一個早已不成立的限制——舊快照無 open 為真、新快照為假，字串未隨資料演進更新，混合窗成了單一謊言。

### F7 🟡 **績效 tab 現況＝「活 code 死輸出」（同 S03 distribution #38 病型的較輕版）**
`cockpit.py:3510` `_BACKTEST_MIN_TRADES = 30`：未達 30 筆只顯示進度條。實跑真資料 4 策略全在 7–9 筆 → **整個績效 tab 目前對使用者只顯示「樣本累積中」，零 KPI**。引擎每晚跑、JSON 每晚寫，但因 universe 太窄（§3-F3 榜母體）＋窗口短，成品長期到不了顯示門檻。門檻本身（避免小樣本誤導）是對的；病在上游 universe 覆蓋讓它幾乎永遠達不到。

### F8 ✅（非病，登記為正面對照）**backtest 全鏈零 sidecar 消費——sidecar 判死無斷炊**
grep 稽核：`paper_trading.py`、`holdings.py`、`run_backtest.py`、`scan_params.py` 的 import 只有 golden / temporal_enrich / strategies / hashing，**零 `intelligence.json`、零 sidecar 讀取**。回測的判斷原料全來自 dated snapshot（reports/*.json）。intelligence.json 的唯一消費者是 `cockpit.py:3282,3329` 的「今日情報」tab（S08 presentation 領域，已隨 #46 判死）——那是與回測**平行**的展示面，非回測依賴。**結論：S08 #46 判死 sidecar，backtest 層無任何斷炊面。**（附帶證據：intelligence_delta 錯 key 死事件 #43 也只污染情報 tab，不進回測。）

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？（提案，不執行）

### 理想態：回測是純粹的 as-was 消費者
- **輸入**：① 落地判斷序列（obs_golden_tier/conviction/action_group、obs_sm_state/transition_risk、obs_chip_grade、weakening——即 S01–S04/S07 核准的 17 欄，逐日 as-was）；② Raw-I 價格（open/current_price）；③ Config-M 策略規則（單一來源）。
- **輸出**：Derived-O 損益報表（trades/summary），grain=strategy×window，帶「每筆交易引用了哪些落地欄位＋哪個 snapshot 版本」的 provenance。
- **絕不做**：① 絕不在回測當下重算歷史判斷（不呼叫 `golden.run` / `temporal_enrich` 回放歷史——改讀落地 `obs_golden_tier` 序列）；② 絕不用「今天的門檻」評價「過去的一天」；③ 絕不覆寫式產出無版本產物。

### 現況 → 理想的差距表

| # | 現況 | 理想 | 依賴 |
|---|---|---|---|
| 1 | 進場 golden/temporal 回測當下重算（F1/F2） | 讀落地 obs_golden_tier / obs_sm_* / temporal as-was 序列 | **前置：17 欄落地**（S01 #26/#27、S04 #30、S02 #35）＋門檻 config 化（#33） |
| 2 | 資格 vs 行動混用不分（進場吃 golden 名單） | 依 S01 #27：回測消費名單須明示用**資格(tier)** 還是**行動(action_group=5%鐵則+weakening)**——現 chip 策略進場＝資格 gate＋現價≤成本×1.05（行動閾），已隱含兩者但未命名分層 | S01 #27（已立法，回測直接引用） |
| 3 | universe=榜，跌出即凍結（F3） | 需 obs 之外的全市場價格母體（跌出榜後仍能 MTM/停損）——即 NOTES #41 的市場母體資料 | S07 #41 母體修正（market_pulse 收編全市場）＝回測正確性前置 |
| 4 | 出場邏輯三份實作、config 部分覆蓋（F4） | 出場判斷單一 SoT：回測與 holdings 共用同一 strategy config＋同一評估函式 | 遷移 checklist（引 #36 單一取值來源紀律） |
| 5 | 產物夜夜覆寫、無版本、無 replay（F5） | 回測產物帶 schema 版本＋輸入 snapshot 版本指紋；version-pinned，可復現「當時給我看的績效」 | S06 #21/#22（Replay Guarantee Strength、version-pinned replay） |
| 6 | limitations 字串硬寫、已成謊（F6） | limitations 由實際資料/程式碼路徑派生（有 open 就不宣告無 open） | 遷移期順手 |

### 一句話理想邊界
17 欄落地後，回測應退化成一個**薄消費者**：讀 as-was 落地判斷序列＋價格，套 config 規則，吐 version-pinned 損益——**不算判斷（零 golden.run/temporal 回放）、不裝判斷、不寫無版本產物**。這與 S08 #45 對 cockpit 的「不算/不裝/不寫」四紅線同構——回測是四紅線的最後一個適用者。

---

## §5 裁定（fable 填）

（留空）

## §6 收尾 checklist
- [ ] CROSS-SESSION-NOTES 已 append 本 session 新發現（下表待 fable 裁定後併入）
- [ ] 00-INDEX 狀態列已更新（證據包/裁定/報告連結）
- [x] 未執行任何 code/schema 改動

---

## 跨 session 事項（待裁定後 append 到 CROSS-SESSION-NOTES；本檔不直接改該檔）

| # | 發現 | 嚴重度 | 歸屬 | 狀態 |
|---|---|---|---|---|
| 48 | **回測重算歷史判斷＝C11 陽性（參數 look-ahead）**：`paper_trading.py:186,423` 每決策日 `_golden.run(snaps[:i+1])`、`:202,439` `temporal_enrich` 用今日 code+今日門檻回放歷史；實測改 entry_streak_min 3→5 歷史交易 8→3、改 trailing_stop 0.05→0.12 為 9→7，歷史意見無痕整段位移。治法＝17 欄落地後改讀 as-was 落地序列（C10 #29「history 由落地序列派生」的回測面實作） | 🔴 correctness | S09/遷移案（依賴 S01#26/S04#30/S02#35 落地＋#33 門檻 config 化） | 待裁定 |
| 49 | **混合出處回測**：同一回測出場讀 as-was 落地 weakening（`:164`，正確）但進場重算 golden/temporal（F2），兩種時間基準混血做損益歸因。落地齊全前無法統一 | 🔴 correctness | S09 | 待裁定 |
| 50 | **universe=榜→持股跌出即隱形凍結**：`paper_trading.py:153-154,343-344` `price is None: continue`，跌出 top-N 榜的部位不 MTM/不停損/不出場，勝率回撤偏樂觀。NOTES #41 母體病的回測層爆發——**回測正確性依賴 S07 #41 市場母體修正** | 🔴 correctness | S09/S07#41 | 待裁定 |
| 51 | **出場判斷三實作、config 部分覆蓋（漂移第 10 例）**：paper_trading v1(`:164`)、v2(`:363`)、holdings(`:82-96` 硬編碼連2、未讀 fii_reversal_days)。遷移 checklist 需納入「出場判斷單一 SoT」 | 🟡 漂移 | S09/遷移 checklist（引 #36） | 待裁定 |
| 52 | **回測產物在 replay 契約之外**：`daily.py:396` 夜夜重算、`run_backtest.py:97` 覆寫 `_latest.json`、sha256 僅單檔防竄改、無版本維度；schema bump/門檻改則產物靜默變。以 #21 Replay Guarantee Strength 衡量＝「不可驗」級卻供決策 | 🟡 replay | S09/S06#21#22 | 待裁定 |
| 53 | **sidecar 判死無斷炊（正面結論）**：backtest 全鏈零 intelligence.json/sidecar 消費，判斷原料全來自 dated snapshot；#46 判死 sidecar 對回測零影響。intelligence tab（cockpit:3282）是平行展示面非回測依賴 | ✅ 稽核結論 | S09（回覆 #46 開工前提） | 已證實 |
| 54 | **績效 tab 活 code 死輸出**：`cockpit.py:3510` 30 筆門檻，真資料 4 策略全 7–9 筆→整個 tab 只顯示進度條、零 KPI。門檻正確，病在上游 universe 覆蓋（#50）＋窗口短使其幾乎永不達標 | 🟡 呈現 | S09/S07#41 | 待裁定 |
| 55 | **出貨 limitations 字串已成謊**：`paper_trading.py:120` 宣告「snapshots carry no open」，但快照現有 open(實測 50.5)且 `_fill_price:87` 已優先用 open。字串未隨資料演進更新 | 🟢 誠實性 | S09/遷移期順手 | 待裁定 |
