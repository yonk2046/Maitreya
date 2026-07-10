# Session 03 — Distribution & Risk（distribution + confidence 兩引擎）（證據包）

> 證據蒐集（opus 2026-07-10）。裁定者只讀本報告＋CROSS-SESSION-NOTES。
> 鐵律：先分析、後才談改；本報告不含 code/schema 改動；證據一律附 `檔案:行號`。§5 留空待 fable。
> 本 session 涵蓋**兩個引擎**：`core/distribution.py`（出貨意圖觀察層）＋ `core/confidence.py`（信心×風險 2D 側寫）。分開分析再看重疊。
> 承接：S05 §5 RC-1／NOTES #12（呈現或被 backtest 消費的 observation 必落；個別引擎落地清單由各 session 列舉）；S06 §5／NOTES #20-22（Replay Guarantee Strength 正交軸、bump 歸零排程代價）；S01 §5／NOTES #24-27（C8 組裝權、C9 純派生不落、**資格 vs 行動＝兩種 O 態**，distribution 的「建議動作」直接踩此線）；S04 §5／NOTES #29-33（C10 as-was、轉弱＝證據→分類→風險分層不合併、**confidence 正式歸入本 session、雙軌 risk 屆時裁**）；S02 §5／NOTES #34-36（C11 判斷參數測試、雙實作漂移系統病）。
> 已鎖決策（不重議，見 NOTES #9 / 00-INDEX）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0、fii cap 維持 2 天。

---

## §0 範圍與輸入

**只看：**
- `core/distribution.py`（全檔 584 行：`CONSISTENCY_CONFIG`/`GRADE_BANDS`/`SAFETY_MARGIN_BANDS`/`AUTO_FILTER_*` 門檻、`DistributionEntry`/`DistributionResult` dataclass、`_ACTION_MATRIX`、`_load_raw_sell_data`、`_side_status`、`_score_consistency`、`_safety_margin`、`_suggest_action`、`_should_flag`、`run`/`generate`/`load_for_date`）
- `core/confidence.py`（全檔 924 行：`CONF_*`/`RISK_*`/`TEMP_*` 權重與門檻、`ConfidenceProfile`/`MarketRiskTemperature`/`ConfidenceResult` dataclass、`_compute_confidence`、`_compute_risk`、`_profile_code`、`_build_temperature`、`_is_deteriorating`、`run`/`ticker_profile`）
- 持久化面：`reports/`（查 distribution.json / confidence 檔案是否存在）、`tools/daily.py:378-392`（pipeline step 4 intelligence）、`core/intelligence_delta.py`（confidence 的第二消費者、intelligence.json 產出者）
- 消費面（只盤點誰讀兩引擎輸出）：`viewer/cockpit.py`（distribution:52,1899-1905,2424-2457；confidence:47,1874,3055-3092,3236-3263,2941-2962）、`core/intelligence_delta.py`
- 落地對照：`reports/2026-07-09.json`（schema 1.8.1）、`reports/2026-07-09.intelligence.json`

**明確不看（留給哪個 session）：**
- `weakening_profile`/`accumulation_velocity`/`sponsorship_persistence`/`failed_breakout_memory`/`regime_shift`/`sector_intelligence` 的**內部演算法** → **S07 Market Context**（distribution 讀 raw archive 的 sellList、confidence 讀 ts.* 借用量，兩者的上游判定內部歸 S07）
- state_machine 的 sm_state/transition_risk **本體與路徑依賴** → **S04 已裁**（本 session 只查 confidence 對 sm 的**消費語意**＝雙軌 risk）
- golden conviction/tier 的**本體** → **S01 已裁**（本 session 只查 confidence 對 golden 的**輸入重疊**）
- chip_score/resonance → **S02 已裁**
- 欄位命名正本 / registry 表格 → **S05 已裁**；replay 等級 / version-pin / strip 白名單 → **S06 已裁**
- viewer 卡片渲染、徽章 CSS、i18n、溫度條/氣泡圖呈現細節 → **S08**
- backtest 對兩引擎輸出的消費 → **S09**

