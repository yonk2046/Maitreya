# Session 08 — Frontend Presentation（前端呈現層）（證據包）

> 證據蒐集（opus 2026-07-10）。裁定者只讀本報告＋CROSS-SESSION-NOTES。
> 鐵律：先分析、後才談改；本報告不含 code/schema 改動；證據一律附 `檔案:行號`。§5 留空待 fable。
> 本 session 是**收割 session**：前 7 個 session 大量指名 S08 的事項在此一次盤點。涵蓋 `viewer/cockpit.py`（3,911 行主前端）、`viewer/cockpit_v2.py`（1,234 行棄置平行前端）、`viewer/app.py`（797 行工程診斷 viewer）、`viewer/metrics.py`（320 行觀察指標）、`core/intelligence_delta.py`（965 行 sidecar 產出）＋ i18n/色彩/標籤住引擎全盤。
> 承接（全部前 session 指名 S08 的事項）：NOTES #2（薄化後 viewer 邊界）、#6（連買/在榜/窗 詞彙複查）、#7（cockpit_v2 刪否）、#24（C8 組裝權違例現行犯 cockpit.py:2672-2680）、#32（轉弱統一標籤＝跨引擎組裝依 C8 必 core 派生）、#36（元大金呈現區隔：顯示性徽章 vs 資格判斷）、#38（intelligence.json sidecar 稽核＝SoR 違憲嫌疑）、#40（市場 banner 三重語意收斂後呈現）、i18n 住引擎 8 例登記。
> 已鎖決策（不重議，NOTES #9-11）：扁平前綴 domain、additive+alias、Observation-First / snapshot=SoR、三態 I/O/M、grain 是契約一級維度（#42）。
> 落地清單前提：已核准 17 欄（obs_golden_* 六、obs_sm_* 六、obs_chip_grade/total/sync_streak 三、obs_dist_consistency 一、obs_market_regime/breadth/temperature 三 = **累計 17**）；薄化後 viewer 理論上只讀這些＋raw 欄位做映射。

---

## §0 範圍與輸入

**只看（Presentation 層）：**
- `viewer/cockpit.py`（主前端）：引擎 import（:46-53 九個 core 引擎）、render-time 呼叫、7 tabs（:3819-3827）、golden 大函式（:1884-2917）、regime（:635-725）、confidence（:3054-3327）、intelligence sidecar 消費（:3329-3433）、市場脈搏 banner（:498）、checklist_history 磁碟寫入（:2076-2137,2811-2816）。
- `viewer/cockpit_v2.py`（:1-1234）：header（:1-13）、引擎 import（:31-43）。
- `viewer/app.py`（:1-797）：header（:1-59）＝工程診斷 viewer。
- `viewer/metrics.py`（:1-320）：純觀察指標（docstring :1-11「NO scoring. NO ranking.」）。
- `core/intelligence_delta.py`（sidecar 產出）：docstring 契約（:1-22）、generate（:737-851，re-run 三引擎＋persist）、load_for_date（:854）、pipeline 產出（tools/daily.py:381-393）。
- i18n/色/HTML 住引擎：13 個 core 檔（見 §3-f）。

**實跑驗證（真磁碟）：**
```
disk reports/*.json（regular snapshot）      → 45 份
disk reports/*.intelligence.json（sidecar）  → 33 份
cockpit.py import core 引擎                    → 9 個（golden/confidence/state_machine/resonance/chip_score/holdings/distribution/intelligence_delta/market_context+narrative）
cockpit.py 磁碟寫入路徑                        → 2 個（checklist_history.json:2089、sidecar generate button:3347-3351）
cockpit_v2.py git commit 數                    → 1（init only，NOTES #7 復現）
i18n/色/emoji 住 core 引擎檔數                 → 13/18 core 檔含 hex/ZH label/emoji/HTML
Makefile viewer 目標                          → make viewer=app.py:8501 / make cockpit=cockpit.py:8502 / cockpit_v2=:8503
```

**明確不看（留給哪個 session）：**
- 各引擎**內部演算法**本體 → 已由 S01-S04/S07 分別裁定；本 session 只查 viewer 如何**消費/組裝/搬運/重算**其輸出。
- 欄位命名正本 / registry / grain 欄 → S05；replay 等級 / sidecar 是否入 replay → S06；backtest 對前端無關 → S09。
- distribution 引擎存廢 → S03 已裁（#38）；本 session 只查 viewer 對 distribution 的 disk-load 消費（cockpit.py:1902-1905）。

---

## §1 這一層真正要回答什麼問題？

