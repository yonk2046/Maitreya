# Session 04 — State Machine（證據包）

> 蒐證者：opus（獨立 session，照 SESSION-TEMPLATE §0–§4 填草稿）。
> 前提：本報告只分析、蒐證，**未改任何 code/schema**；§5 裁定留給 fable。
> 承接：S05 §5 RC-1／NOTES #12（呈現給使用者 or 被 backtest 消費的 observation 必落 snapshot；**個別引擎落地清單由 S01–S04 各自在 Q4 列舉**）；S06 §5／NOTES #21-22（「Replay Guarantee Strength」正交軸＋「每次 schema bump 讓歷史 full-replay 保證歸零」的排程代價）；S01 §5／NOTES #24-27（C8 組裝權、C9 可純派生者不落地、資格 vs 行動＝兩種 O 態，S04 提供 weakening/transition_risk 材料時知道下游是行動層）。
> 已鎖決策（不重議，見 NOTES #9 / 00-INDEX）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0、fii cap 維持 2 天。

---

## §0 範圍與輸入

**只看：** 時序狀態機引擎本體 —
- `core/state_machine.py`（全檔 1007 行：狀態鍵/門檻常數、TickerState/StateTransition/MarketStateSummary dataclass、`_assign_state`、`_raw_state_seq`、`_commit_states`、`_build_state_history`、`_compute_risk`、`compute`、`run_all`、`state_summary`）
- 落地面：`core/ingest.py:227-241`（`temporal_state` stub）、`ingest.py:320-334`（`weakening` 落地）
- 消費面（只盤點誰讀 sm 輸出，內部邏輯歸各 session）：`core/golden.py`、`core/confidence.py`、`core/intelligence_delta.py`、`core/sector_intelligence.py`、`viewer/cockpit.py`
- 落地對照：`reports/2026-07-09.json`（頂層 key 與 stock record 欄位）

**明確不看（留給哪個 session）：**
- `weakening_profile` / `accumulation_velocity` / `sponsorship_persistence` / `failed_breakout_memory` / `regime_shift` 的**內部演算法**（sm 從 `core/market_context.py` import 全部判定材料）→ **S07 Market Context**
- golden 對 sm_state/transition_risk 的**消費語意**（G2/G4 gate、conviction）→ **S01 已裁**（本 session 只記 sm 是 G2/G4 的輸入）
- distribution/weakening_profile 內部與「疑似出貨」判定的完整譜系 → **S03**（本 session 只查 sm 與 weakening 的**歸屬重疊**）
- chip/resonance/共振、confidence 的評分本體 → **S02**
- 欄位命名正本 / registry 表格結構 → **S05**（已裁）
- replay 等級定義、strip 白名單、version-pinned replay 機制 → **S06**（已裁 RC-5/6）
- viewer 卡片渲染、狀態徽章 CSS、i18n 呈現 → **S08**
- backtest 對 sm 輸出的消費 → **S09**

**實跑驗證（真引擎跑全部磁碟快照）：**
```
python3 -c "import json,glob,sys; sys.path.insert(0,'.')
snaps=[json.load(open(f)) for f in sorted(glob.glob('reports/2026-*.json')) if '.intelligence' not in f and '.example' not in f]
from core import state_machine as SM; res=SM.run_all(snaps)
from collections import Counter; print(len(snaps),'snaps',snaps[-1]['date']); print(len(res),'tickers'); print(dict(Counter(t.state for t in res.values())))"
```
輸出摘要：
- **42 份快照，`date=2026-07-09`，245 檔 ticker**。
- `state_counts = {exited:190, distributing:16, accumulating:13, decelerating:9, undiscovered:8, failed:4, strengthening:3, confirmed:2}`。
- **`TickerState.as_dict()` 27 欄**：acceleration, days_in_state, events, failed_breakout, is_tier_a, name, net_cumulative, risk_factors, sector, sponsorship_score, state, state_color, state_en, state_entered, state_flips_30d, state_history, state_zh, streak, structure_unstable, ticker, transition_risk, transition_risk_color, transition_risk_en, transition_risk_zh, transitions, velocity_3d。
- 實例（顯示狀態的**路徑依賴**與 zigzag）：
  - `1409` distributing／risk=elevated／`state_history=[undiscovered, accumulating, decelerating, distributing, exited, distributing, exited, distributing, exited, distributing]`／flips=5／**structure_unstable=True**。
  - `1314` distributing／risk=critical／streak=15／history 含 accumulating↔exited↔distributing 反覆／flips=4。
  - `1710` distributing／risk=critical／days_in_state=4／history=`[undiscovered, accumulating, distributing]`（乾淨單調）。

