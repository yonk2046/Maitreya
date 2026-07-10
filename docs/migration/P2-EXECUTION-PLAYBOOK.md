# P2 執行劇本（無 fable 模式）

> **用途**：fable 5 於 2026-07-13 後不可用。本劇本把 Phase 2（1.9.0 單一 bump）的全部裁定、
> 任務卡、驗收標準、review 機制**預先固化**，讓 opus/sonnet 在沒有 fable 的情況下獨立執行完畢。
> **地位**：本文件＋`P2-single-bump-design.md`（含 fable 裁定節）＝實作的完整依據。
> 兩者衝突時以 design 文件的裁定節為準。
> **使用方式**：主 session（任何模型）依序執行 G0 → W1 → W2 → (W3/W5 可並行) → W4 → W6 → W7，
> 每包完工後跑對應 Review 卡。**任何停機紅線觸發＝停下等 Yonki，不自行裁定。**

---

## G0 閘門：7/13 收盤後 1.8.1 production 驗收（機械化判定）

### 情境 A：Mac 當晚開機（launchd 19:00 先跑）
1. `reports/2026-07-13.json` 存在、`schema_version=="1.8.1"`、`fii_pending` 不存在或 false
2. `python -m tools.verify_all_replay` → 0 failure、full-replay-clean 計數 +1（含 7/13）
3. viewer 正常顯示 7/13 名單（`make cockpit` 開起來人眼看一眼）
→ 三項全過＝**G0 通過**（partial 路徑未觸發，屬正常，NOTES #19 樣本改由 W6 回填 supersede 提供）

### 情境 B：Mac 當晚關機（GHA 20:00 partial → 隔晨 08:35 supersede）
1. 晚間：`reports/2026-07-13.json` 為 partial（`fii_pending: true`、頂層無 T86 派生欄退化）
2. 隔晨後：同檔被 complete 版 supersede（`fii_pending` 消失），`reports/index.json` 該日
   `history[]` 含 partial 版 hash、`current` 指向 complete 版
3. `python -m tools.verify_all_replay` → 0 failure（tip-only walker，只驗 complete 版）
4. viewer 顯示 complete 版名單
→ 四項全過＝**G0 通過**，且 NOTES #19 的真實樣本入手

### G0 失敗處理（機械化）
- 任一項不過 → **Phase 2 不開工**。修 1.8.1 的問題（開一隻 opus 調查，範圍限 1.8.1 機制），
  修完重新走 G0。**不允許**「帶病 bump」。
- 7/13 若又無交易（異常）→ G0 順延至下一交易日，其餘不變。

---

## 停機紅線（觸發即停，等 Yonki，不自行裁定）

1. `make verify-all-replay` 出現任何 failure（不是計數變化，是 FAIL）
2. bit-identical 驗證失敗且原因不明（W 卡內明定的預期差異除外）
3. 需要推翻 design 文件「fable 裁定」節的任何一條（D-1/D-3/D-4/D-5/D-7）
4. 需要改 `docs/ARCHITECTURE_BLUEPRINT.md` 的任何條文（C1-C12/不變量/判定樹）
5. 發現新的 correctness 級病灶（不在 55 條 NOTES 內的資料錯值）——記錄、停手、報告
6. production 當日 pipeline 掛掉（daily 排程中斷）——先救 production 再回遷移
7. 任何需要刪除既有快照/archive 檔案的情況（本劇本內沒有任何一步需要刪檔）

---

## Review 機制（無 fable 的替代）

每個 W 包完工後，**由一隻獨立的 opus reviewer agent** 執行該包的 Review 卡（下方每包附）。
Reviewer 鐵律：
- 只讀不寫（發現問題發回原實作 agent 修，reviewer 不動手）
- 親自重跑驗收命令，不信實作 agent 的回報
- Review 卡每一項逐條打勾；任何一項 fail → 發回；連續兩輪 fail 同一項 → 觸發停機紅線 5 的精神，停下等人
- 抽查紀律（fable 的教訓）：**agent 會寫出自我矛盾的欄位值**（P0 判例：semantic 寫 mc、owner 填
  Distribution）——reviewer 必須實際 grep/讀檔比對，不能只看 diff 摘要

---

## W1 任務卡：schema＋registry 宣告