**Presentation 層要回答的唯一問題是：「把已經算好的 observation，翻譯成使用者能在 30 秒內做決定的畫面」——它是 snapshot（System of Record）的『閱讀器』，不是判斷的生產者。** 使用者拿它做的決定：今天出不出手（regime banner）、買哪幾檔（進場機會 tab 的 golden 名單＋可買進/等回檔分組）、賣哪幾檔（出場警示 tab 的轉弱/假突破）、盯哪幾檔（潛力區/龍頭雷達）、單檔放大體檢（個股顯微鏡）。7 個 tab（cockpit.py:3819）就是這些決定的 7 個入口。

理想定位：**Presentation 是「非資料層」（NOTES #11：六層映射裡 Presentation→非三態）**——它不該擁有任何「改參數會無痕改變歷史意見」的東西（C11 測試）。它的合法動作只有兩種：**(i) 映射**（把落地的 obs_* 欄位配色/配標籤/配 emoji/配版面）、**(ii) 純派生視圖**（把已落地欄位做 C9 純函數重標籤，如 display_tier）。它絕不該做的：組裝跨引擎判斷（C8）、render-time 重算判斷（NOTES #2）、寫任何持久化狀態。

**現況與此定位嚴重背離**：cockpit.py 是一個「把九個判斷引擎在 render-time 重跑一遍、自己組裝跨引擎判斷、還往磁碟寫兩種持久化狀態」的**平行判斷生產者**，只是恰好也負責畫畫面。這是 §3 全部病灶的根源，也是 NOTES #2「UI==snapshot 結構性不成立」在呈現 grain 的完整發作。

---

## §2 它屬於哪一層？

用三態 I/O/M（NOTES #11）＋六層作答。Presentation 本身＝非資料層；但 cockpit.py 現況橫跨多層。逐項列：

| cockpit.py 的動作 | 應屬層 | 現況實屬 | 證據 | 診斷 |
|---|---|---|---|---|
| regime banner 配色/配標籤 | **Presentation**（映射） | 映射，但**色來自引擎** | :640-683 讀 `reg["regime_color"]`＋bg_map | 半合法：映射對，但色住 market_context（§3-f） |
| golden 卡片版面/emoji/星級 | **Presentation**（映射） | 映射，但 icon/color/zh 全來自 golden.py | :2272-2277 讀 `_golden_mod.DTIER_*` | 半合法：display_tier 是 C9 純派生（合法），但配色住引擎 |
| `action_group(e, weakening_severity)` 呼叫 | **不該做**（C8 組裝） | **viewer 搬運 weakening→golden** | :2670-2675＋golden.py:740 | 🔴 C8 違例現行犯（NOTES #24） |
| render-time `_golden.run`/`_sm.run_all`/`resonance.run_all`/`_conf.run`/`chip.compute`/`regime_shift`/`weakening_profile` | **不該做**（判斷生產） | **viewer 重跑九引擎** | :1891-1893,2369,3061,640,1927 | 🔴 NOTES #2 呈現 grain 發作 |
| checklist_history.json 寫入 | **不該做**（Presentation 不落地） | **viewer 產出持久化狀態** | :2089,2811-2816 | 🔴 viewer 是第 4 個持久化寫入點 |
| sidecar generate button | **不該做**（UI 觸發引擎＋寫檔） | **viewer 可 render-time 產 sidecar** | :3347-3351 | 🔴 UI 寫判斷入磁碟 |
| intelligence.json 消費（new_today/market_story/risk） | **Presentation**（讀 sidecar） | 讀一個**平行 SoR** | :1953,2739,3335 | 🔴 sidecar SoR 違憲（§3-d/#38） |
| 量能比 render-time 計算 | **Derived**（本應落地） | viewer 現算 | :2387-2400 | 復現 NOTES #2/#4（volume 家族） |
| app.py / metrics.py | **Presentation**（純讀）＋**Observation**（純函數） | ✅ 名實相符 | metrics.py:1-11 明文無 scoring | 唯一乾淨的呈現層 |

**分層小結**：Presentation 層裡真正「純映射/純派生」的部分是健康的（regime banner、display_tier、app.py/metrics.py）；病灶全部集中在 cockpit.py **越界做了三件非呈現的事**：組裝跨引擎判斷（C8）、render-time 重算判斷（NOTES #2）、寫持久化狀態（第 4 個落地點）。這三件事讓「畫面 == snapshot」在結構上不可能成立——因為畫面上的判斷根本不在 snapshot 裡，是 viewer 當場算的。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 一致；「＋新增」＝本輪新發現。

### (a) 【C8 違例現行犯】viewer 搬運 weakening 判斷進 golden 行動函式（🔴 C8，✔ 復現 NOTES #24）

