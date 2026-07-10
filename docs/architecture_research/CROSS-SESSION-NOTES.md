# Cross-Session Notes

> Protocol 規定：發現會影響其他 session 的問題 → 記在這裡，**不提前展開**。
> 格式：`[來源日期] 發現(附 file:line 證據) → 歸屬 session → 狀態`。
> 每個 session 結束時把新產生的跨 session 事項 append 進來。

## Seed — 2026-07-08（前後端不一致查證 + data contract 評估的產物）

| # | 發現 | 嚴重度 | 歸屬 | 狀態 |
|---|---|---|---|---|
| 1 | `dealer_net_buy`(名自營商)實裝**投信**（core/ingest.py:182 ← investment_trust_net_buy）；真自營商 prop 在 adapter 算了（data/adapters/legacy.py:327）但 ingest 無欄位收、**被丟棄**；投信無正名欄位。resonance「投信」讀誤名欄位碰巧值對（core/resonance.py） | 🔴 correctness | S05 | 待 S05 裁定。**凍結安全**：prop 原始值在 WORM archive 的 today.json（t86 含 prop），可回填，無持續性流失 |
| 2 | Observation 層（golden/confidence/state_machine/resonance/chip_score/distribution/真量能比）全部 viewer render-time 計算（viewer/cockpit.py:46-53 import 九個 core 引擎；量能比 cockpit.py:2388 現算），**不落 snapshot**（P3a：tier 全 IGNORE、composite_score 全 0，2026-07-07 實測）→ replay 不覆蓋判斷層、「UI==snapshot」結構性不成立 | 🔴 架構根病 | S05+S06+S08 | 各 session 分責裁定：S05 定哪些落地、S06 定 replay 等級、S08 定薄化後的 viewer 邊界 |
| 3 | `canonical_sha256` 吃整份 snapshot 含 `environment`(python/os/numpy)（core/hashing.py:52）；replay 比對只抹 `generated_at`（tools/run_pipeline.py:235）→ 跨機器/升套件可能 full-replay 假失敗（legacy-epoch 靠 disk-hash 不受影響） | 🔴 replay | S06 | 待 S06：先寫跨機 replay 測試驗證，再議 metadata strip 白名單 |
| 4 | `volume`/`volume_ratio`/`volume_5d_avg` 名為量、實為主力買超家族（core/ingest.py:155、core/market_context.py:208）；`volume_ratio` 是 **0 消費者死欄位**；唯一正確的量是 `market_volume`（ingest.py:160） | 🟡 命名 | S05 | 對照表已在 FIELD_MAP；rename 凍結至研究完成 |
| 5 | fii_alignment cap：外資連賣 ≥2 天才把 PRIME 降 STRONG（core/golden.py:391-418），1 天不觸發 | ✅ 設計非 bug | S01 | Yonki 2026-07-08 裁定維持。S01 分析時記錄語意，不重議門檻 |
| 6 | 「連買天數」三種語意曾共用相近標籤：strict streak（金卡「主力連買」）/ window 天數（「窗N」）/ **在榜天數**（龍頭雷達，viewer/metrics.py:98 current_streak）。雷達已正名「連續在榜N日」（commit a2037a0） | ✅ 已修 | S08 | S08 盤點顯示層詞彙時複查有無殘留歧義 |
| 7 | `viewer/cockpit_v2.py`（1,234 行）= init commit 即存在、之後零 commit 的**被棄置平行前端**。是「另建乾淨前端」路線的既有失敗案例 | 🟡 死碼 | S08 | S08 裁定刪除與否 |
| 8 | 兩段式快照 1.8.1（fii_pending partial → 早晨 supersede 補完）已出貨（commit a0577ec，分支 claude/sleepy-nobel-3d007c，**待合 main**）。supersede 鏈 + partial 語意成為 replay contract 的一部分 | ⏳ 待驗收 | S06 | S06 分析 replay contract 時把 partial/supersede 語意納入 |
| 9 | 已鎖決策：扁平前綴 domain（market_/mf_/foreign_/trust_/dealer_/derived_/obs_）、additive+alias 跨 minor 遷移、深 nested 留 2.0 | 📌 決策 | S05 前提 | 不重議 |

