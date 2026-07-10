# Session 07 — Market Context（市場環境層）（證據包）

> 證據蒐集（opus 2026-07-10）。裁定者只讀本報告＋CROSS-SESSION-NOTES。
> 鐵律：先分析、後才談改；本報告不含 code/schema 改動；證據一律附 `檔案:行號`。§5 留空待 fable。
> 本 session 涵蓋**市場級（market-grain）環境判斷**：`core/market_context.regime_shift`（廣度/體制）、`core/market_state.py`（統一市場狀態引擎）、`core/confidence.MarketRiskTemperature`（S03 §5 移交的市場風險溫度）、`data/market_pulse.json`（大盤指數/期貨）、`core/narrative_engine.py`（市場敘事）、snapshot 內 `market_regime` stub。
> 承接：S03 §5／NOTES #37（**market_temperature 移交本 session**，market_state 家族、grain=市場級）；S04 §5／NOTES #29-31（C10 as-was；temporal_state=landed-zombie-stub 判例，market_regime 是其同族）；S02 §5／NOTES #34（C11 判斷參數測試）；S01 §5／NOTES #24-25（C8 組裝權、C9 純派生不落）；S06 §5／NOTES #20-22（Replay Guarantee Strength、bump 歸零排程代價）；S05 §5／NOTES #10-15（Observation-First / snapshot=SoR、三態 I/O/M、RC-1 落地準則、C7 非破壞性 ingest）。
> 已鎖決策（不重議，見 NOTES #9）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0。

---

## §0 範圍與輸入

**只看（市場級環境層）：**
- `core/market_context.py` 的**市場級函式**：`regime_shift`（:332-451，廣度/均漲/體制分類/轉換偵測）、`leadership_rotation`（:538-604，板塊資金領導）、`_empty_regime`/`_empty_leadership`。
- `core/market_state.py`（全檔 888 行「市場狀態統一引擎」）：`MarketCondition`/`BreadthCondition`/`VolumeCondition`/`LiquidityCondition` 分類器（:95-237）、`_build_condition_layer`（:244-323）、`_build_flow_layer`（:326-399）、`_build_leadership_layer`（:402-542）、`_build_narrative_layer`（:545-626）、`build`/`market_condition`/`capital_flow_summary`/`leadership_map`（:633-693）、CLI（:849-888）。
- `core/confidence.py` 的**溫度部分**（S03 移交）：`MarketRiskTemperature` dataclass（:277-318）、`_build_temperature`（:518-601）、`_breadth_signal`（:498-513）、`TEMP_W_*`/`TEMP_LEVELS`（:124-126,194-200）。
- `data/market_pulse.json` 生產者 `tools/fetch_market_pulse.py`（:1-43 schema、:671 寫檔）與消費者 `viewer/cockpit.py`（:391-395 load、:498-560 banner、:3724 sidebar）。
- `core/narrative_engine.py`（市場敘事 header:1-40）。
- snapshot 落地面：`core/ingest.py:380-385`（`market_regime` stub_v0）；`core/intelligence_delta.py:430-490,656-669`（breadth/temperature 事件）。
- 消費面盤點：`viewer/cockpit.py`（regime:635-730、temperature:3054-3092、pulse:498/3724、narrative:1676）、`core/state_machine.py:719,788`（消費 regime breadth_series）、`core/confidence.py:503`（消費 regime）、`core/narrative_engine.py:80`、`tools/temporal/market_flow_monitor.py:192`。

**實跑驗證（真引擎跑 42 份真實磁碟快照，2026-07-09 latest）：**
```
regime_shift(42 snaps)            → regime=溫和偏多  latest_breadth=1.0  trend=flat  transition=True
market_state.build(42 snaps)      → condition=體制轉換中  breadth=100.0  breadth_cond=broad  volume_cond=surging
confidence.run(42).temperature    → 0.463 warm  elev_ratio=0.212  dist_ratio=0.762  breadth_signal=0.5
snapshot['market_regime']         → {label:null, classifier:"stub_v0", confidence:null, features:{breadth_index:null,...}}
```
→ **同一天、同一組輸入,三個市場級引擎給三種答案**（見 §3-1/§3-2）；**breadth 全序列 =1.0**（見 §3-3）。

