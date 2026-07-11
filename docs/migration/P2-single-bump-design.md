# P2 — 1.9.0 單一 bump 設計

> **地位**：遷移路線圖（`docs/ARCHITECTURE_BLUEPRINT.md` §7）**Phase 2**的可執行設計文件。
> 整個遷移**唯一一次 schema bump**——所有 canonical 內容變更一次上車，付一次「歸零」代價（判例 #22）。
> **制定**：2026-07-11。**依據**：BLUEPRINT §4/§6/§7、`schema/field_registry.yaml`（planned 22 欄）、
> `docs/migration/P1-version-pinned-replay.md`、`docs/migration/P1-worm-backfill-report.md`、
> CROSS-SESSION-NOTES #22/#26/#29/#30/#35/#38/#40/#41/#43/#54。
> **鐵律（本文件）**：純設計、零 code / 零 schema 變更。有疑義的設計點列「選項＋建議＋理由」，標
> 「需 fable 裁定」，不默默選。實作 agent 照本文件開工。
> **誠實原則（#21/C10）**：做不到的保證明說做不到；落地起點前的歷史誠實放棄，不偽稱可回溯。

---

## 0. 一頁摘要

| # | 決策軸 | 本文件的答案 | 需裁定？ |
|---|---|---|---|
| 1 | 22 欄落地位置 | 15 個 O 欄進 StockRecord（golden6+sm6+chip1+sync_streak1+dist1）、3 個 O 欄（market）進頂層、2 個 I 欄（trust/prop）進 record、2 個 I 欄（賣方 raw）進頂層 | — |
| 2 | Pipeline 重排 | 引擎計算從 render-time（cockpit）移入 `core/ingest.py`，封印前寫入；順序 = breadth→regime→sm→golden→chip→distribution→temperature | — |
| 3 | alias 雙寫 | dealer_net_buy 續寫投信值＋trust_net_buy 同值雙寫＋prop_net_buy 新落地。**volume 家族 rename 建議延後、不與 1.9.0 同車** | 🔶 D-3 |
| 4 | config_snapshot | 從「單一 yaml」升為 `{yaml, engine_params}` 雙來源結構；strategies **不入**；仍居頂層 `config_snapshot`（MUST-I、參與 hash） | 🔶 D-4 |
| 5 | version-pin 機制 | 落 P1-5 候選 B（attestation ledger，L2.5），旁側帳 `reports/_replay_ledger.json`；候選 A（checkout 重算）與 archive 版本維度留後 | 🔶 D-5 |
| 6 | market 欄前置 | breadth 讀 `data/market_pulse/<date>.json`（母體 twse_listed，#41）；temperature 改讀 obs_sm_transition_risk（#43），依賴 sm 同批落地→順序可行 | — |
| 7 | 回填計畫 | I 欄（trust/prop/賣方 raw）回填至 **2026-05-26**（WORM 上限）；O 欄**不回填**（C10，落地起點=1.9.0 首個 production 日） | 🔶 D-7 |
| 8 | 驗收清單 | test 全綠＋1.9.0 快照達 L3 可重算＋viewer 對照＋fable review 檢查點（§8） | — |
| 9 | 風險與回退 | schema 版本回退不可行（快照已寫）；回退 = supersede 重建為 1.8.1-shape，前滾修正優先 | — |

**五句話核心**：
1. 1.9.0 把 22 欄一次落地——18 個 O 態判斷欄（黃金/狀態機/籌碼/同步/賣方/市場）＋4 個 I 態 raw 欄（投信/自營正名＋賣方原始榜），15 進 record、7 進頂層。
2. 引擎計算從 viewer render-time 搬進 pipeline（`core/ingest.py`），封印前寫入——這是「觀察必落地（C2）」與「viewer 不算（不變量 #2）」得以成立的動作。
3. 順序依賴是設計的骨架：**sm 先於 golden**（golden 讀已落地 sm_state，不重算＝治 #30 雙真相病）、**breadth/sm 先於 temperature**（#43 temperature 讀 obs_sm_transition_risk）。
4. config_snapshot 必須同時凍結兩個生效參數來源（`scd.example.yaml` ＋ `core/engine_params.py`），否則「改參數無痕」的紅線（不變量 #7）漏一半。
5. C10 是回填的判準：I 態是 raw 事實、可誠實回填（trust/prop/賣方 raw 補到 2026-05-26）；O 態是判斷、用今日 code 回算即 look-ahead 病（#48），故**一律不回填**，as-was 序列從 1.9.0 首日起算。

---

## 1. 22 欄落地位置（canonical_schema.json 的確切位置與型別）

**現況錨點**：`schema/canonical_schema.json` 頂層 `properties` 18 鍵、`$defs.StockRecord.properties` 61 欄，
兩處 `additionalProperties` 皆未設（預設 true）→ 新增欄位是 additive，schema 驗證不擋；CI 對拍
（`tests/test_field_registry.py`）才是真門檻（未登記欄不得進快照）。**故落地 = ①schema 顯式宣告型別
②registry status: planned→active ③ingest 寫入**，三者齊。

### 1a. 15 個 per-ticker O 欄 → `$defs.StockRecord.properties`（grain=ticker）

放在 record 內既有 `weakening` 之後、`temporal_state`（deprecated）之前，新增一個 `obs_*` 區塊。

