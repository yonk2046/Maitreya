# Maitreya — 操作手冊 Runbook

> 最後更新：2026-07-02（併入 STREAMLIT_DEPLOY.md 精華，修正兩條 pipeline 說明）

## 正常情況（不需要做任何事）

每個交易日有兩條 pipeline（OPS-1）：

| | 時間（台灣） | 執行者 |
|---|---|---|
| **主** | 19:00 | 本機 launchd（Mac 要開機） |
| **備** | 20:00 | GitHub Actions `daily.yml`（主已 commit 當日快照則自動跳過） |

每次執行：
1. 抓大盤脈搏（TAIEX / 台指期 / 三大法人）
2. 抓個股資料（主力 / 外資 / 投信 / 分點）
3. 計算並存入快照 + 跑 4 策略回測
4. Commit + Push 回 GitHub

Streamlit Cloud 下次有人開頁面就會載入最新資料。

---

## 查看 Actions 狀態

https://github.com/yonk2046/Maitreya/actions

- 綠色 ✓ = 正常
- 橘色 (warnings) = 正常，replay mismatch 是已知問題，不影響資料
- 紅色 ✗ = 有問題，點進去看 log（注意：GHA 是備援，主 pipeline 在 launchd，先看本機 log）

---

## 資料沒更新怎麼辦

### Step 1 — 確認主 pipeline（launchd）有沒有跑

```bash
cd "/Users/yoncky/SCD engine/Ai stock"
make daily-status    # launchd 排程狀態
make daily-tail      # 最新 daily log
```

### Step 2 — 確認 GHA 備援

去 Actions 頁面看今天有沒有成功的 run（20:00 後）。

### Step 3 — Pipeline 成功但 Streamlit 沒更新

去 Streamlit Cloud reboot：
https://share.streamlit.io → Maitreya → Manage app → Reboot app

### Step 4 — 兩條都失敗

GitHub Actions 手動觸發：Actions → Maitreya Daily Pipeline → Run workflow。
等它跑完（3–5 分鐘），再去 Streamlit reboot。

### Step 5 — Actions 也完全無法用（極端情況）

本機補跑，且等 **14:30 之後**（TWSE 資料出來後）：

```bash
cd "/Users/yoncky/SCD engine/Ai stock"
git pull --rebase                # 先同步，避免衝突
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

排程在 19:00/20:00 跑，所有資料都已出來。
手動在開盤前/盤中觸發 → TAIEX 會是空值，這是正常的。

---

## 常見錯誤對照表

| 錯誤訊息 | 原因 | 解法 |
|---------|------|------|
| `[rejected] non-fast-forward` | 本機比遠端舊 | `git pull --rebase origin main` 再 push |
| `index.lock exists` | git 上次沒收尾 | 確認沒有在跑，`rm -f .git/index.lock` |
| `verify-all-replay FAILED`（跨平台紅字） | Mac 建 / linux 驗指紋差異，已知 | 忽略，資料正確（observation-hash 契約會根治） |
| TAIEX 顯示 — | 盤中抓取，TWSE 未出資料 | 14:30 後重新抓 |
| 法人同向資料待補 | 舊 snapshot 沒有 T86 資料 | 新 snapshot 會有 |
| 主力成本無資料 | 該股券商未提供分點成本 | 資料來源限制，無法補 |

---

## 修改程式碼後的標準流程

1. 改完 code，在本機測試
2. `git add <檔>` + `git commit` + `git push`（**push 前一定要先 commit**）
3. **不要**手動觸發 Actions（等 19:00 launchd 自動跑）
4. 如果需要立即測試，等推完 code 再去 Actions Run workflow

**核心原則：同一時間只有一個來源在 push（launchd / Actions / 你，不要同時）**

---

## 附錄 — Streamlit Cloud 部署（已完成，重部署時參考）

原 `STREAMLIT_DEPLOY.md`（2026-06 部署完成後併入此處）。

1. https://share.streamlit.io → 以 GitHub 帳號（yonk2046）登入
2. New app → Repository: `yonk2046/Maitreya` · Branch: `main` · Main file: `Ai stock/viewer/cockpit.py`
3. Deploy（首次約 3–5 分鐘，依 `requirements.txt` 安裝）

驗收：頁面載入（深色主題）、sidebar 有快照日期、各 tab 正常渲染。

成本：GitHub private repo + Actions（~10 min/日，額度 2000 min/月）+ Streamlit Community Cloud 全部免費。
無伺服器、無 VPS、無 Docker；Mac 關機時由 GHA 備援 pipeline 更新資料。
