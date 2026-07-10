# SCD Engine 架構藍圖（憲法）

> **地位**：本文件是 SCD Engine 的最高架構文件。所有未來的設計、遷移、code review 以本文件為判準。
> **制定**：2026-07-10，Architecture Research 9/9 session 收官日（fable 編纂；Yonki 核可）。
> **描述對象**：本文件描述**遷移完成後應存在的架構**，不描述現狀。現狀與理想的差距＝§7 遷移路線圖。
> **憲法 vs 判例**：本文件是規範正本；9 份 session 報告（`docs/architecture_research/sessions/`）與
> 55 條 CROSS-SESSION-NOTES 是判例——保存每條裁定的證據與推理，憲法引用判例、不重複判例。
> 任何「為什麼這樣規定」的問題，答案在判例裡。

---

## 1. 系統身份與一頁架構

**SCD Engine 是一個 Observation-First 的台股市場情報系統。**
它每天做一件事：把市場原始資料轉換成一組**確定性的觀察判斷**（誰在黃金名單、誰在出貨、市場是什麼體制），
把這些判斷**落地成一份不可變的快照**，然後讓三種讀者消費它：人（viewer）、歷史（replay）、損益（backtest）。

四句話講完整個系統：

1. **Snapshot 是唯一的 System of Record**——任何呈現給使用者或被回測消費的判斷，都存在於當日快照中。
2. **Replay Contract 是 SoR 的驗證機制**——沒有它，「快照是紀錄」只是一句口號（判例 #20）。
   同輸入必可重算出同觀察；重算不出來的部分，誠實標示保證等級。
3. **Viewer 是快照的閱讀器**——只做映射，不算、不裝、不寫。
4. **Backtest 是判斷的損益裁判**——只消費 as-was 落地序列，絕不用今天的程式重新想像歷史。

**新人只需要記住一個方向**：資料永遠單向流動——原始 → 快照 → 讀者。任何逆流（讀者生產判斷、
判斷回寫原始層、平行的第二份紀錄）都是違憲，研究期間發現的全部病灶皆源於逆流。

---

## 2. 分層與資料流

```
 Raw Sources（TWSE / 富邦 / sinotrade / market_pulse macro）
   ↓  fetch：抓取 + WORM 歸檔（含版本維度）
 Adapter（raw → record，C7 非破壞轉換）
   ↓
 Assembler / Ingest（依 Registry 組裝 canonical 快照骨架 + config_snapshot）
   ↓
 Observation Engines（pipeline 內執行：golden / state_machine / chip / temporal / market）
   ↓  將 obs_* 判斷寫入快照 —— 在封印之前
 Snapshot 封印（canonical hash；partial→supersede 鏈；WORM）＝ System of Record
   ↓                    ↓                     ↓
 Viewer（映射）      Replay（驗證）        Backtest（損益）
```

| 層 | 職責 | 生產者 | 消費者 | 輸入 | 輸出 |
|---|---|---|---|---|---|
| **Raw Sources** | 市場事實的取得與保全 | fetch 工具 | Adapter | 外部 API | WORM 歸檔（per-date、含版本維度）＋ today 原始檔 |
| **Adapter** | raw → record 的形狀轉換 | adapter 模組 | Assembler | 原始檔 | 三態標注的 record；**不得銷毀資訊**（C7） |
| **Registry** | 全部欄位的定義正本 | Data Contract owner | 所有層 | 裁定 | 每欄：名稱/語意/三態/grain/replay 等級/owner/棄用狀態 |
| **Assembler** | 依 Registry 組裝快照骨架 | ingest | Engines | record + config | canonical 快照（未封印） |
| **Observation Engines** | 生產判斷（唯一合法的判斷生產點） | 各引擎（見 §3） | Snapshot | 當日 record + **已落地**的歷史快照序列 + config | obs_* 欄位 |
| **Snapshot** | System of Record | pipeline（封印動作） | Viewer/Replay/Backtest | 以上全部 | 不可變快照 + hash + supersede 鏈 |
| **Replay** | 驗證「同輸入→同觀察」 | verify 層 | 維運/信任 | 快照 + WORM raw + Registry replay 等級 | 逐版本的保證證明 |
| **Viewer** | 翻譯成人能 30 秒決策的畫面 | presentation | 使用者 | 落地欄位 + 呈現映射表 | 畫面（零判斷、零寫入） |
| **Backtest** | 判斷接上價格算損益 | backtest 引擎 | 使用者/策略決策 | as-was 落地序列 + Raw 價格 + Config-M 策略 | version-pinned 損益報表 |