| # | 欄名 | JSON 型別 | 語意 / 內容 | 生產者 |
|---|---|---|---|---|
| 1 | `obs_golden_tier` | `string|null` | enum：PRIME/STRONG/WATCH/IGNORE（`_tier_from_score`） | Golden |
| 2 | `obs_golden_conviction` | `number|null` | 0.0–1.0（4dp quantize） | Golden |
| 3 | `obs_golden_action_group` | `string|null` | enum 行動群組（5%鐵則＋weakening；#27 行動非資格） | Golden |
| 4 | `obs_golden_gates_passed` | `object` | `{G1,G2,G3: bool}` | Golden |
| 5 | `obs_golden_tier_caps` | `object|null` | `{capped_to, reason}`（fii_alignment cap 等） | Golden |
| 6 | `obs_golden_near_miss` | `object|null` | `{missed_gate, ...}`；**不落 tier**（#26） | Golden |
| 7 | `obs_sm_state` | `string` | 生命週期狀態 enum（唯一 SoT，#31） | StateMachine |
| 8 | `obs_sm_transition_risk` | `string` | 風險 enum（「風險」唯一 SoT，#37） | StateMachine |
| 9 | `obs_sm_days_in_state` | `integer` | 在此狀態天數 | StateMachine |
| 10 | `obs_sm_state_entered` | `string|null` | 進入當前狀態日（ISO date） | StateMachine |
| 11 | `obs_sm_structure_unstable` | `boolean` | 結構不穩旗標 | StateMachine |
| 12 | `obs_sm_risk_factors` | `array[string]` | 風險因子清單 | StateMachine |
| 13 | `obs_chip_grade` | `object` | `{grade: enum, total: int, items: {...}}`（含 total 子值，#35） | Chip |
| 14 | `sync_streak` | `integer|null` | 參與者同向連續數（registry 終名 `derived_participant_sync_streak`，alias 見 §3） | temporal_enrich |
| 15 | `obs_dist_consistency` | `object|null` | `{consistency_grade, score, ...}`；tickers 不在賣方榜→null（#38） | Distribution |

**設計註記**：
- `obs_chip_grade` 含 total 子值 = 憲法 §4「17 欄」off-by-one 的來源；registry 逐名登記為 distinct
  欄名，此處落一個 object 欄，total 是其子鍵，不另立頂層欄（NOTES #54 計數正名）。
- `obs_golden_*` 是**新的真值 SoT**；record 內既有的 P3a abstain 欄（`tier`/`composite_score`/
  `stage_*`/`gates`/`checklist`）**維持不變**（仍 abstained stub）。理由：改既有欄語意 = major（C5/C6），
  1.9.0 是 minor，只能 additive 新增。舊 P3a 欄在 Phase 3/5 退場。→ 見 D-1。

### 1b. 3 個 market O 欄 → 頂層 `properties`（grain=date）

放頂層既有 `market_regime`（stub, deprecated-pending）之後，新增：

| # | 欄名 | JSON 型別 | 語意 | 生產者 |
|---|---|---|---|---|
| 16 | `obs_market_regime` | `object` | `{label, features, ...}`（regime_shift 收斂，#40） | Market |
| 17 | `obs_market_breadth` | `object` | `{advancers, decliners, total, breadth, universe}`（母體修正，#41） | Market |
| 18 | `obs_market_temperature` | `object` | `{temperature, level, ...}`（讀 obs_sm_transition_risk，#43） | Market |

頂層舊 `market_regime` stub 維持 deprecated-pending（真值走 `obs_market_regime`；registry alias 已標）。

### 1c. 4 個 I 欄

| # | 欄名 | 位置 | JSON 型別 | 語意 | grain |
|---|---|---|---|---|---|
| 19 | `trust_net_buy` | record | `integer|null` | 投信淨買（張）正名；與 dealer_net_buy 同值雙寫（§3） | ticker |
| 20 | `prop_net_buy` | record | `integer|null` | 自營商淨買（張）新落地（adapter 早算出 `prop_dealer_net_buy`，ingest 從未讀） | ticker |
| 21 | `fii_sell_raw` | **頂層** | `array\|object` | 外資賣超原始榜 passthrough（today.json.sellList；C7 非破壞） | date |
| 22 | `main_force_sell_raw` | **頂層** | `array\|object` | 主力賣超原始榜 passthrough（today.json.mainForceSell；obs_dist_consistency 的輸入） | date |

**賣方 raw 為何進頂層而非 record**：sellList/mainForceSell 是**整份市場級榜單**（一天一份，含不在
universe 內的 ticker），grain=date（registry 已標 `grain: date`）。放頂層一筆、形狀原封（C7），
不拆進 per-ticker record——拆進 record 會銷毀「完整榜」資訊且製造 grain 錯置（判例 #42 教訓）。

---

## 2. Pipeline 重排（render-time → pipeline，封印前寫入）

### 2a. 現況（病）
`viewer/cockpit.py:46-53` import 九個 core 引擎（golden/confidence/state_machine/resonance/
chip_score/holdings/distribution/market_context/narrative），**render-time 計算判斷**。`core/ingest.py`
**零引擎 import**（實測），只產 P3a abstain 骨架。→ 判斷不落快照、replay 不覆蓋判斷層、「UI==snapshot」
結構性不成立（NOTES #2 架構根病）。

### 2b. 目標
引擎計算移入 `core/ingest.py`，在 `ingest()` 組裝 record 之後、`return snapshot` 之前寫入 obs_*。
`ingest.py` 新增 import：`core.state_machine`、`core.golden`、`core.chip_score`、`core.distribution`、
`core.market_context`（regime_shift＋relocated temperature）。呼叫點 = `ingest()` 內，現有
temporal_enrich/weakening 迴圈之後（見 `ingest.py:311-355`）。

**daily.py / run_pipeline.py 哪一步**：`tools/daily.py:355` Step 2 已呼叫 `run_pipeline --check-replay`，
`run_pipeline.run()` 呼叫 `ingest()`（:189）。**兩個 orchestrator 檔零改動**——引擎計算全落在 `ingest()`
內部。daily.py 的 Step 4 intelligence / Step 5 backtest 不變（Phase 3/4 才處理）。

### 2c. 呼叫順序（順序即依賴——設計骨架）

