# Session 02 — Chip Momentum（chip_score + resonance）

> 證據蒐集（opus 2026-07-10）。裁定者只讀本報告＋CROSS-SESSION-NOTES。
> 鐵律：先分析、後才談改；本報告不含 code 改動；證據一律附 `檔案:行號`。§5 留空待 fable。
> 本 session 涵蓋**兩個引擎**：分開分析再看重疊。

## §0 範圍與輸入

**只看：**
- `core/chip_score.py`（全檔 250 行：`CHIP_SCORE_CONFIG` 門檻字典、`GRADE_PCT_MAP`、`ChipScore` dataclass、`_threshold_score`、`compute`、`volume_label`）
- `core/resonance.py`（全檔 210 行：`_PARTICIPANTS`、`_LEVEL_LABELS/STARS`、`ResonanceState` dataclass、`_participant_sign`、`_resonance_for_stock`、`run_all`/`run_one`）
- 重疊對照面：`data/adapters/legacy.py:329-333`（`fii_sync_count` adapter 計算）、`core/ingest.py:167`（fii_sync_count 落地）
- 消費面（只盤點誰讀兩引擎輸出）：`viewer/cockpit.py`
- 落地對照：`reports/2026-07-09.json`（schema 1.8.1；頂層 key 與 stock record 欄位）

**明確不看（留給哪個 session）：**
- `confidence` 引擎內部（數值 risk_score/信心分本體）→ **S03**（NOTES #33 已裁 confidence 歸 S03）
- `weakening` / `market_context` / `accumulation_velocity` 內部演算法 → **S07**
- golden 對 chip/resonance 的消費語意與資格/行動分層 → **S01 已裁**（本 session 只記「golden 是否消費 resonance」的事實：**否**）
- 門檻命名正本 / registry 表格 → **S05 已裁**；replay 等級 / version-pin → **S06 已裁**
- viewer 卡片渲染、徽章 CSS、i18n、bubble map 呈現細節 → **S08**
- backtest 對兩引擎輸出的消費 → **S09**
- state_machine 的路徑依賴 → **S04 已裁**（本 session 借 C10 判 resonance_streak）

**實跑驗證（真引擎跑真實磁碟快照，10 份窗）：**
```
snaps=[json.load(open(f)) for f in sorted(glob('reports/2026-*.json'))][-10:]  # 至 2026-07-09
s=1536 stock  # main_force_buy=5536, fii_net_buy=123, dealer_net_buy=329, market_volume=2144
chip_score.compute(streak=1, fii_sync_count=3, main_force_buy=5536, market_volume=2144, ...)
resonance.run_one('1536', snaps)
```
輸出摘要：
- **chip_score.compute(1536)** → `total/max=19/26`, `grade=中`, items＝`{vol_ratio:8(avail), streak:3(avail), concentration:0(unavail), institutional:8(avail), cost_support:0(unavail)}`。分母 26 是「僅計 available 項」的浮動分母（concentration/cost 資料缺→不計入 max）。
- **resonance.run_one(1536)** → `level=3, members=[main_force,foreign,invest_trust], streak=1, strength=80, label=三方共振`；`participant_status={main_force:True, foreign:True, invest_trust:True}`。同檔**落地** `fii_sync_count=3`。
- **重疊實證（全榜掃描）**：對 latest 快照 35 檔逐檔跑 `resonance.run_one().resonance_level` vs 落地 `stock['fii_sync_count']` → **35 檔 0 不符**。`resonance_level ≡ fii_sync_count`（見 §3-b）。
- **落地面**：`reports/2026-07-09.json` stock record **無任何 `resonance_*` 或 `chip_*` key**（grep 空）；但 `fii_sync_count`（=3）**已落地**。→ **chip_score/resonance 兩引擎輸出落地＝0 欄**（復現 NOTES #2）。
- **chip_score 7 個輸入全部是落地欄位**：`main_force_strict_streak_days` / `fii_sync_count` / `main_force_buy` / `market_volume` / `main_force_cost` / `current_price` / `top5_concentration` 皆在 snapshot record（cost/concentration 為 landed-but-null，引擎 graceful 降級）。→ 見 §4（C9 判斷關鍵）。

