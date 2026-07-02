# SCD Engine — Replay & Reproducibility 規格

> Version: v1.0 (2026-05-22) — corresponds to P1 phase
> Schema: canonical_schema v1.2.0
> 對應 SCORING_RUBRIC.md v1.1 (本階段**不變動**分數規則)

---

## 0. 一句話 (TL;DR)

**任何「過去某日的 snapshot」必須能在未來任意時點被 byte-for-byte 重建。** 重建失敗 = build fail。
*Any historical snapshot must be byte-for-byte reproducible at any future point. Failure = build break.*

---

## 1. Replay 的成功定義 (Definition of Successful Replay)

給定一份 snapshot `reports/2026-05-22.json`，replay 視為成功，當且僅當：

1. 從快取的 `data/raw/2026-05-22/` 重新跑 `/core` pipeline
2. 用同一份 `config/scd.yaml`（透過 `config_hash` 找回）
3. 用同一個 `core` git SHA（從 `environment.core_commit_sha` checkout）
4. 用同一個 Python / NumPy / Pandas 版本（從 `environment.*` pin）
5. 產出的新 snapshot **canonical SHA-256 與原 snapshot sidecar `.sha256` 完全相同**

任一條件失敗，必須在 `audit_log` 留 `event: HASH_MISMATCH` 並阻止 ship。

---

## 2. Replay 必要輸入 (Replay Inputs)

| 輸入 | 來源 | 存放位置 |
|---|---|---|
| 原始資料 (raw) | 來自 `/data` adapter 抓取後落地的檔案 | `data/raw/<date>/*` (WORM) |
| Config | 該日所用 config 副本 | snapshot 內 `config_snapshot` |
| Engine | `core` 的 git commit | snapshot 內 `environment.core_commit_sha` |
| 依賴環境 | Python / numpy / pandas 等版本 | snapshot 內 `environment` |
| Schema 規格 | canonical_schema.json 版本 | snapshot 內 `schema_version` |
| 時區 | UTC 為唯一時間軸 | snapshot 內所有 timestamp 皆 ISO 8601 UTC `Z` |

**缺任一項 = 無法 replay**。CI 必須對每份 snapshot 跑 `replay_check.py` 確認以上全在。

---

## 3. Snapshot Integrity 不變式 (Snapshot Integrity Invariants)

| # | 規則 | 違反後果 |
|---|---|---|
| I1 | Snapshot 檔一旦寫入 `reports/` 即不可修改 (immutable) | 必須改成 `<date>.v2.json` 新檔，並在 `reports/index.json` 標 `supersedes` |
| I2 | Snapshot 檔的 canonical SHA-256 寫入 sidecar `<date>.json.sha256` | sidecar 必須與 snapshot 同時寫入；兩者皆 read-only after write |
| I3 | `reports/index.json` 記錄 `date → snapshot_hash → schema_version → supersedes_chain` | CI 對每份新 snapshot 自動更新 index |
| I4 | Snapshot 內所有 timestamp 均為 ISO 8601 UTC, 必以 `Z` 結尾 | grep `-E '\\+[0-9]{2}:[0-9]{2}' reports/*.json` 必為空 |
| I5 | `environment` 區塊必含 7 欄：`core_commit_sha, python, numpy, pandas, decimal_context, locale, timezone` | jsonschema 強制 required |
| I6 | `raw_data_hashes` 必為每個輸入檔的 SHA-256 (sha256:<hex>) | 缺者 = 不可 replay |

---

## 4. Canonicalization 規約 (Canonical Form for Hashing)

> 這是 hash 一致性的最核心定義。**任何實作必須使用此規約。**

```text
canonical_bytes(snapshot) =
  json.dumps(
      snapshot,
      sort_keys      = True,
      ensure_ascii   = False,         # 保留中文，但寫入 UTF-8
      separators     = (',', ':'),    # 無多餘空白
      allow_nan      = False           # NaN / Inf 一律拒絕
  ).encode('utf-8')

snapshot_hash = sha256(canonical_bytes(snapshot)).hexdigest()
```

**注意**：
- `snapshot` 必須是 Python `dict`（或 `OrderedDict`），不能含 `Decimal` 直接序列化 — Decimal 必須先轉 `str`（這也符合 §0.3 Numeric Policy N1）。
- `snapshot_hash` 本身**不存於 snapshot 內**，避免 bootstrapping problem。它寫在 sidecar `reports/<date>.json.sha256` 與 `reports/index.json`。

---