**實跑驗證（真引擎跑真實磁碟快照）：**
```
# distribution — 跑 latest（load_snapshot + _raw_archive sell-side）
from core import distribution as D; r = D.run()   # 2026-07-09
# confidence — 跑全部 42 份窗
snaps=[json.load(f) for f in sorted(glob('reports/2026-*.json')) if 无.intelligence/.example]
from core import confidence as C; r = C.run(snaps)
```
輸出摘要：
- **distribution.run(2026-07-09)** → `date=2026-07-09`, `universe_count=96`, `counts={total:96, flagged_for_removal:0, strong_sell_signal:32}`。`DistributionEntry.as_dict()` **20 欄**：consistency_color/grade/reason/score, current_price, flag_reason, flagged_for_removal, foreign_detail/status, main_detail/status, main_force_cost, name, safety_color/hint/label/margin, suggested_action/detail, ticker。實例 `1101`：grade=弱 score=-5，safety=—（main_force_cost=None→無安全邊際），action=觀察，flag=False。
- **confidence.run(42 snaps)** → `date=2026-07-09`, `profiles=245`, `counts={total:245, ideal:50, watch:51, deteriorating:0, weak:66}`。`market_temperature=0.463 warm`（elev_ratio=0.212, dist_ratio=0.762, breadth=0.5）。`ConfidenceProfile.as_dict()` **24 欄**（見 §2）。實例 `5880 合庫金`：confidence=0.772(high)、risk_score=0.5(**critical**)、sm_state=strengthening、profile=high_elevated；`conf_breakdown={streak:0.3, sponsorship:0.234, in_golden:0.15, conviction_add:0.038, sector_top3:0.05}`、`risk_breakdown={sm_base:0.25, velocity_negative:0.15, accel_negative:0.1}`；golden_conviction=0.75、streak=18、velocity=-719。**risk_score 恰為 0 者 150/245（61%）**。

**持久化 / 落地面實測（本 session 最關鍵查證）：**
- **`reports/*.distribution.json` 磁碟實存＝0 份**（`ls reports/*.distribution.json` 空）。distribution 有 `generate()`（distribution.py:517）寫 `reports/<date>.distribution.json`，但**全 repo 唯一 caller 是它自己的 CLI `--save`**（distribution.py:555）——`intelligence_delta.py:891` 的 `generate()` 是 **intel 自己的** generate（intelligence_delta 只 import golden/confidence/state_machine，**不 import distribution**，:40-42），`tools/daily.py`/`tools/run_pipeline.py` 對 distribution **零引用**（grep 空）。→ **distribution 的落地能力存在但生產線從不觸發**。
- **confidence 不落 canonical snapshot**：`reports/2026-07-09.json` 頂層無 confidence/temperature/risk key（只有 config_hash/config_snapshot）；stock record 只有 `confidence_tier`（P3a scoring stub，與 confidence 引擎無關）。**但 confidence 的 per-ticker 輸出流入 `reports/<date>.intelligence.json`**（pipeline 寫、sidecar）：intelligence.json 含 `biggest_confidence_changes`、`watch_list`、`risk_alerts`（實測 `mentions confidence:45, risk:130`；**temperature:0**——市場溫度不進 intelligence.json）。
- → **兩引擎都零落 canonical snapshot（復現 NOTES #2 的主結論）；但持久化細節與前四 session 全不同，見 §3(a)。**

---

## §1 這兩個引擎真正要回答什麼問題？

**distribution（出貨意圖觀察層）回答「這檔的賣方籌碼結構有多危險、現價離主力成本多遠、據此建議怎麼做」。** 它把四份 raw 排行榜（外資買/賣超、主力買/賣超）分類成**籌碼一致性**（-5..+5，強/中/弱）、把現價÷主力成本算成**安全邊際**（綠/黃/橙/紅），再用 `_ACTION_MATRIX`（distribution.py:140-153）把兩者查表合成**建議動作**（優先佈局/核心持股佈局/觀察/減碼），最後對「弱籌碼＋安全邊際>1.12x」亮**⚠建議自黃金名單移出**旗標（distribution.py:424-432）。定位是 golden 的**平行風險層**：docstring 明文「Golden Layer scoring is UNTOUCHED … does not feed into conviction scores, gates, or tiers」（distribution.py:22-27）。

