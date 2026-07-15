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