在 `ingest()` 內，建完 per-ticker record 骨架（含 temporal_enrich/weakening）後，依序：

```
① obs_market_breadth   ← 讀 data/market_pulse/<date>.json（純 I，無 O 依賴）        [頂層]
② obs_market_regime    ← regime_shift(已落地歷史序列 + 當日 record)                  [頂層]
③ obs_sm_*  (6 欄)     ← state_machine.run_all(snapshots)；SM_BREADTH_CONFIRMED 讀①  [per-ticker]
④ obs_golden_* (6 欄)  ← golden.run(snapshots)，改讀已落地 obs_sm_state（不重算 sm）  [per-ticker]
⑤ obs_chip_grade       ← chip_score.compute(...)（record 欄，無跨引擎依賴）           [per-ticker]
   sync_streak         ← temporal_enrich 系（已在既有迴圈，改暴露為落地欄）           [per-ticker]
⑥ obs_dist_consistency ← distribution.run(date)，讀 main_force_sell_raw（I）           [per-ticker]
⑦ obs_market_temperature ← 讀③的 obs_sm_transition_risk 聚合 + ①breadth（#43）        [頂層]
```

**關鍵依賴（實測 code 佐證）**：
- **golden 內部現呼叫 `sm_run_all`**（`golden.py:463`）＝重算 sm。#30 紀律「已落地者必改讀」要求
  golden 改讀 record 內的 `obs_sm_state`，**不重跑 sm**（治雙真相病）。→ 實作須改 `golden.run` 簽章或
  在 pipeline 先算 sm、把 sm_states 傳入 golden（避免 double-compute）。見工作包 W3。
- **golden conviction 讀 sm confirmed**（`GOLDEN_W_STATE_CONFIRMED`，golden.py:66 之權重）→ sm 必先於 golden。
- **sm CONFIRMED 要求市場廣度**（`SM_BREADTH_CONFIRMED=0.50`，engine_params.py:83）→ breadth 必先於 sm。
- **temperature 讀 sm transition_risk**（#43）→ sm 必先於 temperature。
- 三者合成一條偏序：`breadth → sm → {golden, temperature}`，regime/chip/dist 可並行插入，無環。

### 2d. C10 bootstrap 語意（1.9.0 首日 = 落地起點）
sm/temporal 是路徑依賴引擎（讀歷史序列）。**歷史序列有兩種**：
- **raw 歷史**（main_force_buy、fii_net_buy 等 I 欄）：1.9.0 之前的快照**都有**→ sm 可從 raw 重建狀態。
- **已落地 obs_sm_state 歷史**：1.9.0 首日**不存在**（O 欄從今天才開始落）。

**裁定（C10）**：1.9.0 首個 production 日，sm 從 **raw 歷史 bootstrap** 計算當日 obs_sm_state（誠實：
路徑依賴的「當日認定」以 raw 序列為據）；**自隔日起**，路徑依賴決策（days_in_state 累計、flips 判定）
改讀**已落地的 as-was obs_sm_state 序列**（#30「已落地者必改讀」）。落地起點之前的 obs_sm_state 歷史
**不存在也不偽造**——bootstrap 首日的 days_in_state 從 1 起算，之前狀態誠實放棄。golden action_group
的 weakening 輸入同理（讀已落地 weakening，不 render-time 組裝，治 C8 違例 cockpit.py:2672）。

> **實作備忘**：bootstrap 首日與穩態日的差別僅在「days_in_state / state_entered 的起算」——首日
> 這兩欄以「本日為進入日」落地（entered=1.9.0 首日、days=1），不回溯 raw 推算更早的 entered
> （那會把「用今日 code 回算的歷史」焊進 as-was，違 #48）。此為 D-1 的一部分。

---

## 3. alias 雙寫機制

### 3a. dealer/trust/prop（correctness 修正，**必上車**）

現況：`core/ingest.py:182` `dealer_net_buy = raw.get("investment_trust_net_buy")`——**名叫自營商、
實裝投信**（🔴 correctness，NOTES #1）；真自營商值 adapter 早算出（`prop_dealer_net_buy`）但 ingest
從未讀取、被丟棄。`data/adapters/legacy.py` 已 staging 輸出 `trust_net_buy`/`prop_net_buy`/賣方 raw。

**1.9.0 動作**（三欄，registry planned 已登記）：
1. `dealer_net_buy`：**舊名續寫投信值**（不動，避免破壞現有消費者；registry `alias: trust_net_buy`）。
   續寫至 2.0 major 移除（C5 additive）。
2. `trust_net_buy`：**新欄、與 dealer_net_buy 同值雙寫**（投信淨買正名）。ingest 讀 adapter 的
   `trust_net_buy` key。
3. `prop_net_buy`：**新欄、新落地真自營商值**（讀 adapter 的 `prop_net_buy`／`prop_dealer_net_buy`）。
   **非既有欄的 alias**——現行快照根本無此值，是搶救被丟棄的 raw。

> **消費端連坐**（#36）：`core/resonance.py:34` 讀誤名 `dealer_net_buy` 當投信（碰巧值對）。
> resonance 已判死（#35 解散），Phase 3 處決時一併移除；1.9.0 不動 resonance（它 render-time、不落快照）。

### 3b. sync_streak alias
`sync_streak` 落地時 registry 終名候選 `derived_participant_sync_streak`（#35）。1.9.0 建議**以
`sync_streak` 為落地欄名、`derived_participant_sync_streak` 為 registry alias**（與 registry 現況一致），
終名切換留 2.0 major（避免 1.9.0 又多一組 rename 雙寫）。

### 3c. volume 家族 rename — 建議**延後，不與 1.9.0 同車**（🔶 需 fable 裁定 D-3）