**派工 prompt（原文照抄即可）**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W1：schema 與 registry 的 1.9.0 宣告。工作目錄
> /Users/yoncky/SCD engine/Ai stock（主 repo，commit main）。
> 必讀：docs/migration/P2-single-bump-design.md §1（22 欄位置與型別）＋「fable 裁定」節、
> schema/field_registry.yaml、schema/canonical_schema.json、core/ingest.py 的 SCHEMA_VERSION。
> 交付：①canonical_schema.json 顯式宣告 22 欄（15 個 obs/I 欄進 $defs.StockRecord.properties、
> 3 個 obs_market_* ＋ 2 個賣方 raw ＋ obs_landing 旗標 ＋ config_snapshot 結構宣告進頂層
> properties），型別照 design §1 表；②core/ingest.py SCHEMA_VERSION="1.9.0"；③registry：22 個
> planned→active（加 landed_version: "1.9.0"），新增 obs_landing（O/date/epoch-scoped-O/
> owner=Pipeline(ingest)）；④config/scd.example.yaml 的 meta.schema_version 同步；⑤tests 內
> assert schema 版本的測試同步改 1.9.0。
> 鐵律：只做宣告，不動 ingest 計算邏輯（那是 W2）——此時跑 pipeline 會產出 1.9.0 版本號但
> 尚無 obs 欄，屬預期中間態；schema 對新欄一律非 required（additive）。
> 驗收：make test 全綠（版本 assert 已同步）；make verify-registry 綠；
> make verify-all-replay 預期變化＝原本 2 份 1.8.1 full-replay 轉為 legacy-epoch
> （3 full→0 full/43+1 legacy 之類的計數位移，0 failure）——這是 bump 的預期代價（#22），
> 不是錯誤，回報時明確標注計數前後。
> commit「feat(P2-W1): schema 1.9.0 宣告 — 22 欄+obs_landing+config_snapshot 型別, registry
> planned→active」→ pull --rebase --autostash → push。

**Review 卡 W1**：
- [ ] `grep -c "obs_" schema/canonical_schema.json` 涵蓋 18 個 obs 欄名（逐名比對 registry planned 清單）
- [ ] 22 欄全部非 required（additive 紀律）
- [ ] registry 無殘留 status=planned 的 1.9.0 欄；obs_landing 已登記
- [ ] SCHEMA_VERSION 只在一處定義（grep "1.8.1" 全 repo 應只剩歷史文件/測試 fixture）
- [ ] 親跑 make test＋verify-all-replay，legacy 計數位移與實作回報一致、0 failure

## W2 任務卡：pipeline 骨架＋config_snapshot＋I 欄落地

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W2：ingest 引擎接線骨架。工作目錄同 W1。
> 必讀：design §2（呼叫順序 breadth→regime→sm→golden→chip→dist→temperature、C10 bootstrap
> 語意）＋§4（config_snapshot={yaml,engine_params} 雙來源、config_hash 覆蓋兩處）＋裁定 D-4/D-7、
> core/ingest.py、core/engine_params.py、tools/run_pipeline.py。
> 交付：①ingest 內建立引擎呼叫框架與順序（本包先接 I 欄與 config_snapshot，O 引擎接線給
> W3/W4，框架留好掛點）；②I 欄落地：trust_net_buy/prop_net_buy 進 StockRecord、fii_sell_raw/
> main_force_sell_raw 進頂層（adapter staging 的值 P1-3/4 已備好）；③config_snapshot 雙來源
> 結構＋config_hash（engine_params 需一個確定性 as_config_dict()——鍵排序、無環境依賴）；
> ④obs_landing 旗標寫入（正常 pipeline=true）。
> 鐵律：strategies 不入 config_snapshot（裁定 D-4）；O 欄此包不寫值（W3/W4）。
> 驗收：make test 全綠；跑 run_pipeline --check-replay 對最新資料日 → h1==h2 PASS（1.9.0
> 快照自身可重算）；新快照含 4 個 I 欄與 config_snapshot、schema validate 通過。
> commit「feat(P2-W2): pipeline 骨架+config_snapshot 雙來源+I 欄落地」→ rebase → push。

**Review 卡 W2**：
- [ ] config_hash 改 engine_params 任一值會變（親測：臨時改→hash 變→還原）
- [ ] config_snapshot 內無 strategies 鍵（D-4）
- [ ] 新快照 4 個 I 欄值與 WORM today.json 原始值逐檔抽查 3 檔一致（C7）
- [ ] trust_net_buy == 快照內既有 dealer_net_buy（同值雙寫，正名語意）；prop_net_buy 是新值非複本
- [ ] --check-replay PASS；make test 綠