**distribution 的「建議動作」是 observation 還是行動判斷（NOTES #27）？** ——**是行動判斷，且比 S01 golden 的 display_tier 更露骨**。distribution 極力自我開脫「Pure observation. No trading signals. No buy/sell recommendations … 『建議動作』是 descriptive label … not investment advice」（distribution.py:35-38），但實況：(i) `_ACTION_MATRIX` 直接輸出「**減碼**」「**優先佈局**」「**核心持股佈局**」——這是進出場動作詞，非狀態描述；(ii) `flagged_for_removal` 的 `flag_reason` 字面「**建議自黃金名單移出**」（distribution.py:430），viewer 渲染成「⚠ 建議自黃金名單移出（display-only）」pill（cockpit.py:2453）。**這與 S01 display_tier 案同型但更嚴重**：display_tier 是把已算好的 tier/action_group **重貼標**（C9 純派生，S01 裁不落）；distribution 的建議動作是**自產一組全新的行動分類**（安全邊際 band × 一致性 grade → 12 格動作矩陣），且其中一格直接對 golden 名單下「移出」指令語意。兩者共病是「observation 引擎尾端長出 action 語意」，但 distribution 是**獨立自產行動矩陣**，不是重貼 golden 的既有判斷。這條線是 §3(a) 與 Q4 核心。

**confidence（信心×風險 2D 側寫）回答「這檔有多少證據支撐（信心 0-1）× 有多少警告證據（風險 0-1），落在 2D 平面哪一格」，外加一個市場級聚合「市場風險溫度」。** 使用者拿 profile（強勢低風險/強勢但有警示/結構惡化中/信號不足）判斷續抱與部位管理；intelligence_delta 拿 per-ticker confidence 的日間差分產「信心升/降級」事件（intelligence_delta.py:369-392、53-54）。

**confidence 的「信心×風險 2D」與 golden conviction（資格信心）、sm transition_risk（惡化風險）是不是第三次回答同一批問題？** ——**信心軸是第三次答「conviction」、風險軸是第二次答「risk」，且兩軸都把上游引擎的結論當輸入再導出**（實測 §0 的 5880）：
- **信心軸重疊 golden**：`_compute_confidence` 把 `in_golden`（+0.15）與 `golden_conviction * 0.05`（conviction_add）直接**加進**信心分（confidence.py:392-397）。即 confidence 的信心分**把 golden 的資格信心當一個加分因子再包一層**——golden conviction 已是「把籌碼訊號加權成品質分」（S01），confidence 再把它＋streak/sponsorship/velocity 二次加權成另一個 0-1 分。**同一批籌碼訊號第三次聚合**（chip_score 顯示聚合＝S02、golden conviction 資格聚合＝S01、confidence 信心聚合＝本 session）。
- **風險軸重疊 sm**：`_compute_risk` 把 sm 的 `transition_risk`（4 級類別）用 `RISK_SM_BASE` 映射成基底分（critical→0.40…low→0.0，confidence.py:109,426），再疊 distributing/funnel/failed_breakout/velocity/accel/streak 因子，導出自己的 0-1 `risk_score`，**再切回 critical/elevated/medium/low 同樣 4 級**（confidence.py:463-470）。→ **雙軌 risk：sm 產類別型 transition_risk、confidence 產數值 risk_score 再桶成同名 4 級**，且 confidence 的建在 sm 的之上。實測 5880：sm transition_risk=elevated（→base 0.25），confidence 加 velocity/accel 後 risk_level=**critical**——**兩引擎對同一檔的「風險級別」給出不同答案**（sm=elevated、confidence=critical）。這正是 NOTES #33 指定本 session 蒐證的「雙軌 risk 存廢」核心。

---

## §2 它們屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）作答。兩引擎都**不寫 metadata**；輸入面不同（distribution 讀 raw archive、confidence 讀他引擎 render 結果）。

**distribution：**
- **輸入是 I 態（Raw）＋部分 O**：一致性軸的四份排行榜（sellList/mainForceSell/buyList/mainForceBuy）**直接讀 `reports/_raw_archive/<date>/` 的 raw bytes**（distribution.py:241-299），**這些欄位根本不在 canonical snapshot 裡**（賣方資料從未併入 schema，docstring:5-11）；安全邊際軸的 current_price/main_force_cost 讀 `load_snapshot`（distribution.py:449,480-481）——是已落地 O。
- **輸出 O 態（Classification）**：`consistency_score/grade`（賣方籌碼分類）、`safety_label`（成本距離分類）。一致性分**源自 raw、非 snapshot 可派生**（真新 O）；安全邊際**是 current_price/main_force_cost 的純函數**（可派生，但 band 切點是 code 常數 → C11 見 §4）。
- **輸出跨入近-行動層**：`suggested_action`/`suggested_detail`（12 格動作矩陣）、`flagged_for_removal`/`flag_reason`（移出旗標）——帶進出場動作語意（§1、§3a）。
- **混入非資料層（Presentation）**：`consistency_color`/`safety_color`（#52B788…）、CLI 的 emoji/表格——i18n/顏色住引擎（同 S01/S02/S04 dataclass 越界病灶，→S08）。

