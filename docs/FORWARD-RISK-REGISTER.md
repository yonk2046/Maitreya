# 前瞻風險登記簿（Forward Risk Register）

> **用途**：fable 5 於 2026-07-11 用剩餘額度做的全案前瞻分析——預判接下來 3–12 個月
> **很可能發生**的問題與 bug，附大方向解法，供後續 AI 模型直接引用、不必重新推導。
> **地位**：憲法（ARCHITECTURE_BLUEPRINT）之下的預警文件。與 P2-EXECUTION-PLAYBOOK 並讀。
> 每項標【日期型／高概率 bug／結構型／已證實】與建議執行時機。
> 文末「補充裁定」四條是 fable 的預先裁定，後續模型直接執行不必重裁。

---

## R1【日期型：2026-07-13】G0 當天的特殊狀態

- `data/today.json` 目前殘留 7/10 颱風假的陳舊資料（tradingDate=2026-07-10）。7/13 fetch 會正常覆寫；
  **若 fetch 失敗**而 daily 繼續跑，會嘗試用 7/10 資料建快照（殭屍復活路徑）——但 T86 空 → partial
  分支 → **交易日 oracle 對 7/10 回「無交易」→ fail-closed 跳過**。oracle（acb66ec）已覆蓋此路徑，
  預期安全，但 G0 執行者應知道這條防線的存在與作用。
- 觸發器時序提醒：18:05 dispatch 早於 T86 偶發的晚發布時段（~18:00-18:30）→ **partial 機率比設計時
  預想的高**；20:00 GHA（帶 --allow-partial）與 08:35 T+1 completion 是配套。fii_pending banner
  出現頻率會比過去高，是新常態不是 bug。
- 驗收照 P2-EXECUTION-PLAYBOOK G0 清單，基線計數以當日實跑為準（已改相對表述）。

## R2【日期型：2026-09-04】cron-job.org PAT 到期＝主觸發靜默死亡

18:05 dispatch 用的 PAT 到期後，cron-job.org 會收到 401 但**沒有人會被通知**——pipeline 表面正常
（GHA 20:00 備援還在），實際主觸發已死，所有快照悄悄變成 20:00 的 partial-first 模式。
**方向**：①到期前換發（放行事曆）；②便宜的 heartbeat：GHA 每日檢查「過去 24h 有無 dispatch 觸發的
run」，沒有就在 workflow summary 標紅（一個 step，不用新服務）。

## R3【結構型，已量化】repo 即資料庫的增長天花板

實測 2026-07-11：`reports/` 108MB（其中 `_raw_archive/` 101MB，**已確認 git 追蹤中**，3,567 檔），
約兩個月累積 → **~600MB/年**。一年內會撞上：GitHub repo 體積軟限制、Streamlit Cloud clone 變慢、
本機 git 操作變鈍。
**方向（2.0 議程，憲法 §7 Phase 5 順帶）**：storage split——`_raw_archive` 遷出 code repo
（獨立 data repo 或 object storage＋manifest hash 留在主 repo，replay 契約讀 manifest）。
**中期止血（Phase 3 順帶）**：sidecar 停產後 33 份 `.intelligence.json` 不再增生；
本機定期 `git gc`（2026-07-11 實測 `.git/objects` 有 ~200 個被 kill 的 agent 留下的 tmp_obj 垃圾）。

## R4【高概率 bug：W3 期間】混合 epoch 歷史窗

1.9.0 後引擎在 pipeline 內讀 20 日歷史窗，窗內會同時出現三種快照：1.8.x（**無任何 obs_\* 欄**）、
backfill（`obs_landing=false`，有 I 無 O）、1.9.0 正常（全欄）。**最可能的 bug 群＝引擎裸讀舊快照
的 KeyError／None 未防護**——這會是 W3/W4 實作中最大宗的錯誤來源，且測試容易只用新快照 fixture 而漏掉。
**方向（見補充裁定 A）**：建一個 epoch-aware history view（單一讀取層），引擎一律透過它讀歷史，
絕不裸讀 dict；view 對缺 obs 的舊快照回傳明確的 absent 語意。fixture 必含三種 epoch 混合窗。

## R5【高概率 bug：1.9.0 後】partial 鏈時序破洞

情境：週一晚 partial（T86 晚到）→ 週二早 completion **失敗**（GHA 抖動/TWSE 掛）→ 週二晚 pipeline
直接開建週二快照 → **週二的 obs 建立在「已被標記待補完」的週一 partial priors 上**；之後週一被
completion 補完，週二不會重推 → 鏈上出現一個永久的「用舊 priors 算的日子」。1.8.1 時代同樣會發生
但只影響 temporal 欄位；1.9.0 後 obs 全落地，破洞被焊進 as-was 紀錄。
**方向（見補充裁定 B）**：build-order invariant 進 daily.py——「開建日 N 前，若 N-1 是 partial
且其 T86 現在可得 → 先補完 N-1 再建 N」（一個 gate 檢查，W2 一併實作）。

## R6【doctrine 缺口】1.9.0 後的資料修正案 SOP

Handoff #2 的教訓泛化：**supersede 任何一天都會 cascade 下游 20 日 hash pin**。1.9.0 後 obs 是
as-was 紀錄，cascade 重推會把「當時相信的」換成「本應相信的」——supersede 鏈保留原版故可接受，
但必須有明文 SOP，否則每次修正都要重新辯論。
**方向（見補充裁定 C）**：修正案 SOP＝①只修 I 態輸入②cascade 範圍預先聲明（任務卡必填）
③兩版都留鏈上④ledger 註記修正案⑤O 態永不手工改。