**欄位生命週期（一個欄位的一生）**：

- **創建**：只有兩個合法出生點——fetch（Raw-I）或 pipeline 內的引擎（O 態）。出生前必先在 Registry 登記。
- **轉換**：只有兩個合法轉換點——Adapter（形狀轉換，C7 非破壞）與引擎（判斷計算）。
- **消費**：封印之後全系統唯讀。Viewer/Backtest/Replay 只讀不寫。
- **修改禁區**：落地即定案（C10 as-was）。快照唯一的「變更」是 supersede 鏈（partial→complete），
  那是**取代**不是修改，且新舊版本都保留可驗。
- **死亡**：欄位不刪除，先標 deprecated（replay 生命週期內續寫），major 版才移除。

---

## 3. 所有權表（一個概念、一個 owner，無例外）

| 概念 | 唯一 Owner | 備註 |
|---|---|---|
| 欄位定義（名稱/語意/三態/grain） | **Canonical Field Registry** | 全系統唯一字典；CI 對拍 |
| 可重現性 / replay 參與權 | **Replay Contract**（verify 層） | 每欄的 replay 等級由 Registry 記載、verify 層執行；**驗證器內不得硬編碼清單** |
| 快照組裝與封印 | **Pipeline（ingest）** | 唯一寫入 canonical 的地方 |
| 進場資格 + 進場行動 | **Golden 引擎** | 資格（tier/gates/conviction）與行動（action_group）是兩種 O 態，同 owner 分欄（判例 #27） |
| 生命週期狀態 | **State Machine**（sm_state） | 「狀態」概念家族唯一 SoT（判例 #31） |
| 風險 | **obs_sm_transition_risk** | 「風險」唯一 SoT；一切風險呈現是它的映射（判例 #37） |
| 籌碼評分 | **Chip 引擎** | grade + total |
| 賣方證據 | **dist_consistency**（distribution 拆解後重生的唯一產出） | 判例 #38 |
| 時序派生（streak 家族） | **temporal_enrich 系** | 外資賣超 streak、sync_streak 等皆歸此，golden 等引擎改讀不自建（判例 #28/#35） |
| 市場 grain 判斷 | **Market 家族**（regime_shift 收斂後的唯一市場級生產者） | regime/breadth/temperature 一個生產者（判例 #40） |
| 大盤 macro 原始值 | **market_pulse**（per-date I 態） | 亦是市場母體資料（漲跌家數）的家（判例 #41） |
| 呈現（色/雙語/emoji/版面） | **Presentation 映射表** | 引擎只吐語意 enum（C12）；viewer 是唯一畫畫面的地方 |
| 回測 | **Backtest 引擎** | 薄消費者；出場判斷單一評估函式（判例 #51） |
| Hashing | **Hashing 模組** | 吃什麼、抹什麼，由 Registry replay 等級決定，不自作主張 |
| 版本策略 | **Schema versioning**（本文件 §6） | 單一 bump 原則見 §7 |
| 判斷參數（門檻/權重/名單） | **Config**（config_snapshot 參與 hash） | 含 TIER_A 人工名單——改參數必留痕（C11） |
| Raw 保全 | **WORM Archive**（含版本維度） | supersede 後舊版本仍可重建（治 RC-7） |

**不存在的 owner（刻意）**：獨立的 confidence 分數（已降級為派生視圖）、resonance 引擎（已解散為一欄
時序＋映射）、sidecar 事件檔（已廢除——事件是落地序列的純 diff）、market_state 平行引擎（已判死）。
任何人想「復活」這些概念，先讀判例 #35/#37/#38/#40/#46。

---

## 4. Observation 生命週期

**核准落地的 obs 欄位（17 欄，Registry 為正本，判例 #54 定稿）**：

| 家族 | 欄位 | 生產者 | 主要消費者 |
|---|---|---|---|
| golden | obs_golden_tier / conviction / action_group / gates_passed / tier_caps / near_miss | Golden | Viewer、Backtest |
| state machine | obs_sm_state / transition_risk / days_in_state / state_entered / structure_unstable / risk_factors | State Machine | Viewer、Backtest、市場 temperature |
| chip | obs_chip_grade（含 total） | Chip | Viewer、Backtest |
| temporal | sync_streak（derived_ 前綴，終名歸 Registry） | temporal_enrich | Viewer（共振呈現的唯一來源） |
| distribution | obs_dist_consistency | 賣方證據產線 | Viewer、Backtest |
| market | obs_market_regime / breadth / temperature | Market 家族 | Viewer banner、Backtest 環境濾網 |