**snapshot 落地面（`reports/2026-07-09.json`，schema 1.8.1）：**
- 頂層 key（20）：**無 sm/state_machine/transition_risk 任何產物 key**。
- stock record 只有兩個「state/weakening」相關欄位：`temporal_state`（P3a scoring 生命週期 **stub，恆 abstained**，見 §3b）與 `weakening`（**有實內容**，producer=market_context，見 §3c）。**無 sm_state、無 transition_risk、無 days_in_state、無 state_history**。
- → **TickerState 27 欄，落 snapshot 的是 0 欄**。sm 全部輸出都是 render-time（`sm_run_all(snapshots)` 現算）。復現 NOTES #2、與 S01 golden 同構。
- `temporal_state` 實測內容：`{prior_tier:null, tier_in_current_state_days:1, score_velocity:null, trend:null, abstained:{velocity:true, acceleration:true, trend:true, reason:"P3a ingest-only; no scoring computed yet"}}` — 全 null/abstained。
- `weakening` 實測（有命中的 `1718`）：`{severity:"yellow", flags:[{code:"W1", zh:"動能衰竭", detail:"連買7日但速度 -29,384/日"}], flag_count:1, label_zh:"失速", net_cumulative:214693, present_latest:true}`。

---

## §1 這個模組真正要回答什麼問題？

State Machine 回答「**這檔股票在主力生命週期的哪一個階段，以及它離惡化多近**」。它不自產原始訊號，而是把上游 market_context 的四個時序判定（accumulation_velocity 的 streak/velocity/acceleration、sponsorship_persistence、failed_breakout_memory、weakening_profile 的 W 旗標）＋ sector rank ＋ market breadth，逐快照分類成 **10 個離散生命週期狀態**（undiscovered→discovered→accumulating→strengthening→{decelerating/distributing}→confirmed→extended→failed→exited），再套 P0.5 反鋸齒紀律（debounce 兩日、distribution lockout 五日、veto）committed，最後輸出一個 4 級 **transition_risk**（low/medium/elevated/critical）。下游拿它做兩件不同性質的事：(i) golden 用 `sm_state∈{confirmed,strengthening}` 當 G2 資格閘門、`transition_risk≠critical` 當 G4 閘門（golden.py:318,320）；(ii) 使用者在網站看「狀態徽章＋在此狀態N日＋風險等級」判斷續抱/出場。

**定性（影響 Q2/Q4）：sm 輸出的是「狀態」（observation）還是「狀態轉移的警告」（近行動語意）？** 兩者都有，且是**兩個不同的 O 子型**：
- **`sm_state`（生命週期狀態）＝純 observation**（Classification）——「觀測到這檔現在處於 accumulating/confirmed/distributing」。這是純描述，無行動語意。
- **`transition_risk`＋`distributing`/`failed`（惡化警告）＝仍是 observation，但被下游當行動材料消費**。code 自我宣稱純函數觀測（state_machine.py:5-6「No stored state. No side effects. Pure function.」），且 `DISTRIBUTING`「疑似出貨」是**觀測到的賣方證據**、非「賣出建議」。但 NOTES #27 已定調：sm 提供的 weakening/transition_risk 材料**下游是行動層**——golden G4 直接用 `transition_risk!="critical"` 當進場資格閘門、confidence 用 `sm_state==DISTRIBUTING` 加風險分（confidence.py:432）。∴ sm 是**「資格 vs 行動」兩種 O 態的共同上游**：sm_state 餵資格（golden G2）、transition_risk/distributing 餵行動/風險（golden G4、confidence risk）。這條「同一引擎同時餵兩種下游語意」是 §3 與 Q4 的取捨核心。

---

## §2 它屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）作答。State Machine **不讀 raw（只透過 market_context helper 間接讀）、不寫 metadata**，是純粹的 **O 態生產者**——Protocol 六層裡的 **Classification 子型**（把連續的 streak/spon/velocity/breadth 切成 10 個離散生命週期狀態 + 4 級風險）。三個層次細節：

- **O 態（Classification）— sm 的本體**：`sm_state`（10 態）、`transition_risk`（4 級）、`days_in_state`、`state_entered`、`state_history`、`transitions`、`state_flips_30d`／`structure_unstable`（P0.5 遙測）、`risk_factors`。這是 sm 唯一自產的東西。**但完全不落 snapshot**（§0 實測、NOTES #2、S05 RC-1）——是**只在 render-time 才存在的 O 態**。且比 golden 更棘手：因為 committed 狀態是**路徑依賴**（§3e），這批 O 每次 render 從全部 42 份快照從頭推演。
- **O 態（借用的中間量）— 非 sm 自產**：`streak/net_cumulative/velocity_3d/acceleration/sponsorship_score/failed_breakout/sector`＝來自 market_context（accumulation_velocity/sponsorship_persistence/failed_breakout_memory）與 sector_intelligence。sm 只**搬運+複製**進 TickerState，所有權在 S07。**注意：其中 velocity_3d/acceleration 已由 temporal_enrich 落地在 snapshot（ingest.py:341-342）、weakening flags 已落地（ingest.py:325）——sm 卻是 render-time 重算而非讀落地欄位**（§3e/§4）。
- **跨入非資料層（Presentation）— 越界處**：`state_zh/state_en/state_color`（STATE_ZH/EN/COLOR，state_machine.py:118-155）、`transition_risk_zh/en/color`（RISK_ZH/EN/COLOR，:159-178）是純 i18n/顏色（應屬 S08），卻住在引擎的 dataclass 與 as_dict 裡。

