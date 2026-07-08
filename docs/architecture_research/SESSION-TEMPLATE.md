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
- 責任邊界結論：
- 需要改的（**只記錄，不執行**；影響他 session 的 → 同步 append 到 CROSS-SESSION-NOTES）：
- 不需要改的（現況即合理，避免未來被誤重構）：
- 對已鎖決策的相容性檢查（扁平前綴 / additive 遷移 / C1–C6）：

## §6 收尾 checklist
- [ ] CROSS-SESSION-NOTES 已 append 本 session 新發現
- [ ] 00-INDEX 狀態列已更新（證據包/裁定/報告連結）
- [ ] 未執行任何 code/schema 改動
