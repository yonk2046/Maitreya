# Session 01 — Golden Layer（證據包）

> 蒐證者：opus（獨立 session，照 SESSION-TEMPLATE §0–§4 填草稿）。
> 前提：本報告只分析、蒐證，**未改任何 code/schema**；§5 裁定留給 fable。
> 承接：S05 §5 RC-1 已立法「呈現給使用者或被 backtest 消費的 observation 必落 snapshot；個別引擎的落地清單由 S01–S04 各自在 Q4 列舉」（NOTES #12）；S06 §5 RC-6/NOTES #21-22 已立「Replay Guarantee Strength」正交軸與「每次 bump 讓歷史 full-replay 保證歸零」的排程代價。
> 已鎖決策（不重議，見 CROSS-SESSION-NOTES #9 / 00-INDEX）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0、**fii_alignment cap 維持連賣 2 天（NOTES #5，本 session 只記錄語意，不重議門檻）**。

---

## §0 範圍與輸入

**只看：** Golden Layer 引擎本體 —
- `core/golden.py`（全檔 804 行：門檻常數、GoldenEntry/GoldenResult dataclass、`_score_conviction`、`_evaluate_gates`、`_apply_tier_caps`、`_fii_contra_streak`、`run`、`action_group`、`display_tier`）
- `config/scd.example.yaml`（`gates.fii_alignment`、`gates.cost_safety` — golden 讀的兩組 config 門檻）
- 消費面：`viewer/cockpit.py`（golden 的唯一消費者：import、`_run_golden`、`action_group`/`display_tier` 呼叫、weak_map 供給）
- 落地面：`reports/2026-07-07.json`（snapshot 頂層 key 與 stock record 欄位）

**明確不看（留給哪個 session）：**
- funnel layer 判定（G1 輸入）、sector rank、market_context/dual_cost_anchor 內部邏輯 → **S07 Market Context**
- state_machine 狀態（G2/risk 輸入）、transition_risk、distributing/疑似出貨判定 → **S04 State Machine**
- chip/resonance/共振 → **S02**；distribution/weakening_profile 內部 → **S03**
- 欄位命名正本 / registry 表格結構 / schema additionalProperties → **S05**（已裁 RC-2）
- observation 的 replay 等級定義、strip 白名單、version-pinned replay 機制 → **S06**（已裁 RC-5/6）
- viewer 卡片渲染、CSS、display_tier 的視覺呈現方式 → **S08**
- backtest 對 golden 輸出的消費 → **S09**

**實跑驗證（真引擎跑全部 40 份磁碟快照）：**
```
python3 -c "import json,glob,sys; sys.path.insert(0,'.')
snaps=[json.load(open(f)) for f in sorted(glob.glob('reports/2026-*.json')) if '.intelligence' not in f and '.example' not in f]
from core import golden as G; res=G.run(snaps); e=res.all_golden[0]
print(res.date, res.as_dict()['counts']); print(sorted(e.as_dict().keys()))"
```
輸出摘要：
- 40 份快照，`date=2026-07-07`，`counts={'prime':2,'strong':1,'qualified':0,'near_miss':56,'total':3}`。
- `all_golden = [('2885','prime'),('1717','prime'),('2845','strong')]`；`near_miss[:5]=['2892','5880','1303','1802','2882']`（56 檔）。
- **GoldenEntry `as_dict()` 32 欄**：acceleration, conviction, cost_conservative, cost_diverged, cost_divergence_pct, cost_episode_weighted, current_price, days_in_sm_state, funnel_layer, gates_passed, is_tier_a, main_force_cost, name, net_cumulative, score_breakdown, sector, sm_state, sm_state_color, sm_state_entered, sm_state_zh, sponsorship_score, streak, ticker, tier, tier_caps, tier_color, tier_en, tier_zh, transition_risk, transition_risk_color, transition_risk_zh, velocity_3d。
- `tier_caps` 本輪空（無 SKELETON/fii_contra cap 觸發）——cap 機制在但此資料集未命中。