---

## §1 這兩個引擎真正要回答什麼問題？

**chip_score（籌碼動能分）回答「這檔的籌碼結構強度，壓縮成一個 0–40 / 強中弱 的一眼徽章」。** 它把五個既有訊號（投量比＝main_force_buy÷market_volume、連買 streak、TDCC 集中度、法人同向數、成本支撐）各按門檻切成分數再加總，最後由 `GRADE_PCT_MAP` 依「占 available max 的百分比」給 強/中/弱＋顏色（chip_score.py:68-72,85-93）。docstring 自我定位明確：「**Information compression, not prediction**」（chip_score.py:4）。使用者拿它做的決定：golden 金卡上看一顆彩色圓點＋「強/中/弱」字（cockpit.py:2379-2383）——純顯示。

**chip_score 是否在答與 golden conviction／temporal_enrich streak 家族同一題？** 本質上是**同類題的輕量顯示版**：(i) chip_score 的 `streak` 子分讀的是**同一個** `main_force_strict_streak_days`、`institutional` 子分讀的是**同一個落地 `fii_sync_count`**、`vol_ratio` 讀 `main_force_buy/market_volume`——**全部是已落地欄位的再打包**，不自產任何新判定材料。golden conviction 也是把籌碼訊號加權成品質分，但 conviction **餵資格閘門（進場判斷）**；chip_score grade **只印徽章、不 gate、不落地**。∴ 兩者是「同一堆籌碼訊號的兩次聚合」，一個是判斷（golden conviction，S01 已裁必落）、一個是**純顯示再聚合**。關鍵在 §2/§4：chip_score 的 grade 是「判斷」還是「可由落地欄位純派生的顯示標籤（C9）」。

**resonance（共振）回答兩件事，只有第二件是它獨有的：**（i)「當日有幾方法人同向淨買（0–3）」＝`resonance_level`；(ii)「這個 level≥2 的同向狀態連續維持了幾天」＝`resonance_streak`＋由此導出的 `resonance_strength`（resonance.py:148,159-170）。前端「★★★ 三方共振　主力✓外資✓投信✓　連N日」即此輸出（cockpit.py:2342-2363）。使用者拿它判斷「法人是否抱團、抱多久」。

**resonance 的「N 方同向」與 fii_sync_count 是不是同一題兩個答案？** **是，且已實證重合**（§3-b）：`resonance_level` 的定義（幾個 participant 淨買為正，resonance.py:142-148）＝ `fii_sync_count` 的定義（幾個 participant 淨買為正，legacy.py:329-333）**逐字同構**，全榜 35/35 相等。resonance 唯一**新增**的是 (ii) 的**時序軸**（跨快照連續天數）——這是 fii_sync_count（單日、adapter 算、已落地）沒有的。∴ resonance 真正獨有回答的只是「同向連了幾天」，其「幾方同向」部分是 fii_sync_count 的 render-time 重算複本。

**2026-07-08 元大金（2885）實戰案例的架構訊號**：用戶見「共振 主力✓外資✗投信✓」誤以為外資✗會擋執行、報 bug；實則 resonance 是**獨立顯示系統，與可執行資格（golden action_group／5% 鐵則）正交**（golden 不消費 resonance，見 §3-e）。**這個誤解本身就是架構訊號**：resonance level（顯示 observation）與 golden 資格/行動（判斷）並置於同一張金卡，**兩系統的語意邊界沒有在呈現上劃清**，使用者把「顯示層的同向計數」讀成「行動層的閘門」。定性歸屬：呈現邊界問題→S08；但根因是「resonance 到底是不是判斷、該不該落地、和 fii_sync_count 誰是 SoT」，屬本 session §4。

---

## §2 它們屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）作答。兩引擎**都不讀 raw、不寫 metadata**，都是 render-time 的 O 態生產者；但**可派生性**與**時序性**不同，這正是 §4 的分野。