**confidence：**
- **輸入全是他引擎的 render-time 結果（借用 O）**：`golden_run`（confidence.py:699）、`sm_run_all`＋`sm_state_summary`（:700-701）、`_breadth_signal`→`regime_shift`（:702）、`_sector_top3_set`→`sector_intelligence`（:606-623）——**confidence 自己不讀 snapshot 欄位、不讀 raw，純消費四個引擎現算輸出再合成**。ts.streak/velocity/acceleration/sponsorship 亦全來自 sm（本身借自 market_context）。
- **輸出 O 態（Classification）**：`confidence`(0-1)+`confidence_band`、`risk_score`(0-1)+`risk_level`、`profile_code`（2D 分類 high_low…deteriorating）；市場級 `market_temperature`（0-1）+`temperature_level`（cool…extreme）——**注意 temperature 的 grain 是 per-date（市場），非 per-ticker**（唯一非個股粒度輸出）。
- **`deteriorating` 是時序 O**：`_is_deteriorating`（confidence.py:628-674）比對 3 快照前的 streak/velocity → 路徑依賴，**適用 C10 as-was**（NOTES #29）。
- **混入 Presentation**：confidence_zh/color、risk_zh/color、profile_zh/en/color、temperature_zh/color（PROFILE_ZH/EN/COLOR 等 map，:129-200）——i18n/顏色住引擎（→S08）。

**分層小結**：distribution 是**唯一輸入含 raw 的 O 生產者**（一致性源自 archive、繞過 snapshot）＋尾端長出獨立行動矩陣；confidence 是**純二階聚合器**（不碰 raw/snapshot、只重組四引擎結論），其兩軸分別重疊 golden（信心）與 sm（風險）。兩者的「本體 O」性質相反：distribution 一致性軸是**真新 O（但 source 是 archive）**、confidence 兩軸幾乎是**既有 O 的再聚合**。這是 §3/§4 取捨的關鍵定性差異。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 一致；「＋新增」＝本輪新發現。對應交辦 (a)–(e)。

### (a) 【持久化真相】distribution＝唯一有落地能力的引擎，但落地生產線斷線＋消費者只讀落地→雙重死區（🔴 架構，＋新增，本 session 最關鍵）

1. **distribution 是 9 引擎中唯一自帶檔案輸出 code path**：`generate()` 寫 `reports/<date>.distribution.json`（distribution.py:517-532），設計為**明確的 sidecar、在 canonical hash 邊界之外**——docstring 立約「reads RAW … persists its own output … replay (verify_all_replay) is COMPLETELY UNAFFECTED. Adding/changing fields here can never change a canonical hash」（distribution.py:13-22）。這是 NOTES 從未見過的型態：**「有落地但刻意走旁路（sidecar，不在 replay 覆蓋）」**。
2. **但這條 sidecar 生產線從不被觸發**：`generate()` 全 repo 唯一 caller 是 distribution 自己的 CLI `--save`（distribution.py:555）；`intelligence_delta.py:891` 的 `generate()` 是 **intel 模組自己的**（intelligence_delta **不 import distribution**，:40-42 只 import golden/confidence/state_machine）；`tools/daily.py` step 4 只跑 `python -m core.intelligence_delta`（daily.py:386），**對 distribution 零引用**。→ **磁碟 `reports/*.distribution.json`＝0 份**（§0 實測）。
3. **消費者只讀落地、無 render-time fallback**：viewer `from core.distribution import load_for_date as _dist_load`（cockpit.py:52）；`dist_result = _dist_load(active_date)  # may be None`（cockpit.py:1902）——**只 disk-load，不呼叫 `run()`**。0 份檔案 → `dist_result=None` → `dist_map={}`（cockpit.py:1903-1905）→ 每檔 `dist_e=None` → `dist_html=""`（cockpit.py:2456-2457）。
   - → **雙重死區**：生產線不寫（步驟 2）＋消費者只讀不算（步驟 3）＝**distribution 的一致性/安全邊際/建議動作/移出旗標在部署的 viewer 中永不顯示**。它是「活 code、死輸出」——與 NOTES #7 cockpit_v2 死碼不同（那是整檔棄置），distribution 是**被 import、被聯結、但輸出鏈斷成兩截**。
   - **✱ 推翻 NOTES 認知**：NOTES #2 稱「Observation 層(…distribution…)全部 viewer render-time 計算」——**對 distribution 不成立**。distribution 是唯一**不**被 viewer render-time 計算的引擎（viewer import 的是 `load_for_date` 非 `run`），且因 0 檔案而根本不顯示。NOTES #2 的「全部 render-time」概括需對 distribution 修正為「disk-load-only、且生產線斷線→實際不顯示」。

