> ⚠️ **已被取代**:最新交接為 repo 根目錄 `MAITREYA_HANDOFF_20260923.md`(2026-09-23)。
> 本檔的 9 月斷更事故分析與環境/憑證資訊仍有效;「回測數字」「黃金名單語意」「待辦 T1」等節已被新檔取代。

# Maitreya 交接文件 — 2026/09/15(9 月斷更事故全面檢修 · 搬家可用版)

> **這是最新一份 handoff。** 舊版(0702/0706 等)已移至 `docs/handoffs/`,內容僅供考古,**其中的觸發器與「雲端抓不到當日 T86」等描述已過時**。
> 規範正本仍是 `docs/ARCHITECTURE_BLUEPRINT.md`;觸發器正本是 `ARCHITECTURE.md §5`(本次已改為實測版)。
> 撰寫:Claude(Opus 5),2026-09-15 下午。

---

## 0. 一句話狀態

**9/1–9/14 斷更已止血並找到真正根因;今晚起新流程上線。但同時查出回測撮合價有系統性錯誤、回測引擎成本立方成長(約 2026-12 ~ 2027-01 會撐破 CI 上限),以及 9/4 正式快照混日。回測數字在修正前不可用於決策。**

---

## 0.1 2026-09-22 更新(9/15 之後一週)—— 先讀這節

| 事項 | 狀態 |
|---|---|
| replay 修正 `36f6652` | replay 只取快照**記錄的**前序日期集合。補插 9/14 **不再牽動 9/15 及之後的快照**,D2 不再有 cascade 與時間壓力。零影響證明:全部 current-schema 日期新舊結果相同;9 個不同者皆為 1.4.0 凍結 epoch(不做 full replay) |
| 9/14 正式快照 | **尚未建**。計畫見 §3.2 末;須 Yonki 看過結果才推(D2) |
| F-16 驗證 | ✅ 9/16 起 `launchd.out.log` 首次出現 rebase 之後的訊息(`already on origin/main — nothing to do`) |
| **F-17 新事故(第二次)** | 9/17 Mac 夜間睡眠,run 拖到 9/18 04:26 才 commit;push 被拒後重試的 `git fetch` 遇 DNS 失敗 → `set -euo pipefail` **無聲中止** → 本機 `ae9ddce` 卡住 → 9/21 起每晚開頭 rebase 衝突,Mac 備援再度失效(與 8/31 同型)。**9/22 已清除**(備份 `backup/stranded-0917-mac`)。結構修正 = T9 |
| canary #11(9/17)、#12(9/21) | 當晚 18:05 未建成;**隔日 08:35 cron-job.org T+1 補建完整**(`fii_pending=False`、`tradingDate` 一致;盤前抓取時「只給最新一天」的來源仍是前一交易日 → 無混日)。資料無損 |
| run #296(9/18 晚班,紅) | 原生 20:00 cron 於 9/19 00:15 落地,解出 9/17 < 最新 9/18 → stale-fetch 守門員拒建(exit 3)。**這是 F-10 被擋下**,不是 bug |
| 快照 | 9/15–9/18、9/21、9/22 皆在(5 個交易日全齊) |
| **9/22 晚:黃金名單稽核 → 引擎修正弧開工** | 稽核 `docs/migration/AUDIT-golden-list-20260922.md`(系統看不到主力賣出;影子比對:修正讓系統不說錯話,但 4 個月內訊號無超額)。執行正本 `docs/migration/EXEC-PLAN-engine-correction-20260922.md`。**已上 main(`3aa1527`)**:A4 開盤/量/漲跌改 MI_INDEX 按日期、A5① 分點涵蓋全快照(兩者立即生效);A1–A3 在 `feature_flags.engine_correction_v1`(**false**,10/2 收盤後改 true、10/5 生效)。**9/23 18:05 後驗證**:`python3 "/Users/yoncky/SCD engine/_research/engine-correction/verify_a4a5.py" 2026-09-23` 應全 ✅ |
| **D5 已完成(9/22)** | canary #3–#10 已逐張附結果(無損/永久遺失/混日/救援待 D2)後關閉;#1、#2、#11、#12 仍 open |
| **D1 已決(9/22)** | 9/4 **只註記、不重建**,列已知不可用日(前推評估不計、T1 回測不在 9/4 撮合)。細節 EXEC-PLAN §7.4 |

