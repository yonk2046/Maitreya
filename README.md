# Maitreya — 台股主力行為觀測引擎

> *彌勒觀市，不測，只記。*
>
> Repo：`yonk2046/Maitreya` · Viewer：Streamlit Cloud（`viewer/cockpit.py`）
> 最後更新：2026-07-02

---

## 一句話 (TL;DR)

**Maitreya = TWSE 股票的決定論狀態偵測引擎（SCD）。** 每交易日自動抓主力分點＋外資＋投信資料，算籌碼動能，存進不可篡改、可 byte-for-byte 重放的快照。同一份輸入永遠產同一份 snapshot。

**哲學**：籌碼 > 心理 > 消息 > 預測。不預測，只偵測「主力正在做什麼」。
**紀律**：連買 <3 日不進場；現價 ≤ 主力成本 ×1.05；空手是獲利的一部分。

---

## 從哪開始讀

| 想知道 | 讀這份 |
|---|---|
| **現在進度 / 待辦 / 已知 bug** | 最新的 `MAITREYA_HANDOFF_*.md`（唯一的進度真理來源） |
| 系統結構、紅線、設計決策 | `ARCHITECTURE.md` |
| 日常操作、資料沒更新怎辦 | `RUNBOOK.md` |
| 開發規範、路徑/環境 quirk | `CONTRIBUTING.md` |
| Replay / schema / WORM 等規格 | `docs/`（部分為 2026-05 凍結規格，實作以 code 為準） |
| 歷史 handoff / 已完成的規格 | `docs/handoffs/`、`docs/archive/` |

---

## 黃金名單（現行制）

`core/golden.py`：G1-G5 五道 gate 全過 → conviction 加權分 → 內部 tier（prime/strong/qualified）→ 前端顯示 **🟢可買進 / ◆增強 / ●中**（`display_tier()`，可買進 = PRIME + 現價≤主力成本×1.05 + 未轉弱）。

門檻全在 `config/scd.example.yaml`。
⚠️ 舊制「GOLDEN ≥85 / WATCH ≥70」（docs/SCORING_RUBRIC.md）已不用，以 `core/golden.py` 為準。

---

## 每日自動流程

```
launchd 19:00（主）/ GHA 20:00（備，skip-guard）
fetch → ingest → verify replay → intelligence → backtest×4 → commit+push
Streamlit Cloud 下次載入頁面即更新
```

---

## 常用指令

```bash
make daily               # 完整每日流程
make verify-all-replay   # 全量重放驗證
make test                # pytest 全套
make cockpit             # UI :8502
python -m tools.run_backtest --strategy chip_anchored_swing --latest-only
```

---

## 給未來自己的提醒

- 想加新指標 → 先進 schema → 再進 core → 再進 viewer。**不可跳關。**
- 想調門檻 → 改 config，commit message 寫理由。不要改程式碼。
- 想讓某檔進黃金名單 → 看它卡在哪道 gate，是該檔不適合，還是規則該調。
- 系統開始不穩 → 第一步永遠是 replay 驗證，跑兩次比對 hash。