1. **cockpit.py:2670-2675 把 viewer 自算的 weakening severity 當參數餵進 `golden.action_group`**：
   ```
   action_of = {e.ticker: _golden_mod.action_group(e, weak_map.get(e.ticker, {}).get("severity", "none")) ...}
   ```
   `action_group(entry, weakening_severity)`（golden.py:740-768）的 WEAKENING 分組**依賴呼叫方傳入 weakening**（golden.py:754 `if weakening_severity == "red" or entry.sm_state == "distributing"`）。→ **golden 自己拿不到 weakening，靠 viewer 當「配線工」把 mc 的 weakening 搬進 golden**。這正是 C8（NOTES #24）：「跨引擎判斷的組裝屬 core 生產者、輸出必落地；presentation 不組裝、不搬運判斷輸入」的現行犯。
   - 加重：`weak_map` 本身是 viewer 組的（:1918-1929）——先讀 snapshot 的 `weakening` 欄，**缺欄時 render-time fallback 呼叫 `weakening_profile(_t, snaps, ...)` 現算**（:1927）。所以 viewer 不只搬運，還在 severity 缺資料時**當場重算 weakening 判斷**。
   - 同函式 `display_tier(e, weakening_severity)`（cockpit.py:2678-2680、golden.py:788+）同型：viewer 搬 weakening 進 display_tier。display_tier 本體是 C9 純派生（合法），但它的 weakening 輸入靠 viewer 配線＝C8 違例。

### (b) 【NOTES #2 呈現 grain 發作】viewer render-time 重跑九個判斷引擎（🔴 架構根病，✔ 復現 NOTES #2）

2. **cockpit.py import 九個 core 引擎（:46-53）並在 render-time 全跑一遍**：`_golden.run`（:1891）、`_sm.run_all`（:1892）、`resonance.run_all`（:1893）、`chip.compute`（:2369，per-card）、`_conf.run`（:3061）、`regime_shift`（:640）、`weakening_profile`（:1927,1192）、`leadership_rotation`（:1441）、`full_ticker_context`（:1075,1293,1361,1590）。→ **畫面上每一個判斷（tier/state/共振/籌碼分/信心/體制/轉弱/輪動）都是 viewer 當場算的，snapshot 裡沒有**（P3a：tier 全 IGNORE、composite_score 全 0，NOTES #2 實測）。
   - 後果：**「UI == snapshot」結構性不成立**——replay 覆蓋的是 snapshot 裡的 raw/stub，畫面顯示的判斷全在 replay 邊界外。這是 17 欄落地要解的核心（落地後 viewer 改讀，不再重算）。
   - 量能比同病（:2387-2400，render-time 從 snapshot history 現算 vol_ratio）：復現 NOTES #4（volume 家族）＋NOTES #2。

3. **雙實作漂移風險：viewer 重算的判斷 vs 落地欄位/sidecar 三方可能不一致**。同一個 golden.run 被三處各跑一次：cockpit.py:1891（畫面）、intelligence_delta.py:768/782（sidecar today+yesterday）、且未來落地欄位是第三份。→ 承接 S02 #36「雙實作漂移＝第四次確認的系統病」，本 session 坐實**第 9 例（呈現層 vs sidecar 同引擎各跑）**。

### (c) 【viewer 產出持久化狀態】cockpit 是第 4 個磁碟寫入點（🔴 落地越界，＋新增）

4. **cockpit.py 往磁碟寫兩種持久化狀態，且都不在 snapshot/replay 邊界內：**
   - **checklist_history.json**（:2076 路徑、:2089 `write_text`、:2811-2816 每次 render 最新日就寫）：一個「learning layer」——記錄每檔 golden 的 checklist 通過狀態＋「隔日是否還在列」（still_active），並算留存率顯示（:2124-2137「留存率 {pct}%」）。→ **這是 viewer 自產的判斷型持久化狀態**：still_active 是跨快照的路徑依賴判斷（C10 領域），卻由 viewer 在 render-time 累積寫檔，不落 snapshot、不入 replay、不受 hash 保護。改看哪一天 = 改寫這個檔。
   - **sidecar generate button**（:3347-3351）：`_render_intelligence` 在 sidecar 不存在時給一顆「⚡ 立即生成本日情報」按鈕，點下去 render-time 呼叫 `intelligence_delta.generate()`（re-run 三引擎＋write_text sidecar）。→ **UI 可觸發判斷生產並寫入磁碟**——presentation 層寫判斷入持久化，最直接的越界。
   - → viewer 是繼 ingest/archive/intelligence_delta 之後的**第 4 個持久化寫入點**，且是唯一「render-time、由使用者互動觸發」的寫入點。