**明確不看（留給哪個 session）：**
- `market_context.py` 的**per-ticker 函式**（`accumulation_velocity`/`temporal_enrich`/`sponsorship_persistence`/`failed_breakout_memory`/`weakening_profile`/`dual_cost_anchor`）**本體演算法** — 其消費者已由 **S01（golden 讀 dual_cost）/S02（chip）/S04（sm 讀 velocity/streak/weakening）** 分別裁定落地與否；本 session 只查它們與市場級函式**同住一檔的 grain 混用**（§3-9），不重裁個別欄位。
- `core/sector_intelligence.py` 內部演算法 → 板塊層，本 session 只查 market_state flow layer 對它的消費。
- 欄位命名正本 / registry → S05；replay 等級 / strip 白名單 → S06；卡片/徽章 CSS/i18n 呈現細節 → S08；backtest 對市場層輸出的消費 → S09。

**落地面實測（本 session 關鍵）：**
- **市場級判斷零落 canonical snapshot**：`reports/2026-07-09.json` 頂層唯一市場級 key 是 `market_regime`，且是**永久 null 的 stub_v0**（ingest.py:380）；regime/breadth/temperature/condition/leadership 全部 **render-time 計算，不落地**（復現 NOTES #2 於市場 grain）。
- **temperature 部分入 intelligence.json**（sidecar，intelligence_delta.py:475-490 temperature_change 事件），但市場級 `market_temperature` 數值本身不落 canonical。
- **`data/market_pulse.json` = 單檔覆寫、非 per-date、不入 snapshot、不入 replay**（§3-8）。

---

## §1 這一層真正要回答什麼問題？

**市場環境層回答「今天整體盤面是進攻還是撤退、資金流向哪個板塊、市場廣度/量能/風險溫度冷熱如何」——它是個股 golden/sm 判斷被閱讀時的『背景座標』。** 使用者拿它做兩件事：(i) **決定整體積極度**（過熱/撤退→收手、進攻/冷靜→加碼），viewer 頂端 regime banner（cockpit.py:635）＋temperature strip（cockpit.py:3078）＋market_pulse banner（cockpit.py:498）就是給這個決策；(ii) **當個股訊號的分母**——`state_machine` 把市場 breadth_series 當每檔 state history 的輸入（state_machine.py:719,788）、`confidence` 把 breadth 當溫度的一個成分（confidence.py:503,552）。

定位是 **market-grain 的 O（唯一非個股粒度的觀察層）**：其他所有引擎（golden/chip/sm/distribution/confidence-per-ticker）grain=ticker，本層 grain=date（整個市場一天一個判斷）。這個 grain 差異是 §2/§3 的核心——市場級判斷散落在**四個互不相認的地方**，沒有一個 System of Record。

---

## §2 它屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）作答。市場級判斷全部 grain=date。

| 輸出 | 層 | 三態 | 證據 | 落地狀態 |
|---|---|---|---|---|
| regime label（強勢進攻/溫和偏多/…）、breadth、avg_chg、breadth_trend、transition | **Classification**（市場體制分類） | **O**（市場 grain） | market_context.py:401-441 | 不落，render-time |
| market_state condition/breadth/volume/liquidity 四分類 + flow + leadership + narrative | **Classification**（更細的市場分類） | **O**（市場 grain） | market_state.py:294-323 等 | 不落，且**整個引擎無消費者**（§3-1） |
| market_temperature（0-1）+ level（冷靜…極端） | **Classification**（市場風險溫度） | **O**（市場 grain） | confidence.py:586-601 | 不落 canonical；level 差分入 intelligence.json |
| market_pulse taiex.close/change、tx_futures、三大法人期貨未平倉 | **Raw**（大盤指數/期貨原始值） | **I**（市場 grain macro） | fetch_market_pulse.py:11-40 | **單檔覆寫、不入 snapshot、不入 replay**（§3-8） |
| snapshot `market_regime`（label/classifier/features） | 佔位 stub | **M-ish 死欄**（永久 null） | ingest.py:380-385 | **落地但永遠空**（§3-4） |
| narrative（summary/bullets 雙語） | **Presentation**（翻譯層，非資料） | 非資料層 | narrative_engine.py:4-10 明文「ONLY interprets」 | 不落，render-time |
| regime_color/label_zh/en、四個 Condition 類的 LABELS/COLORS | **Presentation**（i18n/色） | 非資料層 | market_context.py:402-412、market_state.py:103-237 | 住引擎（S08 病灶） |

