# Session 05 — Data Contract（證據包）

> 蒐證者：opus（獨立 session，照 SESSION-TEMPLATE §0–§4 填草稿）。
> 前提：本報告只分析、蒐證，**未改任何 code/schema**；§5 裁定留給 fable。
> pre-work 兩份（assessment + field_map，2026-07-08）已完成約 70%，本輪**驗證其證據仍成立、補齊缺口、標行號**。
> 已鎖決策（不重議，見 CROSS-SESSION-NOTES #9 / 00-INDEX）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0。

---

## §0 範圍與輸入

**只看：** snapshot 的資料契約層 —
- `core/ingest.py`（SCHEMA_VERSION、`_abstain_stock_record`、snapshot 組裝、`_field_to_source_map`）
- `data/adapters/legacy.py`（`adapt_legacy`：t86/fii/trust/prop 映射、provenance）
- `data/adapters/contract.py`（`validate_adapter_output`、`_REQUIRED_*` 欄位集）
- `schema/canonical_schema.json`（頂層 + `StockRecord` `$defs`）
- `core/hashing.py`（`canonical_sha256` 吃什麼）
- `core/market_context.py`（`temporal_enrich`，volume_ratio 真實計算來源）
- 實測快照：`reports/2026-07-07.json`

**明確不看（留給哪個 session）：**
- observation 的 replay 等級 / metadata strip 白名單設計 → **S06 Replay Contract**
- viewer render-time 計算、薄化後的顯示層邊界 → **S08 Frontend Presentation**
- 各引擎（golden/resonance/distribution/state_machine）自身邏輯 → S01/S02/S03/S04/S07
- backtest 對 snapshot 的消費 → S09

**實跑驗證（確認「observation 不落 snapshot」仍成立）：**
```
python3 -c "import json,collections; s=json.load(open('reports/2026-07-07.json')); \
  print('top keys:', sorted(s.keys())); \
  print('tier:', collections.Counter(x.get('tier') for x in s['stocks'])); \
  print('composite set:', set(x.get('composite_score') for x in s['stocks']))"
```
輸出摘要：
- `top keys`（17 個）= `audit_log, config_hash, config_snapshot, core_version, date, eligible_count, environment, episodes_active_at_start, episodes_changed_today, generated_at, market_regime, provenance, rankings, schema_version, stocks, tier_transitions, universe_size` — **無 golden / confidence / resonance / distribution / sector 任何頂層 key**。
- `tier: Counter({'IGNORE': 39})`（39 檔全 IGNORE）
- `composite set: {0}`（全 0）

→ **pre-work §2 的 P3a abstain 證據 100% 復現，仍成立。**

---

## §1 這個模組真正要回答什麼問題？

Data Contract 回答：**snapshot（`reports/<date>.json`）這份檔案裡「每個欄位代表什麼、由誰產生、是否參與 replay」**。它是全系統唯一的資料界面正本——adapter 從外部世界讀進的 raw、引擎算出的 observation、以及純環境 metadata，全部匯流到這一份 JSON。下游（viewer 顯示、backtest 回測、replay 驗證、WORM 稽核）都以它為準。因此它的品質決定三件事的可信度：(a) 使用者在網站上看到的判斷能否被 snapshot 佐證；(b) 歷史某天「系統當時到底判了什麼」能否重建；(c)「同一份資料在別處是不是同一個語意」。目前這三件都被系統性違反（見 §3）。

---

## §2 它屬於哪一層？

Data Contract 是**定義分層的 meta 層**：它把資料切成 Input(raw) / Observation(derived) / Metadata 三態（pre-work field_map 已對 60 欄位逐一標 I/O/M）。核心問題是**現況這套分層在 code 與 schema 裡並沒有被結構性分開**——三態混在同一層 flat 欄位，靠「人腦記憶哪個是 raw、哪個是算出來的」維持，schema 沒有任何機制把它們分區。具體：