### (b) 【distribution 行動語意】自產 12 格行動矩陣＋「移出黃金名單」指令，偽裝成 display-only（🔴 資格 vs 行動，＋新增）

4. **`_ACTION_MATRIX` 輸出進出場動作詞**（distribution.py:140-153）：「優先佈局／核心持股佈局／減碼」是 buy/sell 動作，非狀態描述；`_suggest_action`（:412-421）純查表 `(consistency_grade, safety_label)→(action, detail)`。docstring 自稱「descriptive label … not investment advice」（:35-38）與輸出字面**自相矛盾**（同 S01 golden.py:9 vs display_tier「可買進」的矛盾，本 session 第二例）。
5. **`flagged_for_removal` 對 golden 名單下指令語意**：`_should_flag`（:424-432）「弱籌碼＋安全邊際>1.12x → flag_reason='建議自黃金名單移出'」。雖 code 反覆聲明「display-only … 不會更動 Golden 名單本身」（:71-74）、實際也不改 golden（golden 不消費 distribution，見步驟 6），但**輸出的語意是對另一引擎的判定結果下否決建議**——這是 distribution 越出「平行風險層」自我定位、對 golden 資格判定伸手的證據。門檻 `AUTO_FILTER_MARGIN_MIN=1.12`（:135）與 golden action_group 的 `max_premium_ratio=1.05`（S01）**是兩套不同的成本容忍閾值**，各自寫死、無共同 SoT。
6. **判定鏈輸入來源＝raw archive，不呼叫他引擎、不讀 snapshot 賣方欄位（因後者不存在）**：`_load_raw_sell_data` 直讀 `_raw_archive` bytes（:241-299），**不經 adapter、不碰 raw_inputs_per_ticker**（:224-225 立約）。→ **無 C8 組裝違例**（不搬運他引擎判斷輸入）；但代價是 distribution 的一致性分**依賴一組 snapshot 完全看不到的 raw 欄位**（sellList 等），落地時無法宣稱「可由 snapshot 派生」（§4）。golden 確認**不消費 distribution**（grep：golden.py 無 distribution import）——「平行、不回饋」自我定位在**資料流上成立**。

### (c) 【confidence 雙軌 risk 完整證據】risk_score 建在 sm transition_risk 之上、信心分建在 golden conviction 之上，輸入大量重疊（🔴 責任重疊，＋新增，NOTES #33 指定蒐證）

7. **風險軸：confidence 把 sm 的類別 risk 當基底再導數值 risk，切回同名 4 級**（confidence.py:413-472）：
   - `RISK_SM_BASE = {critical:0.40, elevated:0.25, medium:0.10, low:0.0}`（:109）→ 讀 `ts.transition_risk`（:736,426）當 base；
   - 疊加因子：`distributing`（sm_state==DISTRIBUTING，+0.25，:432）、`funnel_warning`（funnel==risk_warning，+0.20，:437）、`failed_breakout`（+0.20，:442）、`velocity_negative`（velocity<0，+0.15，:447）、`accel_negative`（accel<-500，+0.10，:452）、`streak_zero`（+0.10，:457）；
   - 再桶回 `critical/elevated/medium/low`（切點 0.50/0.30/0.15，:463-470）。
   - → **與 sm transition_risk 的輸入高度重疊**：sm 的 `_compute_risk`（S04 §3-2）本就用 velocity/accel/streak/failed_breakout/distributing 算 transition_risk；confidence **把 sm 已消化過這些因子的結論（transition_risk）當 base，又把同一批原始因子（velocity/accel/streak/failed_breakout/distributing）再加一次**——**同一組證據被 double-count**：一次以 sm 類別型式進 base、一次以原始因子進疊加。實測 5880 即此：sm 給 elevated（0.25），confidence 用 velocity_neg+accel_neg 再加 0.25 → critical。**兩引擎對「風險」給出分歧答案，且 confidence 的分歧來自重複計入 sm 已算過的因子**。
