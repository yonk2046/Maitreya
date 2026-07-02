# SCD Engine — 現況稽核與不穩定點 (Audit Findings)

> Version: v1.0 (2026-05-22)
> Audience: 自己（系統重構時自查）

> 本文件假設讀者已使用 SCD 工作流程一段時間，目前出現「同樣資料、不同結果」的不穩定狀態。
> 以下逐項列出「最常見的污染源 → 為什麼會發生 → 重構後的修法」。

---

## 1. 七大不穩定症狀與根因 (Seven Symptoms & Root Causes)

### 症狀 ① ─ 同份資料、不同 ranking
**Root cause**：AI 在執行過程中參與了排序判斷（「我覺得這檔比較強」）。
**修法**：
- ranking 由 `/core/ranking.py` 純函式產出，固定 tie-breaker（見 SCORING_RUBRIC.md §5）。
- AI 的 prompt 規定只能引用既有 ranking，不可重排（見 AI_GOVERNANCE.md Rule 2）。
- CI 加 hash-equality test：同輸入兩次跑必須產出 byte-identical snapshot。

### 症狀 ② ─ 同一檔股票，今天分數 78、明天說 85（資料沒大變）
**Root cause**：門檻數字寫死在 prompt 內，prompt 在不同對話中被無意改寫（「上次寫 1.8x，這次寫 1.5x」）。
**修法**：
- 所有門檻數字搬進 `config/scd.example.yaml`。
- core 與 prompt 都只允許讀 config，不寫死。
- snapshot 內附 `config_snapshot` + `config_hash`，可審計當日所用版本。

### 症狀 ③ ─ UI 顯示與後端輸出對不起來
**Root cause**：UI 端的 JavaScript 重做了部分過濾/排序（例如 `if (score > 80 && volume > X)`）。
**修法**：
- 違反「ui 不得含業務邏輯」原則（ARCHITECTURE.md §2.5）。
- UI 只負責 render，所有 filter/sort 結果由 core 算好寫進 `rankings`。
- code review 規則：任何 PR 改 `/ui/*.html` 內 JS 含 `score`/`stage` 變數需 reject。

### 症狀 ④ ─ AI 引用了不存在的指標
**Root cause**：AI 在 long context 中混入訓練知識（如「該檔 RSI 超賣」），但本系統根本沒算 RSI。
**修法**：
- AI prompt 顯式列出 ai_readable_subset 欄位白名單（CANONICAL_SCHEMA.md §7）。
- AI_GOVERNANCE.md Rule 3 明訂幻想新指標 = 違規。
- 若真要 RSI → 先在 schema 註冊 + core 計算 + 寫進 snapshot，再 AI 引用。

### 症狀 ⑤ ─ 排序鍵不一致（有時依分數、有時依外資、有時依量）
**Root cause**：沒有「official sort order」契約，每次 ad-hoc。
**修法**：
- snapshot 內存 `rankings.sort_keys_used`，固定 5 個鍵的順序（SCORING_RUBRIC.md §5 tie-breaker）。
- UI 切換 view 不變更 ranking 本身，只變「顯示哪些欄位」。

### 症狀 ⑥ ─ 集保股權分散用了「上週」資料當「本週」算 delta
**Root cause**：TDCC 是週報，更新有 lag。core 若以 `date` 為基準，會把同一份 TDCC 用兩次。
**修法**：
- provenance 區塊強制標記 `fetched_at`。
- core 計算 delta 時必須比對 TDCC 自己的兩個快照（上一週 vs 本週），不可隔太近。
- 若 TDCC 尚未更新本週：`shareholder_count_delta_pct = null`，並在 audit_log 紀錄 DATA_WARNING。

### 症狀 ⑦ ─ Snapshot 看不出「為什麼這檔被剔除」
**Root cause**：filter 邏輯失敗時只是 silently drop。
**修法**：
- 任何被 gate 剔除的股票仍寫入 `stocks[]`，但 `eliminated_by` 填 `"G1"|"G2"|"G3"`，並在 `audit_log` 加一筆 reason 字串。
- AI 解讀層可用此資訊回覆「為什麼 2317 今天不在 Golden」。

---

## 2. 必跑稽核腳本（建議 CI）

```bash
# A. Hash-equality
python -m core.pipeline --date 2026-05-22 > /tmp/run1.json
python -m core.pipeline --date 2026-05-22 > /tmp/run2.json
sha256sum /tmp/run1.json /tmp/run2.json   # 兩個 hash 必相同

# B. Config drift (no magic numbers in /core)
ast-grep --pattern 'NumericLiteral' core/ \
  | grep -vE '\b(0|1|-1)\b'  # 應為空輸出

# C. AI quarantine
grep -rE "openai|anthropic|llm|claude" core/ data/   # 應為空輸出

# D. Schema validation
jq -c '.' reports/2026-05-22.json \
  | python -m jsonschema -i - schema/canonical_schema.json

# E. Invariants
python -m tests.invariants reports/2026-05-22.json   # 全綠才可 ship
```

---

## 3. 重構路徑優先序 (Refactor Priority)

| Priority | 動作 | 投入 | 回報 |
|---|---|---|---|
| P0 | 寫死所有門檻數字進 config + bump core 為純函式 | 小 | 立即消除症狀 ①②③⑤ |
| P0 | 凍結 daily snapshot 並計算 SHA-256 | 小 | 消除症狀 ① 的可疑性 |
| P1 | AI prompt 套 AI_GOVERNANCE.md 樣板 | 小 | 消除症狀 ④ |
| P1 | UI 移除所有業務邏輯 | 中 | 消除症狀 ③ |
| P2 | TDCC 週報專屬時序對位 | 中 | 消除症狀 ⑥ |
| P2 | audit_log 全面記錄 | 小 | 消除症狀 ⑦ |
| P3 | 回測引擎 (replay 歷史 snapshot) | 大 | 驗證新 config 是否更好 |

---

## 4. 「決定論測試」的最小可行版本 (Smallest viable determinism test)

```python
# tests/test_determinism.py
import hashlib, json, subprocess

def sha(path): return hashlib.sha256(open(path,"rb").read()).hexdigest()

def test_snapshot_deterministic(tmp_path):
    out1 = tmp_path / "r1.json"
    out2 = tmp_path / "r2.json"
    subprocess.check_call(["python","-m","core.pipeline","--date","2026-05-22","--out",out1])
    subprocess.check_call(["python","-m","core.pipeline","--date","2026-05-22","--out",out2])
    assert sha(out1) == sha(out2), "Pipeline is non-deterministic"
```

**這支測試是整個系統的『憲法守門員』。一旦它紅了，整個 build 必須擋下，不准 ship。**

---

## 5. 重構完成的驗收 (Definition of Done)

- [ ] `config/scd.yaml` 包含所有門檻；`grep -rn "1\.05\|1\.8\|140" core/ data/` 結果為 0
- [ ] `reports/*.json` 對同輸入 sha256 一致
- [ ] `audit_log` 對每筆 elimination / data_warning 有明確 step + reason
- [ ] AI 不能在不引用 snapshot 路徑的情況下回覆任何分數相關問題
- [ ] UI 不存在任何 `if (score > X)` 等業務邏輯
- [ ] 一份 5 行 README 能讓新人 30 分鐘內理解「core 跑哪→ snapshot 在哪 → AI 讀哪 → UI 顯示哪」