**snapshot 落地面（`reports/2026-07-07.json`）：**
- 頂層 key（17）：**無 `golden` / `near_miss` / 任何 golden 產物 key**。（同 S05 §0 復現）
- stock record 有 `tier`（P3a abstain stub，恆 IGNORE）與 `confidence_tier`（golden cap 讀的 SKELETON 來源）；**無 `conviction`、無 golden 的 prime/strong/qualified tier、無 gates_passed、無 action_group**。
- → **GoldenEntry 的 32 欄，落 snapshot 的是 0 欄**。golden 全部輸出都是 render-time（viewer 呼叫 `_golden_mod.run(snaps)` 現算，cockpit.py:1869-1891）。復現 NOTES #2。

---

## §1 這個模組真正要回答什麼問題？

Golden Layer 是全系統的**錢路收斂點**——它回答「**今天哪些股票值得進場、憑什麼**」。它不自產原始訊號，而是把上游三個引擎的結論綜合成一個**資格判定**：漏斗結構（funnel confirmation）+ 生命週期狀態（state machine confirmed/strengthening）+ 贊助度/連買/淨累計/速度/類股強度，經 5 道硬門檻（G1-G5）過濾、再用加權 conviction 分數（0-1）分成 PRIME/STRONG/QUALIFIED 三級，最後套硬上限（SKELETON、外資反向 cap）。下游（使用者在網站看名單決定進場、未來 backtest 回測名單績效）拿它的輸出做**最終選股決策**。

**定性（影響 Q2/Q4 的關鍵）：golden 的輸出是 observation（觀測到的「資格狀態」）還是 recommendation（建議）？** code 自我宣稱是純觀測（golden.py:9 `Pure observation. No trading signals. No buy/sell recommendations.`），但實況已跨過那條線：`action_group()`（golden.py:740）把每檔分類為「🟢可執行 / 🟡等回檔 / 🔵資料待補 / 🔻動能轉弱」，`display_tier()`（golden.py:790）把 tier 改寫成「**可買進** / 增強 / 中」，且註解明文「『可買進』must mean *actually buyable*」（golden.py:773-776）。這已是**帶行動語意的 recommendation 呈現**，只是判定材料仍全部來自 observation。這條「observation 引擎尾端長出 action/buy 語意」的張力是 §3 的核心病灶，也決定 Q4 該把哪條邊界劃在哪。

---

## §2 它屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）作答。Golden **不讀 raw、不寫 metadata**，它是純粹的 **O 態生產者**——Protocol 六層裡的 **Classification 子型**（把連續的 conviction 分數切成 PRIME/STRONG/QUALIFIED 離散級別 + 硬 cap）。但有三個層次細節：

- **O 態（Classification）— golden 的本體**：`tier`（prime/strong/qualified）、`conviction`（0-1）、`gates_passed`、`tier_caps`、near_miss 歸屬。這是 golden 唯一自產的東西。**但它現在完全不落 snapshot**（§0 實測、NOTES #2、S05 RC-1）——是**只在 render-time 才存在的 O 態**，snapshot 裡連佔位 stub 都沒有（不同於 S05 §3-8 講的 `composite_score/tier` abstain stubs，那是另一條 P3a scoring pipeline；golden 的 prime/strong/qualified tier 連 stub 都不在 schema）。
- **O 態（借用的中間量）— 非 golden 自產**：`streak/net_cumulative/velocity_3d/acceleration/sponsorship_score/sector`（來自 funnel，cr.*）、`sm_state/transition_risk/days_in_sm_state`（來自 state_machine，ts.*）、`cost_*`（來自 market_context dual_cost_anchor）。golden 只是**搬運+複製**進 GoldenEntry，這些 O 的所有權在 S07/S04，不在 S01（避免重複落地，見 §4）。
- **跨入非資料層（Presentation）— 越界處**：`tier_zh/tier_en/tier_color`、`sm_state_zh/color`、`transition_risk_zh/color` 是純 i18n/顏色（應屬 S08）；`action_group()`/`display_tier()` 產「可執行/可買進」是**帶判定的 presentation**（材料是 O，輸出是行動標籤）。

**分層是否清楚：不清楚。** golden.py 一個檔案裡同時住了：(1) 純 O 態引擎判定（gates→conviction→tier→cap，golden.py:298-418）、(2) 顯示用 i18n/color 常數（golden.py:85-107）、(3) 帶行動語意的分組/改標（`action_group`/`display_tier`，golden.py:698-803）。三者混在同一模組、同一 dataclass（GoldenEntry 把 tier 與 tier_color 並列），**引擎判定與顯示邏輯沒有結構邊界**。這正是 §3(a) 的病灶。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 既有認知一致，「＋新增」＝本輪新發現。(a)-(e) 對應交辦五項。