### (d) 【sidecar 稽核 NOTES #38】intelligence.json ＝平行 System of Record，含判斷、re-run 已廢引擎（🔴 SoR 違憲，✔ 復現＋加重 NOTES #38）

5. **intelligence.json sidecar 是一個「自稱不可變事件檔案、卻在 canonical snapshot 之外、不受 hash/replay 保護」的平行 SoR**：
   - docstring 自我定位（intelligence_delta.py:3-11）：「immutable DailyIntelligenceReport」「self-contained event archive for that trading day」——**宣稱是權威事件檔案**。
   - 但它 write 到 `reports/<date>.intelligence.json`（:752,847），**與 canonical `reports/<date>.json` 平行、獨立 `generated_at`（:824）、不入 canonical_sha256、不入 replay verify**（S06 verify_all_replay 只查 canonical）。→ **兩個競爭的 SoR**：canonical snapshot（WORM/hashed/replay-verified）vs sidecar（自產 generated_at、無 hash、無 replay）。sidecar 有 SoR 的「招牌」（immutable archive），沒有 SoR 的任何保證。
6. **sidecar 的內容是 re-run 引擎產出的跨快照判斷，非 raw**：generate（:768-803）**re-run golden/confidence/state_machine 於 today 與 yesterday 兩窗**（:768-770,782-784），再 diff 出 golden_entry/golden_exit/state_transition/confidence_upgrade/risk_elevation/temperature_change 等**判斷型事件**（:793-803）。→ 這些事件在 17 欄落地後多數是 **C9 純派生**（diff 兩份落地 snapshot 即得），現況卻靠 sidecar re-run＋持久化＝第三份判斷複本。
7. **sidecar re-run 的是 S03 已判死的 confidence 引擎**（🔴 加重）：`_conf.run`（:769,783）＋ `market_temperature`（:787,800）。S03 #37 已裁 confidence 降級為派生視圖、risk_score 廢除。sidecar 的 `confidence_upgrade`/`confidence_downgrade`/`risk_elevation` 事件（:53-57）全建在已廢引擎上，還在 UI 顯示（cockpit.py:3015-3019「多頭分上升/警訊分上升」）。
8. **sidecar 已知 dead consumer 未修**（承接 NOTES #43）：`breadth_milestone` 事件因 intelligence_delta 用錯 key 讀 null stub 永不觸發（S07 §3-5/NOTES #43）。→ sidecar 稽核加重證據：一個含永不觸發死事件、re-run 已廢引擎、平行 SoR 招牌的持久化 artifact。
9. **sidecar 是「顯示關鍵判斷」的唯一來源**：cockpit.py:1953-1955 從 sidecar 的 `new_today` golden_entry 事件決定「哪些是今日新進名單」（畫面上獨立 render 的一區）；:2739 market_story、:3335 全 tab。→ 一個 SoR 保證為零的 sidecar，是「新進名單」這個顯示判斷的唯一真值源。

### (e) 【死碼】cockpit_v2.py＝1 commit 棄置平行前端（🟡 死碼，✔ 復現 NOTES #7）

10. **cockpit_v2.py（1,234 行）git commit 數 = 1（init only）**，之後零 commit；import 同一批 core 引擎（:31-43，同樣 render-time 重算）。→ 復現 NOTES #7「另建乾淨前端」路線的既有失敗案例，與 market_state.py（#40）、distribution 死輸出（#38）同型的**第 9/10 個死平行實作**。
   - **加重（＋新增）**：Makefile 仍保留啟動目標（Makefile:54,58 跑 cockpit_v2.py:8503）——不是完全孤兒，有 launch path 但無維護、無資料驗證。「棄置但可啟動」比純死碼更危險（可能被誤當有效替代品）。

### (f) 【i18n/色/HTML 住引擎】完整盤點：13/18 core 檔含呈現內容，引擎直接吐 HTML（🔴 呈現洩漏 core，＋新增完整清單）