8. **信心軸：confidence 把 golden 的資格信心當加分因子再包一層**（confidence.py:392-397）：`in_golden→+0.15`、`golden_conviction * 0.05→conviction_add`。→ **與 golden conviction 輸入重疊**：golden conviction（S01，資格分）本身是 streak/sponsorship/sector/state 加權；confidence 信心分**又用 streak（:370）/sponsorship（:376）/sector_top3（:400）/velocity（:382）** 加權——**同一批訊號第三次聚合（chip=S02 顯示、golden=S01 資格、confidence=信心），且 confidence 額外把 golden 的成品 conviction 也吃進來**。
9. **viewer 把 confidence 輸出與 golden/sm 並置**：市場溫度 banner（cockpit.py:3061-3092，`_run_confidence` render-time）、多空體檢表「多頭分＝confidence／警訊分＝risk_score」（cockpit.py:3236-3263 用 `p.confidence`/`p.risk_score`）、watch_list（cockpit.py:2941-2962）。cockpit.py:3135 註解自承「Core risk_score piles ~35% of names at exactly 0」——實測 **150/245（61%）risk_score 恰為 0**（§0），confidence 的風險軸對六成標的無鑑別力（sm 有狀態、golden 有 tier 時，confidence 風險欄大量塌到 0）。→ 使用者同一畫面看到 golden tier／sm 狀態徽章／confidence 多頭分警訊分，**三套語意來源重疊卻並列無譜系**（呼應 S02 §1 元大金並置誤解、S04 §3-5 兩個轉弱出口，本 session 是第三、四例）。

### (d) 【與 weakening 鏈的關係 #32】distribution/confidence 是第四、第五個「轉弱/風險」出口（🔴 責任重疊，＋新增）

10. **S04 已立「轉弱＝證據→分類→風險」三層鏈**（weakening severity[A,mc產已落] → sm distributing[B] → transition_risk[C]，NOTES #32）。本 session 確認**再多兩個平行出口**：
    - **出口 D：distribution 一致性 grade=弱 ＋ suggested_action=減碼 ＋ flagged_for_removal**（distribution.py，源自 raw sell-side，**與 weakening 完全不同的證據源**——weakening 讀 velocity/branch，distribution 讀外資/主力賣超榜）。
    - **出口 E：confidence risk_level=critical/elevated ＋ profile_code=deteriorating**（confidence.py，源自 sm transition_risk 再聚合 §3-7）。
    - → **使用者面現存至少 5 個「這檔在轉弱/有風險」的並行語言**（weakening 徽章 severity、sm 狀態徽章 distributing、sm 風險級 transition_risk、confidence 警訊分 risk_score、distribution 建議動作減碼＋移出旗標），來自**三種不同證據源**（market_context velocity、raw 賣超榜、sm 聚合），落地狀態各異（weakening 落 snapshot、intelligence.json 有 confidence 差分、distribution sidecar 空、sm/confidence render-time）。NOTES #32 裁「不合併、統一標籤若需要＝C8 core 派生」——本 session 提供第 4/5 出口的完整清點，統一協調歸 S08 議程。

### (e) 【門檻現況＋C11＋輸出/消費面】

11. **門檻全寫死 code、非 config_snapshot（引 NOTES #33，不重裁）**：
    - distribution：`CONSISTENCY_CONFIG`（strong_rank_max=15/strong_vol_min=8000/scores dict，:106-118）、`GRADE_BANDS`（4/1/-99 切點，:120-124）、`SAFETY_MARGIN_BANDS`（1.03/1.08/1.15，:126-132）、`AUTO_FILTER_MARGIN_MIN=1.12`/`AUTO_FILTER_CONSISTENCY=弱`（:135-136）、`_ACTION_MATRIX`（12 格，:140-153）——全模組級常數。
    - confidence：`STREAK_SCALE/CAP`、`SPON_WEIGHT`、所有 `CONF_*`/`RISK_*` 權重（:97-115）、`RISK_SM_BASE`（:109）、profile 門檻 `CONF_HIGH=0.55`/`CONF_MID=0.30`/`RISK_LOW=0.15`/`RISK_MED=0.30`（:118-121）、`TEMP_W_*`（:123-126）、`TEMP_LEVELS`（:194-200）——全模組級常數。
    - → 兩引擎同 S01/S04/S02 的門檻治理病（NOTES #33 已升格系統性、registry 統一前置）；本條只登記、引用不重裁。