**分層是否清楚：O 態本體清楚（單一職責：生命週期分類），但三個結構性問題**：(1) 引擎輸出契約（TickerState）混入 i18n/color 欄（同 S01 golden 病灶）；(2) 判定材料 render-time 重算而非讀已落地的同名欄位（velocity/weakening 都已落地卻不讀）；(3) committed 狀態的路徑依賴使這批 O 的 replay 語意比一般 render-time observation 更脆弱（§3e）。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 既有認知一致，「＋新增」＝本輪新發現。(a)-(e) 對應交辦五項。

### (a) 狀態集/轉移規則全寫死，門檻治理與 golden 同病（🟡 治理，＋新增）

1. **10 態、進入/離開條件全部硬編碼在 `_assign_state`**（state_machine.py:324-426）：EXITED（tail 3 快照皆缺，:349-352）、FAILED（failed_breakout 或 streak 3→0 崩塌，:371-381）、DISTRIBUTING/DECELERATING（was_strong ＋ 賣方證據分流，:387-402）、CONFIRMED/EXTENDED（:405-415）、STRENGTHENING（:418）、ACCUMULATING（:422）、DISCOVERED（:426）。轉移觸發字串亦硬編碼（`_transition_trigger`，:665-683）。
2. **所有門檻寫死為模組級常數**（state_machine.py:80-96）：`STREAK_STRENGTHENING=3`、`STREAK_CONFIRMED=3`、`SPON_STRENGTHENING=0.40`、`SPON_CONFIRMED=0.50`、`SECTOR_TOP_N_CONFIRM=5`、`BREADTH_CONFIRMED=0.50`、`ABSENT_EXITED=3`、`COLLAPSE_WINDOW=2`、`DAYS_SINCE_FAIL_RISK=10`。**P0.5 常數更明文自承該進 config 卻沒進**：`ACCEL_DISTRIBUTING=-500`、`DEBOUNCE_SNAPSHOTS=2`、`DIST_LOCKOUT_SNAPSHOTS=5`、`FLIPS_UNSTABLE_30D=2`，註解 state_machine.py:92「# P0.5 reform constants (candidates for SCORING_RUBRIC config at P3b)」。risk 分級的分數切點也寫死在 `_compute_risk` 函式體（score≥4=critical/≥2=elevated/≥1=medium，:486-493；各因子加分 +3/+2/+1 散在 :447-483）。
   - → **與 S01 §3(b)/golden 完全同構的治理不一致**：這些是 sm 判定的核心數字、全部寫死、不可 config 調。對照 S01 §5 裁定「門檻 config 化是 obs_* 落地的前置條件（寫死在 code 的權重對 replay 不可見，config_snapshot 才參與 hash）」——**sm 若要落地 obs_sm_*，同一前置條件成立**：現在改 DEBOUNCE 或 SPON_CONFIRMED 不進 config_snapshot、對 replay 不可見。（門檻正本歸屬 → S05 registry；此處只記 sm 的門檻治理現況。）

### (b) 「兩套狀態系統」疑雲：temporal_state 是**殭屍 stub**、與 sm_state 平行不相交（🔴 概念重疊，＋新增 — 本 session 最需釐清點）

3. **`temporal_state`（ingest.py:228-241，落地）與 sm_state（render-time）是兩套語意不同、互不消費的狀態系統**：
   - `temporal_state` 追的是 **P3a scoring pipeline 的「分數 tier 生命週期」**：`prior_tier`（＝composite_score 的 tier，非 sm_state）、`tier_in_current_state_days`、`score_velocity`、`score_acceleration`、`trend`、`current_episode_ids`。**全部 abstained**（ingest.py:237-240 `abstained:{velocity:true,...,reason:"P3a ingest-only; no scoring computed yet"}`，§0 實測恆 null）。
   - `sm_state` 追的是 **主力籌碼的生命週期**（accumulating→confirmed→distributing）。
   - **兩者從不相交**：sm 不讀 temporal_state，temporal_state 不讀 sm。查 `temporal_state` 全 repo 消費者（grep）：**只有 `tests/test_replay.py:84` 與 `viewer/app.py:166` 的一段說明文字**——**沒有任何引擎消費 temporal_state**。
   - → **結論：不是「兩套平行運作的狀態系統打架」，而是「一套殭屍 stub（temporal_state，P3a 從未啟用的 scoring-tier 生命週期）＋ 一套活的但不落地（sm_state）」**。語意重疊處在**欄位家族層級**：`temporal_state.tier_in_current_state_days` vs sm `days_in_state`、`temporal_state.score_velocity/trend` vs sm `velocity_3d`／狀態趨勢——兩套都在描述「在某狀態多久／趨勢往哪」，但主體不同（分數 tier vs 主力狀態）。這是**兩個「狀態＋在狀態天數＋速度」概念家族並存於同一 record**，一個是殭屍、一個不落地。哪套是 SoT、殭屍 stub 是否清除，留 §5。