## S05 裁定產出 — 2026-07-09（fable；詳見 sessions/S05-data-contract.md §5）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 10 | **系統身份正式採納**：SCD = Observation-First 情報系統，snapshot 終局角色 = System of Record。所有 session 的 Q4 以此為判準 | 全 session | 📌 已立 |
| 11 | **三態詞彙 I/O/M 正式採納**為分層語言；Protocol 六層映射：Raw→I、Observation/Derived/Classification→O 子型、Presentation→非資料層、Metadata→M。各 session Q2 用此作答 | 全 session | 📌 已立 |
| 12 | **立法/列舉分工**：observation 落地準則已立法（呈現給使用者或被 backtest 消費者必落 snapshot；stubs=補完、render-time=新增 obs_*）。**個別引擎的落地清單由 S01–S04 各自在 Q4 列舉**，S05 不代決 | S01–S04 | 待各 session |
| 13 | **S06 介面需求**：Canonical Field Registry 必須帶 replay 等級欄；replay 等級定義、metadata strip 白名單、跨機測試、observation lifecycle（含 1.8.1 partial→supersede 重算語意）歸 S06 設計 | S06 | 待 S06 |
| 14 | **today.json 形狀無主**：fetch→adapter 契約只隱含在 fetch_daily.py，是第四個欄位定義點。registry 是否向上游多管一跳＝P2 治理題 | S05 遺留/S06 | P2 登記 |
| 15 | **新契約原則 C7 非破壞性 ingest**：raw→record 轉換不得銷毀資訊（volume 正值裁切為違例先例）；lossy 轉換必須保留完整值或依構造可自 archive 回復 | 全 session | 📌 已立 |

## S06 證據包產出 — 2026-07-10（opus；詳見 sessions/S06-replay-contract.md §3/§4，待 fable 裁定）

| # | 發現 | 嚴重度 | 歸屬 | 狀態 |
|---|---|---|---|---|
| 16 | **refine #3**：跨機 full-replay 假失敗現況已被 `verify_all_replay.py:213-242` 的 strip 清單擋住（抹 environment/audit_log/mtime 衍生 provenance）；`run_pipeline.py:235` 只抹 generated_at 但那是同機二跑不涉跨機。#3「只抹 generated_at→跨機假失敗」的機制需修正。**真病＝strip 清單是驗證器內硬編碼、兩份不同步（run_pipeline{generated_at} vs verify_all_replay 6 欄），新增 metadata 欄會無聲重引入 false-fail** | 🔴 replay | S06 | 證據包待裁定；設計面接 S05 RC-4 registry replay 等級欄 |
| 17 | **full-replay 保證隨每次 schema bump 歸零**：實測 `SCHEMA_VERSION=1.8.1`、磁碟 41 份全 <1.8.1 → full-replay 覆蓋 **0/41**，全走 legacy-epoch(disk-hash)。`verify_all_replay.py:176-194` epoch 分流語意正確，但後果是「同輸入可重算出同 O」對全部歷史歸零，只剩防竄改。O 態可重算保證需 version-pinned replay 才不歸零 | 🔴 replay 結構 | S06 | 證據包待裁定（epoch bump 保證如何不歸零＝S06 核心懸置） |
| 18 | **archive 無版本維度 → supersede 後舊版本只保 disk-hash、不可從 archive 重建**：`core/archive.py:94-114` 歸檔以 date 為鍵、per-date 覆寫。partial 被 complete supersede 後 archive today.json 被換成含 T86 版，舊 partial 的 raw_sha256 不再匹配 → full-replay 會拋 sha mismatch。supersede 鏈(`run_pipeline.py:86-136`)記錄 hash 曾存在，卻不保證可復現。verify_only 信任鏈(`legacy.py:395-431`)只對 current tip 完整 | 🔴 replay | S06 | 證據包待裁定；archive 加版本維度屬 additive |
| 19 | **1.8.1 partial→supersede 重算語意 production 零覆蓋**：磁碟 fii_pending 快照 0 份、20 條 supersede 鏈無一是 partial→complete（全來自 backfill/epoch re-ingest）。機制齊備(`daily.py:108-122,306`＋`legacy.py:322`＋`ingest.py:379`)但無真實樣本可作證。呼應 #8「待驗收」 | ⏳ 待驗收 | S06＋操作軌 | 證據包待裁定；隔日驗收 partial→supersede |