**分層小結**：本層的 O 是真正的市場級觀察（regime/breadth/temperature），**應該有一個 market_state 家族的落地 SoT**；但現況是 O 散在 regime_shift（活）、market_state.py（死）、confidence（活）三處各算各的，Raw macro（market_pulse）自成一個 ephemeral 孤島，唯一落 snapshot 的 `market_regime` 是永久 null。這是 §3 的全部病灶來源。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 一致；「＋新增」＝本輪新發現。

### (a) 【死碼】market_state.py（888 行、自稱「市場狀態唯一 SoT」）= 零消費者的棄置引擎（🔴 死碼／雙實作，＋新增，第 7 例）

1. **market_state.py 自我定位「Single source of truth for what the market is doing today」（market_state.py:4），卻被全 repo import 0 次**：`grep -rn "market_state"` 除自身外唯一命中是 docstring；`viewer/cockpit.py`、`tools/daily.py`、`intelligence_delta.py` 全部**不 import market_state**。它只有一個 `if __name__=="__main__"` CLI（market_state.py:849）。→ **與 NOTES #7 cockpit_v2、S03 §3a distribution「活 code 死輸出」同型的第 7 個死平行實作**：一個宣稱是市場級統一 SoT 的 888 行引擎，實際部署中從不執行。
   - viewer 真正用的市場體制是 `regime_shift` **直接呼叫**（cockpit.py:640 `_render_regime`），繞過 market_state.py。market_state.py 把 regime_shift 包成四層（condition/flow/leadership/narrative）的努力**全部沒有消費者**。

### (b) 【三重市場級分類漂移】regime_shift vs market_state vs temperature，同輸入不同答案（🔴 雙實作漂移，＋新增，第 8 例）

2. **同一天、同一組 42 快照，三個市場級引擎給三種市場狀態**（§0 實跑坐實）：
   - `regime_shift` → **「溫和偏多」**（market_context.py:403-404，latest_b≥0.6 且 latest_chg>1.0）。
   - `market_state._build_condition_layer` → **「體制轉換中」**（market_state.py:266-267：`transition_detected` 時**覆寫**成 TRANSITIONING）——**同一個 regime_shift 輸入,market_state 硬加一個 regime_shift 自己沒有的第 6 態 TRANSITIONING**，於是兩者對同一天給出不同體制標籤。
   - market_state 另加 `BreadthCondition`（5 級,:136-164）、`VolumeCondition`（5 級,:172-205）、`LiquidityCondition`（4 級,:208-237）**三套 regime_shift 完全沒有的分類法**，門檻各自寫死。
   - `confidence.MarketRiskTemperature` → **「warm 偏熱 0.463」**（第三個市場級答案,風險軸,confidence.py:586）。
   - → **市場級判斷有三個平行 code path、各自的門檻與分類法、彼此不知道對方存在**；沒有任何一個是 SoR。使用者在 viewer 看到 regime banner 說「溫和偏多」、temperature strip 說「偏熱」，語意來源無譜系（同 S03 §3-9 個股層並置病，本輪是市場層版本）。

### (c) 【correctness】breadth 結構性退化為常數 ≈1.0（🔴 correctness，＋新增）

3. **breadth = 「universe 中 main_force_buy>0 的佔比」（market_context.py:363），但 universe 本身是主力買超排行的 top-N 榜——依構造幾乎全員 mfb>0 → breadth 恆 ≈1.0**：實跑 42 快照 `breadth_series` 末 5 筆全 =1.0（§0）。後果連鎖：
   - **regime 分類切點失效**：`latest_b>=0.75 / >=0.6 / <0.25 / <0.35`（market_context.py:401-408）——breadth 恆 1.0 → 永遠落在 ≥0.6 分支,regime 實際只由 `latest_avg_chg` 單一變數決定；「廣度」維度在體制判斷裡是死的。
   - **breadth_trend 恆 flat**（market_context.py:384-398,delta 恆 0）→ cockpit 廣度趨勢欄（cockpit.py:681）永遠顯示「→ 持平」。
   - **transition_detected 只由 avg_chg 觸發**（market_context.py:419,b_delta 恆 0）→ §3-2 的「體制轉換中」覆寫是被單一 avg_chg 抖動觸發的假訊號。
   - → **這是量測了錯的母體**：breadth 該量「整體市場多少檔上漲/被買」,現在量的是「一個已被買超篩選過的榜單裡多少檔被買超」（近乎恆真）。與 **NOTES #4 同根**（universe 是主力買超家族、`volume` 實為買超）——買超榜當母體使任何「廣度」類指標退化。