### (c) 「weakening」歸屬與「兩個轉弱」語意並存（🔴 責任重疊，＋新增）

4. **`weakening_profile` 的 owner 是 `core/market_context.py:656`（→S07），落地由 ingest.py:320-334 寫成 `snapshot.weakening`**（producer=market_context）。**state_machine 是它的消費者**：state_machine.py:67 import `weakening_profile`，在 `_raw_state_seq` 每個窗 render-time 重算它（:522 `weak = weakening_profile(ticker, sub, branch_data)`），取 W 旗標碼（:523）餵 `_assign_state` 的賣方證據分流。code 自稱這是「single source of truth with core.market_context」（state_machine.py:17-18、386、521）——W3（吸籌後消失）/W5（分點賣壓）＋ latest mfb<0 → 判 DISTRIBUTING（:395-399）。
   - → **∴ sm 的「疑似出貨」不是與 weakening 平行的第二套轉弱判定，而是 weakening 的下游**（DISTRIBUTING = weakening W3/W5 or mfb<0）。「單一真相」宣稱只涵蓋**賣方證據的輸入（W 旗標）**。
5. **但「轉弱」在呈現面確實有兩個並存出口，來自同一證據、不同 owner、不同落地狀態**（🔴 這才是真重疊）：
   - **出口 A：`weakening.severity`（red/orange/yellow/none）＋ flags**——producer=market_context、**已落地**（ingest.py:325-334）、viewer 直接讀 `weak_map`（cockpit.py:1918-1929，含 render-time fallback）。
   - **出口 B：`sm_state=distributing`＋`transition_risk=critical`**——producer=state_machine、**render-time 不落地**、下游 golden G4/confidence risk 消費。
   - 兩者對同一檔可同時亮（實測 `1718` weakening=yellow「失速」W1 ＋ sm 可為 decelerating/distributing）。→ **使用者面同時存在兩個「轉弱」語言**（severity 徽章 vs 狀態徽章＋風險級），一個落地一個不落地，語意來源部分重疊（都吃 weakening_profile）但不完全（severity 的 W1/W2 vs sm 只認 W3/W5+mfb<0）。誰是轉弱的對外 SoT、兩個出口如何協調，留 §5。呼應 S01 §3(a)-5／NOTES #24（viewer 把 weakening 中轉進 golden 行動函式的 C8 違例）——**weakening 這條線橫跨 market_context(S07 產)／state_machine(S04 消費判 distributing)／golden(S01 行動)／viewer(S08 呈現) 四個模組**。

### (d) 輸出面 27 欄全不落、消費面橫跨 4 核心引擎＋2 前端（🔴 架構根病 → 分責 S05/S06/S08）

6. **TickerState 27 欄（dataclass state_machine.py:192-259，as_dict 見 §0）vs snapshot 實存＝0**：sm 判定 100% render-time、snapshot 零落地。與 golden 同類、比 S05 §3-8 abstain stubs 更徹底（sm 連 stub schema 欄位都沒有；那個 stub 是 temporal_state，追的是別的東西 §3b）。
7. **消費清單（輸出證據，內部語意各歸其 session）**：
   - `core/golden.py`：`sm_run_all`（:458），讀 `ts.state`/`ts.transition_risk`（:495,498）→ G2 資格閘門（sm_state∈{confirmed,strengthening}，:318）、G4 風險閘門（transition_risk≠critical，:320）、conviction 加分（sm_state==CONFIRMED，:275）、複製 sm_state/transition_risk/days_in_sm_state 進 GoldenEntry（golden.py:125-186）。**→ sm 是錢路 G2/G4 的資格輸入（S01 已裁消費語意）**。
   - `core/confidence.py`：`sm_run_all`＋`sm_state_summary`（:700-701），`sm_state==S_DISTRIBUTING` 加 `RISK_DISTRIBUTING`、`sm_risk_level` 當 risk base（confidence.py:415-432）。**→ confidence 有自己的 `_compute_risk`，把 sm 的類別型 transition_risk 再導出一個數值 risk_score**——**兩套 risk 計算並存**（sm 的 4 級類別 vs confidence 的數值），confidence 消費 sm 類別當基底再疊加。此重疊是否合理留給 confidence 所屬 session（S02?，未明確指派）＋§5。
   - `core/intelligence_delta.py`：`_sm.run_all` **跑兩次**（今日 :770 ＋昨日 :784），比對 sm_state 差異產「狀態變化」delta（sm_state/sm_state_zh，:630-631）。
   - `core/sector_intelligence.py`：import `S_EXITED/S_UNDISCOVERED`（:1096）過濾。
   - `viewer/cockpit.py`：`_run_sm_all`（:1878-1881）每次現算；並經 GoldenEntry 的 sm_state/transition_risk 欄呈現。`viewer/cockpit_v2.py`（NOTES #7 死碼前端）亦讀 sm_state_zh/transition_risk。
   - → sm 餵 **4 個核心引擎（golden/confidence/intelligence_delta/sector_intelligence）＋2 前端**，全部 render-time 重算。intelligence_delta 甚至一輪跑兩次全量 sm。