**chip_score：**
- **輸出 O 態（Classification）＝`grade`（強/中/弱）＋ `total`**。但**其全部 7 個輸入都是已落地欄位**（§0 實測）→ `grade = f(已落地欄位)` 是**確定性純函數**。∴ chip_score 產出**不是新判斷材料，而是可由落地欄位純派生的顯示標籤**——與 S01 裁定的 `display_tier` 同型（C9「可純派生者不落地」）。
- 混入**非資料層（Presentation）**：`grade_color`（#D4A84B…）、`bar_html()`（chip_score.py:99-108，直接吐 `<span>`）、`volume_label()` 的顏色與中文標籤（:237-249）——i18n/HTML/顏色住在引擎裡（同 S01/S04 的 dataclass 越界病灶，→S08）。
- **門檻字典 `CHIP_SCORE_CONFIG`（chip_score.py:23-64）本身已外部化為模組級 dict**（比 golden/sm 的散落常數整齊）——但仍是 **code 內字典、非 config_snapshot**，對 replay 不可見（NOTES #33，只記錄不重裁）。

**resonance：**
- **`resonance_level`（0–3）＝ O 態，但是 `fii_sync_count`（已落地）的重算複本**（§3-b）——不是新 O，是既有落地 O 的 render-time 派生。
- **`resonance_streak`（level≥2 連續天數）＋ `resonance_strength`（=level×25＋min(streak×5,25)，:170）＝時序 O 態**，需跨快照歷史才能算，**單一 record 無法派生**——這是 resonance 唯一 fii_sync_count 沒有、且非純派生的產物。時序、路徑依賴→**適用 C10 as-was**（NOTES #29）。
- **`participant_status`（per-participant True/False/None）＝ O 態，但同樣是各 participant 欄位符號的單日純派生**（`_participant_sign`，:110-115），可由落地的 main_force_buy/fii_net_buy/dealer_net_buy 逐檔導出。
- 混入 **Presentation**：`stars`（★★★）、`badge_html()`（resonance.py:70-105，整段 inline HTML）、`_LEVEL_LABELS`（無/單/雙/三方共振中文）、顏色 map——i18n/HTML 住在引擎（→S08）。

**分層小結**：兩引擎的「本體 O」大多是**已落地欄位的純派生**（chip grade、resonance_level、participant_status）＝C9 候選（不落）；只有 **resonance 的時序軸（streak/strength）**是無法從單一 record 派生的真新 O（C10 候選）。這與 S01 golden（自產真判斷必落）、S04 sm（狀態分類必落）不同——**本 session 兩引擎的多數輸出反而是「不該落」的派生**，這是取捨反向的關鍵定性。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 一致；「＋新增」＝本輪新發現。對應交辦 (a)–(e)。

### (a) chip_score 輸入面：viewer render-time 組裝七輸入呼叫 compute → C8 現行犯（🔴 組裝權，＋新增確認）

1. **chip_score 的合成判斷（grade）100% 發生在 presentation 層**：`viewer/cockpit.py:2369-2377` 在金卡渲染迴圈裡 `_chip_mod.compute(streak=streak_n, sponsorship=e.sponsorship_score, fii_sync_count=stock.get("fii_sync_count"), main_force_buy=stock.get("main_force_buy"), market_volume=mkt_vol, main_force_cost=mf_cost, current_price=cur_price)`——viewer **組裝 7 個輸入、呼叫評分引擎、當場產出 grade**，結果只餵一顆彩色圓點（:2379-2383），**不落地**。
   - → **這是 NOTES #24 C8（組裝權）的又一現行犯**，與 S01 §3(a)-5 的「viewer 中轉 weakening 進 golden 行動函式」同型：presentation 層在**執行跨欄位的合成判斷**。但**性質比 golden 案輕**：此處 7 個輸入多為 `stock.get(...)` 單欄讀取，`streak_n=e.streak`（:2269）、`mf_cost=e.main_force_cost`（:2326）、`cur_price=price or e.current_price`（:2327）皆為 GoldenEntry 的落地欄位直讀，非二次判斷搬運。∴ 違例的是「**合成動作（grade 的產生）住在 render-time**」，而非「搬運別的判斷結果」。C8 的處置（合成屬 core、輸出必落 or 判定為純派生不落）與 §4 的 C9 判斷交織——見 §4。