## W3 任務卡：per-ticker 引擎解耦落地

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W3：per-ticker O 欄落地。必讀：design §2c 順序＋
> NOTES #26/#30/#35（各引擎落地欄語意）、core/golden.py、core/state_machine.py、core/chip_score.py。
> 交付：①sm 六欄落地（obs_sm_*，先於 golden）；②golden 六欄落地（obs_golden_*），且 golden
> 的 sm 輸入**改讀當日已落地 obs_sm_state**（不重跑 sm——治 #30 雙真相病）；③obs_chip_grade
> （含 total 子值）落地；④sync_streak 落地（owner=temporal_enrich）；⑤obs_dist_consistency
> 落地（讀頂層賣方 raw，safety band 參數入 engine_params）。
> 鐵律：C10——sm 的歷史輸入用「已落地快照序列」，1.9.0 首日之前無 as-was 序列＝bootstrap
> 起點，誠實從零開始（days_in_state 從 1 起算），不用今日 code 回算歷史狀態。
> 驗收：落地值與 viewer render-time 現算值**當日全欄一致**（寫一個對照測試：同一快照，
> viewer 引擎路徑 vs 落地欄逐檔 diff 空——遷移期雙軌一致性檢查，Phase 3 薄化後移除）；
> make test 綠；--check-replay PASS。
> commit「feat(P2-W3): per-ticker O 欄落地(sm→golden→chip→dist) — golden 改讀落地 sm」→ push。

**Review 卡 W3**：
- [ ] grep 確認 golden 落地路徑內無 `_sm.run`/`run_all` 呼叫（改讀 obs_sm_state）
- [ ] 對照測試存在且綠（落地值 == render-time 值，245 檔全數）
- [ ] obs_golden_near_miss 不含 tier 欄（判例 #26：near_miss 不落 tier）
- [ ] days_in_state 首日=1（C10 bootstrap，不是回算的大數字）
- [ ] --check-replay PASS

## W4 任務卡：market 家族搬家

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W4：market grain 落地。必讀：design §6＋NOTES
> #40/#41/#43、core/market_context.py（regime_shift）、core/confidence.py（temperature 部分）、
> data/market_pulse/（P1-2 per-date 檔）。
> 交付：①新模組 core/market_state_family.py（或 design 指定名）：regime_shift 邏輯遷入＝
> 唯一市場級生產者；②obs_market_breadth＝讀 data/market_pulse/<date>.json 的 breadth
> （twse_listed 母體）——**不再用買超榜當母體**；③obs_market_regime（切點讀 engine_params）；
> ④obs_market_temperature：elev/dist 成分改讀當日已落地 obs_sm_transition_risk（#43），
> breadth 成分讀修正後 obs_market_breadth；⑤三欄寫入頂層。
> 鐵律：market_state.py（888 行死碼）**此包不刪**（Phase 3 處決清單）；confidence.py 只搬
> temperature 邏輯不動其餘；market_pulse 當日檔缺失（假日/抓取失敗）→ obs_market_breadth
> 誠實 null＋errors 記錄，不用舊榜母體 fallback（fallback 到病態母體＝復發 #41）。
> 驗收：make test 綠；--check-replay PASS；當日三欄有值且 breadth 分母=1078 量級（非 1.0 常數）。
> commit「feat(P2-W4): market 家族落地 — breadth 換母體/temperature 改讀 sm SoT」→ push。

**Review 卡 W4**：
- [ ] obs_market_breadth 值≠1.0 且來源檔為 data/market_pulse/（grep 無買超榜母體殘留）
- [ ] temperature 計算路徑 grep 無 confidence risk_level 引用（改讀 obs_sm_transition_risk）
- [ ] market_pulse 缺檔情境測試存在（null＋error，無 fallback）
- [ ] market_state.py 未被刪（不在本包範圍）

## W5 任務卡：attestation ledger（可與 W3 並行）

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W5：replay attestation ledger。必讀：design §5b＋
> P1-version-pinned-replay.md 候選 B＋裁定 D-5（合憲性釐清全文——ledger=M 態驗證證明，
> 非第二 SoR，replay 通過永不依賴它）。
> 交付：①run_pipeline --check-replay 通過時 append 一筆到 reports/_replay_ledger.json
> （date/schema_version/core_commit_sha/config_hash/h1==h2/verified_at）；②append-only＋冪等
> （同 date+hash 不重複記）；③verify_all_replay 對 ledger 做軟核對（有 ledger 記錄的日子
> 顯示 attested 標記；**無 ledger 記錄不算 fail**——D-5 鐵律）。
> 驗收：make test 綠；重跑兩次 --check-replay ledger 只有一筆；手刪 ledger 後 verify 仍 0 fail。
> commit「feat(P2-W5): replay attestation ledger(L2.5) — append-only 旁側驗證帳」→ push。