**背景**：registry 對 `volume`/`volume_ratio`/`volume_5d_avg`/`fii_*`/`main_force_*`/`tdcc_*` 約 40 欄
標了 `mf_*`/`foreign_*`/`tdcc_*` 扁平前綴 alias（FIELD_MAP 2026-07-08 提議），但這些**只是 alias 標註、
rename 待 Phase 1/3**，不在 planned_fields（未核准落地）。

**張力**：判例 #22「每次 bump 讓此前全部快照的 L3 保證歸零」→ 表面上論證「所有 canonical 變更（含
alias 雙寫新欄）都該塞進 1.9.0，只付一次歸零」。

**選項**：
- **A（同車）**：1.9.0 同時對 volume 家族做 alias 雙寫（新增 mf_net_buy=volume 副本等 ~40 欄）。
  優點：只付一次歸零。缺點：把 40 個純命名副本欄塞進遷移最關鍵的一次 bump，欄數/驗證面翻倍，
  零 correctness 收益。
- **B（延後，建議）**：1.9.0 只做 dealer/trust/prop 正名（correctness 修正，非做不可）＋22 欄落地；
  volume 家族純命名 rename 留 **2.0 major**（major 本就移除舊名、換新名，不需雙寫過渡）。

**建議 B，理由**：
1. dealer/trust/prop 是**修錯值**（wrong data in wrong field），volume 家族是**改對值的名**
   （欄位裝的是正確值、只是名字誤導）——兩者嚴重度不同，不該綁死。
2. #22 的歸零論證有前提：**只有當某消費者需要在 1.9.0～2.0 window 內遷移到新名**時，才需要在 1.9.0
   就把新名雙寫上車。查證：Phase 3 viewer 薄化的判準是「不 render-time 重算」（四紅線），**不是改欄名**
   ——viewer 讀 `volume` 或讀 `mf_net_buy` 對薄化無差別。故 **1.9.0～2.0 之間無消費者需要 mf_* 名**
   → 不需在 1.9.0 雙寫 → 留 2.0 major 直接 rename，**不多付一次歸零**（2.0 本就是計畫內的最後歸零）。
3. C5「alias 跨 minor 雙寫、major 才移除」的精神是**服務真實的消費者遷移窗口**；沒有窗口需求就雙寫，
   是為制度而制度。
- **反對意見（供裁定參考）**：若未來 1.9.x 有任何 minor bump（非計畫內），volume rename 拖到那時會
  多付一次歸零。緩解：本文件明列「1.9.0→2.0 之間不再 minor bump」為遷移紀律（BLUEPRINT §7 單一 bump
  原則的直接延伸），若守此紀律，B 無額外成本。

---

## 4. config_snapshot 結構設計

### 4a. 現況（病）
`config_snapshot` = `scd.example.yaml` 整份 dict（`ingest.py:374`）；`config_hash =
canonical_sha256(config)`（:358），config 就是 yaml。**但 Phase 1 已把一批判斷參數外置到
`core/engine_params.py`**（TIER_A 名單、GOLDEN_*/SM_*/CHIP_SCORE_CONFIG/GRADE_PCT_MAP/MC_* 門檻權重）
——這些**生效參數不在 config_snapshot 內**。→ 改 engine_params.py 任一值會無痕改變歷史意見，對 replay
不可見（違反不變量 #7）。Phase 1 明言「config_snapshot 入 canonical hash 隨 1.9.0」（engine_params.py:14）。

### 4b. 目標結構（雙來源，皆凍結、皆參與 hash）

`config_snapshot` 頂層鍵不變（registry 已登記 MUST-I、參與 hash），**值從 flat-yaml 升為結構化**：

```json
"config_snapshot": {
  "yaml":          { ...scd.example.yaml 整份原封... },
  "engine_params": {
    "TIER_A":            { ...名單... },
    "GOLDEN_GOLD_SPON_MIN": 0.45, "GOLDEN_W_STREAK_HIGH": 0.25, ... (全 UPPERCASE 常數),
    "SM_STREAK_ACCUMULATING": 1, ...,
    "CHIP_SCORE_CONFIG": { ... }, "GRADE_PCT_MAP": [...],
    "MC_BREAKOUT_LOOKBACK": 10, ...
  }
}
```

- **序列化**：`core/engine_params.py` 新增 `as_config_dict() -> dict`，回傳所有 public UPPERCASE
  名稱→值的**有序 dict**（sorted keys，確定性）。純資料、零環境依賴（engine_params 本就是純 Python）。
- **`config_hash`**：改為 `canonical_sha256(config_snapshot)`（覆蓋 yaml＋engine_params 雙來源）。
  這是 config_snapshot **內容變更**→自然屬 1.9.0 bump 的一部分。
- **C11 演示保持**：改 yaml 或 engine_params 任一值 → config_snapshot 變 → config_hash 變 → replay
  偵測得到（`tests/test_config_extraction.py` 已證 reload 語意，擴充一測涵蓋 hash）。

### 4c. strategies 是否納入？（🔶 需 fable 裁定 D-4）
`core/strategies.py` 是回測策略規則（config 化的先天健康樣本，#53）。
- **選項 A**：納入 config_snapshot.strategies——「所有判斷參數集中一處」。
- **選項 B（建議）**：**不納入**。理由：strategies 只影響**回測產物**，而回測產物 #52 裁定「不落
  canonical、per-run version-pin（帶 strategy config hash）」。把 strategies 塞進**每日 canonical**
  config_snapshot 會讓「改回測策略」污染每日快照 hash（每日快照與回測無關）——違反關注點分離。
  strategies 的凍結歸 Phase 4 回測產物的 per-run pin（S09 #52），不歸每日 canonical。

**建議 B**：config_snapshot = `{yaml, engine_params}` 兩鍵；strategies 留給回測產物 pin。

---