## 5. Replay Workflow 完整流程

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 載入目標 snapshot                                          │
│    snap = json.load(open("reports/2026-05-22.json"))         │
│    target_hash = open("reports/2026-05-22.json.sha256").read()│
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 還原環境                                                  │
│    git checkout {snap.environment.core_commit_sha}           │
│    pyenv use     {snap.environment.python}                   │
│    pip install   numpy=={snap.environment.numpy} \           │
│                  pandas=={snap.environment.pandas}            │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 還原 config                                               │
│    cfg = snap.config_snapshot                                │
│    assert sha256(canonical(cfg)) == snap.config_hash         │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 還原 raw data                                             │
│    for src_id, meta in snap.provenance.sources.items():     │
│      f = open(meta.raw_file, "rb").read()                    │
│      assert sha256(f) == meta.raw_sha256                     │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 重跑 pipeline                                             │
│    new_snap = core.run_pipeline(date=snap.date, cfg=cfg)     │
│    new_hash = sha256(canonical_bytes(new_snap)).hexdigest()  │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. 比對                                                      │
│    if new_hash == target_hash:                               │
│       emit REPLAY_VERIFIED                                   │
│    else:                                                     │
│       emit HASH_MISMATCH + jdiff(snap, new_snap)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 什麼會破壞 Replay (Things That Break Replay)

對應 AUDIT_v1.0.md §3 + 新增。

| 破壞點 | 為何 | 解法 |
|---|---|---|
| 浮點而非 Decimal | 跨平台 IEEE 754 不一致 | §0.3 N1 強制 Decimal |
| `generated_at` 進入 hash | 牆鐘時間每秒不同 | hash 不包含 `generated_at`（見 §4 — 全部欄位都進，但 `generated_at` 是「資料窗口時間」非牆鐘時間） |
| `dict` 順序 | Python 3.7+ 保序，但 YAML loader 不保證 | canonical `sort_keys=True` |
| NaN / Inf | json 序列化非標準 | `allow_nan=False` |
| 區域數字格式 | `1,234.56` vs `1.234,56` | `LC_NUMERIC=C` rule (env §7) |
| 時區 | 同一時刻寫成不同字串 | 全 UTC `Z` |
| NumPy / Pandas 版本 | 統計函式輸出在 1.x 與 2.x 不同 | environment 鎖版本 |
| 字串 normalization | NFC vs NFD (中文標題如「群創」) | canonical 前先 NFC normalize |
| Hash 自包含 (self-hash) | 經典 bootstrap 問題 | snapshot_hash 寫 sidecar，不入檔 |
| 資料修正後就地覆蓋 | 破壞 immutability | 修正必須產 `<date>.v2.json` 新檔 |

---

## 7. Locale & 字串標準化

```
LC_ALL  = "C.UTF-8"
LC_NUMERIC = "C"
PYTHONHASHSEED = 0           # 雖然不影響 sort_keys 序列化，但鎖死避免遺漏
TZ = "UTC"                    # 程式內部時區
```

中文字串（公司名、分點名）寫入 snapshot 前必須 NFC normalize：

```python
import unicodedata
def n(s): return unicodedata.normalize("NFC", s)
```

---

## 8. Audit Event 增補 (Audit Event Additions)

新增至 `canonical_schema.json` 的 `audit_log[].event` enum：

| Event | 何時 emit | reason 內容 |
|---|---|---|
| `REPLAY_VERIFIED` | replay 跑出來 hash 與原 snapshot 一致 | `"new_hash=sha256:... matches target"` |
| `HASH_MISMATCH` | replay hash 不同 | `"target=sha256:abc... new=sha256:def... first_diff_path=stocks[3].main_force_buy"` |
| `RAW_DATA_HASH_MISMATCH` | raw data sha256 與 provenance 不符 | `"source=twse_three_institutional expected=sha256:xx actual=sha256:yy"` |
| `CONFIG_HASH_MISMATCH` | config 還原後 hash 對不上 | `"config_snapshot hash differs from config_hash"` |
| `ENVIRONMENT_DRIFT` | 環境某項版本不同 (replay 可繼續，但會留警告) | `"runtime numpy=1.26.4 differs from snapshot numpy=1.26.3"` |
| `SCHEMA_VERSION_MISMATCH` | snapshot 的 schema_version 與本地不同 | `"snapshot schema_version=1.2.0 cannot be replayed by core@... built for 1.3.0"` |

---

## 9. Provenance 結構 (Per-source granularity)

> Patch P1-3. 取代 v1 的 `provenance.<group>.{source,fetched_at}`。