**Review 卡 W5**：
- [ ] 刪掉 ledger 檔（備份後）重跑 verify → 仍 0 failure（replay 不依賴 ledger）
- [ ] ledger 內無任何市場判斷欄位（只有 hash/版本/時間戳——M 態紀律）
- [ ] 冪等親測

## W6 任務卡：I 欄歷史回填（W2 後即可，與 W3/W4 並行）

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W6：I 欄回填（裁定 D-7 選項 A）。必讀：design §7
> 全節＋裁定 D-7 附帶條件、docs/migration/P1-worm-backfill-report.md（逐日覆蓋表）、
> core/replay_contract.py。
> 交付：①ingest backfill 模式（obs_landing=False：只寫 4 個 I 欄＋既有 raw 重組，跳過全部
> O 引擎）；②**replay contract 認得旗標**：verifier 對 obs_landing=false 快照重算時同走
> backfill 模式（D-7 硬條件——否則回填快照永遠 full-replay fail）；③回填腳本：2026-05-26→
> 1.9.0 前一交易日，逐日 supersede（1.8.1→1.9.0 鏈），**冪等**（重跑不產生第二條 supersede；
> 用 hash 比對跳過已回填日）；④rollup-only 11 天＋fii_pending 5 天照覆蓋表誠實跳過（prop 缺
> 的日子 trust/賣方 raw 照回填、prop 誠實缺欄）。
> 驗收：回填後 make verify-all-replay 0 failure 且回填日轉為 1.9.0 epoch 可重算；抽驗
> 2026-06-09 一日：快照 trust/prop 值與 WORM today.json 逐檔一致；index.json supersede 鏈
> 完整（舊 1.8.1 版 hash 在 history）。
> commit「feat(P2-W6): I 欄回填 2026-05-26起(backfill 模式 obs_landing=false, 冪等 supersede)」→ push。

**Review 卡 W6**：
- [ ] 隨機抽 3 個回填日：obs_* 欄全部不存在（O 未落）、4 個 I 欄有值或誠實缺（照覆蓋表）
- [ ] 回填腳本重跑一次 → git status 乾淨（冪等親測）
- [ ] verify-all-replay：回填日顯示 full-replay-clean（backfill 模式重算路徑通）、0 failure
- [ ] index.json 抽 1 日：history 含舊 1.8.1 hash（supersede 不覆滅歷史）

## W7 任務卡：整合驗收收尾

**派工 prompt**：
> 你在 Maitreya/SCD Engine 專案執行 P2-W7：Phase 2 整合驗收。必讀：design §8 全部＋本劇本
> 全部 Review 卡。
> 交付：①design §8 驗收清單逐項執行並在 design 文件勾選；②viewer 對照：cockpit 顯示值 vs
> 快照落地值逐 tab 抽查（golden 名單/sm 狀態/chip 分/market banner 各 3 檔）記錄於
> docs/migration/P2-acceptance-report.md；③全 Review 卡重跑一輪（W1-W6 各卡逐項）；④更新
> docs/ARCHITECTURE_BLUEPRINT.md §7 Phase 2 狀態為完成（只改狀態行，不改條文）；⑤registry
> counts 與 meta.notes 收尾同步。
> 驗收：make test 全綠、verify-all-replay 0 failure、驗收報告完整。
> commit「docs(P2-W7): Phase 2 整合驗收報告 — 1.9.0 落地完成」→ push。

**Review 卡 W7**（Yonki 或最後一隻 reviewer）：
- [ ] P2-acceptance-report.md 的 viewer 對照表無不一致
- [ ] 隔日 production 跑完後回頭看一眼：新快照 22 欄有值、replay 0 fail、ledger +1

---

## 執行順序總表

```
G0（7/13 驗收，機械化判定）
 └─ W1 schema/registry ──→ W2 骨架+config+I 欄 ──┬─→ W3 per-ticker 引擎 ──→ W4 market 家族
                                                  ├─→ W5 ledger（並行）
                                                  └─→ W6 I 回填（並行）
                                    W3+W4+W5+W6 全收 ──→ W7 整合驗收
每包：實作 agent（opus）→ Review agent（另一隻 opus，只讀，親跑驗收）→ 過了才派下一包
```

## Phase 3 預告（本劇本不含）
Phase 2 收尾後的 viewer 薄化＋處決清單（sidecar/checklist_history/cockpit_v2/market_state/
resonance/confidence）依憲法 §7 Phase 3 執行，屆時另寫劇本或由 fable（若可用）裁定。
處決涉及刪檔，**全部觸發停機紅線 7 的例外程序：需 Yonki 逐項點頭**。