## 5. version-pin 機制實作規格（P1-5「與 bump 同車」的部分）

### 5a. 承 P1-5 的裁決
P1-5 §2 誠實分級：候選 A（git-checkout 重算，L3）最強但最重、且 zero-SHA 的 17 份 1.4.0 快照永久做不到；
候選 B（attestation ledger，L2.5）是**推薦的務實中間態**；候選 C（參與權契約化）P1 已落。
P1-5 §5 交棒 Phase 2：**候選 B 與 bump 同車設計**（避免半套 ledger）。

### 5b. 落地規格 — 候選 B：attestation ledger

**目的**：把「bump 後全部既往快照 L3 歸零」補成「歸 L2.5」——記錄每份快照**生成當時**通過
`--check-replay`（同機二跑 byte-identical）的證明，連同 `core_commit_sha`＋hash。

**檔案**：`reports/_replay_ledger.json`（**旁側帳，不入 canonical、不入快照、不參與 canonical hash**）。
結構（append-only，每份快照一筆）：
```json
{
  "ledger_version": "1.0.0",
  "entries": [
    {
      "date": "2026-07-13",
      "canonical_hash": "sha256:...",
      "core_commit_sha": "abc123...(40hex 或 zero-SHA)",
      "schema_version": "1.9.0",
      "check_replay_passed": true,
      "attested_at": "2026-07-13T12:00:00Z"
    }
  ]
}
```

**寫入點**：`tools/run_pipeline.py` 的 `--check-replay` 分支（:226-246）——在 h1==h2 判定成立後，
append 一筆 ledger entry（date/hash/sha/schema/passed=true/attested_at）。h1!=h2 則寫 passed=false。
**冪等**：同 (date, canonical_hash) 已存在則不重複 append（re-ingest byte-identical 是 no-op，呼應
`_update_index` 的 no-op 語意）。supersede（partial→complete）產生**新** hash → append 新 entry，
舊 entry 保留（append-only，記錄「這個 hash 曾在生成當時通過驗證」）。

**誠實界線（不許諾 L3）**：ledger 證明「生成當時同輸入→同輸出成立」，**不**證明「今天用今天的機器
還能重算」。它是 L2.5（強於裸 disk-hash 的 L2、弱於隨時可重算的 L3）。**絕不**被 verify/viewer/backtest
當真值源消費——只作驗證輔助（避免漂成第二份 SoR，守不變量 #1）。

**verify_all_replay 的角色**：不改判定邏輯（仍 tip-only walker、epoch 分流）；可**額外**讀 ledger
交叉核對「current tip 的 hash 是否 == ledger 最新 entry」，作為軟報告，**不 gate**。

### 5c. 不落的部分（明列，避免半套）
- **候選 A（per-epoch checkout replay，L3）**：CI 依 core_commit_sha checkout＋pin venv 重算——受
  zero-SHA 硬邊界與依賴可重建性限制，**留 Phase 2 之後**評估，1.9.0 不落。
- **archive 版本維度（RC-7）**：#23 已證 standard verify-all-replay tip-only walker 踩不到 archive
  覆寫坑；archive 改 `(date, hash)` append-only 是候選 A 的前提、屬 additive，待 partial→supersede
  有真實樣本後再評估（P1-5 §4），1.9.0 不落。
- **environment 退出 canonical hash（不變量 #6）**：現況靠 normalize 於**比對時**排除；徹底修法
  （計算時排除）屬 hash 規則變更，留 Phase 4，1.9.0 不動。

---

## 6. market 欄的特殊前置

### 6a. obs_market_breadth — 讀 market_pulse per-date（#41 母體修正）
**現況病**：`regime_shift`（market_context.py:336）的 breadth = `sum(mf>0)/len(mf)`——**以主力買超
top-N 榜當母體**，依構造恆 ≈1.0（breadth 維度死、temperature 30% 權重常數、transition 假訊號，#41）。

**修法**：obs_market_breadth 改讀 **`data/market_pulse/<date>.json`**（P1-2 已產，commit 4f6f191）的
`breadth` 區塊：`{advancers, decliners, unchanged, total, universe: "twse_listed_stocks"}`——真全市場
漲跌家數母體。breadth 值 = `advancers / (advancers + decliners)` 或既定公式（實作照 registry 語意）。
`universe` 欄明文宣告母體（C1），未來加上櫃是 additive 新 scope key。

**缺料處理（C10）**：market_pulse per-date 檔缺失或 `breadth` 解析失敗（errors 非空）→ obs_market_breadth
落 null-with-reason，**絕不靜默給 0.5**（fetch_market_pulse 已嚴格失敗寫 errors，不靜默給 0）。

### 6b. obs_market_temperature — 改讀 obs_sm_transition_risk（#43）
**現況病**：temperature 計算在 `core/confidence.py:518 _build_temperature`，讀 `ConfidenceProfile.
risk_level`（confidence 引擎，#37 已判死降級）＋ sm state_counts ＋ breadth_sig。

**修法（#43 雙前置）**：
1. **搬家**：temperature 計算移出 `confidence.py`，歸 **Market 家族**（market_context.py 或新
   market 模組），confidence 引擎不再是它的依賴。
2. **改讀源**：`elev_ratio` 分子從 `p.risk_level in (elevated, critical)` 改為讀**當日已落地的
   `obs_sm_transition_risk`** 聚合（不得續建在已廢 confidence risk_level 上）；breadth 成分改用
   §6a 的母體修正 breadth。
3. **順序保證**：temperature 在 pipeline 順序 ⑦（sm 已於 ③ 落地 obs_sm_transition_risk、breadth 已於
   ① 落地）→ 讀當日 record 聚合即可，**同批落地順序可行**（§2c 已證無環）。