## S06 裁定產出 — 2026-07-10（fable；詳見 sessions/S06-replay-contract.md §5）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 20 | **系統身份延伸**：Replay Contract 是「Snapshot=System of Record」得以被驗證的機制，非附加特性；沒有它 SoR 只是命名慣例 | 全 session | 📌 已立 |
| 21 | **新缺失概念「Replay Guarantee Strength」**：與三態 I/O/M 正交的第二軸——可重算/僅防竄改/不可驗。現況把此軸焊死在 schema epoch 這一個開關上，是 RC-6 得以無聲發生的根因。供任何 session 判斷「這個 observation 落地後我能許諾到哪一級」時引用 | 全 session | 📌 已立 |
| 22 | **排程級約束（重要）**：S05 RC-1 已核准 observation 逐步落地進 snapshot；S01–S04/S07 完成時各自會觸發 minor bump。依 RC-6，**每次 bump 讓此前全部快照的 full-replay 保證瞬間歸零**、無任何訊號提示。排定各 session 落地順序與時機時，須知道這個代價；是否需要 version-pinned replay 才能安心繼續 bump，留待後續裁定 | S01–S04/S07 排程 | 待各 session 排程時參考 |
| 23 | **P2 操作面查證（廉價、不違反凍結）**：`make verify-all-replay` 的標準流程是否曾經/可能對非-tip(superseded) 版本嘗試 full-replay，而非只查 current tip？若會，1.8.1 partial→supersede 一旦在正式環境真的發生，可能撞上 `archive.py:148-155` 的 sha mismatch。本裁定判斷此為優先查證項，不預先斷定會炸 | S06 遺留/操作軌 | 待查證 |

## S01 裁定產出 — 2026-07-10（fable；詳見 sessions/S01-golden-layer.md §5）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 24 | **新契約原則 C8（組裝權）**：跨引擎判斷的組裝屬 core 生產者、輸出必落地；presentation 只映射，不組裝、不搬運判斷輸入（違例現行犯：viewer 中轉 weakening 進 golden 行動函式，cockpit.py:2672-2680）。S02/S03/S04 的組合判斷（resonance/chip/distribution）裁定時直接引用 | 全 session | 📌 已立 |
| 25 | **新契約原則 C9（可純派生者不落地）**：能由已落地欄位純函數派生的顯示標籤不進 snapshot（判例：display_tier=f(tier,conviction,action_group)→不落）；判斷不適用、判斷必落。與 C2 一正一反閉合 | 全 session | 📌 已立 |
| 26 | **golden 落地清單已核准（六欄）**：obs_golden_tier/conviction/action_group/gates_passed/tier_caps/near_miss(含missed_gate,**不落tier**)。前置條件：golden 寫死門檻(conviction權重/tier切點,golden.py:68-78)先 config 化——config_snapshot 參與 hash,code 內權重對 replay 不可見,先落地=判定帶不可見參數。時序:計算移 pipeline 即可落,不需等上游全落 | 遷移案/S05 registry | 待遷移期 |
| 27 | **資格 vs 行動 = 兩種 O 態**（S01 RC-8）：gates/conviction/tier=資格;action_group(5%鐵則+weakening)=進場行動,是判斷非顯示。S09 回測消費名單時需分清用哪一種;S04/S03 提供 weakening 材料時知道下游是行動層 | S03/S04/S08/S09 | 📌 已立 |
| 28 | **ownership 缺口**：外資賣超 streak 無 owner，golden 自建快照迭代撿走（golden.py:371-388）。遷移期由 temporal_enrich 一系補一欄（additive），golden 改讀 | 遷移案 | 登記 |