### (e) 路徑依賴：宣稱「無記憶純函數」，但 committed 狀態依賴全歷史推演（🔴 replay 結構 → S06）

8. **sm 自稱「No stored state. Pure function. same snapshot inputs → same state output」（state_machine.py:5-6），確為純函數；但今天的 committed 狀態是「全歷史路徑依賴」的推演結果，非「從當日算」**：
   - `_raw_state_seq`（:500-527）對 **每個前綴窗 `snapshots[:i]`（i=1..N）重算一次 RAW 分類**；
   - `_commit_states`（:542-609）再走完整 raw 序列，套 **debounce（連續 2 日才 commit，:590）＋ distribution lockout（DISTRIBUTING 後 5 快照內禁升 CONFIRMED，:568-577）＋ veto**，`cur` 逐步演進；
   - `days_in_state`/`state_entered`/`state_history`/`transitions`/`state_flips_30d`/`structure_unstable` 全部是**這條 committed 序列的衍生**（:629-662）。
   - → **後果（比 golden 更嚴重）**：committed tail（今天的狀態）依賴**整條 42 份快照的迭代順序＋debounce 路徑**。任何對 `_assign_state` 門檻或 debounce/lockout 邏輯的改動，會**無聲改寫全部歷史狀態與今天的狀態**。golden 是「同輸入今昔可產不同名單」；sm 更進一步——**連「當時是什麼狀態、在此狀態幾天」都會被 code 改動重寫，且沒有任何落地值可比對**。對照 NOTES #21「Replay Guarantee Strength」：sm 的 O 態現落在**「不可驗」**級（不落地→連 disk-hash 防竄改都沒有）；NOTES #22 排程代價在 sm 上是**放大版**（路徑依賴使 version-pinned replay 尤其必要）。機制修法（落地後給什麼 replay 等級、如何 pin 版本）→ **S06**；本 session 只登記事實。
9. **`exited` 狀態把「跌出當日主力買超榜」與「生命週期退場」混為一態**（＋新增，語意）：`ABSENT_EXITED=3`（:88），EXITED = tail 3 快照 record 全缺（:349-352）。實測 state_history 大量 `accumulating↔exited↔distributing` 反覆（§0 的 `1409`：4 次 exited 夾在 distributing 間），因為個股常態性進出「當日榜單」。→ **「exited」語意過載**：它其實是「近 3 日不在主力買超清單」，不是「主力已出場」，卻與 distributing/failed 並列在同一狀態字母表，餵 `state_flips_30d`／structure_unstable 的 flip 計數（榜單進出被算成狀態反覆）。此語意是否該與「真退場」分離，留 §5（部分涉 S07 的 universe 定義）。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：Observation-First / snapshot=SoR（NOTES #10）、扁平前綴、additive+alias。）

**State Machine 引擎的理想邊界：**
- **輸入**：只吃**已落 snapshot 的 O 態欄位**（market_context 的 streak/velocity/acceleration/sponsorship、weakening 的 W 旗標＋severity、sector rank、market breadth）。**絕不 render-time 重算 market_context/weakening_profile/sector**——上游 O 先落地，sm 純讀。
  - 差距：現況 sm `_raw_state_seq` 每窗 render-time 呼叫 weakening_profile/accumulation_velocity/sponsorship（§3c/§3e），**即使 velocity_3d/acceleration/weakening flags 都已落地在 snapshot（ingest.py:341-342,325）仍重算**。sm 的落地依賴上游先落地，但至少 velocity/weakening 已具備、可先改讀。
- **輸出**：sm **自產的 O 態**（sm_state/transition_risk/days_in_state/state_entered/state_history/transitions/structure_unstable）**必落 snapshot**，帶 producer=state_machine ＋ replay 等級。因路徑依賴，此批 O 的 replay 必須 version-pinned（S06 語意）。下游（golden/confidence/intelligence_delta/viewer）純讀，禁 render-time 重算 sm。
  - 差距：現況 27 欄全 render-time、零落地（§3-6/7）；intelligence_delta 甚至一輪跑兩次（§3-7）。