```jsonc
"provenance": {
  "sources": {
    "twse_three_institutional": {
      "dataset":      "TWSE.three_institutional.daily",
      "url":          "https://www.twse.com.tw/rwd/zh/fund/T86",
      "fetched_at":   "2026-05-22T07:30:12Z",
      "raw_file":     "data/raw/2026-05-22/twse_three_institutional.csv",
      "raw_sha256":   "sha256:6f3a...",
      "row_count":    1812,
      "provides_fields": ["fii_net_buy", "fii_buy_ratio"]
    },
    "tdcc_weekly_distribution": {
      "dataset":      "TDCC.weekly_distribution",
      "report_date":  "2026-05-17",
      "data_lag_days": 5,
      "fetched_at":   "2026-05-22T01:00:00Z",
      "raw_file":     "data/raw/2026-05-22/tdcc_weekly_2026-05-17.csv",
      "raw_sha256":   "sha256:1a2b...",
      "provides_fields": ["shareholder_count", "large_holder_400_pct", "large_holder_1000_pct"]
    }
  },

  "field_to_source": {
    "fii_net_buy":               "twse_three_institutional",
    "shareholder_count":         "tdcc_weekly_distribution",
    "top5_branches":             "vendor_broker_chip",
    "margin_maintenance_ratio":  "twse_margin"
  },

  "derived_fields": {
    "main_force_buy": {
      "derived_from": ["top5_branches[*].net"],
      "formula":      "sum",
      "step":         "core.derivations.main_force_buy"
    },
    "volume_ratio": {
      "derived_from": ["volume", "volume_5d_avg"],
      "formula":      "volume / volume_5d_avg",
      "step":         "core.derivations.volume_ratio"
    },
    "main_force_consecutive_days": {
      "derived_from": ["top5_branches series (5 sessions)"],
      "formula":      "longest_consecutive_net_buy_run",
      "step":         "core.derivations.mf_consec_days"
    }
  }
}
```

**好處**：
- 任一欄位都能 `field_to_source[field]` → 取得 source ID → 取得 raw_file 與 raw_sha256
- Derived 欄位明示 derived_from + step，事後追溯不會「不知道從哪算出來」
- raw_sha256 進入 replay check 防止資料污染

---

## 10. Environment 區塊 (Environment Block)

新增至 snapshot 頂層：

```jsonc
"environment": {
  "core_commit_sha":  "abc1234567890def...",
  "core_version":     "core@1.0.0+abc1234",  // human-readable, redundant with sha
  "python":           "3.11.7",
  "numpy":            "1.26.4",
  "pandas":           "2.2.0",
  "pyyaml":           "6.0.1",
  "jsonschema":       "4.26.0",
  "decimal_context":  { "prec": 28, "rounding": "ROUND_HALF_EVEN" },
  "locale":           { "LC_ALL": "C.UTF-8", "LC_NUMERIC": "C" },
  "timezone":         "UTC",
  "os":               "linux-5.15.0-x86_64",           // 資訊性，不入 replay match
  "_required_fields": ["core_commit_sha","python","numpy","pandas","decimal_context","locale","timezone"]
}
```

> 標 `_required_fields` 是文件 hint；jsonschema `required` 才是 binding。

---

## 11. Raw Data Retention 政策 (Raw Data WORM)

```
data/raw/
  2026-05-22/
    twse_three_institutional.csv        ← 抓下來即不可改
    tdcc_weekly_2026-05-17.csv
    vendor_broker_chip.csv
    margin.csv
    price_volume.csv
    intraday_kline.parquet
    _hashes.json                         ← sha256 of each file, frozen at write time
    corrections/
      2026-05-23T03:00:00Z/              ← TWSE 隔日修正某筆，全新目錄寫入
        twse_three_institutional.csv
        _correction_note.md              ← 為何修正、改了什麼
```

**規則**：
- `data/raw/<date>/` 內所有檔案在抓取完成的當下 freeze (chmod 444)
- 任何修正放 `corrections/<timestamp>/` 子目錄，**不可覆蓋**原檔
- 若要用修正後資料重生 snapshot → `reports/<date>.v2.json` 新檔，原 snapshot 不動
- 保留期限 ≥ 3 年（壓縮歸檔可移至冷儲）

---

## 12. Snapshot Index 結構

`reports/index.json`：