2. **chip_score 的 `institutional` 子分直接消費已落地的 `fii_sync_count`**（chip_score.py:185-192，讀 viewer 傳入的 `stock.get("fii_sync_count")`）——即 chip_score 內部**再消費一個已落地的合成 O**（fii_sync_count 本身是 adapter 的 0–3 同向計數）。疊加 §3-b，**「法人同向」這一個概念在系統裡有三個表示**（見 §3-b 末）。

3. **`sponsorship` 參數是死參數**：`compute(sponsorship: float, ...)` 收下但 docstring 標「kept for future use」（chip_score.py:128），函式體從不使用。viewer 仍每次傳 `e.sponsorship_score`（:2371）。🟡 死參數，記錄不展開。

### (b) resonance_level ≡ fii_sync_count：同一題兩個答案，一個落地一個 render-time 重算（🔴 重複判斷，＋新增——本 session 最關鍵發現）

4. **定義逐字同構**：
   - `fii_sync_count`（adapter，**已落地**）：`ri["fii_sync_count"] = sum(1 for v in [mfb, fii, trust] if v is not None and v > 0)`（legacy.py:333），落地於 `ingest.py:167`。
   - `resonance_level`（引擎，**render-time**）：`level = len(members)`，members＝`[pid for pid,fname,_ in _PARTICIPANTS if _participant_sign(stock,fname) is True]`（resonance.py:142-148）——同樣是「三個 participant 中幾個淨買為正」。
   - **實證**：全榜 35 檔 `resonance_level == fii_sync_count`，**0 不符**（§0）。
   - → **這是交辦「疑似同一題兩個答案」的證實**：resonance 的「幾方同向」＝ fii_sync_count 的 render-time 重算，**語意零差異**。兩者差別只在**落地狀態（landed vs render-time）**與**時序延伸（resonance 額外算 streak）**，非「分層」。消費者：fii_sync_count → chip_score.institutional（§3-a-2）＋ cockpit.py:2024,2578 直讀；resonance_level → 只有 viewer 兩處（§3-e）。**兩個消費路徑各算各的，同一數字算兩次。**

5. **潛在分歧風險（latent divergence，＋新增）**：兩者「主力方」取值來源**不同欄位**——fii_sync_count 用 `mfb = ri.get("total_buy_vol") or ri.get("buy_vol_lots")`（legacy.py:330，adapter 前欄位），resonance 用落地的 `main_force_buy`（resonance.py:34 `_PARTICIPANTS[0]`）。當前 35/35 符號一致，但**兩個不同來源欄位一旦符號分歧（例如某檔 total_buy_vol>0 而 main_force_buy≤0），兩個「同向計數」會給出不同值而無人察覺**——因為沒有一致性檢查、也沒有共同 SoT。此為「同一概念雙實作」的固有脆弱性。

6. **概念三重表示總結**：「法人同向數（0–3）」在系統裡有 **三個表示**：① `fii_sync_count`（adapter 算、**已落地**、單日）；② `chip_score.institutional`（render-time 讀①再切分數）；③ `resonance_level`（render-time 從 raw 重算①的同一數字）。①③ 實證相等、②消費①。**誰是 SoT、②③是否都該廢除改讀①、resonance 是否只保時序軸**——留 §5。

### (c) resonance 的「投信」participant 依賴誤名欄位 dealer_net_buy（🔴 correctness 消費端，✔ 復現 S05 RC-3）