## R7【已證實 bug，小】market_pulse 把陳舊指數標成今天

實證：7/11（週六）dispatch 照跑，`market_pulse.json` 的 `date=2026-07-11` 但 taiex=45,354.61
（實為 7/09 收盤）。banner 顯示「2026-07-11 更新」＝假新鮮。per-date archive 也多了一份非交易日
檔案（breadth 誠實 error，**不會騙過 oracle**——oracle 只認 parsed breadth 無 error）。
**方向**：market_pulse 分離 `session_date`（資料屬於哪個交易日）與 `fetch_date`；banner 顯示
session_date。順帶議題：cron-job.org 是否該跳過週末（跑了無害但製造噪音檔）。

## R8【已證實 noise】多源驗證天天喊狼

fetch step 9「多源交叉驗證」每天輸出「外資榜重疊 0/10、主力榜重疊 0/5、個股一致 0/5」——一個
**恆定失敗的死檢查**。天天喊狼的後果是訓練操作者忽略 warning，真正的資料異常反而會被淹沒。
**方向**：查證比對源是否已死 → 修母體或 tri-state 化（ok/fail/disabled）或直接刪（ponytail：
壞掉的檢查比沒有檢查更糟）。

## R9【git 噪音，過渡】checklist_history.json

viewer 每次 render 寫此檔（S08 判死的第 4 持久化點，Phase 3 廢除）。廢除前它會持續弄髒 git 工作區
（本 session 已撞三次，autostash 衝突的常客）。
**方向**：提前執行 `git rm --cached data/checklist_history.json`＋入 `.gitignore`——viewer 行為
不變、純停止追蹤，零風險，任何模型可立即做。

## R10【replay 決定性】GHA runner 環境漂移

同 epoch full-replay 的重算在 GHA runner 與本機兩種環境發生；numpy/python 小版本更新歷史上是
replay 假失敗的頭號兇手。environment 已記錄於 snapshot（M 態、比對時 strip），但**重算本身**若跨
版本可能產生浮點差異 → hash 不合。
**方向**：pipeline workflow 內 requirements 精確 pin（==，不用 >=）；W5 ledger 記錄每次驗證的
環境指紋，環境變動時 ledger 顯示「環境已漂移」警示（不 fail，供診斷）。

## R11【接受型風險】富邦單源、不可回溯

榜單唯一來源；site 改版＝斷糧且歷史不可補（7/10 事故與 handoff #2 都繞著這個事實）。
**裁定：不追第二榜單源**（成本／收益不成比例）——接受為系統性風險。要求只有兩條：fetch 失敗大聲
（已具備）、缺日誠實跳過（oracle 已具備）。使用者預期管理：這個系統的資料完整性上限＝富邦的可用性。

## R12【已證實，體驗】Streamlit Cloud 部署漂移

實證：7/11 使用者 reboot 雲端後仍看到舊色票——雲端「目前跑的是哪個 commit」對使用者不可見，
Phase 3 viewer 改版頻繁時這個困惑會反覆發生。
**方向（見補充裁定 D）**：cockpit 頁腳顯示 short commit hash（讀 `git rev-parse` 或部署時注入的
環境變數，一行 `st.caption`）——一眼比對「雲端版本 vs main HEAD」。部署 SOP 一句話：改版後
確認頁腳 hash 前進。

---

## 補充裁定（fable 2026-07-11，後續模型直接執行不必重裁）

| # | 裁定 | 執行時機 |
|---|---|---|
| **A** | **epoch-aware history view**：W3 前置構件。單一歷史讀取層，引擎不裸讀舊快照；三種 epoch（1.8.x／backfill／1.9.0）的缺欄語意由 view 統一回答；測試 fixture 必含混合窗 | W3 開工首日 |
| **B** | **build-order invariant**：建日 N 前檢查 N-1 partial 且可補完 → 先補完。實作於 daily.py gate | W2 一併 |
| **C** | **修正案 SOP**：I 態修正→cascade 範圍預先聲明→兩版留鏈→ledger 註記→O 永不手工改。重建類任務卡必含「cascade 影響天數」欄位 | 即日起生效（文字即法） |
| **D** | **viewer 頁腳 commit hash**：一行 st.caption。R9 的 untrack 一併做 | 任何模型隨手做，不需審批 |

## 明確不做（防過度工程，與憲法「絕不做」條款同位階）

- 不追第二榜單資料源（R11 已裁）
- 不遷資料庫／不引入 DB（storage split 在 2.0 用「檔案搬家」解，不是換儲存引擎）
- 不重寫前端框架（S08 已裁薄化不重寫，R12 的 hash 頁腳不是重寫的開端）
- oracle 不擴大成完整交易日曆服務（正面證明開盤、fail-closed，夠用即停）
- 不為 R4 建通用 ORM／schema 抽象層——一個 history view 函數層就是全部

## 優先序一覽

| 時機 | 項目 |
|---|---|
| 立即可做（任何模型） | R9 untrack、補充裁定 D（hash 頁腳）、R8 查證、本機 git gc |
| G0（7/13） | R1 知情執行 |
| W2 | 補充裁定 B |
| W3 | 補充裁定 A |
| Phase 3 | R3 中期止血（sidecar 停產）、R7（隨 market 家族搬家順帶） |
| 8 月內 | R2 PAT 換發＋heartbeat、R10 pin |
| 2.0 | R3 storage split |
