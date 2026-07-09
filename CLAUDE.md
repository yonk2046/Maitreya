# Maitreya / SCD Engine — Claude 專案指令(薄路由,規則正本不在此)

## 開工順序(每個 session 照做,不要跳)

1. 讀 `~/.agents/indexes/CLAUDE.index.md` → 按它載入常載三檔(工作規則/調度/判斷 rubric)。
2. 讀本 repo **最新日期**的 `MAITREYA_HANDOFF_*.md`(現為 20260706)——目前狀態/已知雷/待辦優先序都在裡面。
3. 跑 `git log --oneline -10` 確認 handoff 之後有沒有新 commit。
4. 架構/紅線細節按需讀 `ARCHITECTURE.md`(§⛔ AI_GOVERNANCE 五條紅線必須遵守)。

## 待辦優先序(以最新 handoff §5 為準,此處僅鏡像)

兩段式快照 → 重建 7/02+7/03 滯後快照 → 1.9.0 打包(fetchDate/universe/fii_buy_ratio) → B1 隔日沖標記

## 本機環境(Claude Code 在 Yonki 的 Mac 上,與 Cowork 沙箱不同)

- 你**可以**直接 git commit/push(先 pull --rebase)、直接連 TWSE/Sinotrade 抓資料、直接跑 make。
- 慣例:push 前先 commit;pipeline 資料 commit 訊息用 `data:` 前綴、程式用 `fix:/feat:`;
  reports/_raw_archive 是 WORM 禁改;滯後資料絕不冒充當日(t86Date gate 是底線)。
- 測試:`make test`;全量重放:`make verify-all-replay`;UI 本機看:`make restart-cockpit` → :8502。

## 分工(這個 repo 的哪類事歸誰)

- 歸你(Claude Code):改 code、修 pipeline、跑抓取與驗證、git、除錯、回測執行。
- 歸 Cowork:回測解讀報告、UI/UX 討論、文件整併、盤後資料解讀。你被問到這類事可以做,但提醒使用者 Cowork 較合適。

## 使用者是誰

Yonki,設計背景非工程師,繁中溝通,能貼終端指令。給指令要完整可貼上。他重視:資料正確>速度、
一次講一個重點、每個專有名詞要有白話解釋。