12. **C11 判斷參數測試**（NOTES #34：改參數→歷史意見會不會無痕改變）：
    - distribution：一致性 grade（改 strong_vol_min 8000→歷史一致性分改變）、安全邊際 label（改 band 切點→顏色改變）、建議動作（改 _ACTION_MATRIX→動作改變）、移出旗標（改 1.12→旗標翻轉）——**全部 C11-positive（含別處未落地的判斷參數）**；一致性軸更是 source（raw sell-side）本身不在 snapshot → 純新 O。
    - confidence：confidence/risk_score/profile_code/temperature 全含 code-only 權重與門檻 → **全部 C11-positive**。但需與 §3-7/8 並讀：confidence 的因子**大量重複計入 sm/golden 已落地或已算過的判斷**——C11-positive 不等於「該獨立落地」，可能是「不該存在的重複軌」（留 §5）。
13. **輸出面：dataclass 欄 vs 落地**：
    - distribution `DistributionEntry` 20 欄（§0）vs canonical snapshot 落地＝0；sidecar distribution.json 落地＝0 份（§3a）。
    - confidence `ConfidenceProfile` 24 欄 vs canonical snapshot 落地＝0；per-ticker confidence 值經 intelligence.json 落地（sidecar，pipeline 寫，含 biggest_confidence_changes/watch_list/risk_alerts）；`market_temperature` **不進 intelligence.json**（實測 temperature:0）→ 溫度純 render-time。
14. **消費者清單（輸出證據，渲染歸 S08、内部歸各 session）**：
    - distribution：`viewer/cockpit.py`（唯一，且因 0 檔案實際不顯示，§3a）。**無其他消費者**。
    - confidence：`viewer/cockpit.py`（市場溫度 banner＋多空體檢表＋watch_list，render-time）、`core/intelligence_delta.py`（`_conf.run` → confidence_upgrade/downgrade 事件＋temperature_change 事件＋biggest_confidence_changes，:369-392,475-490,517-556；**其輸出 intelligence.json 由 pipeline 落地**）、`viewer/cockpit_v2.py`（NOTES #7 死碼）。
    - 時序輸出標 C10：confidence `deteriorating`（§2，路徑依賴）；distribution 一致性/安全邊際皆單日、無跨快照時序（distribution.run 只吃單 date）→ **distribution 無 C10 面**（它的「歷史」是逐日獨立重算，非路徑依賴推演）。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：Observation-First / snapshot=SoR（NOTES #10）、扁平前綴、additive+alias。）

**distribution 引擎的理想邊界：**
- **輸入**：賣方 raw（sellList/mainForceSell 等）**應先經 ingest 落入 canonical snapshot**（賣方資料進 schema），distribution 純讀落地欄位；安全邊際續讀已落地 current_price/main_force_cost。
  - 差距：現況一致性軸繞過 snapshot 直讀 `_raw_archive`（§3-6）——這是 docstring 刻意的 sidecar 設計，但代價是一致性分的 source 不在 SoR、落地時無 replay 譜系。**賣方 raw 併入 schema 是 distribution 落地的前置**（屬 S05 registry／C7 非破壞性 ingest 範圍）。
- **輸出**：distribution **自產的 O**（consistency_score/grade、safety_label）**必落 snapshot**（若確認保留該引擎）；行動語意（suggested_action/flagged_for_removal）＝**進場行動判斷**（同 S01 action_group 性質）——是判斷、必落，但需先釐清它與 golden action_group 的關係（兩套成本容忍閾值 1.12 vs 1.05、兩個「移出/等回檔」語意是否該統一）。
  - 差距：現況 20 欄零落 canonical＋sidecar 空（§3a/13）；建議動作偽裝 display-only（§3-4/5）。
- **絕不做**：(i) 不自產顯示字串（color→S08 映射）；(ii) **不對 golden 名單下「移出」指令語意**——若「風險否決」是真需求，該是 golden 消費 distribution 的一個落地 O 因子（core 組裝，C8），不是 distribution 旁路輸出一個 viewer 直接顯示的建議；(iii) 一致性軸的 source 不該永久停在 archive 旁路。
  - **存廢懸置**：distribution 目前**部署中完全不顯示**（§3a）——「保留並修正落地鏈」vs「本就是未完成/已擱置的實驗層」是先於落地清單的問題，留 §5。

**confidence 引擎的理想邊界：**
- **輸入**：只吃已落 snapshot 的 O（golden tier/conviction、sm state/transition_risk、breadth、sector rank），不 render-time 重跑四引擎。
  - 差距：現況純二階聚合、四引擎全 render-time 重算（§2）。