## S04 裁定產出 — 2026-07-10（fable；詳見 sessions/S04-state-machine.md §5）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 29 | **新契約原則 C10（as-was）**：路徑依賴的 O 態以「當日認定」逐日落地為正本——落地後路徑依賴從負債變成紀錄本身，history/transitions 由落地序列派生（不落）、days_in_state 落（C9 邊界釐清：同 record 純函數不落，跨快照時序派生視 bootstrap/backtest 人體工學可落）；落地起點前的歷史誠實放棄不偽稱可回溯。適用一切有狀態/時序引擎（S02/S03/S07 引用） | 全 session | 📌 已立 |
| 30 | **sm 落地清單核准（六欄）**：obs_sm_state/transition_risk/days_in_state/state_entered/structure_unstable/risk_factors。前置：①門檻 config 化②**exited/absent 詞彙先拆**（「跌出當日榜」≠「生命週期退場」，不拆則缺陷燒進 as-was 紀錄且 flips 失真）。消費面紀律：**已落地者必改讀**（sm 現重算已落地的 velocity/weakening=雙真相病） | 遷移案/S07(universe面) | 待遷移期 |
| 31 | **temporal_state 標 deprecated-pending-P3b**：零引擎消費的殭屍 stub（非 S05 保護的 scoring stubs——那些有 P3b 未來）；不填不擴不消費，P3b 啟用時改從落地 obs_* 派生並正式移除（major）。**sm_state=「生命週期狀態」概念家族唯一 SoT** | S05 registry | 📌 已裁 |
| 32 | **「轉弱」是證據→分類→風險的健康分層，不合併**：weakening(mc,已落地)→sm distributing→transition_risk 各答不同問題。統一對外「轉弱」標籤若產品需要＝跨引擎組裝＝依 C8 必須 core 派生欄位，viewer 不得組裝 | S08 議程 | 📌 已裁 |
| 33 | **門檻 config 化升格系統性**（golden+sm 兩引擎同病確認 pattern）：不再逐 session 裁，registry 遷移(S05 RC-2)統一前置一次掃全引擎寫死門檻。**confidence 引擎正式歸入 S03 範圍**，「類別 risk(sm) vs 數值 risk(confidence) 雙軌」屆時裁 | S02/S03/S07 引用；S03 | 📌 已立 |

## S02 裁定產出 — 2026-07-10（fable；詳見 sessions/S02-chip-momentum.md §5）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 34 | **新契約原則 C11（判斷參數測試）**：可由落地欄位派生的輸出，函數內含「別處未落地的判斷參數」（門檻/權重/分母規則）→ 新判斷必落（判例：chip grade 落）；只是重標籤已落地判斷 → 呈現不落（判例：display_tier/共振星號不落）。測試法：改參數，歷史意見會不會無痕改變。至此「落不落」判定樹完整：C2/C8→C9→C11→C10 | 全 session（S03/S07/S08 直接引用） | 📌 已立 |
| 35 | **S02 落地裁定**：obs_chip_grade＋total 落（前置：CHIP_SCORE_CONFIG config 化，引 #33）；resonance_level **不落**（≡已落地 fii_sync_count，35/35 實證，SoT=落地欄）；sync_streak 落（owner=temporal_enrich 系，命名候選 derived_participant_sync_streak，終審 registry）；**resonance 引擎遷移後解散**為一欄時序＋呈現映射 | 遷移案 | 待遷移期 |
| 36 | **雙實作漂移＝第四次確認的系統病**（S06 strip 清單×2、S04 落地而不讀、S02 level 複本＋主力方向取值欄位不一致 total_buy_vol vs main_force_buy）。遷移 checklist 必含「主力方向單一取值來源」；RC-3 消費端必改名單坐實 +resonance.py:34（讀誤名 dealer_net_buy）。元大金呈現區隔（顯示性徽章 vs 資格判斷的視覺語言）列 S08 議程 | 遷移案/S08 | 登記 |

