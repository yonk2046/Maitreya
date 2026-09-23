---
paths: ["tools/**/*.py"]
---
# tools/ pipeline 操作鐵則（規範正本＝docs/ARCHITECTURE_BLUEPRINT.md；風險登記簿 docs/FORWARD-RISK-REGISTER.md）

- **雲端優先**：daily.py 的 remote-first 守門（origin 已有當日快照→pull 跳過；網路失敗 fail-open 照跑；
  `--force-local` 繞過）。本機 launchd 19:00 只是備援。
- trading-day oracle **fail-closed**：只有正面證明開盤才建快照；「T86 缺席」不是放假證據，
  `--allow-partial` 正是繞過該訊號的開關（7/10 殭屍事故根因）。
- build-order invariant（補充裁定 B）與 ingest 日期 guard（raw tradingDate==目標日，INGEST_DATE_MISMATCH）不可弱化。
- run_pipeline 的 `_assert_lookback_fresh`＝build-time 不變量（裁定 W6-1），寫入/attest 前 fail fast，不可繞過。
- replay strip 清單唯一來源＝`core/replay_contract.py`（從 registry excluded-M 派生），不要另開黑名單。
- 長任務紀律：**先 commit 再長驗證**（P2 期間 4 次 agent 中斷全靠這條零損失）。
- **改任何會讀時鐘／日曆的東西前，先看 `docs/FAILURE-MODE-INDEX.md`**：已發生事故按
  「時刻 T／日型 D／執行者 M／上游 U」歸軸，每列指名可執行守門員。`make test` 固定在
  「執行的那一刻」，測不到這四軸——那是「改一改隔天壞掉」的固定形狀。守門員＝
  `tests/test_clock_matrix.py`（凍結時鐘＋產物不變式）。
- **「只給最新一天」的來源**(富邦 ZGK_D/ZGK_F、Sinotrade 分點、TWSE STOCK_DAY_ALL OpenAPI)**晚建/補建必混日**:
  過午夜或次日才建前一日快照時,這些欄位會是較新的日期,而 T86/MI_MARGN 是按日期抓的正確日期(9/4 事故)。
  **15:00–18:00 與過午夜不得建前一日快照。** 要救前一日資料,窗口是次日盤後到 ~18:00 結算前,且**逐頁驗證頁面日期**
  (各檔換日時間不同)。救援品存 repo 外(`/Users/yoncky/SCD engine/_rescue/`),避免被 `git add data/ reports/` 掃進去。
- **CI 測試必須排在 commit 之後**(`tests/test_workflow_commit_order.py` 守門):`continue-on-error` 管不到 job 層逾時,
  排在前面會連帶丟棄已建好的快照(9 月斷更 7 天)。在 14 顆讀 `data/today.json` 的測試改用 WORM fixture 之前,
  **不要移除測試步驟的 `continue-on-error`**(否則原生 08:35 cron 盤中落地時每天假紅)。
- 讀完整語料跑回測的測試必須標 `@pytest.mark.slow`(`tests/test_slow_marker_guard.py` 守門);回測成本隨快照數立方成長。
- 最新交接 = repo 根目錄 `MAITREYA_HANDOFF_20260923.md`;觸發器正本 = `ARCHITECTURE.md §5`(實測版)。