- **輸出**：**此處是本 session 最需裁的存廢題**——confidence 的信心軸重疊 golden conviction（§3-8）、風險軸重疊並 double-count sm transition_risk（§3-7），且 61% 標的 risk_score 塌到 0（§3-9）。理想態下 confidence 若保留，應是**「把已落地的 conviction/transition_risk 兩個既有 O 組成 2D 座標的純派生視圖」（C9 不落）**，而非**自己重算一套權重疊加、產生與上游分歧的第三/第二個分數**（C11-positive 的重複軌）。
  - 差距：現況 confidence 有獨立權重（§3-11/12），改權重會無痕改變信心/風險意見，卻與 golden/sm 各說各話。
- **絕不做**：(i) 不重複計入 sm 已消化的因子（velocity/accel/streak 不該既進 sm base 又進 confidence 疊加）；(ii) 不產與 sm transition_risk 同名但不同值的第二個 4 級 risk_level；(iii) market_temperature（市場級聚合）與 per-ticker profile 是**兩種 grain**，不該混在同一引擎 dataclass 契約（temperature 可能屬 market_state/S07 家族）。

---

### NOTES #12 列舉義務：兩引擎哪些欄位屬「契約級 observation」候選

準則（S05 RC-1）：呈現或被 backtest 消費 → 必落；純派生（C9）/重複軌不必落；時序引 C10。取捨（含**兩引擎存廢**）留 §5。

**distribution（obs_dist_*）候選：**
| # | 現欄 | 建議命名 | C 分類 | 理由 |
|---|---|---|---|---|
| 1 | consistency_score/grade | `obs_dist_consistency` | C11-positive**真新 O** | 源自 raw 賣超榜（不在 snapshot），改門檻無痕改歷史；但前置＝賣方 raw 先入 schema |
| 2 | safety_margin/label | `obs_dist_safety_margin` | C11-positive（band 是判斷參數） | =current_price/main_force_cost（可派生），但 band 切點 code-only→改切點改歷史 label |
| 3 | suggested_action | `obs_dist_action`? | **行動判斷（#27）** | 若引擎保留＝進場行動 O 必落；但需先解與 golden action_group 的重疊 |
| 4 | flagged_for_removal | — | **爭議** | 對 golden 名單的否決語意；該不該存在＝§5 先於落地 |

**confidence（obs_conf_*）候選：**
| # | 現欄 | 建議命名 | C 分類 | 理由 |
|---|---|---|---|---|
| 1 | confidence/band | `obs_conf_confidence`? | **重疊 golden conviction** | 是新分還是 conviction 的再包裝＝§5 |
| 2 | risk_score/risk_level | — | **重疊 sm transition_risk（double-count）** | 與 sm 同名 4 級、值分歧；雙軌存廢＝§5 核心 |
| 3 | profile_code（2D） | `obs_conf_profile`? | 可能 C9 純派生 | 若信心/風險都改讀既有 O，profile=兩軸純派生視圖→不落 |
| 4 | market_temperature | — | 市場級、grain 不同 | 可能屬 S07 market_state 家族；已部分入 intelligence.json 差分 |

→ **候選數**：distribution 4、confidence 4（合 8）；但**與前四 session 不同，本 session 多數候選的前置是「存廢裁定」而非「落地命名」**——distribution 整層在部署中不顯示（§3a）、confidence 兩軸疑為重複軌（§3-7/8）。**取捨前三名（最需 §5 定調）**：① confidence 雙軌 risk 存廢（obs_conf risk vs sm transition_risk）；② distribution 整層存廢（活 code 死輸出）；③ 兩引擎的行動/否決語意（suggested_action、flagged_for_removal、profile deteriorating）與既有出口的協調（#32 第 4/5 出口）。

---

## §5 裁定（待 fable 裁定）

---

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES：本 session 新發現於 §3/§4 就地標歸屬（distribution 持久化雙重死區→本 session／S08；行動語意→#27；雙軌 risk→NOTES #33 指定；weakening 第 4/5 出口→#32/S08；門檻治理→#33 引用；賣方 raw 入 schema→S05/C7）。蒐證階段不預先 append，待 fable 裁定後由裁定者決定入 NOTES 條目。
- [x] 00-INDEX 狀態列已更新（S03：證據包完成，待 fable 裁定；報告連結 `sessions/S03-distribution-risk.md`）
- [x] 未執行任何 code/schema 改動
