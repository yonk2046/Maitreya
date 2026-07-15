# Phase 3 逐項核准文件（viewer 薄化＋處決清單）

> 給 Yonki：每項勾「☑ 核准」或改寫「保留，原因＝…」。全部勾完即可照此派工，不再逐案回來問。
> 憲章依據：`docs/ARCHITECTURE_BLUEPRINT.md` §7 Phase 3 ＋ §8 處置清單（處置本身研究期已定案不重議，
> 這份文件核准的是「**現在動手刪檔**」這個動作）。
> 實證依據：`docs/migration/P2-acceptance-report.md` F-1——viewer 現場重算 vs 落地 obs_* 的分歧
> 100% 是窗口差（viewer 餵全歷史、pipeline 用 20 日窗），以快照記錄的窗重算 41 檔×14 欄 diff=0，
> **黃金名單成員與分級兩邊完全一致**。落地值就是 canonical 真值，viewer 改讀零語意損失。
> 安全網：所有刪除都在 git 歷史裡，任何一項出事 `git revert` 即回。

## 執行順序（憲章紅線：改讀先行，刪除殿後）

```
P3-a viewer 改讀（不刪任何檔）──逐 tab 驗收「畫面 == 快照欄位」
 └─ P3-b 消費者歸零後才處決（import 數=0 是刪檔前置條件）
完成準則（憲章 §7）：viewer 對 core 引擎 import=0、viewer 磁碟寫入=0、grep 引擎檔無 hex/HTML
```

---

## A 組：零消費者，純刪除（風險最低）

### A-1 刪 `core/market_state.py`
- **現況**：888 行，自稱市場 SoT，**全 repo 零 import**（今日親測）。語意從未被驗證（判例 #40）。
- **為什麼安全**：沒有任何程式讀它；刪除前後系統行為 bit-identical。
- ☐ 核准

### A-2 刪 `viewer/cockpit_v2.py` ＋ Makefile 兩個目標
- **現況**：1234 行，零 import；Makefile `cockpit-v2` / `restart-cockpit-v2` 兩目標（:56/:59）。
- **為什麼安全**：研究期已定性為「另建前端的失敗案例」（判例 #7/#45），保留只會誘惑後人重蹈。
- ☐ 核准

## B 組：先改讀、後停產／解散（P3-a 完成後執行）

### B-1 resonance 引擎解散：刪 `core/resonance.py`
- **現況**：209 行，唯一消費者＝cockpit（:51）。研究實證 level ≡ 已落地的 fii_sync_count（35/35 全同，判例 #35）；sync_streak 已於 W3 落地為快照欄。
- **改讀**：cockpit 讀 `sync_streak`／`fii_sync_count`，共振徽章變純呈現映射（C12）。
- ☐ 核准

### B-2 confidence 引擎降級：刪 `core/confidence.py` 獨立分數路徑
- **現況**：923 行，消費者＝cockpit（:49）、cockpit_v2（隨 A-2 消失）、intelligence_delta（隨 B-3 消失）。獨立信心分數已判廢（double-count sm／61% 塌零，判例 #37）；風險唯一 SoT＝已落地的 `obs_sm_transition_risk`；溫度已由 W4 落地為 `obs_market_temperature`。
- **W7 實證**：溫度 tab 現在顯示的就是死引擎算的 0.45/warm，落地真值 0.37/warm——**改讀本身就是修 bug**。
- **改讀**：溫度 tab 讀 `obs_market_temperature`；信心欄位換成 2D profile 的 C9 派生視圖（render-time 映射，不再有獨立分數）。若拆完後檔案只剩被判活的派生函式，縮檔保留；全死則刪。
- ☐ 核准