11. **色彩/ZH label/emoji/HTML 住 13 個 core 引擎**（前 session 登記「8 例」，本輪給完整清單）：
    | core 檔 | 呈現內容證據 | 型別 |
    |---|---|---|
    | golden.py | TIER_COLOR（:97-100）、ACTION_META icon/zh/en/color（:712-715）、DTIER_ZH/EN/COLOR/ICON（:784-787） | hex+emoji+雙語 |
    | state_machine.py | STATE_COLOR 10 色（:144-154）、RISK_COLOR（:173+）、STATE_ZH「轉強/疑似出貨」（:122-124） | hex+ZH |
    | chip_score.py | GRADE 色（:69-71）、grade_color（:82）、**engine 直接吐 `<span style=...>` HTML**（:105-107） | hex+**HTML** |
    | confidence.py | 溫度色/level ZH（S07 已查） | hex+ZH |
    | market_context.py | regime_color/label_zh/label_en（:402-424）、weakening label_zh/en（:776） | hex+雙語 |
    | resonance.py | 星號/色（15 處 grep 命中） | hex+符號 |
    | market_state.py | 四 Condition LABELS/COLORS（死碼，#40） | hex+ZH |
    | sector_intelligence.py | 57 處色/label 命中 | hex+ZH |
    | distribution.py | 32 處（已判死，#38） | hex+ZH |
    | intelligence_delta.py | 事件 label 映射（37 處） | ZH |
    | funnel.py / holdings.py / narrative_engine.py | 色/label/emoji | 混合 |
    → **`chip_score.py:105-107` 是最嚴重的一例：observation 引擎直接產出 `<span style="color:{grade_color}">` HTML 字串**——引擎連 markup 都吐了，Presentation 與 Observation 完全焊死。
12. **viewer 反向硬編碼引擎的色盤**：cockpit.py:644-652 的 `bg_map` 把 market_context 吐的 regime hex 色（#52B788 等）映射成背景 hex 色。→ 引擎吐前景色、viewer 查表配背景色＝**雙向色彩耦合**：改引擎色盤要同步改 viewer bg_map，否則配色崩。若 regime 只吐 label（純分類），viewer 可獨佔全部配色決定。

### (g) 【詞彙層複查】轉弱/連買/在榜/元大金徽章（承接 #6/#32/#36）

13. **「轉弱」對外標籤有三個獨立來源、未收斂（承接 NOTES #32）**：
    - `weakening_profile`（market_context.py:776）吐 "轉弱"（orange severity）；
    - state_machine S_DISTRIBUTING 吐 "疑似出貨"（:124）；
    - golden ACTION_WEAKENING 吐 "動能轉弱"（golden.py:715，來源＝weakening RED **或** SM distributing）。
    - viewer 端 UI 出現：「轉弱出貨」header（cockpit.py:1199）、「🟠 轉弱」（:1222，來自 weakening_profile）、「🔻 動能轉弱」（:2714，來自 action group）、「疑似出貨」state badge（:1939）。
    → S04 #32 已裁「weakening→distributing→transition_risk 是健康分層，不合併；但若產品要**單一對外『轉弱』標籤**＝跨引擎組裝＝依 C8 必須 core 派生欄位，viewer 不得組裝」。**現況正是 viewer 在組裝**：golden action_group 把 weakening(mc)＋distributing(sm) 合成「動能轉弱」一個顯示分組，而 golden 靠 viewer 配線 weakening（§3-a）。→ 統一「轉弱」標籤若要，須 core 派生 obs 欄，非 viewer 拼。
14. **「連買/在榜/窗N」詞彙已大致正名，殘留一處新歧義（承接 NOTES #6）**：
    - strict streak → 「連買{n}日」（cockpit.py:787,934,1095,2009）；
    - window buy → 「窗口買(日)」「窗口累計」（:1096,1268）；
    - appearance streak → 「連續在榜{n}日」（:1791，已正名，NOTES #6 commit a2037a0 復現）；
    - **新歧義（＋新增）**：checklist_history 的 still_active 顯示為「持續在列 {n}」「留存率」（:2135）——第 4 個「連續」語意（黃金名單留存），與「連買/在榜」易混，且來源是 §3-c 的 viewer 自產持久化狀態。
15. **元大金：顯示性徽章 vs 資格判斷未區隔（承接 NOTES #36，＋坐實）**：`is_tier_a` 同時是**顯示徽章**（cockpit.py:1101「Tier A: ★」、:2196「屬 Tier-A 核心標的」）**與資格/計分輸入**：golden.py:279-280 `if is_tier_a: breakdown["tier_a"] = 0.10`——Tier-A 名單身分**直接加 0.10 conviction**。→ NOTES #36 問的「顯示性徽章 vs 資格判斷視覺區隔」，更深的病是**兩者根本沒分**：一個「人工維護的觀察名單」（元大金在 TIER_A）同時驅動一顆 cosmetic ★ 和一個 +0.10 的評分判斷。這是**顯示集合洩漏進資格計分**（與 S01 RC-8「資格 vs 行動分離」同精神，本例是「顯示 vs 資格」未分離）。

### (h) 【S03 已判死引擎仍在 UI 全渲染】confidence 多空體檢（🔴 承接 S03，＋新增）