7. **resonance 的第三個 participant「投信」讀 `dealer_net_buy`**：`_PARTICIPANTS = [("main_force","main_force_buy","主力"), ("foreign","fii_net_buy","外資"), ("invest_trust","dealer_net_buy","投信")]`（resonance.py:31-35）。註解甚至自承迂迴：`# from T86 t86["trust"] via dealer_net_buy`（:34）。實跑 1536：`invest_trust=True` 來自 `dealer_net_buy=329`（實裝值為投信，符號碰巧對）。
   - → **這是 S05 RC-3 / NOTES #1「dealer_net_buy 名自營商實裝投信」的消費端鐵證**：resonance 的「投信」判定**依賴這個誤名欄位**、且 docstring（resonance.py:18「dealer_net_buy 投信淨買」）也把誤名當真名寫進契約。**trust/dealer 正名時，resonance 是必改名單**（`_PARTICIPANTS` 的 fname 與 docstring）。fii_sync_count（legacy.py:332 讀 `investment_trust_net_buy`）用的是**正名的 adapter 內部變數**，反而比 resonance 乾淨——又一個「①③同題但②③實作品質不齊」的側證。

### (d) 門檻現況（🟡 治理，只記錄引用 NOTES #33，不重裁）

8. **chip_score 門檻**：集中於 `CHIP_SCORE_CONFIG`（chip_score.py:23-64，各子項 `thresholds/scores` 陣列）＋ `GRADE_PCT_MAP`（:68-72，0.80/0.60 切點）＋ cost_support 的 1.02/1.05 硬編碼在函式體（:207-212）。**多數已外部化為模組級 dict（優於 golden/sm），但仍是 code 內、非 config_snapshot**。
9. **resonance 門檻**：**全部散在函式體、未外部化**——level≥2 才算 streak（resonance.py:162）、`strength = level*25 + min(streak*5, 25)`（:170）、streak≥2 才顯示（:79）、badge 顏色切點（:74）。比 chip_score 更未治理。
   - → 兩引擎寫死門檻均引用 **NOTES #33**（門檻 config 化已系統性升格，registry 遷移 S05 RC-2 統一前置一次掃全引擎）。本 session 只記現況、不重複裁。

### (e) 輸出面 vs 落地面＋消費面（🔴 落地 0／消費全在 viewer，✔ 復現 NOTES #2）

10. **輸出 dataclass 欄位 vs snapshot 落地**：
    - `ChipScore`（chip_score.py:77-83）5 個實欄（total/max_total/grade/grade_color/items）＋ `pct`/`bar_html` → **snapshot 落地 0**（§0 grep 空）。
    - `ResonanceState`（resonance.py:54-63）6 個實欄（level/members/streak/label_zh/strength/participant_status）＋ `stars`/`badge_html` → **snapshot 落地 0**。
    - → 復現 NOTES #2、與 S01/S04 同構。但**性質不同**（見 §4）：golden/sm 落地 0 是「真判斷不落」的病；chip/resonance 落地 0 的大部分（chip grade、resonance_level）其實**本就該不落**（C9 派生）——只有 resonance 時序軸是「真該落卻沒落」。
11. **消費面（誰讀兩引擎輸出）**：
    - **chip_score**：**唯一真消費者＝`viewer/cockpit.py:2369`**（金卡 grade 圓點）＋ `volume_label` at :2402。**`tools/correlation_analyzer.py:39-45` 的 `composite.chip_score.fii_sub.*` 是不同命名空間**（P3b scoring stub 的 dotted leaf 路徑，非 `core/chip_score.py` 的 ChipScore）——不是本引擎消費者，記錄澄清避免誤判。**golden 不消費 chip_score**（golden.py import 無 chip_score）。
    - **resonance**：**唯二消費者皆在 `viewer/cockpit.py`**：金卡共振 pill（:2342-2363，讀 level/label/participant_status/streak）＋ 三維泡泡圖 `_engine_kind`（:3116-3151，讀 level 分 dual/single/diverge 顏色，明文「viewer 不做分級」:3107）。**golden 不消費 resonance**（golden.py:458 只 import state_machine；grep 確認 golden 無 resonance import）——**證實 §1 的元大金案例：resonance 與 golden 資格/行動完全正交，外資✗確實不擋執行**。