### (d) 【landed-zombie-stub】snapshot 的 market_regime 是永久 null，且被錯 key 消費（🔴 死欄＋key 漂移，＋新增）

4. **唯一落 canonical snapshot 的市場級欄位 `market_regime` 是永久 null 的 stub_v0**（ingest.py:380-385：label=None、classifier="stub_v0"、features 全 None）。真正的 regime 活在 render-time 的 regime_shift,從不寫回這個 stub。→ **與 S04 NOTES #31 temporal_state 同族的 landed-zombie-stub**：落地了但永遠空、零真實內容、參與 canonical hash（在 snapshot 內 → 進 hash 邊界）。
5. **intelligence_delta 用錯誤 key path 讀這個 null stub → breadth_milestone 事件永不觸發**（🔴 dead consumer，＋新增）：`intelligence_delta.py:436,659` 讀 `snap["market_regime"]["breadth"]`,但 stub **沒有 `breadth` key**（實際 breadth 在 `features.breadth_index`,且=None）。實測 `market_regime.get("breadth",0)` → 0（key 不存在）。→ 「市場廣度連續 ≥70% N 天」里程碑事件（intelligence_delta.py:440-448）**在生產中永遠 0<0.70 不觸發**。雙重死：欄位是 null stub ＋ 消費者 key path 又對不上。

### (e) 【temperature 承接 S03】溫度的 breadth 成分是凍結常數（🔴 承接病灶，＋新增）

6. **market_temperature 三成分之一(30%)因 §3-3 的退化 breadth 而恆定**：`_breadth_signal`（confidence.py:498-513）讀 regime_shift 的 breadth_series 算斜率,breadth 恆 1.0 → slope 恆 0 → 恆回傳 0.5（實測 breadth_signal=0.5）→ `breadth_risk=1-0.5=0.5` → `TEMP_W_BREADTH(0.30)*0.5` 是常數。溫度實際只由 `elev_ratio`＋`dist_ratio` 兩軸驅動（confidence.py:555-559）。→ **S03 移交的 temperature 帶著一個結構性死成分**;S03 §5 已裁「temperature 可能是真的 market-level O、歸 market_state 家族由 S07 裁落地」——但落地前必須先解 §3-3 的 breadth 退化,否則落地一個 30% 權重是常數的分數。
7. **temperature 的另兩軸重疊 sm/confidence 已裁範疇**：`elev_ratio` 數 `risk_level in (elevated,critical)`（confidence.py:538-542）、`dist_ratio` 數 sm DISTRIBUTING（:545-549）——兩者都源自 S03 已裁「廢除」的 confidence risk_level 與 sm 狀態。temperature 若落地,其輸入定義需改讀 **obs_sm_transition_risk（S03 定的風險唯一 SoT）**,不能續建在已廢的 confidence risk_level 上。

### (f) 【grain 混用＋門檻治理＋i18n】

8. **market_pulse.json = ephemeral 單檔 macro 孤島**（🟡 持久化錯位,＋新增）：`fetch_market_pulse.py:671` 寫 `data/market_pulse.json`（**單一檔、每日覆寫、非 per-date**);cockpit 只 render-time load（cockpit.py:391,502,3724）。→ (i) **不入 snapshot、不入 replay、無歷史**：唯一的大盤指數/期貨 macro 層無法回放、無法對齊歷史 snapshot;(ii) **來源脆弱**：實測當前檔 taiex 有值但 `tx_futures` 與 `institutional_futures` 皆 error（"TX not found in CSV"）,errors 陣列非空。它是唯一的「真·大盤環境」（指數點位/三大法人期貨),卻是全系統最不受治理的一塊。
9. **market_context.py 一檔混兩個 grain**（🟡 模組邊界,＋新增）：同檔同時住 per-ticker O（accumulation_velocity/temporal_enrich/sponsorship/failed_breakout/weakening/dual_cost）與 market-level O（regime_shift/leadership_rotation）。市場級判斷沒有自己的模組家,寄居在 per-ticker 溫床檔;而**宣稱是市場級家的 market_state.py 又是死碼**(§3-1)。leadership 亦有兩實作:`market_context.leadership_rotation`(:538,板塊 mfb 加總) vs `market_state._build_flow_layer`(:326,走 sector_intelligence)——只有 narrative＋死的 market_state 消費前者。
10. **市場級門檻全寫死 code**（引 NOTES #33,不重裁）：regime 切點(market_context.py:401-419)、四個 Condition 類門檻(market_state.py:159-232)、`TEMP_W_*`/`TEMP_LEVELS`(confidence.py:124-126,194-200)——全模組級常數,改門檻無痕改市場歷史體制判斷（**C11-positive**,NOTES #34）。i18n/color 住引擎（regime_color、四類 LABELS_ZH/EN/COLORS,market_state.py:103-237）= S08 病灶第 8 例。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述,非藥方;每點附與現況差距。前提:Observation-First / snapshot=SoR(NOTES #10)、扁平前綴、additive+alias、market_temperature 已由 S03 移交本層。）