- **Input(raw)**：`ticker/name/current_price/change_pct`、`market_volume`(ingest.py:160)、`fii_net_buy`(ingest.py:163)、`main_force_buy`(ingest.py:171)、`dealer_net_buy`(ingest.py:182，實為投信)、TDCC 週資料(ingest.py:186-193)。這些是 adapter 讀入、參與 replay。
- **Observation(derived)**：`velocity_3d/acceleration`、`volume_5d_avg/volume_ratio`、`main_force_strict_streak_days` 家族、`fii_consecutive_buy_days`——由 `temporal_enrich`(market_context.py:238-253)算出、在 ingest.py:343-351 覆寫進 record。**這些有落 snapshot**。但另一批 observation（golden tier / resonance / confidence / distribution / sector / 真量能比）**完全不落**（§3-c）。
- **Metadata**：`schema_version`(ingest.py:367)、`generated_at`、`core_version`、`environment`（含 python/os/numpy）、`provenance`。

**分層是否清楚：不清楚。** 三態在 flat 命名空間裡沒有任何前綴或分區標記；`StockRecord`（schema:254）把 raw 欄位（volume、fii_net_buy）與 observation 欄位（volume_ratio、composite_score、tier）並列在同一個 properties 區塊，schema 層無法區分「這個欄位是外部讀進來的」還是「引擎算的」。三態分離目前只存在於 pre-work 這份 markdown 表格裡，**不存在於任何可執行的 schema/code**。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條列，每條附 `檔案:行號`。（a)-(d) 對應交辦四項；標「✔ 驗證」= 復現 pre-work，「＋新增」= 本輪補的。

### (a) Domain 錯置 — participant 三分被打亂（🔴 correctness）

1. **`dealer_net_buy`（名：自營商）實裝投信** — `core/ingest.py:182` `"dealer_net_buy": raw.get("investment_trust_net_buy")`（註解自承「投信淨買（張）from T86」）。✔ 驗證：與 pre-work 病 B 完全一致。
2. **真自營商(prop) 在 adapter 算了卻被 ingest 丟棄** — `data/adapters/legacy.py:327` `ri["prop_dealer_net_buy"] = t86_row.get("prop")`，且 legacy.py:414 把 `prop_dealer_net_buy` 列入 provenance `provides_fields`；但 `_abstain_stock_record`(ingest.py:136-252) 全域 **無任何 key 讀 `prop_dealer_net_buy`**（grep 0 命中）→ 自營商訊號在 adapter→ingest 邊界永久蒸發。✔ 驗證成立。
3. **投信無正名欄位** — schema `StockRecord`(canonical_schema.json:254-322) 與 ingest record 皆無 `trust_net_buy`（grep 0 命中）；想加真自營商的人只會看到 `dealer_net_buy`，拿到的是投信。✔ 驗證成立。
   - 對照證據：adapter 端三個 participant 是**分開且正名**的 —legacy.py:325 `fii_net_buy=foreign`、:326 `investment_trust_net_buy=trust`、:327 `prop_dealer_net_buy=prop`。**錯置只發生在 ingest 的映射那一行(182)**，adapter 本身乾淨。→ 這使修正點很集中。

### (b) 誤導命名 — volume 家族（🟡 命名，其中 volume_ratio 兼 🔴 死欄位）

4. **`volume`（名：成交量）實為主力買超張數，且是「正值裁切」的 lossy 版本** — `core/ingest.py:139-143`：`buy_vol = raw.get("buy_vol_lots")`；`if buy_vol < 0: volume_field = None`（註「signed net buy doesn't belong in 'volume'」），否則 `volume_field = buy_vol`；ingest.py:155 `"volume": volume_field`。
   → **＋新增（修正 pre-work）**：field_map B 段寫「`volume` = 主力買超張數（←buy_vol_lots）」方向對，但**不完整**：實況是 `volume` = `buy_vol_lots` **裁切為 ≥0**（淨賣日 →None）。所以它不是完整的主力買超序列，而是「只保留買超日、賣超日抹成 None」的 lossy 切片。不推翻語意/命名 verdict，但改名時要知道舊 `volume` 資料本身已失真（賣超日不可回復）。