### (a) 三層判定鏈的責任切分：引擎判定 vs 顯示邏輯界線模糊（🔴 架構，＋新增）

golden 的判定鏈實為**五段**，前三段是引擎判定、後兩段跨進顯示/行動層，但全部住在同一檔、部分共用 GoldenEntry：

1. **G1-G5 gates**（`_evaluate_gates`，golden.py:300-323）→ 純引擎，二元通過/否。✔
2. **conviction 加權**（`_score_conviction`，golden.py:243-295）→ 純引擎，9 個加分項疊加封頂 1.0。✔
3. **tier caps**（`_apply_tier_caps`，golden.py:391-418）→ 純引擎硬上限：SKELETON cap（golden.py:407-409，讀 `confidence_tier`）+ fii_alignment cap（golden.py:411-416，連賣≥2 天降 PRIME→STRONG，NOTES #5 已裁語意）。✔
4. **`action_group()`**（golden.py:740-768）→ **「5% 成本鐵則」在這**：`price <= anchor * max_premium_ratio`（golden.py:766，max_premium_ratio=1.05）決定 EXECUTABLE vs WAIT_PULLBACK。註解自承「Business logic … lives HERE per the AI_GOVERNANCE red line (UI renders, core decides)」（golden.py:698-700）——即刻意把商業邏輯放 core。但這段**不在 gate 鏈裡**：一檔可以「gate 全過、conviction PRIME」卻因價格超成本 5% 被分到「等回檔」。價格容忍是**進場行動判定**，不是資格判定，卻與資格判定混在同一引擎的兩個不相連函式。
5. **`display_tier()`**（golden.py:790-803）→ **號稱「display-only」（golden.py:778-779 `does NOT change gates, conviction, the snapshot tier field, or replay hashes`），但實含實質條件**：`if ag == ACTION_EXECUTABLE and entry.conviction >= TIER_PRIME: return DTIER_BUY`（golden.py:799）——「可買進」標籤同時要求 (i) PRIME conviction (ii) 價格 executable(≤cost×1.05) (iii) 非 weakening。**這不是純顯示**：它把「資格(conviction)」「價格(action_group)」「動能(weakening)」三個異質判定 AND 在一起產出一個 buy 語意標籤。→ 交辦所問「display_tier 說純顯示層卻含 EXECUTABLE+未轉弱等實質條件」**成立**。
   - **界線模糊的具體證據**：`action_group`/`display_tier` 都吃一個 `weakening_severity` 參數，該參數**不是 golden 自產**——由 viewer 從 snapshot 的 `weakening` 欄位取（cockpit.py:1918-1929 weak_map，含 render-time fallback `weakening_profile`）再傳入（cockpit.py:2672-2680）。即 golden 的「行動判定」依賴一個**由 distribution/weakening 引擎（→S03/S04）產、經 viewer 中轉**的外部輸入。判定材料的所有權在別的 session，行動標籤的產出在 golden，呈現在 viewer——**同一個「可買進」語意橫跨三個模組**。

### (b) 門檻治理：核心門檻寫死在 golden.py，與 config 化門檻並存（🟡 治理，＋新增）

對照紅線「core 不寫死門檻」，實況是**一半一半**：

6. **寫死在 golden.py 的門檻**（golden.py:68-78 模組級常數）：`GOLD_SPON_MIN=0.45`（G3 閘門）、`TIER_PRIME=0.65`/`TIER_STRONG=0.40`（tier 切點）、`SCORE_STREAK_HIGH=5`/`MID=3`、`SCORE_SPON_HIGH=0.70`/`MID=0.55`、`SECTOR_TOP_N_TIGHT=3`，以及 conviction 各加分權重（0.25/0.15/0.20/0.10/0.15/0.10/0.10/0.05/0.05，硬編碼在 `_score_conviction` 函式體 golden.py:261-292）。**這些是 golden 判定的核心數字，全部寫死、不可由 config 調**。
7. **已 config 化的門檻**：`gates.fii_alignment.contra_days_cap=2`/`enabled`（config:165-168，經 `_load_fii_alignment_cfg` golden.py:336-352 讀）、`gates.cost_safety.max_premium_ratio=1.05`/`anchor`/`divergence_alert_pct`（config:149-153，經 `_load_cost_safety_cfg` golden.py:719-727 讀）。
   - → **治理不一致**：後進的兩個 gate（P0.7 fii_alignment、P0.6 cost_safety）走 config，但更核心、更常需調校的 conviction 權重與 tier 切點反而寫死。改 PRIME 門檻或加分權重要動 code，改外資 cap 天數只要動 yaml。同一引擎兩套門檻治理標準。