16. **cockpit.py 個股顯微鏡 tab 仍完整渲染 S03 已判死的 confidence 引擎**：`_render_confidence`（:3054）render-time `_conf.run`（:3061），顯示「多頭分/警訊分」（:2924-2925,2958-2959）、temperature banner、`deteriorating` 分群（:3072，profs 含 result.deteriorating）。S03 #37 已裁：獨立 risk_score/confidence 分數**廢除**、deteriorating**廢**、「多頭分/警訊分」改為 obs_golden_conviction/obs_sm_transition_risk 的呈現映射。→ 現況 viewer 不但沒改映射，還 render-time 重跑整個死引擎並顯示已廢的 deteriorating 分群。**薄化的最大單一工作量**在此 tab。

### (i) 【唯一乾淨的呈現層】app.py/metrics.py 名實相符（✅ 非病灶，＋新增為對照）

17. **app.py（工程診斷 viewer）＋metrics.py（觀察指標）是全前端唯一名實相符的部分**：metrics.py docstring（:1-11）明文「NO scoring. NO ranking. NO trading signals. All functions are pure (no side effects)」；app.py header（:8,57）明文「Read-only. Replay-safe. No scoring. No AI generation.」「All scoring is currently abstained. No writes happen here.」→ 它只讀 snapshot 做連續性/streak/audit/lookback 的**純觀察投影**，零判斷、零寫入。**這是 §4 理想態的既有樣本**：一個真正只映射的呈現層長什麼樣，repo 裡已經有。
   - 注意：metrics.py:147-171 `tier_transitions` 明文「At P3a every tier == IGNORE so this returns an empty list」——復現 NOTES #2（tier 全 IGNORE），且誠實標示（不偽稱有資料）。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：Observation-First / snapshot=SoR、17 欄已落地、扁平前綴、grain 一級維度。）

**Presentation 層的理想邊界：**

- **輸入＝落地的 obs_* 欄位＋raw 欄位；輸出＝畫面；絕不做判斷**。薄化後的 cockpit 對每個判斷只做兩種事：**(i) 映射**（obs_golden_tier → 配色配星級配版面）、**(ii) C9 純派生視圖**（obs_golden_conviction + obs_sm_transition_risk → display_tier「可買進/增強/中」）。所有 `_run_golden/_run_sm/resonance.run_all/_conf.run/regime_shift/weakening_profile/leadership_rotation` 的 render-time 呼叫**刪除**，改讀 snapshot 的 obs_* 欄。
- **絕不做（四條紅線）**：(i) 不 render-time 重跑任何判斷引擎（§3-b）；(ii) 不組裝/搬運跨引擎判斷（§3-a，action_group 的 weakening 配線移入 core，golden 落地 obs_golden_action_group 已含 weakening）；(iii) 不寫任何持久化狀態（§3-c，checklist_history 若有價值＝跨快照 C10 判斷→歸 core 落地 obs 欄，非 viewer 寫檔；sidecar button 移除）；(iv) i18n/色/HTML 不住引擎（§3-f，obs 欄只帶語意 key，viewer 或一個 presentation 映射表獨佔配色/雙語/emoji）。
- **色彩/i18n 單一擁有者**：引擎輸出**語意 enum**（如 `regime="cautious_bullish"`、`state="distributing"`），不吐 hex/emoji/HTML。一張 presentation 映射表（住 viewer 或獨立 i18n 模組）把 enum → (zh, en, color, icon)。差距：現況 13 個引擎各吐各的色，chip_score 甚至吐 HTML；viewer 還反向硬編碼引擎色盤（bg_map）。
- **sidecar 的去留（§3-d／NOTES #38）**：17 欄落地後，intelligence.json 的 golden_entry/exit/state_transition 等事件**多數變 C9 純派生**（diff 兩份落地 snapshot 即得），不需持久化第三份判斷複本。理想態：**要嘛 sidecar 廢除**（事件 render-time 從落地 snapshot 序列純派生）、**要嘛 sidecar 收編進 canonical**（若「當日事件檔案」是真需求＝C10 as-was 紀錄，則落 snapshot 頂層、受 hash/replay 保護，不當平行 SoR）。現況「平行 SoR 招牌＋無保證＋re-run 已廢 confidence」三者不可並存。
- **元大金/Tier-A（§3-g／NOTES #36）**：顯示徽章（★ 觀察名單成員）與資格計分（+0.10 conviction）**分離**——is_tier_a 若是計分輸入，屬 golden 資格判斷（落地 obs_golden 的 breakdown）；★ 徽章是 viewer 純映射「此檔在人工觀察名單」。兩者不共用同一個「洩漏進計分的顯示集合」。