- **絕不做**：(i) 不自產顯示字串（state_zh/color、risk_zh/color 應由 S08 從 sm_state/transition_risk 映射，不進引擎 dataclass，C9 派生）；(ii) 不重算已落地的上游 O（讀 snapshot 的 weakening/velocity，不 render-time 重跑 weakening_profile）；(iii) **transition_risk 是否為 sm 獨佔、confidence 是否該重導一套數值 risk**——兩套 risk 計算並存（§3-7）是需釐清的邊界，留 §5；(iv) `temporal_state` 殭屍 stub（§3b）：是清除、還是與 sm_state 合流為單一「狀態＋在狀態天數」SoT，留 §5。
  - 差距：現況 dataclass 混 i18n 欄（§2）、render-time 重算已落地上游（§3e）、confidence 平行 risk（§3-7d）、temporal_state 殭屍與 sm_state 概念家族重疊（§3b）。

**門檻治理理想**：所有判定門檻（含 P0.5 debounce/lockout、SPON/STREAK 切點、risk 分數切點）統一為 config/registry 可調，core 不寫死。**且此為 obs_sm_* 落地的前置條件**（同 S01 §5 邏輯：寫死門檻對 config_snapshot/replay hash 不可見）。
  - 差距：全門檻寫死（§3-2），P0.5 常數註解自承該進 config 未進。

---

### NOTES #12 列舉義務：TickerState 哪些欄位屬「契約級 observation」候選

準則（S05 RC-1）：**呈現給使用者 or 被 backtest 消費 → 必落 snapshot**；純中間計算/可由已落欄位映射者不必落。取捨（是否真落、命名終審、殭屍清除）留 §5。

**A. 契約級 observation 候選（sm 自產、user-facing/backtest，建議落地，命名建議 obs_sm_*）：**
| # | 現欄 | 建議命名 | 理由 |
|---|---|---|---|
| 1 | `state`（10 態） | `obs_sm_state` | sm 核心分類輸出；使用者看到的狀態徽章、golden G2 資格閘門輸入、backtest 生命週期主鍵 |
| 2 | `transition_risk`（4 級） | `obs_sm_transition_risk` | golden G4 閘門輸入＋confidence risk 基底＋使用者風險徽章；**NOTES #27 的「餵行動層的 O 材料」本體** |
| 3 | `days_in_state` | `obs_sm_days_in_state` | user-facing「在此狀態 N 日」；風險鄰近度、EXTENDED 判定 |
| 4 | `state_entered` | `obs_sm_state_entered` | 稽核/replay 錨；「何時進入此狀態」 |
| 5 | `structure_unstable`（＋`state_flips_30d`） | `obs_sm_structure_unstable` | P0.5「⚡結構不穩」徽章，user-facing；zigzag 遙測 |
| 6 | `risk_factors` | `obs_sm_risk_factors` | 解釋「為何是此風險級」的稽核證據；viewer 顯示風險因素明細 |

**B. 邊界候選（留 §5 定歸屬）：**
- `state_history` / `transitions`：稽核軌，user-facing（狀態歷程/近期轉換），但**路徑依賴＋巢狀**——落地成本高，且若上游可 version-pinned replay 則可從歷史重建。落地 or 派生二選一（但 §3e 的路徑依賴使「可重建」有前提）。
- `events`（debounce 單日訊號/veto 遙測）：P0.5 除錯用，user 價值低，可暫不落。
- `failed_breakout`（bool）：sm 讀 market_context 的 failed_breakout_memory 結果——**借用**，落地權宜歸 S07。

**C. 不必落地（中間計算 or 他 session 所有 or 純顯示）：**
- `streak/net_cumulative/velocity_3d/acceleration/sponsorship_score/sector`＝market_context/sector 借用（→S07 落地，其中 velocity_3d/acceleration **已落地**在 snapshot，sm 不重複落）；`is_tier_a`＝watchlists 靜態 config。
- `state_zh/state_en/state_color`、`transition_risk_zh/en/color`＝純 i18n/顏色（→S08 從 obs_sm_state/obs_sm_transition_risk 映射，C9 派生不落，絕不進引擎契約）。

→ **sm 自產、契約級候選核心 3 名**：`obs_sm_state`、`obs_sm_transition_risk`、`obs_sm_days_in_state`（含 state_entered/structure_unstable/risk_factors 共 6 項 A 級）。

---

## §5 裁定（fable，2026-07-10）

> 裁定框架：SESSION-TEMPLATE §5 rubric。凍結期，只立契約方向。

### 系統身份判準
sm 是「系統當天相信這檔股票處於什麼階段」的生產者——而「當天相信什麼」正是 System of Record 這個詞的字面意義。S04 因此暴露了 SoR 命題最尖銳的版本：**一個路徑依賴的判斷若不逐日落地，連歷史都會被未來的 code 無聲改寫**。本裁定的核心產出（C10）就是把這件事變成法。