### (c) 輸入依賴的跨模組耦合：讀 snapshot 欄位 vs 呼叫他引擎 render-time 結果混用（🟡 耦合，＋新增；他引擎內部→標歸屬不展開）

golden 的輸入來自**三種不同機制**，混在 `run()`（golden.py:446-584）裡：

8. **呼叫他引擎的 render-time 結果**：`funnel_run(snapshots)`（golden.py:457→G1 layer、streak、net_cumulative、sponsorship、velocity、acceleration、sector 全取自 `cr.*`）、`sm_run_all(snapshots)`（golden.py:458→G2 state、transition_risk、days_in_state 取自 `ts.*`）、`dual_cost_anchor`（golden.py:527→cost_*）、`_latest_sector_rank`→`build_sector_map`（golden.py:431，→sector_intelligence）。**這些引擎每次跟 golden 一起 render-time 重跑**，非讀 snapshot 既有值。（各引擎內部邏輯不評：funnel/sector→**S07**、state_machine→**S04**、dual_cost/market_context→**S07**。）
9. **直接掃 snapshot 欄位、自己迭代**：`_fii_contra_streak`（golden.py:371-388）**自行 `for snap in reversed(snapshots)` 掃歷史快照**的 `fii_net_buy` 欄位算外資連賣天數——這是 golden **唯一**直接消費 raw snapshot 欄位、且**自建時序迭代**之處（不透過任何引擎）。SKELETON cap 則讀 `latest_stock_map[ticker]["confidence_tier"]`（golden.py:407、521）。
   - → **耦合面不一致**：同一個 `run()` 裡，大部分判定材料是「呼叫他引擎現算」，但外資 cap 卻是「golden 自己掃 snapshot 欄位」。fii 連賣這段本可屬於某個 institutional-flow 引擎的職責，golden 自建迭代=**把跨快照時序邏輯洩漏進 golden**。（fii_net_buy 欄位本身的 domain 正確性→S05 已裁 RC-3；此處只記 golden 自建迭代這件事。）

### (d) 輸出面：GoldenEntry 32 欄全不落 snapshot，viewer 消費一份 render-time 物件（🔴 架構根病 → 分責 S05/S06/S08）

10. **GoldenEntry 完整欄位（dataclass golden.py:112-196，as_dict 32 欄見 §0）vs snapshot 實存＝0**：§0 實測頂層無 golden key、stock record 無 conviction/prime tier/gates_passed。**golden 的判定 100% render-time，snapshot 零落地**。這與 S05 §3-8 的 abstain stubs 是**不同狀態**：scoring-pipeline 的 `composite_score/tier/checklist` 至少被 schema `required` 佔位（值恆 abstain）；golden 的 tier/conviction **連 schema 欄位都不存在**。→ 兩類 render-time observation，golden 屬「完全不在 schema、不在 snapshot」那類（S05 §3-8-ii）。
11. **viewer 實際消費清單（輸出證據，渲染方式→S08）**：cockpit.py import `core.golden`（:46），`_run_golden`（:1869）每次現算 GoldenResult。屬性讀取實測（grep `e.<attr>`）消費：`ticker`(高頻)、`conviction`、`streak`、`sponsorship_score`、`sm_state`/`sm_state_zh`、`velocity_3d`、`acceleration`、`net_cumulative`、`gates_passed`、`days_in_sm_state`、`sm_state_entered`、`tier`、`is_tier_a`、`score_breakdown`、`name`；並呼叫 `action_group`(:2672)、`display_tier`(:2679)、`ACTION_*`/`DTIER_*` 常數與 `near_miss` 清單(:1910,1916)。→ viewer 依賴 golden 的**引擎產出 + 行動分組 + 顯示標籤**三者，全部 render-time。
12. **near_miss 語意**（golden.py:208-209、571-573）：`len(gates_fail) == 1` 即 5 gate 只差 1 道未過→列 near_miss。**且 near_miss entry 仍被算了 tier（`_tier_from_score`）與 cap**，儘管它沒通過 gate（tier 只是 score 映射，不代表資格）。tier_caps 刻意排除在 gates_fail 外（golden.py:518-520、144-146 註解），確保 cap 不影響 near_miss 的「差 1 gate」計數。本輪 56 檔 near_miss（§0）。→ near_miss 是「觀察名單候選」語意，但其 entry 帶著一個**不具資格意義的 tier 值**，消費端若誤讀 near_miss.tier 會失真。