### 6c. obs_market_regime
`regime_shift`（收斂為唯一市場級生產者，#40）搬出 market_context.py 成家；breadth 維度改用 §6a 母體
（不再用榜當分母）。`obs_market_avg_chg` **不落**（#40：純平均無判斷參數＝C9）。頂層舊 `market_regime`
stub → deprecated-pending（真值走 obs_market_regime）。

---

## 7. 回填計畫（哪些回填、哪些不回填——明確寫出）

**判準 = C10**：I 態是 raw 事實、可誠實回填；O 態是判斷、用今日 code 回算 = look-ahead 病（#48）→ 不回填。

### 7a. 回填（I 欄）— 至 2026-05-26
依 `P1-worm-backfill-report.md`：WORM 存檔 today.json（含 T86＋賣方榜）最早完整日 = **2026-05-26**。

| I 欄 | 回填範圍 | 上限依據 |
|---|---|---|
| `trust_net_buy` | 2026-05-26 → 1.9.0 前一交易日 | T86 存在的 27 天（prop/trust 同源 T86，逐檔 100%） |
| `prop_net_buy` | 2026-05-26 → 1.9.0 前一交易日 | 同上（自營商值在 WORM today.json 的 t86，可回填） |
| `fii_sell_raw` | 2026-05-26 → 1.9.0 前一交易日 | sellList 非空的 32 天 |
| `main_force_sell_raw` | 2026-05-26 → 1.9.0 前一交易日 | mainForceSell 非空的 32 天 |

**結構性放棄（誠實，C10）**：11 個 rollup-only 日（2026-05-08/13/14/15/17/18/20/21/22/25/27）WORM 無
today.json，trust/prop/賣方 raw 三者**結構性不存在**，backfill 無解；5 個 fii_pending 空 t86 日
（05-28/05-29/06-03/06-25/07-10）prop/trust 缺、賣方榜有。早於 2026-05-26 一律不回填。

### 7b. 不回填（O 欄）— 落地起點 = 1.9.0 首個 production 日
18 個 obs_* O 欄**一律不回填**（C10 as-was，#29/#48）。理由：obs_golden_*/obs_sm_*/obs_chip/
obs_dist/obs_market_* 都是路徑依賴或判斷欄，用今日 code＋今日門檻回算歷史 = 參數 look-ahead
（#48 實證改 entry_streak_min 歷史交易 8→3 無痕位移）。**as-was 序列從 1.9.0 首日起算**，之前誠實放棄。

### 7c. I 回填不得順帶落 O（🔶 需 fable 裁定 D-7 — 本文件最需裁定點）

**衝突**：回填 I 欄 = re-ingest 歷史日期。但 1.9.0 的 `ingest()` **會計算 O 引擎**（§2 重排的直接後果）
→ re-ingest 歷史日期會**順帶算出 obs_* O 欄**，直接違反 7b「O 不回填」。

**選項**：
- **A（I-only backfill 模式，建議）**：`ingest()` 加 backfill 旗標（如 `obs_landing: bool`）。歷史
  I 回填走 `obs_landing=False`：只寫 4 個 I 欄、**跳過 O 引擎、obs_* 欄不寫**（schema additive 容忍
  缺欄）。這些歷史快照 schema_version 升 1.9.0、標記 `obs_landing: false`（頂層旗標，registry 登記
  為 O/date/epoch-scoped），viewer/backtest 據此知道「此日無 as-was O 序列」。
- **B（不回填 I，只留 WORM）**：歷史快照完全不動，trust/prop/賣方 raw 只從 1.9.0 首日起出現在快照；
  歷史值留在 WORM archive，未來需要時另闢讀路。優點：零 supersede churn、歷史快照凍結。缺點：違背
  任務明示「I 欄回填至 2026-05-26」的要求；歷史快照的 dealer_net_buy 仍是誤名投信值（correctness 未修）。
- **C（re-ingest 全跑，O 也落）**：直接違反 C10/#48，**排除**。

**建議 A**，理由：
1. 精確落實「I 回填、O 不回填」——backfill 模式只碰 raw、不碰判斷，C10 語意乾淨。
2. `obs_landing: false` 旗標讓「這天有 I 但無 as-was O」對 Phase 4 backtest 顯式可見（backtest 讀
   as-was 序列時，據旗標跳過 obs_landing=false 的日子，不誤把「無」當「有」）。
3. 相對 B，修好了歷史 dealer/trust/prop 的 correctness（正名值進歷史快照可供分析）。
- **裁定要點**：A 增加 ingest 一個分支（backfill 模式）與一個頂層旗標，是 1.9.0 pipeline 的額外複雜度；
  請 fable 裁 A（精確但多一分支）vs B（簡單但歷史 correctness 不修、且違任務明示回填要求）。
- **供料註記**：無論 A/B，回填都經 supersede 鏈（`_update_index` partial→history），會產生 1.8.1→1.9.0
  的 epoch 轉移樣本——這正是 NOTES #19「partial→supersede production 零覆蓋」缺的真實樣本來源之一。

### 7d. 1.9.0 首日的兩段式快照交互
若 1.9.0 首日恰為 fii_pending partial（T86 未到）：obs_* 中依賴 fii 的部分（golden conviction 的
fii_alignment、sm 的 fii 同向、chip institutional）在 partial 上會退化。**建議**：partial 快照照樣落
obs_*（fii 依賴部分誠實 abstain/降級），早晨 supersede 補完時重算全量 obs_*——與現有 partial→complete
機制一致，obs_* 隨 supersede 一起被 complete 版取代（as-was：partial 當日認定 vs complete 當日認定，
兩版都留可驗）。此點併入驗收（§8）觀察。

---

## 8. 驗收清單（bump 當日完整步驟 / 供 fable review 檢查點）