12. **時序輸出的 C10 適用**：`resonance_streak`（「連N日」，cockpit.py:2360「連{res.resonance_streak}日」）是**跨快照路徑依賴**的時序 O——每次 render 從全部快照重推。**適用 NOTES #29 C10（as-was）**：與 sm `days_in_state` 同型（當日認定逐日落地為正本、落地起點前歷史誠實放棄）。chip_score 無時序輸出（單快照純函數），不涉 C10。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：Observation-First / snapshot=SoR（NOTES #10）、扁平前綴、additive+alias、C8/C9/C10。）

**分野總綱（本 session 與 S01/S04 反向的關鍵）**：S01 golden、S04 sm 的多數輸出是**真判斷→必落（C2）**；本 session 兩引擎的多數輸出是**已落地欄位的純派生→不落（C9）**。∴ 兩引擎的理想邊界不是「補一堆 obs_* 落地」，而是「**認清哪些是純派生顯示（不落）、哪些是唯一真新 O（落）**」。

**chip_score 的理想邊界：**
- **輸入**：只吃已落地欄位（現況已如此——7 輸入全落地）。
- **輸出**：一個 **grade（強/中/弱）＋ total**，**確定性純函數 of 落地欄位**。
- **絕不做**：不 render-time 當場合成（C8）、不自產新判斷材料。
- **與現況差距**：(i) 合成動作住在 viewer render-time（§3-a-1，C8 違例）；(ii) i18n/HTML/顏色住引擎（→S08）；(iii) `sponsorship` 死參數（§3-a-3）。
- **落地判斷（C9 vs C8 的交會，本 session 最需 fable 裁的點）**：chip grade 既是「viewer 組裝的合成」（C8 說合成屬 core、輸出必落），又是「100% 落地欄位的純函數」（C9 說純派生不落）。**兩法在此相遇**：若判 grade＝純派生顯示標籤（如 display_tier），則正解是**把計算移進 core 純函數、但不落地**（C9 勝出，C8 的「合成屬 core」滿足於「移出 viewer」、「輸出必落」被 C9 豁免）。這需要 fable 確認 C8「輸出必落」是否對「純派生合成」讓位於 C9。

**resonance 的理想邊界：**
- **輸入**：只吃已落地的三 participant 淨買欄位（正名後的 main_force/foreign/trust）。
- **輸出職責拆三段**：
  - `resonance_level` / `participant_status`＝**單日純派生**（＝fii_sync_count＋各欄符號）→ **C9 不落**，且應**廢除重算、統一讀落地的 `fii_sync_count`**（消除 §3-b 的雙實作與 §3-b-5 的分歧風險）。
  - `resonance_streak`＝**跨快照時序 O**，無法純派生 → **C10 as-was 落地候選**（唯一真新 O）。
  - `resonance_strength`＝`f(level, streak)`，一旦 streak 落地即為純派生 → **C9 不落**。
- **絕不做**：不重算 fii_sync_count（改讀落地）、不 render-time 從全歷史重推 streak（改 C10 逐日落地）。
- **與現況差距**：(i) level 重算而非讀 fii_sync_count（§3-b）；(ii) streak 全歷史 render-time 重推、不落地（§3-e，C10 應落）；(iii) 投信讀誤名 dealer_net_buy（§3-c，正名必改）；(iv) i18n/HTML 住引擎（→S08）；(v) 門檻散在函式體（§3-d）。

**NOTES #12 列舉義務——兩引擎契約級 observation 候選（取捨留 §5）：**

*chip_score 候選（**列舉後多數自我否決為 C9**）：*
- `obs_chip_grade` / `obs_chip_total`：**C9 候選（傾向不落）**——100% 落地欄位純派生，落地只製造雙真相（同 display_tier 判例）。**若 fable 判 C8「合成屬 core 必落」壓過 C9，則此二欄為落地候選**；否則 0 落地、僅計算移出 viewer。此為兩引擎唯一需 fable 拍板的落地爭點。

