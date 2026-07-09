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

## 操作軌（與研究平行，不動 schema，不記入 session 範圍）
- 合併 claude/sleepy-nobel-3d007c → main（1.8.1 生效前提）＋隔日驗收 partial→supersede。
- Handoff 待辦 #2：重建 7/02、7/03 滯後快照（資料修正）。
- cronjob PAT 2026-09-04 到期。