**市場環境層的理想邊界：**

- **唯一 market-grain O 生產者**：把散在 regime_shift（活）、market_state.py（死）、confidence temperature（活）三處的市場級判斷**收斂成一個 market_state 家族**,在 pipeline 算好、**落地 snapshot**（obs_market_* 前綴,取代永久 null 的 market_regime stub）。候選落地欄（依 RC-1「呈現或被 backtest 消費 → 必落」;C11-positive 因含寫死門檻;grain=date,一天一筆）：
  - `obs_market_regime`（體制分類）、`obs_market_breadth`（**修正母體後**）、`obs_market_avg_chg`、`obs_market_temperature`（含 level）。
  - 差距:現況三處各算、零落地、唯一落地的是 null stub。
- **先修 breadth 母體再落地**（§3-3 是前置）：breadth 應量「一個定義清楚的市場母體」(如全市場漲跌家數,或明確宣告分母),而非主力買超 top-N 榜(恆真)。否則 regime 的廣度維度與 temperature 的 30% 權重都是死的——**落地一個結構性退化的分數比不落更糟**（會把假訊號焊進 as-was 紀錄,C10）。與 NOTES #4 同根(買超榜當母體),需一併處理。
- **temperature 落地前改讀已裁 SoT**（承接 S03）：其 elev_ratio/dist_ratio 現建在 S03 已廢的 confidence risk_level 上,理想態改讀 `obs_sm_transition_risk`（風險唯一 SoT）;breadth 成分改讀修正後的 obs_market_breadth。
- **market_state.py 二選一**：要嘛成為真的市場級 SoT（被 pipeline 呼叫、輸出落地、viewer 改讀落地）、要嘛承認是棄置實驗刪除（同 NOTES #7 cockpit_v2 判例）——**不能既是死碼又掛著「single source of truth」招牌**。
- **market_pulse macro 的去留**：若大盤指數/三大法人期貨是真需求（它是唯一的真·大盤環境）,應 **per-date 歸檔＋納入 snapshot**（才能回放、對齊歷史）;若只是輔助顯示則誠實標為 ephemeral、不假裝是可回放的市場層。來源脆弱性(2/3 error)屬操作軌,非架構。
- **絕不做**：(i) 不由三個引擎各產一套市場體制;(ii) 不落地退化 breadth 派生的分數;(iii) narrative 續留 Presentation（純翻譯,不落）;(iv) 市場級 O 不再寄居 per-ticker 檔、不再靠 null stub 佔位。

**與現況差距總表：**
| 面向 | 現況 | 理想 |
|---|---|---|
| 市場體制 SoT | 三處各算、答案分歧、零落地 | 單一 obs_market_* 家族、落地、pipeline 算 |
| breadth | 恆 ≈1.0（買超榜當母體） | 定義清楚母體、非退化 |
| market_regime snapshot 欄 | 永久 null stub_v0 + 被錯 key 讀 | 真值落地或移除 stub |
| market_state.py | 888 行死碼 + 假 SoT 招牌 | 成為真 SoT 或刪除 |
| temperature 輸入 | 建在已廢 confidence risk_level + 退化 breadth | 改讀 obs_sm_transition_risk + 修正 breadth |
| market_pulse | 單檔覆寫、無歷史、無 replay | per-date 歸檔入 snapshot,或誠實標 ephemeral |

---

### NOTES #12 列舉義務：市場級哪些屬「契約級 observation」候選

準則(S05 RC-1):呈現或被 backtest 消費 → 必落;純派生(C9)不落;時序引 C10;含未落地判斷參數者(C11)必落。取捨(含 market_state 存廢、breadth 修正前置)留 §5。