*resonance 候選：*
- `obs_resonance_streak`（含 state_entered 語意）：**C10 as-was 落地候選（本 session 唯一明確該落的真新 O）**——時序、路徑依賴、無法純派生，與 sm days_in_state 同型。
- `resonance_level` / `resonance_strength` / `participant_status`：**C9 派生不落**（level＝讀落地 fii_sync_count；strength＝f(level,streak)；status＝各欄符號）——**明確列舉為「不落」候選**，且 level 應收斂到 fii_sync_count 單一 SoT。

**前三名（跨兩引擎，依架構重量排序）：**
1. `obs_resonance_streak`（C10 落地）——兩引擎唯一無爭議該落的真新 O。
2. `resonance_level → fii_sync_count` 收斂（C9 不落＋廢重算）——消除「同一題三表示」的核心。
3. `obs_chip_grade` 落地與否（C8×C9 交會）——需 fable 裁 C8「必落」是否對純派生讓位。

---

## §5 裁定（fable，2026-07-10）

> 裁定框架：SESSION-TEMPLATE §5 rubric。凍結期，只立契約方向。

### 系統身份判準
S02 的兩個引擎都是「已落地訊號的再聚合」——它們考驗的是 SoR 命題的細緻面：**什麼樣的再聚合是新判斷（必落），什麼樣只是重新標籤（不落）**。本裁定以第 11 條法把這條線一次劃死。

### 核心裁定：C11（判斷參數測試）——解 C8×C9 正面相撞
證據包正確指出 chip grade 讓 C8「組裝必落」與 C9「派生不落」相撞。裁定確立判準：
**一個可由落地欄位派生的輸出，若其函數內含「別處未落地的判斷參數」（門檻/權重/分母規則），它就是新判斷、必落地（C2/C8）；若只是對已落地判斷的重新標籤/粗化/i18n，它是呈現、不落（C9）。**
- 測試法：改動該函數的參數，系統的「歷史意見」會不會無痕改變？會→判斷→落；不會（底層判斷仍落著）→標籤→不落。
- 據此：`display_tier`（S01）輸入是**已落地的判斷**（tier/conviction/action_group），重標籤→不落，維持原裁；**`chip grade` 輸入是落地的度量**（streak/量/同向數），其 `CHIP_SCORE_CONFIG` 門檻＋浮動分母規則是**別處不存在的判斷**，使用者按金卡的「強/中/弱」行動過→**落地（obs_chip_grade＋total）**。**推翻證據包「傾向不落」的傾向**——它把「輸入已落地」誤當充分條件，C11 問的是「參數落了沒」。
- 前置：CHIP_SCORE_CONFIG 門檻 config 化（引 #33 系統性前置，不重裁）；C8 違例（viewer 組裝 7 輸入，cockpit.py:2369-2377）隨落地遷移消失（組裝移 pipeline）。

### resonance 裁定：一個引擎被證明是重複實作，解散
- **resonance_level ≡ fii_sync_count**（逐字同構＋35/35 實證）：**不落第二份**。已落地的 count 是 SoT；level/stars/label（★★★/三方共振）＝其呈現映射（C9/C11 標籤側），遷移期廢除 render-time 重算、改由落地欄位派生。
- **resonance_streak 是本 session 唯一真正的新 O**（時序）：**落地**。owner 歸 temporal_enrich 一系（先例＝fii_consecutive_buy_days 同型）；命名候選 `derived_participant_sync_streak`（與 S05 field_map 的 derived_participant_sync_count 成對），終審歸 registry。`strength`＝f(level,streak) 呈現派生，不落。
- **∴ resonance 引擎在遷移完成後解散**為「一個時序欄＋一組呈現映射」——本研究第一個「整引擎被證明是平行重複實作」的案例。凍結期不動 code，僅立方向。
- **雙實作漂移（第四次確認的系統病）**：S06 兩份 strip 清單、S04 落地而不讀、S02 level 重算複本＋**主力方向取值欄位不一致**（resonance 用 total_buy_vol、fii_sync_count 用 main_force_buy 一系——今日同值、明日可分歧的潛伏 bug）。不另立法（C2 消費紀律＋RC-2 registry 即解），但**遷移 checklist 必含「主力方向單一取值來源」**。