## S03 裁定產出 — 2026-07-10（fable；詳見 sessions/S03-distribution-risk.md §5。第一個存廢級裁定，零新法）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 37 | **confidence 降級為派生視圖**：獨立 risk_score/confidence 分數廢除（double-count sm、與之分歧、61%塌零；信心軸=第三次聚合）。**sm transition_risk=「風險」唯一 SoT**（#33 雙軌問題的答案）；「多頭分/警訊分」改為 obs_golden_conviction/obs_sm_transition_risk 的呈現映射；2D profile 概念存活為 C9 純派生視圖；deteriorating 廢（weakening+sm 已覆蓋）；**market_temperature 移交 S07**（market_state 家族，grain=市場級） | 遷移案/S07/S08 | 📌 已裁 |
| 38 | **distribution 拆解重生**：「活 code 死輸出」（generate 僅 CLI 觸發、pipeline 零引用、磁碟 0 檔、viewer 只 disk-load→部署中不顯示）。搶救：賣方 raw（sellList/mainForceSell）入 canonical schema（前置，S05/C7）→ obs_dist_consistency 落地（唯一賣方證據源）→ safety band config 化。處決：_ACTION_MATRIX/flagged_for_removal 不以 distribution 輸出存活，併入唯一行動層（RC-8）。**sidecar 判斷=SoR 違憲**定調；**intelligence.json 同罪嫌疑→S08/S09 稽核**。⚠ refine NOTES #2：distribution 非 render-time，是 disk-load-only＋生產線斷線 | 遷移案/S08/S09 | 📌 已裁 |
| 39 | **轉弱出口五個坐實、裁定後收斂回三層**（weakening→distributing→transition_risk；confidence/distribution 兩出口廢）。雙實作漂移第 5/6 例：成本容忍雙閾值（1.12 vs 1.05，語意不同不合併、都 config 化+registry 記載）、第二個同名 4 級 risk（已廢）。**引擎 session 完結統計：4 法（C8-C11）、14 欄核准落地、2 引擎解散/降級、6 例漂移** | S08/遷移 checklist | 📌 已裁 |

## S07 裁定產出 — 2026-07-10（fable；詳見 sessions/S07-market-context.md §5。零新法、零新 RC，一個缺失概念）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 40 | **市場級 SoR 收斂裁定**：market_state.py（888 行、自稱「市場唯一 SoT」、全 repo 0 import、語意從未經使用者驗證）**判死**，隨 cockpit_v2 同批處決（#7 判例）；**regime_shift＝唯一收斂點**，遷移後市場級 O 搬出 market_context.py 成家。obs_market_regime/breadth/temperature 三欄核准落地（**累計 17 欄**）；obs_market_avg_chg **不落**（C9 純平均無判斷參數，且現母體是榜非市場）；snapshot `market_regime` stub → deprecated-pending（同 #31 temporal_state 判例，真值走 obs_market_* 新欄）。三重引擎分歧＋死碼＝漂移第 7/8 例登記 | 遷移案/S08 | 📌 已裁 |
| 41 | **母體修正＝一切市場級落地的 P0 前置（#4 市場層爆發）**：breadth 恆 ≈1.0（買超 top-N 榜當母體，依構造恆真）→ regime 廣度維度死、temperature 30% 權重常數、transition 假訊號；avg_chg 同分母病（榜內平均僭稱市場平均）。**修母體＝需要新 I 態輸入（全市場漲跌家數），解在 market_pulse**：收編為 per-date I 態（WORM 歸檔，C7）並擴充為市場母體資料的家，breadth 改以它為分母。落地退化分＝把假訊號焊進 as-was（C10），故母體修正先於一切 obs_market_* 落地 | 遷移案/S05/S06 | 📌 已裁 |
| 42 | **缺失概念「grain 是契約的一級維度」**：I/O/M（#11）答「什麼態」、Replay Guarantee Strength（#21）答「保證多強」，grain 答「一筆的粒度」——三軸正交。**S05 registry 必須帶 grain 欄（ticker/date/sector）**；market-grain O 落 snapshot 頂層一天一筆。sector grain（leadership/sector_intelligence）暫無主管 session，registry 建欄時登記歸屬 | S05 registry/全 session | 📌 已立 |
| 43 | **temperature 移交收尾（承 #37）**：obs_market_temperature 核准，雙前置＝elev_ratio/dist_ratio 改讀 obs_sm_transition_risk（不得續建在已廢 confidence risk_level 上）＋breadth 成分等 #41 母體修正。另：intelligence_delta 錯 key 讀 null stub（breadth_milestone 永不觸發）＝ sidecar 稽核（#38）加重證據，不單修，記入 S08/S09 卷宗 | 遷移案/S08/S09 | 📌 已裁 |