### (e) 每日重算的不確定性：無版本釘選，同歷史快照集今昔可產不同名單（🔴 replay 結構 → S06）

13. **golden 每次 render 重跑、無版本釘選** — `run()`（golden.py:446）吃 `snapshots` 現算，**輸出不落地、不帶 golden 版本號、不參與 replay hash**（§0/§d）。同一份歷史快照集，今天跑 vs 上月跑，只要 golden.py（或其上游 funnel/state_machine/門檻常數）演進過，就可能產出**不同的 prime/strong 名單**——且無任何機制能重建「當時 golden 判了什麼」。對照 NOTES #21「Replay Guarantee Strength」：golden 的 O 態目前落在**「不可驗」**一級（連 disk-hash 防竄改都沒有，因為根本不落 snapshot）。→ 這是 NOTES #22 排程代價的**放大版**：不只「bump 讓歷史 full-replay 歸零」，golden 是**從一開始就不在 replay 覆蓋範圍內**。此結構問題的機制修法（落地後給什麼 replay 等級）→ **S06**；本 session 只登記「golden O 態現況＝不可驗」這個事實。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：Observation-First / snapshot=SoR（NOTES #10）、扁平前綴、additive+alias、fii cap 維持 2 天。）

**Golden 引擎的理想邊界：**
- **輸入**：只吃**已落 snapshot 的 O 態欄位**（funnel 的 streak/sponsorship/net_cumulative、state_machine 的 sm_state/risk、market_context 的 cost 錨、sector rank），以及自己需要的 raw（fii_net_buy）。**絕不 render-time 呼叫他引擎重算**——上游 O 先落地，golden 純讀。
  - 差距：現況 golden `run()` render-time 呼叫 funnel/state_machine/dual_cost/sector（§3-8），因為上游 O 也沒落地（NOTES #2 連鎖）。golden 的落地依賴上游先落地。
- **輸出**：golden **自產的 O 態**（tier/conviction/gates_passed/tier_caps/near_miss 歸屬）**必落 snapshot**，帶 producer=golden + replay 等級（epoch-scoped O，S06 語意）。viewer 純讀，禁 render-time 重算 golden。
  - 差距：現況 32 欄全 render-time、零落地（§3-10）。
- **絕不做**：(i) 不自產顯示字串（tier_zh/color/icon 應由 S08 presentation 從 tier 映射，不進引擎 dataclass）；(ii) 不自建跨快照時序迭代（fii 連賣應由 institutional-flow 提供既算好的 O，golden 讀，不自己 `for snap in reversed`）；(iii) **行動/buy 語意（action_group/display_tier）是否屬 golden 引擎，是本 session 最需裁定的邊界**——它把「資格(O)」與「進場行動(價格容忍、動能)」綁在一起，材料橫跨 S03/S04/S07。留 §5。
  - 差距：現況 golden dataclass 混入顯示欄（§2）、自建 fii 迭代（§3-9）、尾端長出 action/buy 層（§3-4/5）。

**門檻治理理想**：所有判定門檻（含 conviction 權重、tier 切點）統一為 config/registry 可調，core 不寫死。
  - 差距：核心門檻寫死 golden.py:68-78 + 函式體權重，與 config 化的 fii/cost gate 並存（§3-6/7）。

---

### NOTES #12 列舉義務：GoldenEntry 哪些欄位屬「契約級 observation」候選

準則（S05 RC-1）：**呈現給使用者 or 被 backtest 消費 → 必落 snapshot**；純中間計算/可由 tier 映射者不必落。取捨（是否真落、命名終審）留 §5。