**cockpit_v2 / app.py / metrics.py 各自去留（證據面，不裁定）：**
| 檔 | 證據 | 去留傾向（證據，非裁定） |
|---|---|---|
| cockpit_v2.py | 1 commit、零維護、render-time 重算同病、Makefile 仍掛啟動目標 | 死碼；隨 market_state（#40）/distribution（#38）同批處決的候選（NOTES #7 判例） |
| app.py + metrics.py | 名實相符、純讀、零寫入、零 scoring（§3-i） | 保留；是理想呈現層的既有樣本，薄化 cockpit 的參照對象 |
| cockpit.py | 3,911 行、九引擎 render-time、C8 違例、2 磁碟寫入、re-run 已廢引擎 | 薄化 vs 重寫＝§4 核心懸置（下） |

**「重寫 vs 薄化」cockpit.py 的證據面（列證據，不裁定）：**
- **支持薄化的證據**：(i) 主結構健康——7 tab 分工清楚（進場/潛力/出場/市場/顯微鏡/持倉/績效）、版面/CSS 成熟、使用者驗證過的產品語意（regime banner、可買進/等回檔）；(ii) 病灶是**可定位的**：九個 render-time 引擎呼叫（§3-b 列出行號）、2 個磁碟寫入（§3-c）、C8 配線（§3-a）——薄化＝把這些逐點換成讀 obs_* 欄，不動版面；(iii) app.py/metrics.py 已示範乾淨映射長什麼樣，有現成模式可套。
- **支持重寫的證據**：(i) cockpit_v2 已是「另建乾淨前端」的失敗前例（§3-e）——重寫路線在本 repo 有一次 1-commit 死亡紀錄；(ii) 3,911 行裡判斷邏輯與呈現邏輯高度纏繞（如 golden 大函式 :1884-2917 一千行內混 checklist 判斷/history 寫入/action 組裝/卡片 render）；(iii) 但重寫要先有 17 欄落地，否則新前端一樣得 render-time 重算＝重蹈 cockpit_v2 覆轍。
- **關鍵前置（兩路線共用）**：無論薄化或重寫，**都依賴 17 欄先落地**——在落地前，任何前端都被迫 render-time 重算判斷（因 snapshot 只有 raw/stub）。故「前端怎麼改」在時序上**必然晚於 S01-S07 的落地遷移**；本 session 的證據支持「落地遷移完成前不動前端結構，只凍結現況待薄化」。

**與現況差距總表：**
| 面向 | 現況 | 理想 |
|---|---|---|
| 判斷來源 | viewer render-time 重跑 9 引擎 | 讀落地 obs_* 欄 |
| 跨引擎組裝 | viewer 配線 weakening→golden（C8 違例） | core 生產者組裝＋落地 |
| 持久化寫入 | viewer 寫 checklist_history＋sidecar button | 零寫入（C10 判斷歸 core 落地） |
| i18n/色/HTML | 住 13 個引擎，chip_score 吐 HTML | 引擎吐語意 enum，presentation 獨佔配色 |
| sidecar | 平行 SoR、re-run 已廢 confidence | 廢除（C9 純派生）或收編 canonical |
| Tier-A 徽章 | 顯示集合洩漏進 +0.10 計分 | 徽章映射與資格計分分離 |
| confidence 多空體檢 | render-time 重跑已判死引擎 | 映射 obs_golden_conviction/obs_sm_transition_risk |
| 死碼 | cockpit_v2 掛 Makefile 目標 | 處決（NOTES #7 判例） |

---

### NOTES #12 列舉義務：Presentation 層無新落地欄位（本 session 特性）

**Presentation 是非資料層（NOTES #11），不產生任何 obs_* 落地候選欄**——它的產物是畫面，不是 observation。本 session 對「落地清單」的貢獻是**反向的**：指出哪些 viewer 現在自產的東西**應由別的 session 的引擎落地後 viewer 改讀**：

| viewer 現自產 | 應由誰落地 | C 分類 | 依據 |
|---|---|---|---|
| action_group（配線 weakening） | golden 落 obs_golden_action_group（已核准六欄含 action_group） | C8 | S01 #24/#26 |
| weakening 顯示（render-time fallback 重算） | mc 落地、sm 落 obs_sm_state | C8/C10 | S04 #30 |
| 共振星號 | 不落（≡fii_sync_count，S02 #35） | C9/C11 | S02 |
| 籌碼分卡片 | chip 落 obs_chip_grade/total（已核准） | C11 | S02 #35 |
| 多頭分/警訊分 | obs_golden_conviction + obs_sm_transition_risk 呈現映射 | C9 | S03 #37 |
| regime banner | obs_market_regime（已核准） | C11 | S07 #40 |
| checklist_history still_active | 若有價值＝C10 跨快照判斷→core 落地，非 viewer 寫 | C10 | S04 #29 |
| sidecar 事件（golden_entry 等） | 17 欄落地後 C9 純派生 or 收編 canonical | C9 | 本 session §3-d |