### Root Causes — 9 條發現壓縮：0 個新根因、既有 RC 的最強實例、1 條新法

**（新法）C10｜as-was 原則：路徑依賴的 O 態以「當日認定」逐日落地為正本（P0）**
吸收 §3-6/8 與懸置 4/6。sm 的 committed 狀態依賴全 42 份快照的推演路徑（debounce/lockout），改任何門檻就無聲改寫全部歷史——**這不是 landing 的又一個理由，是 landing 語意的升級**：System of Record 要記的是「系統當天相信什麼」（as-was），不是「今天的 code 回頭看那天會怎麼判」（as-would-be）。裁定：
- **逐日落地 committed 狀態後，路徑依賴從負債變成紀錄本身**——每天的 obs_sm_state 寫入即凍結，days_in_state/state_history 從此由**落地序列**派生，對 code 改動免疫；引擎的執行依賴也從「全歷史推演」縮成「昨日落地狀態＋今日輸入」。
- **落地起點前的歷史不可如實重建**（code 已漂移），契約誠實聲明：as-was 紀錄自落地日起算，不偽稱可回溯。
- `state_history`/`transitions` **不落地**（由落地序列派生）；`days_in_state` **落地**——C9 邊界在此釐清：**C9 的「派生不落」適用於同一 record 內的純函數（顯示標籤）；跨快照的時序派生在 bootstrap 期無法派生、backtest 直讀有其人體工學，屬 as-was 座標的一部分，落**。`events` 除錯遙測不落。
- C10 普適於一切有狀態/時序引擎（weakening streak、episodes、S02/S03/S07 的同類輸出），是本研究至今對「Observation-First」最具體的一次定義。

**（實例確認，不另立 RC）**
- §3-6/7＝RC-1 第二個引擎級實例：27 欄零落地、餵 4 引擎＋2 前端、intelligence_delta 一輪跑兩次全量 sm（落地後自然消失的症狀）。**加一條消費面紀律**：velocity_3d/acceleration/weakening 明明已落地、sm 仍 render-time 重算（§3e）——「落地而不讀」會讓同名資料再度雙真相（同 S06 兩份 strip 清單的病）；C2 的完整語意＝**判斷必落地，已落地者必改讀**。
- §3-1/2＝S01 門檻治理的第二個實例：P0.5 常數註解自承該進 config 卻沒進。**兩個引擎同病＝系統性**：門檻 config 化不再逐 session 裁，升格為 registry 遷移（S05 RC-2）的**統一前置步驟**——一次掃全部引擎的寫死門檻，S02/S03/S07 只需引用本條。
- §3e＝S06 RC-6 的最強實例（路徑依賴使 version-pin 尤其必要）；C10 解未來、RC-6 的 version-pin 問題只剩「驗證歷史 O 可重算」一途，歸 S06 不變。

### 懸置點裁定
1. **temporal_state＝殭屍，判定死刑緩期**：它與 S05 裁定保護的 abstain stubs（composite_score/tier，有明確 P3b 未來）不同——零引擎消費、且其概念家族（狀態+天數+速度）已被 sm 實質擁有。裁定：registry 標 **deprecated-pending-P3b**；不填、不擴、不消費；P3b scoring 啟用時其生命週期需求改從落地的 obs_* 派生，屆時正式移除（major）。**sm_state 是「生命週期狀態」概念家族的唯一 SoT**。
2. **兩個轉弱出口＝健康的分層，不是重複判斷**：weakening（證據分級，mc 產）→ sm distributing（生命週期分類）→ transition_risk（惡化鄰近度）是一條「證據→分類→風險」鏈，各答不同問題，**不合併**。真問題在呈現面兩套詞彙無譜系可見——落地後鏈條可檢視即解大半；若產品面要一個統一「轉弱」標籤，**該標籤是跨引擎組裝＝依 C8 必須是 core 派生欄位**，列入 S08 議程，viewer 不得自行組裝。sm 的 SSOT 宣稱（W 旗標輸入面）正確，保留。
3. **confidence 平行 risk**：材料不足以在 S04 裁，明確指派——confidence 引擎歸入 **S03 Distribution（風險側）session 範圍**，屆時裁「類別 risk（sm）vs 數值 risk（confidence）雙軌」的存廢。
4. **obs_sm_* 六欄核准**（state/transition_risk/days_in_state/state_entered/structure_unstable/risk_factors），修正見 C10（history/transitions/events 不落）。`failed_breakout` 借用，落地權歸 S07。
5. **門檻 config 化＝落地前置** ✓ 沿用 S01 並升格系統性（見上）。
6. 見 C10。
7. **exited 語意過載＝真缺陷，且是落地的前置**：把「近 3 日不在主力買超榜」（absent/off-radar）與「生命週期退場」（exited）混為一態，會把榜單進出污染成狀態反覆（flips/structure_unstable 失真）。**先把詞彙拆開（additive：新增 absent 態或正名）再落地 obs_sm_state**——否則缺陷被燒進 as-was 紀錄。universe 定義面歸 S07，狀態字母表修正屬 sm 遷移案。