5. **`market_volume` 是唯一正確的量，卻不在 schema** — `core/ingest.py:160` 寫入 `market_volume`（真市場成交量，from volRows）；但 `grep market_volume schema/canonical_schema.json` = **0 命中**。→ **＋新增**：唯一命名正確的欄位反而沒被 canonical schema 定義（見 (d) 的 schema 開放性）。
6. **`volume_ratio` 是 0 消費者死欄位** — 計算在 `core/market_context.py:207-208`（`vol_ratio = today_vol / vol5`，兩者皆取自被裁切的 `volume`），寫回 ingest.py:351。消費端 grep：`volume_ratio` 只出現在 `core/ingest.py`（寫）、`core/market_context.py`（算）、`tests/test_temporal_enrich.py`（測），**viewer/ core/ tools/ paper_trading/ 無任何讀取以參與決策**。✔ 驗證 pre-work「死欄位」成立。（viewer 真正顯示的量能比是另算的，見 c-8。）
7. **`volume_5d_avg` 同源誤導** — market_context.py:206,249，5 日均同樣建在裁切後 `volume` 上，名為成交量均、實為主力買超正值均。✔。

### (c) Observation 不落 snapshot（🔴 架構根病 → 分責 S05/S06/S08）

8. **viewer 顯示的判斷全是 render-time，不在 snapshot** — 實測（§0）tier 全 IGNORE、composite_score 全 0、頂層無 golden/resonance/confidence/distribution key。P3a ingest-only：`_abstain_stock_record` 把 `composite_score/tier/gates/stage_*` 全填 abstain（schema 值域上 tier∈枚舉、score≥0，但實際恆 IGNORE/0）。真·量能比、黃金 tier、共振、confidence、distribution、sector 全由 viewer render-time 呼叫 core 算（歸屬證據見 CROSS-SESSION-NOTES #2：viewer/cockpit.py:46-53 import 九引擎、量能比 cockpit.py:2388）。✔ 復現。
   - **雙層 observation 的重要區分（＋新增）**：snapshot 裡其實有**兩類** observation，狀態不同——
     (i) **scoring pipeline stubs**：`composite_score/tier/gates/stage_1..3/checklist` —被 schema `required` **強制存在**（canonical_schema.json:256-260），但 P3a 全 abstain（佔位空值）。**在 schema、在 snapshot、但無內容**。
     (ii) **render-time observations**：golden tier / resonance / confidence / distribution / sector / 真量能比 —**不在 schema、不在 snapshot**，viewer 現算。
     → 「sink observation 進 snapshot」對這兩類是不同動作：(i) 是「讓 pipeline 真的算、填進既有欄位」；(ii) 是「新增欄位並落地」。裁定時宜分開處理。
   - **歸屬**：哪些 observation 該落地 → **本 S05 裁定**；每個 observation 的 replay 等級 → **S06**；落地後 viewer 薄化邊界 → **S08**。

### (d) adapter→ingest→schema 三處欄位定義不一致、無單一正本（🔴 治理）

9. **欄位「定義」散在三個互不一致的地方（＋新增，本輪最關鍵的結構性發現）：**
   - **A. adapter 契約** `data/adapters/contract.py:35-46` `_REQUIRED_RAW_KEYS` = `{ticker,name,rank,is_etf,current_price,change_pct,buy_vol_lots,top5_branches,_branches_present}`。注意：`fii_net_buy/investment_trust_net_buy/prop_dealer_net_buy` **不在必填集**（可選、可 None）→ participant 資料在契約層是「有就好」，沒有被契約保障。
   - **B. snapshot record 形狀** `core/ingest.py:136-252` `_abstain_stock_record` 的字典字面量——這才是實際寫進 JSON 的欄位全集（含 `market_volume`、含把 prop 丟棄的映射）。
   - **C. 驗證 schema** `schema/canonical_schema.json:254-322` `StockRecord`——含 `volume/volume_ratio/dealer_net_buy`(:270,272,304)，但**缺 `market_volume`**（B 有 C 無）。
   → 三者對不上：B 寫的 `market_volume` C 沒定義；B 丟棄的 prop 三處都沒收；`dealer_net_buy` 三處同名但語意是投信。**沒有任何一處是「正本」**，改一處不會強制另兩處跟上。