```jsonc
{
  "schema_version": "1.2.0",
  "snapshots": {
    "2026-05-21": {
      "current": "2026-05-21.json",
      "current_hash": "sha256:abc123...",
      "history": [
        { "file": "2026-05-21.json", "hash": "sha256:abc123...", "created_at": "2026-05-21T15:59:00Z", "supersedes": null }
      ]
    },
    "2026-05-22": {
      "current": "2026-05-22.v2.json",
      "current_hash": "sha256:def456...",
      "history": [
        { "file": "2026-05-22.json",    "hash": "sha256:111222...", "created_at": "2026-05-22T15:59:00Z", "supersedes": null,           "superseded_by": "2026-05-22.v2.json", "supersede_reason": "TWSE corrected FII data on 2026-05-23" },
        { "file": "2026-05-22.v2.json", "hash": "sha256:def456...", "created_at": "2026-05-23T03:15:00Z", "supersedes": "2026-05-22.json" }
      ]
    }
  }
}
```

`reports/<date>.json.sha256`（單行 sidecar）：

```text
sha256:abc1234567890def... reports/2026-05-22.json
```

---

## 13. Replay Verification Examples

### 13.1 「我想驗證昨天的 GOLDEN 名單沒被竄改」

```bash
python -m tools.replay --date 2026-05-22 --check-only
# 預期輸出：
# Loading reports/2026-05-22.json (hash: sha256:abc123...)
# Verifying environment...        ✓ all versions match
# Verifying config_hash...        ✓ sha256:cfg111... matches
# Verifying raw data hashes...    ✓ 6 sources match
# Re-running core pipeline...     done (1842 stocks, 142 eligible, 3 GOLDEN)
# Comparing snapshot hash...      ✓ sha256:abc123... matches
# REPLAY_VERIFIED
```

### 13.2 「我懷疑某次 ranking 異常」

```bash
python -m tools.replay --date 2026-05-22 --diff
# Loading reports/2026-05-22.json (hash: sha256:abc123...)
# ...
# Comparing snapshot hash...      ✗ MISMATCH
#   target:   sha256:abc123...
#   actual:   sha256:xyz789...
#   first diff: stocks[3].main_force_buy: 192341 (target) vs 192340 (actual)
#   suspect:  source=vendor_broker_chip raw_sha256 differs:
#             target:  sha256:6f3a...
#             actual:  sha256:6f3b...
# HASH_MISMATCH + RAW_DATA_HASH_MISMATCH
# → likely data file was modified after the snapshot was created
```

### 13.3 「我想跑一年的 batch replay」

```bash
python -m tools.replay --from 2025-06-01 --to 2026-05-22 --parallel 4
# Output: 252 snapshots, 252 REPLAY_VERIFIED, 0 mismatches
# Coverage: 100%
```

---

## 14. CI 必跑 (Continuous Replay Verification)

CI pipeline 內每次 push 必跑：

```bash
# 1. 對最近 5 個 snapshot 做 replay check
python -m tools.replay --recent 5 --check-only --strict

# 2. 任一份失敗 → red light
# 3. 每週日 cron 跑全歷史 replay (--all)
```

---

## 15. 限制與注意 (Caveats)

1. **本階段不變動分數規則**。replay 證明的是「v1.1 規則 + 當時資料 = 當時結果」，**不證明分數規則是對的**。後者是 P4 backtest 的工作。
2. **TDCC 週報的 `data_lag_days`** 必須由 snapshot 紀錄；replay 時不可用更新的 TDCC 資料。
3. **券商分點供應商** 是商業資料源，須注意：
   - vendor 修正歷史資料 → 需建 `corrections/`
   - vendor 失效換源 → 必須在 schema 內保留舊 source_id 直至所有歷史 snapshot 被遷移
4. **環境差異容忍**：CI 可接受 `os` / patch-level numpy 版本不同（emit `ENVIRONMENT_DRIFT` warning），但 minor 版本不同必須 fail。

---

## 16. 與其他文件交叉指引

- 為何需要 replay → [AUDIT_v1.0.md](archive/AUDIT_v1.0.md) §3 F1-F7、§5.3
- 分數規則 → [SCORING_RUBRIC.md](SCORING_RUBRIC.md) (本階段不變)
- Schema 細節 → [CANONICAL_SCHEMA.md](CANONICAL_SCHEMA.md) v1.4.0
- AI 不可介入 → [AI_GOVERNANCE.md](AI_GOVERNANCE.md) — AI 不可作為 replay 路徑的一部分

---

## 17. Temporal / Window Replay (新增 by T-pivot)

> 對應 TEMPORAL_ARCHITECTURE.md §10。本節擴充 §5 的 single-shot replay 至 **window replay**。

### 17.1 為何需要

當 snapshot 內含 `temporal_state` 或 `score_tree` 帶 `temporal` 區塊時，其值衍生自 prior snapshots。要重現結果，必須先重現整個 lookback window。

### 17.2 Window Replay Workflow