**每一個 obs 欄的統一答案**（這張表對 17 欄全部成立，不逐欄重複）：

| 問題 | 答案 |
|---|---|
| 誰生產？ | §3 表中的唯一 owner，在 pipeline 內、封印之前 |
| 誰消費？ | Viewer（映射）、Backtest（as-was）、事件視圖（diff 派生） |
| 是否儲存？ | 是——落地於 canonical 快照（C2） |
| 可否 replay？ | 是——epoch-scoped-O 等級（同 schema 版本內同輸入必重算相同） |
| 是否參與 hash？ | 是——canonical hash 覆蓋全部 O 態 |
| Viewer 能不能自己算？ | **不能。永遠不能。**（四紅線之「不算」） |
| Backtest 能不能自己算？ | **不能。**歷史判斷只能讀 as-was 落地序列（C10；判例 #48-49） |

**呈現視圖（合法但不落地）**：display_tier、共振星號、留存率、「今日新進」、多頭分/警訊分、
統一「轉弱」標籤——全部是落地欄位的 C9 純派生或 diff，viewer render-time 計算，**不進快照**。
判別法見 §6 判定樹。

---

## 5. 憲法條文

### 三個正交契約軸（每個欄位在三軸上各有一個位置）

1. **三態 I/O/M**：Input（原始事實）／Observation（判斷，含 Derived/Classification 子型）／Metadata（環境與出處）。
2. **Replay Guarantee Strength**：可重算／僅防竄改／不可驗。承諾哪一級，Registry 寫明哪一級。
3. **Grain**：ticker／date（市場）／sector／strategy×window（回測）。一筆資料的粒度是契約的一部分。

### 十二條法（C1–C12）

| # | 條文 | 一句話 |
|---|---|---|
| C1 | 命名即語意 | 欄位名說什麼，裡面就裝什麼 |
| C2 | 觀察必落地 | 呈現給使用者或被回測消費的判斷，必存在於快照 |
| C3 | 三態分離 | I/O/M 不混裝，一欄一態 |
| C4 | 一資料一語意 | 同一事實不得有兩個名字、同一名字不得裝兩種事實 |
| C5 | Additive 遷移 | 新欄用加的；alias 跨 minor 雙寫；major 才移除 |
| C6 | 生產者標記 | 每欄記載誰產的 |
| C7 | 非破壞性 ingest | raw→record 不得銷毀資訊；lossy 必可自 archive 回復 |
| C8 | 組裝權歸生產者 | 跨引擎判斷由 core 組裝並落地；presentation 不組裝、不搬運判斷輸入 |
| C9 | 可純派生者不落地 | 能由已落地欄位純函數派生的標籤不進快照 |
| C10 | as-was 原則 | 路徑依賴判斷逐日落地為「當日認定」；history 由落地序列派生；落地前的歷史誠實放棄 |
| C11 | 判斷參數測試 | 含「別處未落地判斷參數」的輸出必落地。測試法：改參數，歷史意見會不會無痕改變 |
| C12 | 呈現單一擁有者 | 引擎吐語意 enum；色/雙語/emoji/HTML 由 presentation 映射表獨佔（C8 的鏡像） |

### 不變量（多年不變的紅線；違反即架構事故）

1. Snapshot 是唯一的 System of Record——不存在第二份掛「紀錄」招牌的持久化 artifact。
2. Presentation 永不生產：不算、不裝、不寫（viewer 對磁碟零寫入）。
3. 引擎永不呈現（C12）。
4. 一欄一 owner、一概念一 SoT（§3 表窮舉）。
5. Replay 參與權由 Registry 契約化——驗證器內不得硬編碼任何 strip 清單。
6. Replay 不依賴執行環境——environment 屬 M 態，記錄但不參與比對。
7. 改變意見的參數必須可見（config_snapshot 參與 hash）——不存在改了無痕的門檻。
8. Backtest 永不重建歷史判斷——讀不到的觀察就是不存在，回測誠實面對缺資料。
9. 落地即定案——修正錯誤走 supersede/backfill 留痕，永不原地改寫。
10. 遷移永遠 additive——刪除只發生在 major 版。

---

## 6. 未來決策框架