## S08 裁定產出 — 2026-07-10（fable；詳見 sessions/S08-frontend-presentation.md §5。一條新法 C12、零新 RC）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 44 | **新契約原則 C12（呈現單一擁有者，C8 的鏡像）**：引擎輸出語意 enum，不輸出呈現（hex/雙語 label/emoji/HTML）；映射表（enum→zh/en/color/icon）由 presentation 層單一擁有。C8 禁 presentation 做判斷、C12 禁 judgment 做呈現，合封 Observation↔Presentation 雙向滲漏。違例 13/18 core 檔（清單見 S08 §3-f），最重＝chip_score.py:105-107 引擎直接吐 HTML；cockpit bg_map（:644-652）反向硬編碼引擎色盤＝雙向耦合，C12 遷移後自然消解。入遷移 checklist | 全 session/遷移案 | 📌 已立 |
| 45 | **cockpit 路線定案：薄化，不重寫**（開案第一天懸置結案）：7-tab 版面＝驗證過的產品資產、病灶全可定位行號、重寫有 cockpit_v2 死亡前例、app.py/metrics.py＝目標形態活樣本（保留為薄化參照）。時序必然晚於 17 欄落地遷移。**四條紅線＝薄化驗收標準：不算（render-time 零引擎呼叫）、不裝（零跨引擎組裝/搬運）、不寫（零持久化）、引擎不吐呈現（C12）**。cockpit_v2.py 處決，含 Makefile:54,58 啟動目標一併移除（與 market_state #40 同批） | 遷移案 | 📌 已裁 |
| 46 | **sidecar intelligence.json 判死（廢除，不收編）**——#38 定讞：自稱 immutable archive 卻不入 hash/replay、re-run S03 已判死 confidence、含永不觸發死事件（#43）；內容窮舉後全部＝落地序列 C9 純派生（golden_entry/exit/transition=兩份 snapshot diff、temperature_change=obs 序列派生、market_story=Presentation）→ 收編無正當理由。廢除後「今日新進」由兩份落地 snapshot 純 diff；停產留檔不刪（as-was 誠實）。**S09 開工前提：sidecar 非可消費真值源，需稽核 backtest 有無斷炊** | 遷移案/S09 | 📌 已裁 |
| 47 | **viewer 持久化越界處決＋Tier-A 分離**：checklist_history.json 廢除——still_active＝落地 obs_golden_tier 序列的無參數 diff＝**C9 非 C10**（修正證據包提案），留存率 render-time 派生；sidecar generate button 移除。Tier-A：★ 徽章＝viewer 映射，`is_tier_a→+0.10 conviction`（golden.py:279-280）＝人工名單洩漏進資格計分，TIER_A 名單＝人工維護的 I 態判斷參數（C11 陽性）隨 #33 入 config/registry，兩者分離。漂移第 9 例（畫面 vs sidecar 同引擎各跑）隨 sidecar 判死消失 | 遷移案/S05 registry | 📌 已裁 |

## S09 裁定產出 — 2026-07-10（fable；詳見 sessions/S09-backtest-logic.md §5。零新法、零新 RC＝法典閉合性通過。**9/9 session 完成，研究階段收官**）