→ **Presentation 層的裁定不是「落哪些欄」，而是「四條紅線＋sidecar 存廢＋cockpit_v2 處決＋薄化 vs 重寫的時序」**。全部依賴 17 欄先落地——本 session 是收割前 7 session 落地決定的**下游驗收點**，非新落地生產點。

---

## §5 裁定（fable 填）

（留空）

---

## §6 收尾 checklist
- [ ] CROSS-SESSION-NOTES 已 append 本 session 新發現（蒐證階段不預先 append，待 fable 裁定）
- [ ] 00-INDEX 狀態列已更新（證據包連結）
- [x] 未執行任何 code/schema 改動

---

## Cross-Session 待記事項（供 fable 裁定後 append 至 CROSS-SESSION-NOTES）

| 發現 | 嚴重度 | 歸屬 | 摘要 |
|---|---|---|---|
| C8 違例現行犯坐實：viewer 配線 weakening→golden.action_group（cockpit.py:2670-2675）＋缺資料時 render-time 重算 weakening（:1927） | 🔴 C8 | S08/S01 #24 | golden 靠 viewer 當配線工；display_tier 同型 |
| viewer render-time 重跑九引擎，UI==snapshot 結構性不成立（cockpit.py:46-53 import＋1891/3061/640 等） | 🔴 NOTES #2 呈現 grain | S08/全落地 | 17 欄落地後改讀；量能比同病（:2387） |
| viewer 是第 4 個持久化寫入點：checklist_history.json（:2089,2811）＋sidecar generate button（:3347） | 🔴 落地越界 | S08 | still_active 是 C10 跨快照判斷卻 viewer 寫；UI 可寫判斷入磁碟 |
| intelligence.json sidecar＝平行 SoR（自稱 immutable archive、不入 hash/replay、re-run 已廢 confidence、含永不觸發 breadth_milestone） | 🔴 SoR 違憲 | S08/S09/NOTES #38,#43 | 17 欄落地後多數事件變 C9 純派生；廢除 or 收編 canonical |
| cockpit_v2.py 1 commit 死碼但 Makefile 仍掛啟動目標（:54,58） | 🟡 死碼 | S08/NOTES #7 | 第 9/10 死平行實作；「棄置但可啟動」 |
| i18n/色/HTML 住 13 個 core 引擎完整清單；chip_score.py:105-107 引擎直接吐 HTML；viewer 反向硬編碼引擎色盤（bg_map :644-652） | 🔴 呈現洩漏 core | S08/NOTES #33 i18n | 引擎應吐語意 enum，presentation 獨佔配色 |
| 「轉弱」三來源未收斂（weakening/distributing/action_weakening）；統一標籤＝C8 須 core 派生 | 🟡 詞彙/C8 | S08/S04 #32 | viewer 正在組裝（action_group 合成） |
| 元大金/Tier-A：顯示徽章與資格計分未分離，is_tier_a 直接 +0.10 conviction（golden.py:279-280） | 🟡 顯示洩漏資格 | S08/NOTES #36/S01 RC-8 | 顯示集合洩漏進計分 |
| confidence 多空體檢 tab 仍 render-time 重跑 S03 已判死引擎，顯示已廢 deteriorating（cockpit.py:3054-3072） | 🔴 承接 S03 | S08/S03 #37 | 薄化最大單一工作量 |
| 雙實作漂移第 9 例：同 golden.run 於畫面（:1891）＋sidecar today/yesterday（:768/782）各跑 | 🔴 漂移 | S08/S02 #36 | 遷移 checklist 記載 |
| app.py+metrics.py＝唯一名實相符呈現層（純讀、零寫、零 scoring），理想態既有樣本 | ✅ 非病灶 | S08 | 薄化 cockpit 的參照對象；保留 |
| 「重寫 vs 薄化」cockpit.py：薄化證據（結構健康、病灶可定位、有乾淨樣本）vs 重寫證據（cockpit_v2 失敗前例、判斷呈現纏繞）；兩路線共用前置＝17 欄先落地、時序晚於 S01-S07 遷移 | 🔴 存廢級 | S08 | 證據列出待裁定 |