**新輸出「落不落快照」判定樹**（依序問，第一個命中即停）：

```
① 呈現給使用者或被 backtest 消費？(C2)  ─否→ 不落
② 是跨引擎組裝的判斷？(C8)              ─是→ core 組裝後落地
③ 可由已落地欄位純函數派生？(C9)        ─是→ 不落（呈現視圖）
④ 函數含別處未落地的判斷參數？(C11)     ─是→ 落
⑤ 路徑依賴／時序狀態？(C10)             ─是→ 以「當日認定」逐日落
```

**其餘決策規則**：

| 問題 | 答案 |
|---|---|
| 什麼留在 Metadata？ | 環境、出處、審計、時間戳——描述「這份紀錄怎麼來的」而非「市場怎麼了」的一切。M 態記錄但排除於 replay 比對 |
| Observation 何時可承諾 replay？ | 其全部輸入是 MUST-I 或已落地 O，且判斷參數在 config_snapshot 內。缺一項則誠實降級為「僅防竄改」 |
| 何時 bump minor？ | 新增欄位／alias 雙寫開始。**代價自覺**：每次 bump 使既往快照 full-replay 保證歸零（判例 #22），故落地欄位盡可能批次進單一 bump |
| 何時 bump major？ | 移除 deprecated 欄位／改變既有欄語意（後者原則上禁止——語意變＝新欄＋舊欄棄用） |
| 何時引入 alias？ | rename 時。舊名續寫至下一個 major，Registry 標注指向關係 |
| 新 grain 出現時？ | Registry 先登記 grain 與 owner，才准出生（判例 #42：市場層無家可歸的教訓） |

---

## 7. 遷移路線圖

**總原則：單一 bump。** 每次 schema bump 讓全部既往快照的 full-replay 保證歸零（RC-6／判例 #22），
所以 17 欄不分批落地——一切前置完成後，**一次 1.9.0** 付一次代價。
**排序即依賴**：Registry 是字典（沒有它一切無名分）→ 前置修正（沒有它落地的是退化分）→ bump →
消費端改讀＋處決（沒有落地欄就無從改讀）→ 回測正確化（終端消費者，最後）→ major 清場。

### Phase 0 — Registry（字典先行）
- **目的**：建 Canonical Field Registry：每欄名稱/語意/三態/grain/replay 等級/owner/棄用狀態；最小 CI 對拍。
- **依賴**：無（純新增，不動 schema）。
- **交付**：registry 檔＋CI 檢查；現有 60+ 欄全數登記（含殭屍欄的 deprecated-pending 標注）。
- **完成準則**：任何欄位問「你是誰」有唯一答案；CI 擋住未登記欄位進入快照。
- **風險**：低。最大風險是登記時發現新的語意衝突——照 C4 裁決，不擴大範圍。

### Phase 1 — Bump 前置（可平行進行）
- **目的**：讓 1.9.0 落地的是正確的判斷，不是把病焊進 as-was 紀錄。
- **五條工作線**：
  1. 門檻 config 化（#33）：全引擎寫死門檻/權重/TIER_A 名單入 config_snapshot。
  2. 母體修正（#41）：market_pulse 收編 per-date I 態＋擴充全市場漲跌家數；breadth/avg_chg 分母修正。
  3. Domain 修復（RC-3）：dealer/trust/prop 正名，WORM 回填；volume 家族 rename（alias 雙寫）。
  4. 賣方 raw 入 schema（C7 前置，判例 #38）。
  5. **Version-pinned replay 設計（S06）**：讓 1.9.0 之前的歷史保住「可重算」保證——**必須在 bump 前完成**，
     否則 bump 當日全部既往快照永久降級為 disk-hash。
- **依賴**：Phase 0（config 與新欄都要 registry 名分）。
- **交付**：config_snapshot 擴充；market_pulse per-date 歸檔；正名欄位 alias 雙寫；version-pinned verify。
- **完成準則**：`make test`＋`make verify-all-replay` 全綠；C11 測試通過（改任一 config 參數，歷史快照判斷不變）。
- **風險**：**中高**。母體修正需要新資料源（全市場漲跌家數）——外部資料可得性是本計畫唯一的外部依賴；
  version-pinned replay 是唯一的新機制設計（其餘都是搬家）。此二項先做 spike。