### 8a. 落地前（前置閘門，缺一不 bump）
- [ ] Phase 1 五線全綠：門檻 config 化（engine_params.py 就位）、母體修正（market_pulse per-date 歸檔）、
      adapter staging（trust/prop/賣方 raw 已輸出）、replay 契約化（replay_contract.py）、version-pin 設計。
- [ ] `data/market_pulse/<date>.json` 對目標交易日存在且 breadth 解析成功（errors 空）。
- [ ] `make test` 全綠（以執行當日 main 實際通過數為基線，不得少）。
- [ ] `make verify-all-replay` 0 fail（**先記錄執行前 full/legacy 計數當基線**；絕對數字隨資料修正
      演進——2026-07-11 handoff#2 重建 cascade 後約 6 full + 36 legacy / 42，以當日實跑為準）。

### 8b. bump 當日（實作 agent 執行順序）
1. [ ] schema：canonical_schema.json 顯式宣告 22 欄型別（§1）；`SCHEMA_VERSION` 1.8.1→1.9.0；
       registry 22 planned→active、寫 landing_version 落地紀錄；scd.example.yaml meta.schema_version 同步。
2. [ ] ingest：引擎計算移入（§2）、config_snapshot 雙來源結構（§4）、config_hash 覆蓋新結構。
3. [ ] golden 改讀已落地 obs_sm_state（不重跑 sm，§2c/W3）；temperature 搬家＋改讀 obs_sm_transition_risk（§6b）。
4. [ ] 跑 1.9.0 首個 production 日：`run_pipeline --date <D> --check-replay` → **replay ✅ PASS**
       （h1==h2 byte-identical）→ ledger append 一筆 passed=true（§5b）。
5. [ ] I 欄回填（backfill 模式，§7c-A）：2026-05-26 → 1.9.0 前一日，每日 supersede；抽驗一日
       `dealer_net_buy == trust_net_buy`（雙寫）、`prop_net_buy` 非 None（有 T86 日）、無 obs_* 欄
       且 `obs_landing: false`。

### 8c. 落地後（bump 完成的核對）
- [ ] **當日 1.9.0 快照含全部 22 欄**且值與（尚未薄化的）viewer render-time 顯示**一致**——逐欄對照：
      obs_golden_tier == cockpit golden 名單 tier、obs_sm_state == cockpit 狀態、obs_chip_grade ==
      cockpit 籌碼評級、obs_market_breadth == market_pulse 母體、obs_market_temperature == cockpit 溫度。
- [ ] **replay 對 1.9.0 快照達 L3「可重算」**（same-machine check-replay 綠；ledger 記錄）。
- [ ] `make verify-all-replay` 仍 0 fail（1.9.0 快照走 full-replay-clean、既往走 legacy-epoch-clean）。
- [ ] **C11 測試**：改 engine_params.py 任一值＋改 scd.example.yaml 任一值 → config_hash 變、canonical
      hash 變（`test_config_extraction.py` 擴充涵蓋雙來源）。
- [ ] **fii_pending 交互**（若首日 partial）：partial 落 obs_*、supersede 補完後 obs_* 重算為 complete 版。
- [ ] **fable review 檢查點**：22 欄型別/grain/owner 對齊 registry；O/I 態分離無誤裝；C10 回填邊界
      （I 回填、O 不回填、obs_landing 旗標）；config_snapshot 雙來源；ledger 非 SoR（不被消費）。

---

## 9. 風險與回退

### 9a. 風險
- **低（機制面）**：replay 契約化、母體修正、adapter staging、version-pin 設計都在 Phase 1 驗證過；
  1.9.0 主要是「搬家＋落地」的一次性資料核對工作量（BLUEPRINT §7 Phase 2 風險評為低）。
- **中（整合面）**：golden 內部重算 sm 的解耦（W3）是唯一需改引擎介面的點，若沒改乾淨會 double-compute
  或雙真相；temperature 搬家＋改讀源（§6b）觸及 confidence.py（判死引擎），須確認不殘留 confidence 依賴。
- **資料面**：market_pulse per-date 對某交易日缺料 → obs_market_breadth/temperature 退化（C10 誠實落 null，
  不 gate bump，但驗收要看到 null-with-reason 而非靜默 0）。

### 9b. 回退策略
- **schema 版本回退不可行**：一旦 1.9.0 快照寫入磁碟＋index，`SCHEMA_VERSION` 改回 1.8.1 會讓該快照
  變成「1.9.0 內容、1.8.1 宣告」的孤兒，且 verify epoch 分流錯亂。**不走版本號回退**。
- **正解 = supersede 前滾**：bump 當日快照若發現錯誤，走**修正後 re-ingest supersede**（`_update_index`
  partial→history 鏈）——新版取代舊版、兩版都留可驗（C10：落地即定案，修正走 supersede 留痕，永不原地
  改寫，不變量 #9）。回填快照同理，錯了 supersede 重跑。
- **ledger 回退**：ledger 是 append-only 旁側帳，錯誤 entry 標 passed=false 保留（不刪），前滾新 entry。
- **最壞情況（bump 根本性錯誤，需棄用 1.9.0）**：因無版本回退，實務是「凍結 1.9.0 首日快照為既成事實
  （as-was 誠實），修正後的邏輯以新的 supersede 版落地、schema 仍 1.9.0」。**不存在乾淨的『退回 1.8.1
  世界』**——這正是 §7/#22「單一 bump、想清楚再上車」的代價與紀律所在。

---

## 附錄：需 fable 裁定點清單