10. **schema 是開放式，無法當守門員** — 全檔 `grep '"additionalProperties": false'` = **0 命中**；`StockRecord`(schema:261 properties 區塊)未關閉 additionalProperties（JSON Schema 預設 = true）。→ 這正是為何 ingest 能寫 `market_volume` 而 schema 不報錯：schema 不強制欄位為封閉集，**驗證不到「多出來/漏掉」的欄位**，單一正本無從落實。
11. **field_to_source(provenance) 是 flat map** — `core/ingest.py:256` `_field_to_source_map`、snapshot 組裝 ingest.py:362 `"field_to_source"`。→ 若未來走深 nested domain 需重寫；扁平前綴方案幾乎不動它（pre-work assessment §3 已載，此處確認 code 位置成立）。

### (e) metadata 污染 replay hash（🔴，但**歸屬 S06**，此處僅登記證據）

12. `canonical_sha256`(core/hashing.py:52) 吃 `canonical_bytes`(hashing.py:32)= 傳入物件全體，即**整份 snapshot**（含 `environment` 的 python/os/numpy）；replay 比對只把 `generated_at` 抹平（`tools/run_pipeline.py:235` `snap2["generated_at"] = snapshot["generated_at"]`，隨即 hashing 236-237），**未抹 environment**。→ 跨機/升套件可能 full-replay 假失敗。✔ 復現 CROSS-SESSION-NOTES #3。**歸屬 S06**：本 S05 只確認「三態中 Metadata 未被排除在 replay 之外」這個契約事實，strip 白名單設計與跨機測試留給 S06。

---

## §4 如果今天重新設計，責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。已鎖決策為前提：扁平前綴、additive+alias、深 nested 留 2.0。）

**snapshot 應是「完整成品」而非「半成品」。** 理想態：任何 UI 顯示、backtest 消費的判斷值，都必須先落 snapshot，viewer/backtest 純讀取、禁 render-time 衍生。
- 差距：現況是「半成品」——判斷層 render-time（§3-8），「UI==snapshot」結構性不成立。

**三態在 schema 層可見。** 理想輸入/輸出/絕不做：
- **Input**：adapter 從外部讀入的原始值，前綴 `market_/mf_/foreign_/trust_/dealer_/tdcc_/margin_`。參與 replay。絕不在此層放引擎算的東西。
- **Observation**：引擎算出、前綴 `derived_/obs_`。**必落 snapshot**、replay 可重建，每欄註 producer（哪個 core 模組）+ replay 等級。絕不 render-time-only。
- **Metadata**：`generated_at/environment/core_version` 等，**排除於 replay hash**。絕不參與判斷。
- 差距：現況 flat 無前綴、schema 不分區（§2）；observation 半數不落（§3-c）；metadata 仍進 hash（§3-e→S06）。

**欄位命名正本該放哪。** 理想態：**單一正本**，且是封閉集、能自動擋住漂移——一個「正名 + domain + 單位 + 三態 + producer + replay 等級」的欄位登記表，schema 由它生成或與它對拍，`additionalProperties: false` 讓多欄/漏欄立即 fail。adapter 契約(_REQUIRED_*)、ingest record、canonical schema 三者從此正本派生，不各寫一份。
- 差距：現況三處各自定義且不一致（§3-9）、schema 開放式擋不住漂移（§3-10）、正本目前只在 pre-work markdown（不可執行）。
- **participant domain 邊界**：foreign/trust/dealer 三分，一欄只裝一個 participant，禁跨裝（現況 §3-1 破此界）；真 prop 要有欄位收（現況 §3-2 丟棄）。

**與已鎖決策的相容性（供 S06 交界確認，不在此裁定）：** 扁平前綴使「命名正本→schema」低成本（不動 nested 結構）；additive+alias 使 `volume→mf_*`、`dealer_net_buy→trust_net_buy` + 新 `dealer_net_buy(prop)` 可跨 minor 遷移而不破舊 epoch replay——但 §3-4 已揭示舊 `volume` 資料本身是 lossy（賣超日 None），alias 只能保住「舊欄位繼續寫同樣的 lossy 值」，找回完整主力買超序列需回 WORM archive 重抓（correctness 面，屬遷移執行期問題，非本證據包）。

---

## §5 裁定（fable，2026-07-09）