| # | 現輸出 | 建議命名 | C 分類 | 理由／前置 |
|---|---|---|---|---|
| 1 | regime label + avg_chg | `obs_market_regime` | C11-positive,市場 grain | 呈現於 banner;含寫死切點;**前置:三處收斂成一個生產者** |
| 2 | breadth | `obs_market_breadth` | C11-positive **但退化** | **前置:先修母體(§3-3),否則落地退化分** |
| 3 | market_temperature + level | `obs_market_temperature` | C11-positive,S03 移交 | **前置:改讀 obs_sm_transition_risk + 修正 breadth;30% 權重現為常數** |
| 4 | market_state condition/volume/liquidity 四分類 | — | **爭議** | 整個 market_state 引擎是死碼;存廢先於落地 |
| 5 | market_regime snapshot stub | — | landed-zombie-stub | 同 temporal_state(#31):真值落地則取代之、否則移除 |
| 6 | market_pulse taiex/futures | — | Raw macro,grain 錯位 | 去留＋是否 per-date 歸檔入 snapshot(§4) |
| 7 | narrative | — | Presentation | 不落(純翻譯) |
| 8 | leadership_rotation / flow layer | — | 板塊層,可能 C9 派生 | 只 narrative＋死 market_state 消費;歸屬 sector 層 |

→ **候選 8 項,但與 S03 同型:多數前置是「存廢/修正」而非「落地命名」**。市場層獨有的三個最需 §5 定調:① **breadth 母體修正**（correctness,先於一切落地）;② **三重市場體制引擎收斂＋market_state.py 死碼存廢**;③ **temperature 落地的雙前置**（改讀 SoT + 修 breadth,S03 移交的收尾）。

---

## §5 裁定（fable 填）

（留空,待裁定者依 SESSION-TEMPLATE §5 rubric 完成。）

---

## §6 收尾 checklist
- [x] 本 session 新發現於 §3/§4 就地標歸屬（三重市場引擎漂移→本 session/S08;breadth 退化→correctness/NOTES #4 同根;market_state 死碼→NOTES #7 同族;market_regime stub→S04 #31 同族;market_pulse 持久化→S05/S06;temperature→S03 移交收尾）。蒐證階段不預先 append CROSS-SESSION-NOTES,待 fable 裁定後由裁定者決定入 NOTES 條目。
- [ ] 00-INDEX 狀態列更新（S07:證據包完成,待 fable 裁定）— 待裁定後一併。
- [x] 未執行任何 code/schema 改動。

---

## Cross-Session 待記事項（供 fable 裁定後 append 至 CROSS-SESSION-NOTES）

| 發現 | 嚴重度 | 歸屬 | 摘要 |
|---|---|---|---|
| market_state.py 888 行死碼(自稱市場 SoT、零 import) | 🔴 死碼 | S07/S08 | 第 7 個死平行實作(cockpit_v2/distribution generate 之後);viewer 走 regime_shift 直呼繞過它 |
| 三重市場體制引擎同輸入分歧(溫和偏多 vs 體制轉換中 vs warm) | 🔴 雙實作漂移第 8 例 | S07/S08 | 市場級無 SoR;S08 統一市場 banner 呈現 |
| breadth 結構性退化 ≈1.0(買超榜當母體) | 🔴 correctness | S07/NOTES #4 同根 | regime 廣度維度死、temperature 30% 權重恆定;落地前必修母體 |
| snapshot market_regime = 永久 null stub_v0 | 🔴 landed-zombie-stub | S07/S04 #31 同族/S05 | 唯一落地市場欄永遠空、參與 hash;真值 render-time |
| intelligence_delta 用錯 key 讀 stub → breadth_milestone 永不觸發 | 🔴 dead consumer + key 漂移 | S07 | 讀 market_regime['breadth'](不存在),實際在 features.breadth_index |
| market_pulse.json 單檔覆寫、無 per-date、不入 snapshot/replay | 🟡 持久化錯位 | S07/S05/S06 | 唯一大盤 macro 層無歷史、無回放;來源 2/3 現 error(操作軌) |
| market_temperature 移交承接完成:落地雙前置(改讀 obs_sm_transition_risk + 修 breadth) | 🔴 承接 S03 #37 | S07 | temperature 現建在已廢 confidence risk_level 上 |
| market_context.py grain 混用(per-ticker + market-level 同檔);市場級門檻寫死 C11-positive;i18n 住引擎第 8 例 | 🟡 模組邊界/門檻/S08 | S07/NOTES #33/S08 | 市場級 O 寄居 per-ticker 檔;門檻 config 化引 #33 系統性前置 |