**A. 契約級 observation 候選（golden 自產、user-facing/backtest，建議落地）：**
| # | 現欄 | 建議命名 | 理由 |
|---|---|---|---|
| 1 | `tier` (prime/strong/qualified) | `obs_golden_tier` | golden 的核心分類輸出；使用者看到的黃金分級，backtest 回測名單的主鍵 |
| 2 | `conviction` (0-1) | `obs_golden_conviction` | 分數排序依據；viewer 顯示 conv%、backtest 分層 |
| 3 | `action_group` (executable/wait_pullback/…) | `obs_golden_action_group` | **最 user-facing**（🟢可執行分組），現況純 render-time；含 5% 成本鐵則的判定結果 |
| 4 | `gates_passed` (G1-G5 清單) | `obs_golden_gates_passed` | 「憑什麼入選」的稽核證據；viewer 顯示 gate 明細 |
| 5 | `tier_caps` (SKELETON/fii_contra) | `obs_golden_tier_caps` | cap 稽核軌；解釋「為何沒到 PRIME」，backtest 需知 cap 生效 |
| 6 | near_miss 歸屬 + 差哪道 gate | `obs_golden_near_miss` / `_missed_gate` | 觀察名單候選；使用者看 near_miss 區 |

**B. 邊界候選（留 §5 定歸屬）：**
- `display_tier`（可買進/增強/中）：user-facing 標籤，但可由 tier+action_group 派生 → 落地或 S08 render-time 派生二選一。
- `score_breakdown`（各加分項 dict）：稽核/backtest 有用，但屬中間計算，落地成本高（巢狀）→ 可選。
- `cost_conservative/cost_diverged/cost_divergence_pct/cost_episode_weighted`：user-facing（成本背離徽章），但**產生者是 market_context dual_cost_anchor（→S07）**，golden 只搬運 → 落地所有權宜歸 S07，golden 不重複落。

**C. 不必落地（中間計算 or 他 session 所有 or 純顯示）：**
- `streak/net_cumulative/velocity_3d/acceleration/sponsorship_score/sector`＝funnel 借用（→S07 落地，golden 不重複）；`sm_state/transition_risk/days_in_sm_state/sm_state_entered`＝state_machine 借用（→S04）；`is_tier_a`＝watchlists 靜態 config。
- `tier_zh/tier_en/tier_color`、`sm_state_zh/color`、`transition_risk_zh/color`＝純 i18n/顏色（→S08 從 tier 映射，絕不進引擎輸出契約）。

→ **golden 自產、契約級候選核心 3 名**：`obs_golden_tier`、`obs_golden_conviction`、`obs_golden_action_group`（含 gates_passed/tier_caps/near_miss 共 6 項 A 級）。

---

## §5 裁定（fable，2026-07-10）

> 裁定框架：SESSION-TEMPLATE §5 rubric。前提不變：凍結期，只立契約方向；fii cap 已裁不重議。

### 系統身份判準
Golden 是全系統**後果最重的 O 態生產者**（使用者按它進場）——Observation-First 的試金石就在這裡：連錢路的判定都不落 System of Record，SoR 就是空話。同時 code 自我宣稱「No buy/sell recommendations」（golden.py:9）而尾端產出「可買進」，**系統身份與實作已經自相矛盾**，本裁定要把這條線劃清楚。

### Root Causes — 13 條發現壓縮為 1 個新根因 + 2 個既有 RC 的實例 + 1 條紅線違例

**RC-8｜資格判定與進場行動判定被綁成一體，且行動判定偽裝成顯示（P0，本 session 新立）**
吸收 §3-4/5（a 組）與 §1 定性。Golden 實際生產**兩種不同的判斷**：(i) **資格**（gates→conviction→tier→caps）＝「這檔憑籌碼結構夠不夠格」；(ii) **進場行動**（action_group：價格容忍 5% 鐵則＋動能 weakening）＝「夠格的現在能不能買」。兩者輸入不同、變動節奏不同、錯誤代價不同，卻住同一模組尾端，且第二種被標成「display-only」（golden.py:778 自稱不改判定，golden.py:799 實際 AND 三個異質判定產 buy 語意）。
裁定：**承認「進場行動」是獨立的 O 態產品**（Classification 子型，producer 仍可是 golden 模組——是否拆檔屬實作細節 P2）；`action_group` 是判斷、必落 snapshot；`display_tier` **不是判斷**——它可由 (tier, conviction, action_group) 純派生，屬 presentation 映射，**不落地**（見新法 C9）。「可買進」三個字從此有明確譜系：資格(O) + 行動(O) → 顯示映射(P)。