### B-3 intelligence.json sidecar 停產：關 `tools/daily.py` Step 4 ＋ cockpit 改讀
- **現況**：`core/intelligence_delta.py` 965 行；daily.py:734 每晚產 `reports/<date>.intelligence.json`；cockpit（:55）讀它。研究定讞＝平行 SoR 零保證、內容窮舉全為 C9 派生（判例 #46）。**intelligence_delta 讀 confidence——它不停產，B-2 就刪不了。**
- **處置**：停產（daily Step 4 移除＋刪引擎檔）；**既有 `reports/*.intelligence.json` 留檔不刪**（判例原文：停產留檔）。cockpit 事件流改為「落地序列的 render-time diff」（今日 vs 昨日快照欄位比對，同資訊零 sidecar）。
- ☐ 核准

### B-4 checklist_history 廢除：cockpit 停寫磁碟
- **現況**：cockpit.py:2138-2883 讀寫 `data/checklist_history.json`——**viewer 磁碟寫入的唯一現行犯**（薄化紅線「不寫」）。R9 已 untrack，但程式還在寫。留存率統計是 C9 派生（判例 #47），可由快照序列現算。
- **處置**：刪 cockpit 內 `_load_history/_update_history/_save_history` 及該 json 的一切讀寫；留存率改快照序列派生。
- ☐ 核准

### B-5 distribution 拆解收尾：cockpit 改讀後瘦身 `core/distribution.py`
- **現況**：600 行；**pipeline 端已重生**（obs_landing 讀它產 `obs_dist_consistency`，這部分是活的、不動）；cockpit（:54）還在 render-time 另算一份。
- **處置**：cockpit 改讀 `obs_dist_consistency`；distribution.py 只留 pipeline 消費的計算核心，CLI/呈現殘肢刪除。
- ☐ 核准

## C 組：viewer 改讀本體（P3-a，不刪檔，逐 tab 驗收）

### C-1 cockpit 全部 render-time 引擎呼叫 → 讀 obs_*
- **範圍**：golden（:48）→ `obs_golden_*` 六欄；state_machine（:50）→ `obs_sm_*` 六欄；chip_score（:52）→ `obs_chip_grade`；market_context regime/breadth → `obs_market_regime`／`obs_market_breadth`（W7 實證：regime tab 現用舊 breadth 數學，改讀即修正）；歷史視圖走 `core/history_view.py`（裁定 A 的 epoch-aware 三態）。
- **驗收**：逐 tab「畫面 == 快照欄位」對照（W7 驗收報告的對照表直接重跑）；黃金名單成員/分級不得有任何變化（F-1 已證兩邊一致，變了就是改壞）。
- **明確不改**：呈現映射（顏色/中文/emoji）依 C12 歸 viewer 單一擁有——這次是把「判斷」搬走，「呈現」留下。
- ☐ 核准

### C-2 引擎檔清除呈現輸出（C12 違例 13/18 檔）
- **範圍**：引擎吐 hex/雙語/HTML 的部分改吐語意 enum，映射表集中 viewer（最重案例＝chip_score 直接吐 HTML）。
- **驗收**：`grep` 引擎檔無 hex/HTML；畫面不變。
- ☐ 核准

## 派工建議（核准後）

- 一包一組：C-1（最大）→ C-2 → B-3/B-4 → B-1/B-2/B-5 → A-1/A-2（A 組雖最安全，放最後是讓「import=0」成為機械可驗的刪檔前置）。
- 每包照 P2 紀律：opus 實作＋獨立 reviewer 親跑驗收；先 commit 再長驗證；viewer 逐 tab 截圖對照。
- Phase 3 全程**不碰 schema、不碰 reports/、不碰 pipeline 落地邏輯**——快照層在 Phase 2 已凍結收官。

## 明確不在本次範圍

- `temporal_state`／`market_regime` stub：維持 deprecated-pending，**2.0 才移除**（單一 bump 紀律）。
- 回測正確化＝Phase 4；deprecated 欄清場＝Phase 5。
- `reports/*.intelligence.json` 歷史檔案：留檔（WORM 精神），只停新增。
