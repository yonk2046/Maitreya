# Maitreya — 操作手冊 Runbook

## 正常情況（不需要做任何事）

每個交易日 **19:00 台灣時間**，GitHub Actions 自動執行：
1. 抓大盤脈搏（TAIEX / 台指期 / 三大法人）
2. 抓個股資料（主力 / 外資 / 投信 / 分點）
3. 計算並存入快照
4. Commit + Push 回 GitHub

Streamlit Cloud 下次有人開頁面就會載入最新資料。

---

## 查看 Actions 狀態

https://github.com/yonk2046/Maitreya/actions

- 綠色 ✓ = 正常
- 橘色 (warnings) = 正常，replay mismatch 是已知問題，不影響資料
- 紅色 ✗ = 有問題，點進去看 log

---

## 資料沒更新怎麼辦

### Step 1 — 確認 Actions 有沒有跑

去 Actions 頁面看今天有沒有成功的 run。

### Step 2 — Actions 成功但 Streamlit 沒更新

去 Streamlit Cloud reboot：
https://share.streamlit.io → Maitreya → Manage app → Reboot app

### Step 3 — Actions 失敗了

**直接在 GitHub Actions 重新觸發，不要在本機跑：**

https://github.com/yonk2046/Maitreya/actions → Maitreya Daily Pipeline → Run workflow → Run workflow

等它跑完（3–5 分鐘），再去 Streamlit reboot。

### Step 4 — Actions 一直失敗（極端情況）

只有在 Actions 完全無法用時才在本機補跑，且等 **14:30 之後**（TWSE 資料出來後）：

```bash
cd "/Users/yoncky/SCD engine/Ai stock"
git pull                         # 先同步，避免衝突
make daily
git add data/ reports/
git commit -m "data: manual pipeline YYYY-MM-DD"
git push
```

---

## 大盤脈搏顯示 — 正確顯示時間

| 資料 | 何時可用 |
|------|---------|
| TAIEX 收盤指數 | 13:30 收盤後約 30–60 分鐘 |
| 台指期 | 13:45 後 |
| T86 外資/投信 | 14:00–14:30 |

Actions 排在 19:00 跑，所有資料都已出來。
手動在開盤前/盤中觸發 → TAIEX 會是空值，這是正常的。

---

## 常見錯誤對照表

| 錯誤訊息 | 原因 | 解法 |
|---------|------|------|
| `[rejected] non-fast-forward` | 本機比遠端舊 | `git pull --rebase origin main` 再 push |
| `index.lock exists` | git 上次沒收尾 | `rm .git/index.lock` |
| `verify-all-replay FAILED` | replay mismatch，已知問題 | 忽略，資料正確 |
| TAIEX 顯示 — | 盤中抓取，TWSE 未出資料 | 14:30 後重新抓 |
| 法人同向資料待補 | 舊 snapshot 沒有 T86 資料 | 今天起的新 snapshot 會有 |
| 主力成本無資料 | 該股券商未提供分點成本 | 資料來源限制，無法補 |

---

## 修改程式碼後的標準流程

1. 改完 code，在本機測試
2. `git add` + `git commit` + `git push`
3. **不要**手動觸發 Actions（等 19:00 自動跑）
4. 如果需要立即測試，等推完 code 再去 Actions Run workflow

**核心原則：同一時間只有一個來源在 push（Actions 或你，不要同時）**