### 雜訊分離
i18n/color 欄混 dataclass（S08 時清，與 S01 同案）；intelligence_delta 跑兩次（落地後消失的效能症狀）；`1409/1314` zigzag 實例（exited 過載的證據，不獨立成案）。

### 挑戰證據包
- **兩處反錨定值得記錄**：交辦預設「兩套平行狀態系統」與「兩個轉弱並存」，證據包均以證據駁回重立（殭屍 stub＋下游鏈）——裁定採其修正版，原框架作廢。
- 修正其 B-list 的「落地 or 派生二選一（可重建有前提）」猶豫：C10 一次定死——history 由落地序列派生、落地前歷史誠實放棄，不存在含糊地帶。
- 修正其 §4 的「sm 落地依賴上游先落地」：同 S01，pipeline 內算即可落；且 velocity/weakening 已落地，sm 改讀它們甚至不用等遷移。

### 不需要改的（防未來誤重構）
`_assign_state`→debounce→lockout 的 **P0.5 反鋸齒本體**（邏輯清楚、解決真問題——zigzag 實測就是它在管）；weakening→sm 的消費關係（單向下游，健康）；10 態字母表除 exited 外的語意；sm「純函數」設計本身（路徑依賴是輸入形狀問題，不是副作用問題，C10 落地後它依然是純函數、只是輸入變小）。

### 與已鎖決策相容性
扁平前綴 ✓（obs_sm_*）；additive+alias ✓（六欄新增、absent 態 additive、temporal_state 走 deprecated 程序非直刪）；C1-C9 ✓（C10 是 C2/C9 的時序補完，C9 邊界同步釐清：同 record 純函數不落、跨快照時序派生視 bootstrap/人體工學可落）。fii cap 未觸碰 ✓。

### Architecture Verdict
| 級 | 項 | 理由 |
|---|---|---|
| P0 | C10 as-was 原則＋obs_sm_* 六欄核准 | 路徑依賴引擎不逐日落地=歷史可被未來 code 改寫，直接否定 SoR 命題；S02/S03/S07 的時序輸出全部引用本條 |
| P1 | exited/absent 詞彙分離＝落地前置 | 不先拆，缺陷燒進 as-was 紀錄且 structure_unstable 失真 |
| P1 | 門檻 config 化升格系統性（registry 統一前置，不再逐 session 裁） | 兩引擎同病確認 pattern；S02/S03/S07 引用即可 |
| P1 | temporal_state 標 deprecated-pending-P3b；sm_state=概念家族唯一 SoT | 殭屍不清，registry 正本就帶著一個零消費者的重複概念家族 |
| P2 | confidence 雙軌 risk（指派 S03）、i18n 出 dataclass（S08）、統一轉弱標籤若需要=core 派生（S08 議程） | 各歸其 session |

### Executive Summary（兩分鐘版）
1. sm 是路徑依賴引擎的原型：今天的狀態是全歷史推演的結果，改一個門檻就無聲改寫所有歷史——且 27 個輸出欄位零落地，連被改寫了都無從發現。（RC-1/RC-6 最強實例）
2. 新法 C10（as-was）：路徑依賴的判斷逐日落地「當日認定」，落地後路徑依賴從負債變成紀錄本身；history 由落地序列派生；落地前的歷史誠實放棄。這是 Observation-First 至今最具體的一次定義。（P0）
3. 「兩套狀態系統」實為一殭屍一活體：temporal_state 標 deprecated，sm_state 是生命週期概念家族唯一 SoT。「兩個轉弱」實為證據→分類→風險的健康分層，不合併；統一對外詞彙若需要，依 C8 必須 core 派生。
4. exited 把「跌出榜單」與「真退場」混為一態——落地前先拆，否則缺陷燒進永久紀錄。（P1）
5. 門檻寫死已在兩個引擎確認同病，升格為 registry 遷移的統一前置；後續 session 引用即可，不再逐案裁。（P1）

---

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES：本 session 新發現於 §3/§4 就地標歸屬（temporal_state 殭屍→§3b；weakening 兩出口→S03/S07/S08；confidence 平行 risk→S02?；exited 語意→S07；路徑依賴 replay→S06；門檻治理→S05）。蒐證階段不預先 append，待 fable 裁定後由裁定者決定哪幾條入 NOTES。
- [x] 00-INDEX 狀態列已更新（S04：證據包完成，待 fable 裁定；報告連結 `sessions/S04-state-machine.md`）
- [x] 未執行任何 code/schema 改動