---

## 1. 事故:2026-09-01 ~ 09-14

### 1.1 使用者看到的
Viewer 停在舊資料。canary 開了 8 張警報 issue(#3 08-31、#4 09-02、#5 09-04、#6 09-07、#7 09-08、#8 09-10、#9 09-11、#10 09-14),未被處理。

### 1.2 根因鏈(四層疊加,**第一層才是主因**)

| 層 | 事件 | 證據 |
|---|---|---|
| **① 主因** | GHA `daily.yml` 的測試步驟排在 commit **之前**。回測類測試隨快照數立方成長,8/25 起跑超過 job `timeout-minutes: 30` → **整個 job 被取消 → commit 被 skip → 已建好、已驗證的快照隨 runner 銷毀**。`continue-on-error: true` 只管步驟失敗,**管不到 job 逾時**。 | run #34878138316(9/14)、#33861510477(9/4 18:05):pipeline success、verify success、fast tests 22 分鐘 cancelled、commit skipped |
| ② | Mac 的 GitHub 憑證(osxkeychain)~9/1 失效 → launchd 每晚 exit 128,在 `git fetch` 就中止 | `reports/_daily_logs/launchd.err.log`:7 次 `could not read Username` |
| ③ | cron-job.org 兩個 job 用的 PAT 9/4 到期 → 18:05 / 08:35 準時觸發全停 | 9/4 10:05Z 之後無 workflow_dispatch;FORWARD-RISK-REGISTER R2 早已預判此日期 |
| ④ | GHA 原生排程時間嚴重漂移,救不了場:08:35 實際落在 **~13:00**(盤中守門員擋掉);20:00 實際落在 **00:00–02:00**(過午夜,日期解析錯) | 9/4–9/12 runs 的 created_at |

### 1.3 為什麼 8 張警報沒人處理
警報沒說出「**富邦主力榜/分點只給當日,不處理明天就永久遺失**」,看起來像可以晚點再說。→ 已列 FAILURE-MODE-INDEX F-14。

---

## 2. 今天已修好(全部已推上 origin/main 並驗證)

| commit | 內容 | 驗證 |
|---|---|---|
| `cca570b` | 測試步驟移到 commit **之後**;加 `timeout-minutes` | run #281:commit 03:12:15 成功 → 測試才開始;`a6d3cc0` 已落地 |
| `4555161` | 11 個完整語料回測測試標 `@pytest.mark.slow`;`make test-fast` 排除;新增 `tests/conftest.py` | fast path 15–29 分 → **~30 秒**(544 passed / 14 failed,見 §6 待辦 T5) |
| 守門員 | `tests/test_workflow_commit_order.py`(測試不得排在 push 前、需有步驟逾時);`tests/test_slow_marker_guard.py`(讀 `_load_snapshots(` 未標 slow 即紅) | 兩者皆紅綠證明過 |
| 使用者操作 | Mac:`brew install gh` + `gh auth login`(OAuth token,**無強制到期**);cron-job.org 兩個 job 換新 **classic PAT** | 模擬 launchd 乾淨環境 `git fetch` 成功;兩 job Test run 204 |
| **當晚實戰驗收** | 9/15 18:05 雲端 run #283 + 19:00 launchd | 快照 18:14 落地(完整、39 檔);富邦主力榜抽 4 檔收盤價吻合 TWSE 9/15;測試步驟 **40 秒**;launchd fetch 成功、rebase 推進 main、exit 0(雲端已建 → 跳過)。9/1 以來首次三條路皆健康 |
| `3d67801` `2e416a1` | launchd log 停止 git 追蹤 + `.gitignore` | 見 §8 / FAILURE-MODE-INDEX F-16 |
| 本機 | 丟棄卡住的 8/31 本機 commit(origin 已有完整版,本機若保留會讓 19:00 rebase 衝突中止) | 備份於 `backup/stranded-0831-mac`(→ `8b7da17`) |

---

## 3. 資料現況

### 3.1 正式快照(origin/main,截至 9/15 下午)
| 日期 | 狀態 |
|---|---|
| 8/31、9/1、9/3 | ✅ 正常 |
| **9/2、9/7、9/8、9/9、9/10、9/11、9/14** | ❌ **缺(7 個交易日)** |
| **9/4** | ⚠️ **混日**:9/8 01:42 才建。富邦主力榜系欄位(`current_price`、`volume`、`main_force_*`)實為 **9/7**;T86/MI20/融資為真 9/4。TWSE 官方逐分核對確認(9 檔 + 正式報告 6/6)。 |
| 9/15 | 今晚 18:05(雲端)/ 19:00(Mac)建 |

**缺漏日為何補不回正式鏈**:富邦主力榜(ZGK_D/ZGK_F)與 Sinotrade 分點**只提供最新一天**,無歷史 API;`tools/backfill_range.py` 只能建沙盒重建版(不寫 reports/、不進 index)。

### 3.2 9/14 救援資料(**不是正式快照**)
位置:**`/Users/yoncky/SCD engine/_rescue/2026-09-14/`**(刻意放在 repo 外,避免被 pipeline 的 `git add data/ reports/` 掃進去)。詳見該目錄 README。
- 富邦 ZGK_F 主力買賣超:26/26 收盤價吻合 TWSE 9/14
- Sinotrade 分點:219/220 檔,逐頁驗證頁面日期 == 9/14(2867 頁面已切 9/15 → 拒收)
- 富邦 ZGK_D 外資:頁面空白(可由 T86 重建)
- 抓取窗口:9/15 15:35–15:39。**這類「只給最新一天」的來源,前一日資料的救援窗口 = 次日盤後到 ~18:00 結算前,且各檔換日時間不同,必須逐頁驗日期。**


**補建計畫(2026-09-15 擬定,尚未執行)**:在隔離 worktree 跑 `fetch_daily` 的**原組裝邏輯**,只替換資料來源 ——
主力榜/分點用救回檔;T86、融資(MI_MARGN)、成交量排行(MI_INDEX20)、全市場行情與開盤(MI_INDEX ALLBUT0999)用 TWSE **按日期**端點
改寫成 OpenAPI 格式餵給 `fetch_twse` 原解析器;外資榜用 T86 重建,**先用同法重建 9/15 並與富邦真 9/15 榜逐筆比對,吻合才用**。
`derive_trading_date` 固定為 9/14,抓取時間照實記錄(不偽造)。然後 `run_pipeline --date 2026-09-14`。
**不 commit `data/branches/` 與 `data/market_pulse.json`**(origin 上是更新的版本)。驗收:價格/主力榜對 TWSE 9/14 逐筆吻合、
完整 replay 9/14 通過且 9/15 仍通過、測試全綠、變更範圍只含 9/14 的快照/封存/index/per-date pulse/strategy_tags。

### 3.3 9 月沙盒重建(不可用)
舊 worktree 上跑過 `backfill_range` 9/1–9/14,但用的是 **7 月的 core/ingest**,且 `fetch_history` 不抓個股價/加權指數(全 0/null)。**視為無效,需在修正後重跑。**

---

## 4. 查出的資料可信度問題(影響回測,**未修**)

### 4.1 快照 `open` 普遍落後一天 → 回測 look-ahead
- `open` 來自 `today.json["openPrices"]`(TWSE STOCK_DAY_ALL OpenAPI,晚上落後一天)。
- **18–19 點例行建置:95.3% 的 `open` 是前一交易日開盤**;隔天上午建置則 85.7% 正確。5 月至今持續。
- `core/paper_trading.py:103-108 _fill_price` 用下一份快照的 `open` 撮合 → **91.2% 的回測進場價不是真正的進場日開盤**(45% 是前一日開盤=look-ahead;43% 因 open 缺值退回當日收盤)。
- 用 TWSE 真實開盤重算毛報酬(不含成本,排除 end_of_data):

| 策略 | 原 | 真實開盤 | 差 | 勝率 |
|---|---|---|---|---|
| chip_anchored_swing | −0.96% | +0.06% | +1.02pp | 52%→63% |
| chip_anchored_v2 | −1.34% | −0.53% | +0.81pp | 46%→56% |
| chip_anchored_v3 | +3.46% | +3.06% | −0.40pp | 90%→90%(n=10) |
| momentum_continuation | −0.11% | −0.40% | −0.29pp | 53%→43% |
| momentum_v2 | −0.45% | −0.48% | −0.02pp | 50%→42% |

**方向不一**(不是一律高估)。單筆最大誤差 ~15pp(例:2344 華邦電 8/5→8/21 記 +20.00%,真實 +5.39%)。**排名會變,單筆不可信。**
- 回測 JSON 的 `limitations` 仍寫「snapshots carry no open」— 過時文字。

### 4.2 回測引擎成本立方成長
`run_backtest()` 對 chip_anchored 每個交易日呼叫 `golden.run(snaps[:i+1])` 不快取。生產 log(CI)每支 chip_anchored 回測:6/29 ≈5s → 7/28 ≈27s → 8/21 ≈82s → 9/4 ≈85s(快照數 ×2.3,耗時 ×17)。
**pipeline 的回測步驟排在 commit 之前,推估 2026-12 ~ 2027-01 會撐破 job 30 分鐘上限 → 重演本次事故。**

### 4.3 回補批次快照品質
5/08–5/25(5/27 雲端批次)與 5/26–7/09(7/14 Mac 批次)兩批回補:`open` 幾乎全 null;少數日(如 6/12)連 `current_price` 都偏一天。WORM 不可改,但定基準時須標註該期間可信度低。另 7/20、7/30、8/10 三個正常建置日 `open` 全 null(STOCK_DAY_ALL 當日抓取失敗)。

### 4.4 日期解析的兩個破洞
- **過午夜**:`tools/fetch_daily.py::derive_trading_date` 只在「同日 ≥15:00」才用今天;凌晨跑會退回 TWSE OpenAPI 落後的日期 → 9/7 晚班(9/8 01:40 跑)建成 9/4。
- **15:00–18:00**:同一函式在 15:00 後就標今天,但富邦 ZGK 約 18:00 才結算 → 此時段抓到的是**前一天**主力榜卻被標成今天。

---

## 5. 待 Yonki 決定

| # | 問題 | 背景 |
|---|---|---|
| ~~D1~~ | ~~**9/4 混日快照**要不要走修正案重建?~~ **✅ 9/22 決定:只註記不重建**(EXEC-PLAN §7.4) | 修正資料須依 FORWARD-RISK-REGISTER 裁定 C:兩版皆留、supersede 鏈 |
| D2 | **9/14 救援資料**要不要組裝成正式快照? | 非標準流程組裝(富邦 ZGK_D 缺,需用 T86 補外資),修正案層級。**`36f6652` 後補插不影響後續快照,無時間壓力**;原始資料在 `/Users/yoncky/SCD engine/_rescue/2026-09-14/` |
| D3 | cron-job.org 要繼續用 classic PAT,還是換回 fine-grained(只開本 repo Actions)? | classic `repo` 範圍涵蓋所有私有 repo,放在第三方風險較大 |
| D4 | 前推樣本外紀錄的缺口怎麼處理 | 凍結(7/28)後缺 7 天 + 9/4 混日;10 月底評估的 session 數會少 |
| ~~D5~~ | ~~8 張 canary issue(#3–#10)是否附事故說明後關閉~~ **✅ 9/22 已逐張附結果說明後關閉** | #1、#2、#11、#12 仍 open(皆隔日 T+1 補建完整、資料無損) |

---

## 6. 待辦(依優先序)

| # | 項目 | 期限 | 備註 |
|---|---|---|---|
| **T1** | **回測引擎:撮合價改用 TWSE 按日期真實開盤 + 消除每日重算整段歷史** | **2026-11 底前**(12 月會撞牆) | 兩件一起做、一次重定基準;需黃金基準測試防無聲改數字;記入 EXEC-PLAN。**排除 9/4 撮合**(D1) |
| T2 | `derive_trading_date` 過午夜與 15–18 點兩個破洞 + clock matrix 補格 | 盡快 | 會影響正式快照日期標籤 |
| T3 | cron-job.org heartbeat / 警報文字寫出不可逆代價 | **2026-12-14 前**(建議 12 月第一週換發) | 到期日已記錄於 §7。⚠️ 與 R13 回測步驟撞牆窗口(2026-12 ~ 2027-01)重疊 |
| T4 | 把 `34bd7d1`(backfill 不再洩漏/覆寫 `data/history/`)套到 main 並在現行測試集重驗 | — | 修法在舊分支 `claude/sleepy-nobel-3d007c`;兩個檔 7/7 後未改,可乾淨 cherry-pick |
| T5 | 14 顆讀 gitignored `data/today.json` 的測試改用 `reports/_raw_archive` WORM fixture | — | 完成後才能移除 daily.yml 測試步驟的 `continue-on-error` |
| T6 | slow 測試的定期全量執行(本機 `make test` 或週排程) | T1 完成後 | 立方成長未修前 CI 跑不完 |
| T7 | GHA action 升級(checkout@v4.2.2、setup-python@v5.6.0 被強制跑 Node 24) | 低 | 警告,尚未失敗 |
| T8 | 回測 JSON `limitations` 過時文字 | 隨 T1 | |
| **T9** | **`deploy/daily_and_push.sh` 自癒**:(a) push 重試的 `git fetch`/rebase 失敗必須明講,不可被 `set -e` 無聲吞掉;(b) 開頭 rebase 衝突時,若本機獨有 commit 全是 `data: daily pipeline` 且其快照日 origin 已有 → 備份分支後丟棄(origin 先發布者為準)並繼續 | **盡快**(8/31、9/17 已發生兩次) | FAILURE-MODE-INDEX F-17;目前只能人工清除 |
| T10 | 9/14 正式快照補建 | D2 核准後 | 計畫見 §3.2 末 |

---

## 7. 環境與憑證(搬家必讀)

| 項目 | 現況 |
|---|---|
| Repo | `yonk2046/Maitreya`(**私有**,未授權的 API 呼叫一律 404) |
| 本機路徑 | `/Users/yoncky/SCD engine/Ai stock` |
| 本機 Python | `/usr/bin/python3`(3.9.6)。CI 為 3.11。 |
| Mac GitHub 憑證 | `gh`(Homebrew,`/opt/homebrew/bin/gh`)OAuth 登入,scopes `repo, workflow, gist, read:org`,token 存 keyring。**無強制到期。** 查帳單需另加 `user` scope。 |
| launchd | `~/Library/LaunchAgents/com.maitreya.daily.plist` → `deploy/daily_and_push.sh`,週一至五 19:00;plist PATH 含 `/opt/homebrew/bin`。Mac 需開機且未睡眠。 |
| cron-job.org | **兩個 job**,皆 POST `workflow_dispatch` 到 `daily.yml`(ref main):**08:35** 與 **18:05**。Header `Authorization: Bearer <token>`(`Bearer` 後一個空格,token 原樣貼上)。2026-09-15 換成 **classic PAT**。**到期日:2026-12-14(一)**(9/15 建立,90 天期)。Test run 應回 **204**;401=token 錯/過期,403=權限不足,404=URL 錯或看不到私有 repo,422=body 缺 `{"ref":"main"}`。 |
| Viewer | https://maitreya-jcfdybhhdp3pfkgsst8vjv.streamlit.app/(私有需登入,頁腳顯示部署 commit) |
| Actions 用量 | 9 月至 9/15:daily.yml 31 趟約 755 分鐘 + canary ~25 分。私有 repo 免費額度每月 2,000。 |
| canary | `.github/workflows/canary.yml`,週一至五 21:30,缺快照開 issue。**跑在 GHA 上 —— GHA 本身出事時它也會沉默。** |

---

## 8. Git 狀態(2026-09-22)

- `main` == `origin/main`。9/15 當日最後一個人工 commit 為本檔更新之後的那一筆;今日完整序列:`cca570b` → `4555161` → `76ba9ea` → `7211ec7` → `a2b35b6`(9/15 快照)→ `3d67801` → `2e416a1` → `e535370`。之後的 `data: daily pipeline` 為排程自動產生。
- 9/15 之後的人工 commit:`8c67b21`、`391c98e`(PAT 到期日)、`36f6652`(replay 前序依紀錄)。
- 分支:`backup/stranded-0831-mac`、`backup/stranded-0917-mac`(兩次卡住的本機快照備份,origin 已有完整版,可刪);`claude/sleepy-nobel-3d007c`(含未套用的 `34bd7d1`,見 T4);`claude/eloquent-goldwasser-cf8f57`(舊)。
- worktree:`.claude/worktrees/sleepy-nobel-3d007c`(**7 月的舊碼**,勿在其中做事)、`.claude/worktrees/vigorous-diffie-47efd7`(舊)。
- `reports/_daily_logs/launchd.{err,out}.log` **2026-09-15 起不再被 git 追蹤**(`3d67801`+`2e416a1`,守門員 `tests/test_launchd_logs_untracked.py`)。以前追蹤時永遠 dirty,`git rebase --autostash` 會換掉檔案,導致 **6/23–9/15 期間 rebase 之後的所有 launchd 輸出都遺失**(FAILURE-MODE-INDEX F-16)。從 9/16 起本機 log 應完整;若又只剩 starting/python 兩行,先查這條。
- **session scratchpad(`/private/tmp/claude-501/...`)是暫時的**,重要產出必須移出或 commit。

---

## 9. 給下一個 AI

**必讀順序**:本檔 → `ARCHITECTURE.md §5` → `docs/FAILURE-MODE-INDEX.md` → `docs/FORWARD-RISK-REGISTER.md` → `docs/migration/EXEC-PLAN-backtest-arc-20260723.md` §五–§七。

**今天踩過的坑,別再踩:**
1. **不要相信回測數字**,直到 T1 完成。§4.1 的撮合價錯誤影響所有策略。
2. **子代理的工作目錄會落在 session 預設目錄**(可能是 7 月的舊 worktree)。交辦時必須寫死 `cd <路徑> && pwd` 並要求所有 git 指令加 `-C`。本次一個子代理因此把修法做在兩個月前的程式碼上。
3. **「cancelled」≠「沒被觸發」**。先看是哪一步被砍、commit 步驟有沒有跑。
4. **不要在 15:00–18:00 或過午夜跑 pipeline 建前一日快照** —— 會混日(§4.4)。
5. **不要拿掉 daily.yml 測試步驟的 `continue-on-error`**,直到 T5 完成,否則每天一封假警報。
6. 做紅綠證明時,還原後 `touch` 檔案(pytest assert-rewrite 快取以 mtime+size 為 key)。
7. 取消/中斷 GHA run 會被 Claude Code 權限擋下 —— 請使用者自己按,或等它自然逾時。
8. 動 repo 時避開 19:00 前後(launchd 會 `git rebase --autostash origin/main`)。
