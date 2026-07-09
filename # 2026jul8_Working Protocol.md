# Working Protocol

這不是一次性的 Code Review。

這是一個持續數週的 Architecture Research。

請不要試圖在一次對話中分析整個 SCD Engine。

請不要一次提出大量重構方案。

請不要因為看到某個問題，就立刻修改它。

我們的目標不是快速修正，而是逐步建立一套穩定、可演化的 Knowledge Architecture。

---

## 工作方式

整個研究將拆成多個 Session。

每一個 Session 只專注一個主題。

例如：

* Session 01 — Golden Layer
* Session 02 — Chip Momentum
* Session 03 — Distribution
* Session 04 — State Machine
* Session 05 — Data Contract
* Session 06 — Replay Contract
* Session 07 — Market Context
* Session 08 — Frontend Presentation
* Session 09 — Backtest Logic

每個 Session 都必須獨立完成。

不要因為未來可能會重構，就提前修改其他模組。

---

## 每個 Session 的目標

每次只回答四個問題：

1. 這個模組真正要回答什麼問題？
2. 它屬於哪一層？（Raw / Observation / Derived / Classification / Presentation / Metadata）
3. 它目前有哪些設計混亂或責任重疊？
4. 如果今天重新設計，它最合理的責任邊界應該是什麼？

請先完成分析，再討論是否需要修改。

不要跳過分析直接提出 Solution。

---

## 重要原則

在完成所有 Session 之前：

* 不要急著重新命名欄位。
* 不要急著修改 Schema。
* 不要急著新增評分系統。
* 不要急著重構 UI。
* 不要急著修改 Replay Contract。

我們先理解系統，再決定如何演化系統。

Architecture 應該來自於理解，而不是來自於不停重構。

---

如果你發現某個問題會影響其他 Session，可以記錄下來，但不要提前展開。

請建立一份「Cross-Session Notes」，等相關 Session 再一起討論。

避免因為局部最佳化，而破壞整體架構。