### 其他裁定
- **RC-3 消費端名單坐實**：resonance.py:34 讀誤名 `dealer_net_buy`（實投信）——trust_net_buy 正名遷移的必改消費者，登記。
- **元大金誤解的架構歸屬**：golden 不消費 resonance（證據包實證）＝系統行為正確；病在**呈現層把顯示性 observation 與資格判斷並置無區隔**→ S08 議程（顯示性徽章需與 gate 類訊號有可辨識的視覺語言）。

### 雜訊分離
浮動分母（available-only max）＝C11 判斷參數的一部分，隨 config 化處理，不獨立成案；★ 星號/顏色 i18n（S08）；門檻寫死（引 #33，第三、四個引擎實例，不重裁）。

### 挑戰證據包
- 品質高：35/35 全榜掃描是超出交辦的實證；「golden 不消費 resonance」把元大金案徹底閉環。
- **推翻其 chip grade「傾向不落」**：理由見 C11——「輸入皆落地」不等於「無新判斷」，判斷藏在參數裡。
- 接受其 resonance 三段拆分框架，並推進到「引擎解散」的終局結論（證據包止步於拆分，裁定補上存廢）。

### 不需要改的（防未來誤重構）
chip_score 的 graceful 降級設計（缺資料不計分母，誠實）；fii_sync_count 的 adapter 層計算位置（單日同步數屬 ingest 時可算的 derived，位置正確）；resonance 的 participant 三分概念本身（病在重複實作與誤名欄位，不在概念）。

### 與已鎖決策相容性
扁平前綴 ✓；additive+alias ✓（obs_chip_grade/sync_streak 新增，resonance 解散是遷移終局非即刻刪除）；C1-C10 ✓（C11 是 C8/C9 的仲裁條款，三者構成完整的「落不落」判定樹：判斷必落(C2/C8)→標籤不落(C9)→爭議看參數(C11)→時序看 as-was(C10)）。

### Architecture Verdict
| 級 | 項 | 理由 |
|---|---|---|
| P0 | C11 判斷參數測試 | 「落不落」判定樹的最後一塊；S03/S07/S08 每個引擎都會遇到同型爭點 |
| P0 | obs_chip_grade＋total 落地核准（前置：門檻 config 化） | 使用者按它行動過，判斷參數別處無記錄 |
| P1 | resonance_level 收斂到 fii_sync_count＋sync_streak 落地（temporal_enrich 系）＋引擎解散方向 | 第四次雙實作漂移；主力取值欄位不一致是潛伏 bug |
| P1 | RC-3 消費端名單＋resonance.py:34 登記 | trust 正名遷移的必改清單 |
| P2 | 元大金呈現區隔（S08 議程）、星號 i18n | 各歸其 session |

### Executive Summary（兩分鐘版）
1. 新法 C11 解 C8×C9 相撞：可派生輸出落不落，看它的函數有沒有「別處未落地的判斷參數」——有＝新判斷必落，沒有＝標籤不落。至此「落不落」判定樹完整：C2/C8→C9→C11→C10。（P0）
2. chip grade 落地（推翻證據包傾向）：它的門檻與分母規則是別處不存在的判斷，且使用者按它行動過。（P0）
3. resonance 引擎被證明是重複實作：level 與已落地的 fii_sync_count 逐字同構（35/35），唯一真材料是時序 streak——落一欄、其餘呈現映射，引擎遷移後解散。（P1）
4. 雙實作漂移第四次確認（strip 清單/落地不讀/level 複本/主力取值欄位不一致）——registry＋「已落地者必改讀」是唯一解，遷移 checklist 加「主力方向單一取值來源」。（P1）
5. 元大金誤解正式閉環：golden 不消費 resonance，系統行為正確；病在呈現層未區隔「顯示性徽章」與「資格判斷」，交 S08。（P2）

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES 已 append 本 session 裁定產出（#34-36）
- [x] 00-INDEX 狀態列已更新（✅ 完成）
- [x] 未執行任何 code/schema 改動