```
1. Load target snapshot @ T
   target_hash = read sidecar
   target_lookback = snapshot.environment.lookback_snapshots
                     # { "2026-05-21": "sha256:...", "2026-05-20": "sha256:..." }

2. Verify each lookback snapshot
   for date, expected_hash in target_lookback.items():
     prior_snap = load reports/<date>.json
     actual = sha256(canonical_bytes(prior_snap))
     if actual != expected_hash:
       emit LOOKBACK_VERIFICATION_FAILED { date, expected, actual }
       abort

3. Load episodes_active_at_start
   for entry in snapshot.episodes_active_at_start:
     ep = load episodes/<entry.episode_id>.json
     if sha256(canonical_bytes(ep)) != entry.episode_hash:
       emit LOOKBACK_VERIFICATION_FAILED { kind: "episode", ... }
       abort

4. Restore environment (Python/numpy/pandas versions, git SHA)
   (see §5 step 2)

5. Restore config from snapshot.config_snapshot
   (see §5 step 3)

6. Re-run /core temporal pipeline
   new_snap = core.run_temporal_pipeline(
                  date           = snapshot.date,
                  raw_data       = data/raw/<T>/,
                  config         = snapshot.config_snapshot,
                  prior_snapshots= [target_lookback],
                  active_episodes= [episode files])

7. Compare canonical hash
   if sha256(canonical_bytes(new_snap)) == target_hash:
     emit REPLAY_VERIFIED
   else:
     emit HASH_MISMATCH + jdiff(snapshot, new_snap)
```

### 17.3 Cold-Start / Bootstrap Snapshot

當沒有任何 prior snapshot 可用：

| 情況 | 規約 |
|---|---|
| 完全冷啟動 (T = first day) | `environment.lookback_snapshots = {}`；emit `BOOTSTRAP_SNAPSHOT`；所有 `temporal_state` 欄位 `abstained: true, reason: "bootstrap"` |
| 部分 lookback (有 T-1~T-3，要求 T-5) | `lookback_snapshots` 只記實際拿到的；emit `LOOKBACK_PARTIAL { requested: 5, actual: 3 }`；velocity/acceleration 若不足最小樣本則 abstain |
| 缺中間日 (有 T-3, T-1 缺 T-2) | 同 partial；**禁止任何形式的內插**；emit `LOOKBACK_PARTIAL { missing: [T-2] }` |

### 17.4 Snapshot Hash 不包含什麼

為了 replay 穩定，`canonical_bytes(snapshot)` **不可包含**：
- `generated_at` 之外的本機時鐘訊息（已在 §6 列出）
- `audit_log` 內的 `step` 中的計時量
- Episode 的 `last_updated_at`（用 `trajectory[-1].date` 推導）

> 反過來，`lookback_snapshots` 與 `episodes_active_at_start[*].episode_hash` **必須**進入 hash，否則竄改不被偵測。

### 17.5 Chain Replay：從首日重建任意一日

```
replay(T) =
  if T == first_day:
    bootstrap_replay(T)
  else:
    for d in environment.lookback_snapshots:
      ensure replay(d) succeeded                    # 遞迴或迭代
    window_replay(T)
```

CI 應提供 `tools/replay.py --chain --to <date>` 模式自動展開整段歷史。

### 17.6 Episode Continuity Verification

對每個 active episode，CI 必驗：

1. `episode.trajectory[i].snapshot_hash` 必對應 `reports/<date>.json` 的 canonical SHA-256
2. `episode.trajectory` 連續日序無跳號（含交易日校曆）
3. `episodes_active_at_start[*].episode_hash` 必 == hash of episode file at time of T's start of day

### 17.7 新增 Audit Events for Temporal Replay

| Event | 用途 |
|---|---|
| `LOOKBACK_VERIFIED` | 所有 prior snapshot hash 驗證通過 |
| `LOOKBACK_VERIFICATION_FAILED` | 某個 prior snapshot 失效 |
| `LOOKBACK_PARTIAL` | 部分窗口缺檔，已 abstain 對應 temporal 欄位 |
| `BOOTSTRAP_SNAPSHOT` | 冷啟動 snapshot；無 lookback |

---

## 18. 與 P3a 落地的對應

P3a (TEMPORAL_ARCHITECTURE §13) S3-S4：

| Step | Replay 義務 |
|---|---|
| S2 (第 1 天 snapshot) | bootstrap_replay 必過 |
| S3 (連續 2 天) | 第 2 天 window_replay 需驗證 T-1 hash |
| S4 (連續 5 天) | 第 5 天可驗整段 lookback chain；emit `LOOKBACK_VERIFIED` |