> 裁定框架：Chief-Architect rubric（Yonki+ChatGPT 2026-07-09 提出；root-cause 聚類→雜訊分離→責任洩漏→缺失概念→挑戰→P0-P2 verdict→executive summary）。已併入 SESSION-TEMPLATE 作為後續全部 session 的裁定標準。
> 凍結期語意：P0/P1/P2 = **立約順序**（後續 session 的裁定依賴），非修復排程；本裁定不執行任何改動。

### 系統身份（北極星，正式採納）
SCD Engine 是 **Observation-First 市場情報系統，不是交易系統**；snapshot 的終局角色是 **System of Record**——「系統當天相信什麼」的唯一權威紀錄。與 repo 既有鐵律（replay 完整性、WORM、viewer 純渲染）一致。此後所有 session 的 Q4 以此為判準。

### Root Causes — 12 條發現壓縮為 3 個架構真相（+1 移交）

**RC-1｜Snapshot 還不是 System of Record（P0）**
判斷層活在 viewer render-time，snapshot 只記輸入不記判斷。吸收 §3-8(i)(ii)；也是歷次「前端 vs JSON 不一致」回報、cockpit 肥大（→S08）、backtest/viewer 潛在分歧（→S09）的共同上游。
裁定（立法）：**任何呈現給使用者或被 backtest 消費的 observation，必須落 snapshot**（C2 正式化）。兩類 sink 是不同動作：(i) abstain stubs = 讓 pipeline 真的算、填既有欄位——是 P3a 分階段設計的「補完」，不是重構；(ii) render-time observations = 新增 obs_* 欄位落地。**個別引擎的落地清單不在 S05 定**：S05 立法（準則+機制），S01–S04 各自在其 Q4 下列舉本引擎哪些輸出屬契約級 observation。此界線同時解決 §4「備選項未定案」的懸置。

**RC-2｜資料契約沒有正本（P0）**
欄位定義散在三處（adapter 必填集 / ingest 字面量 / JSON schema）互不一致，schema 開放（additionalProperties 全檔 0 命中）使漂移不可偵測。吸收 §3-5/9/10；也是 RC-3 得以無聲發生並存活的機制性原因。
裁定：建 **Canonical Field Registry 作為唯一正本**——單表：欄名/domain/單位/三態(I,O,M)/producer 模組/replay 等級/版本(introduced/deprecated/remove-in)。強制機制取最小可行：**一支 CI 測試對拍三處定義與 registry**；不強求 schema 代碼生成（防 yak-shave，生成留作未來選項）。**三態詞彙 Input/Observation/Metadata 正式採納為全計畫分層語言**，Protocol 六層映射：Raw→I；Observation/Derived/Classification→O 子型；Presentation→非資料層；Metadata→M。

**RC-3｜Domain 完整性已實際受損（P1）**
非「可能出錯」而是「已經錯著」：投信以自營商之名入檔（錯置集中在 ingest.py:182 一行；adapter 端三分乾淨）、真自營商在 adapter→ingest 邊界被丟棄、volume 家族被主力買超語意挪用且 lossy（賣超日抹 None）。吸收 §3-1/2/3/4/6/7。
裁定：屬**待排程資料矯正**，非緊急（WORM archive 保有完整原值可回填，凍結零流失）。作為 registry 落地後的**第一個遷移案**（additive：`trust_net_buy` 正名 + 真 `dealer_net_buy(prop)` 接上 + volume→mf_* 家族）。並新增契約原則 **C7 非破壞性 ingest**：raw→record 轉換不得銷毀資訊（volume 正值裁切即違例）；lossy 轉換必須在 record 保留完整值、或依構造可由 archive 回復。

**RC-4｜Replay 邊界未定義（P1，移交 S06）**
metadata（environment: python/os/numpy）進 hash、比對只抹 generated_at。S05 只裁契約面：**registry 必須帶 replay 等級欄**——每個欄位在契約層宣告是否參與 hash。等級定義、strip 白名單、跨機測試、observation lifecycle（含 1.8.1 partial→supersede 的重算語意）= S06。

### 雜訊分離（技術正確、架構不重要）
`volume_ratio`/`volume_5d_avg` 死欄位＝RC-3 個例，遷移時順手處理；`field_to_source` flat map＝與扁平前綴相容，不動；volume lossy 之於遷移執行是細節——但其揭示的原則已升格為 C7。