| ID | 議題 | 選項 | 本文件建議 | 段落 |
|---|---|---|---|---|
| **D-1** | 舊 P3a scoring 欄（tier/composite/stage_*/gates/checklist）在 1.9.0 是否維持 abstain stub、僅新增 obs_*？ | A 維持不變（additive）｜B 同時活化舊欄 | **A**：改既有欄語意=major（C5/C6），1.9.0 只 additive；舊欄 Phase 3/5 退場 | §1a §2d |
| **D-3** | volume 家族 rename（~40 alias 欄）是否與 1.9.0 同車？ | A 同車｜B 延後至 2.0 major | **B 延後**：純命名、無消費者在 1.9.0～2.0 需要新名、守「不再 minor bump」紀律即無額外歸零 | §3c |
| **D-4** | config_snapshot 是否納入 strategies？ | A 納入｜B 只 {yaml, engine_params} | **B**：strategies 只影響回測產物（#52 per-run pin），塞進每日 canonical 污染 hash | §4c |
| **D-5** | version-pin 落哪一級？ | A checkout 重算(L3)｜B attestation ledger(L2.5)｜兼含 archive 版本維度 | **B ledger**（L2.5，承 P1-5 推薦）；A 與 archive 版本維度留後 | §5 |
| **D-7** | I 回填如何不順帶落 O？（**最需裁定**） | A I-only backfill 模式＋obs_landing 旗標｜B 不回填 I 只留 WORM｜C 全跑(排除) | **A**：精確落實 I 回填/O 不回填、修歷史 correctness、對 backtest 顯式可見；代價=ingest 多一分支 | §7c |

（D-2/D-6 保留編號對齊內部草稿，無獨立議題。）

---

## 附錄：實作工作包拆分（供交辦估算）

| 包 | 範圍 | 依賴 | 估重 |
|---|---|---|---|
| **W1 schema＋registry** | canonical_schema.json 宣告 22 欄型別；SCHEMA_VERSION→1.9.0；registry 22 planned→active＋landing 紀錄；scd.yaml meta 同步；`obs_landing` 頂層旗標登記 | 無 | 小 |
| **W2 pipeline 骨架＋config_snapshot** | ingest 引擎 import＋呼叫順序（§2c）；config_snapshot 雙來源結構＋engine_params.as_config_dict()＋config_hash；I 欄（trust/prop/賣方 raw）寫入 | W1 | 中 |
| **W3 引擎解耦** | golden 改讀已落地 obs_sm_state（不重跑 sm）；sm/golden/chip/dist 落地接線；sync_streak 暴露為落地欄 | W2 | 中 |
| **W4 market 家族搬家** | regime_shift/temperature 搬出 market_context/confidence 成 Market 家；breadth 讀 market_pulse per-date；temperature 改讀 obs_sm_transition_risk（§6） | W2、W3（sm 先落） | 中 |
| **W5 version-pin ledger** | run_pipeline --check-replay 分支 append `reports/_replay_ledger.json`（§5b）；冪等＋append-only；verify 軟核對 | W2 | 小 |
| **W6 I 回填模式** | ingest backfill 旗標（obs_landing=false，只寫 I）；回填 2026-05-26→1.9.0 前一日腳本；supersede 核對（§7c-A） | W1、W2 | 中 |
| **W7 測試＋驗收** | schema/registry 對拍測試；C11 雙來源 hash 測試；22 欄落地值測試；viewer 逐欄對照；make test＋verify-all-replay 全綠（§8） | W1–W6 | 中 |

**建議拆 6–7 個 agent 工作包**（W1–W7），W1 先行（其餘皆依賴 schema/registry 名分），W2 為骨幹，
W3/W4 可在 W2 後半並行（W4 依賴 W3 的 sm 先落），W5/W6 相對獨立，W7 收尾整合驗收。

---

## fable 裁定（2026-07-11）

五個疑義點全數裁定，本節為 P2 實作的最終依據：

| # | 裁定 | 附帶條件 |
|---|---|---|
| **D-7** | **A（I-only backfill 模式）** | ①`obs_landing` 旗標入 registry（O/date/epoch-scoped）且 **replay contract 必須認得它**——verifier 對 obs_landing=false 的快照重算時同樣走 backfill 模式，否則這批快照永遠 full-replay fail；②回填腳本冪等（重跑不產生第二條 supersede）。修歷史 correctness＋對 backtest 顯式可見，值得一個分支 |
| **D-3** | **B（volume 家族 rename 延後 2.0）** | 採納其核心論證：C5 的 alias 雙寫是服務真實消費者遷移窗口，無窗口需求就雙寫＝為制度而制度。**附帶升格為遷移紀律：1.9.0 之後不再 minor bump，下一次 bump 即 2.0**（單一 bump 原則的直接延伸，寫入本文件即生效）。dealer/trust/prop 是修錯值、必上車，兩者嚴重度不同不綁死——維持 |
| **D-4** | **B（strategies 不入 config_snapshot）** | 關注點分離正確：改回測策略不得污染每日快照 hash；strategies 凍結歸 Phase 4 per-run pin（#52） |
| **D-5** | **B（attestation ledger，L2.5）** | 附帶合憲性釐清（防未來稽核誤殺）：ledger 與已判死的 intelligence.json sidecar **本質不同**——sidecar 承載市場判斷且掛 SoR 招牌（違憲）；ledger 是 **M 態驗證證明**（關於紀錄的紀錄），不承載任何市場判斷、不是第二 SoR、**且 replay 通過與否永不依賴 ledger**（它記錄結果，不定義真值）。候選 A 與 archive 版本維度維持延後 |
| **D-1** | **維持 abstain 不動** | 改既有欄語意＝major；1.9.0 只 additive。P3a scoring stubs 的 P3b 未來保持開放 |

**執行時序裁定**：W1–W7 拆包核可。**bump 執行閘門＝7/13 收盤後 1.8.1 production 驗收通過**
（partial→supersede 機制先見真實樣本，再疊 1.9.0；驗收失敗則先修 1.8.1）。
W1（schema/registry 宣告）本身即 SCHEMA_VERSION 變更，**同受閘門管制**——7/13 前不動工。