**RC-9｜判斷材料的組裝發生在錯誤的層（P1，新法 C8 的來源）**
吸收 §3-8/9 與 (a)-5 的 viewer 中轉證據。兩個症狀同根：(i) viewer 從 snapshot 取 weak_map 再**傳入** golden 的行動函式（cockpit.py:2672-2680）——presentation 層在**組裝判斷的輸入**，這比「render-time 重算」更隱蔽的紅線侵蝕；(ii) golden 自建 `for snap in reversed(snapshots)` 掃 fii_net_buy（golden.py:371-388）——跨快照時序邏輯洩漏進資格引擎，而 snapshot 明明已有 `fii_consecutive_buy_days` 這類由 temporal_enrich 落地的先例，賣超 streak 沒有 owner 才被 golden 撿走。
裁定：立**新契約原則 C8（組裝權）**：跨引擎判斷的組裝是 core 生產者的職責，其輸出本身是必落地的 O；presentation 只能讀單一落地欄位做映射，**不得充當判斷輸入的搬運工**。fii 賣超 streak 的 ownership 缺口記入遷移案（institutional-flow O，additive 補一欄，owner=temporal_enrich 一系）。

**（實例，非新根因）§3-10/11/13 ＝ RC-1/RC-6 在錢路上的確認**：GoldenEntry 32 欄零落地、連 schema stub 都沒有（比 abstain stubs 更徹底的第 ii 類）；保證強度落在「不可驗」級。不另立 RC，落地清單見下。

**（紅線違例，非新根因）§3-6/7 門檻治理**：conviction 權重與 tier 切點寫死 code，違紅線 #3，由 S05 RC-2 registry 吸收——**但有一個被證據包低估的 replay 後果，升為落地前置條件**：`config_snapshot` 參與 canonical hash，而寫死在 code 裡的權重**對 replay 不可見**。若先落地 obs_golden_* 再改權重，歷史快照將載著「由看不見的參數算出的判定」——落了也無從解釋。**∴ 門檻 config 化是 obs_golden_* 落地的前置條件**（先 config 化 → 權重進 config_snapshot → 落地的 O 態才有可解釋的譜系）。這是 D6 設計決策的深層理由第一次被說清楚。

### NOTES #12 落地清單終審（golden 自產部分）
核准 §4-A 六項，附修正：
1-5. `obs_golden_tier` / `obs_golden_conviction` / `obs_golden_action_group` / `obs_golden_gates_passed` / `obs_golden_tier_caps` ✓ 照列。
6. `obs_golden_near_miss`（含 missed_gate）✓，**但 near_miss 條目不落 tier**——§3-12 已證那個 tier 值不具資格語意，落了就是給未來的自己埋雷。
B 組裁定：`display_tier` 不落（C9 派生）；`score_breakdown` 暫不落（巢狀成本高、讀值低，backtest 若需歸因再議）；`cost_*` 落地權歸 S07，golden 不重複落。C 組照准（借用的 O 由各 owner 落，golden 不搬運落地）。
**時序註記**：落地不需等上游全落完——把 render-time 計算移到 pipeline（ingest 時算 funnel+sm+golden 一鏈）即可先落 golden 輸出；「golden 只讀落地欄位」是終態不是前置。但**門檻 config 化必須先行**（上段）。

### 新契約原則（本 session 立兩條）
- **C8 組裝權**：跨引擎判斷的組裝屬 core 生產者，輸出必落地；presentation 只映射、不組裝、不搬運判斷輸入。
- **C9 可純派生者不落地**：能由已落地欄位純函數派生的顯示標籤（如 display_tier）不進 snapshot——落地它只會製造雙真相；判斷（如 action_group）不適用此條，判斷必落。

### 雜訊分離
`tier_zh/color` 等 i18n 欄混在 dataclass（→S08 時清）；near_miss.tier 陷阱（已併入落地規格 6）；`tier_caps` 本輪資料集未命中（僅覆蓋註記）——均不上 verdict 表。