### 對證據包的挑戰（rubric Q6）
- **重複**：§3-5（market_volume 不在 schema）是 §3-9/10 的子案例，併入 RC-2。
- **隱藏假設一**：「UI 值必須可由 snapshot 佐證」——非假設，是 Yonki 已批准的 C2，引為已批。
- **隱藏假設二（重要重框）**：報告隱含「abstain stubs 是問題」。**否**——stubs 是 Yonki 簽核的 P3a 分階段設計；真正的債是「系統停留在半成品的同時，UI 已在出貨判斷」＝計畫與產品現實的分歧。故 RC-1 的修復語言是「補完既定計畫」，不是「修正錯誤設計」。
- **錨定檢查**：rubric Q1 示例聚類恰與本裁定相符——已逐項對拍（RC-1↔§0 實測、RC-2↔三處 grep、RC-3↔行號、RC-4↔hashing.py:52）確認非照抄。
- **證據包遺漏**：**today.json 的形狀無主**——fetch→adapter 這跳的契約只隱含在 fetch_daily.py，實為第四個定義點。列 P2：registry 是否向上游多管一跳。

### 不需要改的（防未來誤重構）
adapter 端 participant 三分（乾淨；**不要**重構 adapter，修正點只在 ingest 一行）；provenance/WORM/archive 機制（凍結之所以安全正因它們）；P3a abstain stubs（分階段設計，補完非拆除）；深 nested（已否決，維持）。

### 與已鎖決策相容性
扁平前綴 ✓（registry 即表格+命名，零結構改動）；additive+alias ✓（registry 版本欄讓 SOP 可執行化而非口傳）；C1–C6 ✓（C2=RC-1 之法、C3=三態詞彙、C4=RC-3 之預防）+ 本裁定新增 C7。無衝突。

### Architecture Verdict
| 級 | 項 | 理由 |
|---|---|---|
| P0 | RC-1 Snapshot→System of Record（落地準則已立法） | 全部後續 session 的 Q4 依賴此方向；不立，S01–S04/S08/S09 的邊界裁定無錨 |
| P0 | RC-2 Canonical Field Registry + 最小 CI 對拍 | 沒有正本，任何遷移（含 RC-3 矯正）都會再漂移 |
| P1 | RC-3 domain 矯正（trust/dealer/prop + volume 家族） | 已證實損壞但 WORM 保全、零持續流失；registry 後第一遷移案 |
| P1 | RC-4 replay 邊界（registry 帶 replay 欄；機制→S06） | 契約需求已立，設計歸 S06 |
| P2 | 死欄位清理、C7 落實細節、today.json 形狀所有權、field_to_source 註記 | 遷移期自然吸收 |

### Executive Summary（兩分鐘版）
1. SCD 是 Observation-First 情報系統，snapshot 終局角色是 System of Record——今天它只記輸入不記判斷，所有「UI vs JSON」矛盾皆源於此。（P0）
2. 資料契約沒有正本：三處定義自由漂移、schema 開放無法守門。建 Canonical Field Registry（名/domain/單位/三態/producer/replay 等級/版本）＋最小 CI 對拍。（P0）
3. 一處已證實的 domain 損壞（投信頂自營商名、真自營商被丟、volume 語意挪用且 lossy）——WORM 已保全、凍結零流失，為 registry 後第一個遷移案。（P1）
4. Replay 邊界未在欄位層定義（metadata 污染 hash）——registry 帶 replay 等級欄，機制交 S06。（P1）
5. 一切可 additive 修復、無需重寫任何層——Evidence Phase 的結論是「補完」，不是「推翻」。

---

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES 已含本 session 相關發現（#1/#2/#3/#4/#9 為 seed；本輪新增之 §3-5/9/10（market_volume 缺 schema、三處定義不一致、schema 開放式）屬 S05 內部證據細化，未跨 session，故不另 append；跨 session 項（observation 落地 replay 等級→S06、metadata strip→S06、viewer 薄化→S08）已在 §3 就地標歸屬，seed 表 #2/#3 已涵蓋）
- [x] 00-INDEX 狀態列已更新（S05：證據包完成，待 fable 裁定；報告連結 `sessions/S05-data-contract.md`）
- [x] 未執行任何 code/schema 改動
