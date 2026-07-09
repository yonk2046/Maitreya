# Session NN — <模組名>（範本）

> 用法：證據蒐集者（opus/sonnet）複製本檔為 `sessions/SNN-<主題>.md`，填 §0–§4 的證據草稿；
> 裁定者（fable）只讀本報告 + `CROSS-SESSION-NOTES.md`，完成 §5 裁定與 §6。
> 鐵律：**先分析、後才談改**；本報告不含任何 code 改動；證據一律附 `檔案:行號`。

## §0 範圍與輸入
- 本 session 只看：<模組檔案清單>
- 讀過的證據來源：<file:line 列表 / 實跑指令與輸出摘要>
- 明確不看（留給哪個 session）：<...>

## §1 這個模組真正要回答什麼問題？
（一段話。它存在的理由；使用者/下游拿它的輸出做什麼決定。）

## §2 它屬於哪一層？
Raw / Observation / Derived / Classification / Presentation / Metadata
（若跨層 → 逐一列出哪部分屬哪層，附證據。跨層本身常是 §3 的病灶。）

## §3 目前有哪些設計混亂或責任重疊？
（逐條列，每條附 file:line 證據。只描述，不開藥方。與其他模組的重疊指名對方。）

## §4 如果今天重新設計，最合理的責任邊界是什麼？
（理想態描述：輸入是什麼、輸出是什麼、絕不做什麼。與現況的差距列表。）

## §5 裁定（fable 填）

> **裁定 rubric**（Chief-Architect 框架，Yonki 2026-07-09 立；範例見 S05 §5）。目標是**壓縮複雜度，不是增產發現**——把 §3 的實作發現壓成最少的架構真相：
> ① Root-cause 聚類：全部發現壓成最小集合，敢挑戰證據包的切分（一病拆多條要併回）
> ② 雜訊分離：哪些技術正確但架構不重要，說明為何
> ③ 責任洩漏檢查：有無混入他 session 範疇（Data/Replay/Presentation/Engine/Governance）
> ④ 缺失概念：SoT/ownership/lifecycle/versioning/boundary……只列真正有用的
> ⑤ 挑戰證據包：重複發現/隱藏假設/錯誤抽象/過度工程（只對已驗證證據挑戰，不做第三次 code review）
> ⑥ Architecture Verdict：P0(架構阻斷=後續 session 的裁定依賴) / P1(重要) / P2(治理改善) + 理由。凍結期語意＝立約順序，非修復排程
> ⑦ Executive Summary ≤5 條，另一位架構師兩分鐘讀懂

- 系統身份判準：Observation-First / snapshot=System of Record（NOTES #10）之下，本模組的角色是什麼
- 責任邊界結論：
- 需要改的（**只記錄，不執行**；影響他 session 的 → 同步 append 到 CROSS-SESSION-NOTES）：
- 不需要改的（現況即合理，避免未來被誤重構）：
- 對已鎖決策的相容性檢查（扁平前綴 / additive 遷移 / C1–C7 / 三態詞彙 NOTES #11）：

## §6 收尾 checklist
- [ ] CROSS-SESSION-NOTES 已 append 本 session 新發現
- [ ] 00-INDEX 狀態列已更新（證據包/裁定/報告連結）
- [ ] 未執行任何 code/schema 改動