### 挑戰證據包
- 品質高：viewer 中轉 weakening 是證據包自己的發現，且未越權開藥方。
- **修正其一個隱藏假設**：§4 暗示「golden 落地依賴上游先落地」是硬依賴——否。計算搬進 pipeline 即可先落，硬前置只有門檻 config 化一項（replay 譜系理由）。
- **駁回其 B-1 的「二選一」框架**：display_tier 不是「落地或派生二選一」，是「判斷落地、派生不落」的一體兩面——C9 把這類問題一次定死，S02-S04 不再逐案討論。
- 錨定檢查：a-e 分組沿用交辦結構，但 (a)-5 的三模組橫跨證據與 §1 的自相矛盾定性是獨立挖掘，非餵答案。

### 不需要改的（防未來誤重構）
G1-G5 gate 鏈、conviction 加權、tier caps 的**三段引擎判定本體**（golden.py:243-418）——邏輯清楚、責任單一，RC-8 拆的是尾端不是它們；`action_group` 把 5% 鐵則放 core 的決定**本身是對的**（紅線 D5 的正確落實），錯的只是它的輸出沒落地＋掛錯「display」標籤；fii_alignment cap 語意（已裁，維持）；near_miss「差 1 gate」的定義（語意清楚有用）。

### 與已鎖決策相容性
扁平前綴 ✓（obs_golden_* 即前綴命名）；additive+alias ✓（六欄全新增，零改舊）；C1-C7 ✓（C2 落地準則的第一次引擎級執行；C7 不涉）；新增 C8/C9 與既有原則無衝突，C9 是 C2 的邊界補完（C2 說判斷必落，C9 說派生不落——一正一反閉合）。fii cap 維持 2 天 ✓ 未觸碰。

### Architecture Verdict
| 級 | 項 | 理由 |
|---|---|---|
| P0 | RC-8 資格/行動分離＋六欄落地清單核准 | 錢路的 O 態譜系是 S02-S04（同樣有組合判斷）、S08（顯示映射）、S09（回測消費名單）全部依賴的先例；本裁定的 C8/C9 就是給他們的判例 |
| P1 | 門檻 config 化＝落地前置（D6 的 replay 譜系理由） | 順序約束：先 config 化再落地，否則落地的判定帶著不可見參數 |
| P1 | C8 組裝權違例修正（viewer 中轉 weakening）＋ fii 賣超 streak ownership 缺口 | 遷移期一併處理，均 additive |
| P2 | i18n 欄移出 dataclass、score_breakdown 緩議、是否拆檔 | 自然吸收 |

### Executive Summary（兩分鐘版）
1. Golden 是全系統後果最重的判定，32 個輸出欄位卻 100% 只活在 render-time——連 disk-hash 防竄改都沒有。落地清單已核准：六個 obs_golden_* 欄位。（P0）
2. 新根因：引擎把「資格」與「進場行動」兩種判斷綁成一體，後者偽裝成顯示。裁定：行動是獨立 O 態必落地；display_tier 是純派生、永不落地。（P0，立 C9）
3. 新法 C8（組裝權）：viewer 目前在搬運判斷輸入（weakening 中轉），組裝屬 core、presentation 只映射——這條法 S02-S04 都會用到。（P1）
4. 門檻 config 化是落地的前置條件：寫死在 code 的 conviction 權重對 replay 不可見，先 config 化、權重才進 config_snapshot、落地的判定才有可解釋譜系。（P1）
5. 引擎判定本體（gates/conviction/caps）健康不動；一切 additive，無需重寫。

---

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES 已含本 session 相關發現（seed #2 render-time observation、#5 fii cap 語意已涵蓋；本輪新增之 §3-4/5（action/display_tier 越界）、§3-6/7（門檻治理不一致）、§3-9（golden 自建 fii 迭代）屬 S01 內部證據，跨 session 項已在 §3/§4 就地標歸屬 S03/S04/S05/S06/S07/S08——待 fable 裁定後由裁定者決定哪幾條 append 進 NOTES，蒐證階段不預先 append）
- [x] 00-INDEX 狀態列已更新（S01：證據包完成，待 fable 裁定；報告連結 `sessions/S01-golden-layer.md`）
- [x] 未執行任何 code/schema 改動