### Phase 2 — 唯一一次 minor bump（1.9.0）
- **目的**：17 欄一次落地；引擎計算移入 pipeline、封印前寫入。
- **依賴**：Phase 1 全部完成（缺一項就是落地退化分或不可見參數）。
- **交付**：schema 1.9.0；17 欄逐日落地；temporal_state／market_regime stub 標 deprecated；epoch 語意照 S06。
- **完成準則**：當日快照含全部 17 欄且值與（尚未薄化的）viewer 顯示一致；replay 對 1.9.0 快照達「可重算」級。
- **風險**：低（機制都在 Phase 1 驗證過）；主要是一次性的資料核對工作量。

### Phase 3 — 消費端改讀＋處決清單
- **目的**：viewer 薄化四紅線達標；死物下葬。
- **依賴**：Phase 2（沒有落地欄無從改讀）。
- **交付**：viewer 全部 render-time 引擎呼叫換成讀 obs_*；呈現映射表建立（C12）；
  處決執行——sidecar／checklist_history 停產、cockpit_v2＋Makefile 目標移除、market_state 刪除、
  resonance 解散、confidence 引擎降級、distribution 拆解完成。
- **完成準則**：viewer 對 core 引擎 import 數＝0；viewer 磁碟寫入數＝0；grep 引擎檔無 hex/HTML。
- **風險**：中。工作量最大的一段（confidence tab 重建為映射）；靠「畫面 == 快照欄位」逐 tab 驗收控管。

### Phase 4 — 回測正確化（終端消費者，最後一站）
- **目的**：回測從第三個判斷生產點退化為薄消費者；解除「不具決策效力」宣告（判例 #49）。
- **依賴**：Phase 2（as-was 序列存在）＋Phase 1-2 的母體修正（跌出榜可 MTM）。
- **交付**：進場改讀 obs_golden_*/obs_sm_* as-was 序列；出場單一評估函式＋config；
  產物 version-pinning（schema 版本＋輸入指紋＋config hash，per-run 留檔）。
- **完成準則**：C11 測試——改策略參數只影響「新跑的回測」，歷史報表檔不變；
  同一參數重跑兩次 bit-identical。
- **風險**：低。注意 as-was 序列從 1.9.0 起算，回測窗口初期偏短——誠實顯示樣本量，不回填假歷史（C10）。

### Phase 5 — Major 清場（2.0，不急）
- **目的**：移除全部 deprecated 欄與 alias 舊名；深 nested domain 結構（若仍想要）在此議。
- **依賴**：Phase 3-4 穩定運行一段時間（建議 ≥ 一季，讓 deprecated 欄的消費者確實絕跡）。
- **完成準則**：Registry 中 deprecated 欄數＝0。
- **風險**：低，唯一紀律是不提前。

**與遷移平行的操作軌（不屬任何 Phase）**：1.8.1 production 驗收（下一交易日收盤後）；
7/02、7/03 滯後快照重建；cronjob PAT 2026-09-04 到期。

---

## 8. 附錄：處置清單與判例索引

**處置定案（遷移期執行，不重議）**：

| 對象 | 處置 | 判例 |
|---|---|---|
| resonance 引擎 | 解散（level ≡ 落地欄；sync_streak 一欄存活） | #35 |
| confidence 引擎 | 降級為派生視圖（獨立分數廢除） | #37 |
| distribution 引擎 | 拆解重生（唯一產出 obs_dist_consistency） | #38 |
| market_state.py | 刪除（888 行零消費者假 SoT） | #40 |
| cockpit_v2.py | 刪除（含 Makefile 目標） | #7/#45 |
| intelligence.json sidecar | 廢除（停產留檔；事件改為落地序列 diff） | #46 |
| checklist_history.json | 廢除（留存率改 C9 派生） | #47 |
| temporal_state／market_regime stub | deprecated-pending，major 移除 | #31/#40 |
| 現行回測數字 | 不具決策效力，Phase 4 解除 | #49 |

**判例索引**：規範的證據與推理見 `docs/architecture_research/`——
`00-INDEX.md`（session 登記＋收官總帳）、`CROSS-SESSION-NOTES.md`（55 條裁定）、
`sessions/S01–S09`（各層完整證據包＋裁定）。本文件與判例衝突時，**以本文件為準**，
但修訂本文件必須先寫明推翻了哪條判例、為什麼。

---

*本文件取代一切先前的架構描述文件的規範地位。README／RUNBOOK／ARCHITECTURE.md 維持營運文件角色
（怎麼跑、怎麼修、現狀如何），不承載架構規範。*