| # | 事項 | 歸屬 | 狀態 |
|---|---|---|---|
| 48 | **回測重算歷史判斷＝C11 陽性（參數 look-ahead）**：paper_trading.py:186,423 每決策日 `_golden.run(snaps[:i+1])`＋temporal_enrich 用今日 code+今日門檻回放歷史；實測改 entry_streak_min 3→5 歷史交易 8→3 無痕位移。「No look-ahead」宣稱半真（資料無、code/參數有）——半真比全假危險。混合出處（出場讀 as-was weakening、進場今日回算）同病同治。治法＝17 欄落地後改讀 as-was 落地序列（C10 回測面） | 遷移案（依賴 S01#26/S04#30/S02#35＋#33） | 📌 已裁 |
| 49 | **正式宣告：現行回測數字不具決策效力**——C11 回放偏誤＋母體偏誤同向（偏樂觀），輸出是工程樣本非證據；夜跑無害不停。正確化依賴鏈＝17 欄落地→#33 config→#41 母體→回測薄化，**回測是遷移排程最後一站**。四紅線（不算/不裝/不寫＋#27 資格 vs 行動命名）為薄化驗收標準（S08 #45 同構） | 遷移案/Yonki 知悉 | 📌 已裁 |
| 50 | **universe=榜→持股跌出即隱形凍結**（paper_trading.py:153-154,343-344）：不 MTM/不停損/不出場，最該停損時刻回測失明；同母體病使績效 tab 永卡 30 筆門檻（cockpit:3510，門檻本身正確不動）。**#41 的第三張帳單**（regime 廣度、temperature 權重之後），回測正確性依賴 #41 市場母體修正 | 遷移案/S07#41 | 📌 已裁 |
| 51 | **出場判斷單一 SoT**：paper_trading v1(:164)/v2(:363)/holdings(:82-96 硬編碼連2、未讀 fii_reversal_days) 三實作合併為一評估函式＋一份 config。**漂移登記收案：10 例，全入遷移 checklist，不再增列** | 遷移 checklist | 📌 已裁 |
| 52 | **回測產物 version-pinning**：不落 canonical（跨窗 Derived-O 非當日 observation）；廢除覆寫式 _latest 為唯一真本——產物帶 schema_version＋輸入 snapshot 指紋＋strategy config hash，per-run 留檔，_latest 降為指標。機制設計歸 S06 #21/#22 框架 | 遷移案/S06 | 📌 已裁 |
| 53 | **sidecar 判死零斷炊（正面稽核）**：backtest 全鏈零 intelligence.json 消費，#46 開工前提已回覆，S08 裁定安全著陸。strategies.py 規則外置 config＝先天健康樣本（#33 遷移參照） | 已結案 | ✅ 證實 |
| 54 | **17 欄核准清單經終端消費者反向檢視無缺項→落地清單凍結為最終版**（obs_golden_* 六＋obs_sm_* 六＋obs_chip_grade/total/sync_streak＋obs_dist_consistency＋obs_market_regime/breadth/temperature） | 遷移案總表 | 📌 定稿 |
| 55 | 出貨 limitations 字串已成謊（paper_trading.py:120「snapshots carry no open」，實測 open=50.5 且 _fill_price 已優先用 open）——遷移期順手修 | 遷移期順手 | 登記 |

## 操作軌（與研究平行，不動 schema，不記入 session 範圍）
- ~~合併 claude/sleepy-nobel-3d007c → main~~ ✅ 已完成（2026-07-10 前）。**1.8.1 production 驗收延後：7/10 颱風假無交易資料，下一個交易日 2026-07-13 收盤後才有快照**——屆時看 reports/2026-07-13.json（Mac 開機→直接全量；Mac 關機→晚間 partial + 隔晨 supersede 補完，後者才是 NOTES #19 缺的真實樣本）。颱風假當晚各排程照常醒來、trading_day_gate 乾淨跳過（exit 0）＝正常。
- Handoff 待辦 #2：重建 7/02、7/03 滯後快照（資料修正）。
- cronjob PAT 2026-09-04 到期。
