# SCD Engine — Storage Layout for Temporal State

> Version: v1.0 (2026-05-22)
> 對應 TEMPORAL_ARCHITECTURE.md §7
> Schema: canonical_schema v1.4.0

---

## 0. 設計原則

1. **Source of Truth 唯一**：reports/ + episodes/ 為主檔；其他都可 regenerate。
2. **Append-only / WORM**：所有時序資料**永不就地修改**；修正走 supersedes pattern。
3. **Replay-safe**：每份檔皆有 sha256 sidecar；index 檔串起所有 hash。
4. **可分層儲存**：熱資料 SSD / 冷資料壓縮歸檔 / 物化視圖可重建。
5. **不依賴特定資料庫**：純檔案系統可運作；資料庫只是加速層。

---

## 1. 完整目錄結構

```
ai_stock/
├── data/
│   └── raw/                                # P1: WORM raw market data
│       ├── 2026-05-22/
│       │   ├── twse_three_institutional.csv
│       │   ├── vendor_broker_chip.csv
│       │   ├── twse_margin.csv
│       │   ├── tdcc_weekly_2026-05-17.csv
│       │   ├── price_volume.csv
│       │   ├── intraday_kline.parquet
│       │   ├── _hashes.json                # sha256 of each file
│       │   └── corrections/                # subdir for any vendor corrections
│       └── 2026-05-21/
│           ...
│
├── reports/                                # 每日 snapshot (point-in-time)
│   ├── 2026-05-22.json                     # canonical snapshot
│   ├── 2026-05-22.json.sha256              # P1 sidecar
│   ├── 2026-05-22.audit.jsonl              # high-volume audit events
│   ├── 2026-05-22.audit.jsonl.sha256
│   ├── 2026-05-22.transitions.jsonl        # T-4: tier transitions on this day
│   ├── 2026-05-21.json
│   ├── ...
│   └── index.json                          # date → current hash + history
│
├── episodes/                               # NEW (T-pivot): 跨日事件
│   ├── ep_3481_2026-05-15_accumulation_v1.json
│   ├── ep_3481_2026-05-15_accumulation_v1.json.sha256
│   ├── ep_3481_2026-04-20_breakout_attempt_v1.json
│   ├── ...
│   ├── _market_2026-04-01_regime_shift_v1.json   # market-level episode
│   └── index.json                           # by_ticker / by_status / by_type
│
├── state/                                  # NEW: per-ticker time-series memory
│   ├── 3481.jsonl                          # append-only; one row per snapshot date
│   ├── 3481.jsonl.sha256                   # rolling SHA-256 (Merkle-like)
│   ├── 2317.jsonl
│   ├── ...
│   └── index.json                           # ticker → last_updated_at + current_episode_ids
│
├── parquet/                                # OPTIONAL: materialized columnar views
│   ├── scores/
│   │   └── 2026-05-22.parquet              # one row per (ticker, date); all leaf scores
│   ├── episodes/
│   │   └── 2026-05-22.parquet              # ongoing episodes summary
│   ├── transitions/
│   │   └── 2026-05-22.parquet
│   └── _manifest.json                      # source snapshots used + regenerable=true
│
├── config/
│   └── scd.example.yaml
│
├── schema/
│   └── canonical_schema.json               # v1.4.0
│
├── docs/
│   ├── TEMPORAL_ARCHITECTURE.md
│   ├── EPISODE.md
│   ├── STORAGE_LAYOUT.md                   # this file
│   ├── ...
│
└── tools/
    ├── correlation_analyzer.py
    ├── replay.py                            # P3 to write
    └── materialize_parquet.py               # P3 to write
```

---

## 2. 五大資料夾的職責

### 2.1 `data/raw/<date>/` — 不可變原始資料

對應 REPLAY.md §11 WORM 政策。本文件不重述。

### 2.2 `reports/<date>.json` — 每日 snapshot

對應 REPLAY.md §3-§4。每日一檔，內含：
- 所有 stocks（含 score_tree、temporal_state）
- 當日 episodes 變化 (`episodes_changed_today`)
- 當日 tier transitions
- 當日 market_regime
- environment.lookback_snapshots

**規模**：1800 檔 × 6 KB tree ≈ 11 MB / 日。gzip ~1 MB / 日。

### 2.3 `episodes/<id>.json` — 跨日事件

對應 EPISODE.md。每個 episode 一檔，內含完整 trajectory。

**規模**：估計 100~500 個 active episodes 同時存在，每檔 trajectory 數 KB。總量 < 50 MB。

### 2.4 `state/<ticker>.jsonl` — per-ticker 時序記憶（NEW）

**為什麼需要**：跨 snapshot 查詢「3481 過去 90 日的 composite 軌跡」如果要 load 90 個 reports 太慢。`state/3481.jsonl` 把這 90 天的 condensed view 直接攤平。

**結構**：每行一個 JSON 物件，按日期升序：

```jsonl
{"date":"2026-05-15","schema_version":"1.4.0","snapshot_hash":"sha256:...","tier":"NEUTRAL","composite":"65.20","stage_1":"52.10","stage_2":"66.30","stage_3":"82.00","gates":{"G1":true,"G2":true,"G3":true},"current_episode_ids":["ep_3481_2026-05-15_accumulation_v1"]}
{"date":"2026-05-16","schema_version":"1.4.0","snapshot_hash":"sha256:...","tier":"NEUTRAL","composite":"66.80","stage_1":"54.00","stage_2":"66.40","stage_3":"82.00","gates":{"G1":true,"G2":true,"G3":true},"current_episode_ids":["ep_3481_2026-05-15_accumulation_v1"]}
{"date":"2026-05-22","schema_version":"1.4.0","snapshot_hash":"sha256:47b3...","tier":"NEUTRAL","composite":"63.48","stage_1":"50.92","stage_2":"64.60","stage_3":"82.00","gates":{"G1":true,"G2":true,"G3":true},"current_episode_ids":["ep_3481_2026-05-15_accumulation_v1"]}
```

**規約**：
- **Append-only**。每日 pipeline 結束時對每檔追加一行。
- `state/<ticker>.jsonl.sha256` 是 **rolling Merkle-style hash**：H(state[T]) = SHA-256(H(state[T-1]) || canonical_bytes(state[T]))。
- 任何後修都會破壞 hash 鏈 → CI 立即發現。
- 每行內的 `snapshot_hash` 必對應 `reports/<date>.json.sha256`。

**為什麼用 jsonl 而非單 json**：
- append 不需 rewrite
- streaming-friendly：tail -n 30 即得最近一個月
- grep / awk / jq 直接讀

**regeneratable**：state/ 完全可由 reports/ 重建。若狀態檔損壞，跑 `tools/rebuild_state.py --ticker 3481` 重生。

### 2.5 `transitions/<date>.jsonl` 或 `reports/<date>.transitions.jsonl` — 當日 transitions

**選擇**：我傾向放 `reports/<date>.transitions.jsonl`（與 snapshot 同目錄、同日生命週期）。

每行：

```jsonl
{"ticker":"3481","from_tier":"WATCH","to_tier":"NEUTRAL","from_composite":"72.11","to_composite":"63.48","primary_cause_node_path":"composite.chip_score.fii_sub.sync_score","score_delta":"-8.63","reason":"v1.1 Gate-then-Score: fii_sync_score dropped from 50→0"}
{"ticker":"2454","from_tier":"NEUTRAL","to_tier":"WATCH","from_composite":"68.50","to_composite":"72.30","primary_cause_node_path":"composite.behavior_score.margin_sub.maintenance_score","score_delta":"+3.80","reason":"margin maintenance ratio 145 -> 138 piecewise jump"}
```

CI 必驗：每行的 `from_tier` 對應前一日 `reports/<T-1>.json` 中該 ticker 的 `tier`。

### 2.6 `parquet/` — 物化視圖（可選但建議）

用於：相關性分析、回測、儀表板查詢。**不是 source of truth**；任何時候都可從 reports/ + state/ 重新跑出。

`_manifest.json` 紀錄哪些 source files 被吃進去 + sha256，確保 parquet 與 source 對齊。

---

## 3. Hash 鏈與整體 Merkle 概念

每個檔有 sidecar SHA-256：
- `reports/2026-05-22.json.sha256`
- `reports/2026-05-22.audit.jsonl.sha256`
- `episodes/ep_*.json.sha256`
- `state/3481.jsonl.sha256` (rolling)

```
reports/index.json
  └─ "2026-05-22":
       current_hash: sha256:abc...   ← reports/2026-05-22.json
       audit_hash:   sha256:def...   ← reports/2026-05-22.audit.jsonl
       transitions_hash: sha256:ghi...
       episodes_changed: [
         { episode_id: ep_3481_..., hash_after: sha256:jkl... }
       ]
       lookback_chain: [
         { date: 2026-05-21, hash: sha256:... },
         { date: 2026-05-20, hash: sha256:... }
       ]
```

效果：給定 reports/index.json 的最新一行 hash，可向後逐層驗證整段歷史。任一處被竄改 → 立即發現。

---

## 4. 保留與壓縮政策 (Retention)

| 資料 | 熱儲存 (SSD) | 冷儲存 (壓縮) | 永久歸檔 |
|---|---|---|---|
| `data/raw/<date>/`     | 90 日 | 90 日 → 3 年 | 3 年後可離線移除 |
| `reports/<date>.json` | 365 日 | 1 → 5 年 | 永久（檔案小） |
| `reports/*.audit.jsonl` | 90 日 | 90 日 → 1 年 | 1 年後可移除（高量） |
| `episodes/*.json`     | 365 日 | 1 → 5 年 | 永久（小 + 有 trajectory） |
| `state/*.jsonl`       | 永久熱 | — | 永久（連續性必要） |
| `parquet/*`           | 60 日 | regenerate as needed | — |

> 冷儲存格式建議 zstd 壓縮 + 月 tar 打包：`archive/2026-04.tar.zst`。

---

## 5. 增量寫入順序 (Daily Pipeline Output Order)

每日 pipeline 完成時，必須以下面**嚴格順序**寫檔（確保中斷時可回滾）：

```
1. data/raw/<T>/*                        (raw + _hashes.json freeze)
2. /core temporal pipeline 計算完成
3. reports/<T>.audit.jsonl + sidecar     (先寫 audit，因 snapshot 會引用部分)
4. reports/<T>.transitions.jsonl + sidecar
5. episodes/<id>.json updates (含對應 sidecar)
6. reports/<T>.json + sidecar            (主檔；含 lookback hashes — 最後才能算)
7. state/<ticker>.jsonl append (rolling hash 更新)
8. reports/index.json update             (最後一步；對外宣告該日完成)
9. parquet/ materialize (可後台)
```

**回滾**：任一步失敗 → 不更新 `reports/index.json` 即視為該日 incomplete。下次 pipeline 跑可從步驟 1 重啟（raw 為 WORM，重生 snapshot 安全）。

---

## 6. 路徑常數 (Filesystem Constants)

寫入 `config/scd.example.yaml`：

```yaml
storage:
  base_dir:        "."
  raw_dir:         "data/raw"
  reports_dir:     "reports"
  episodes_dir:    "episodes"
  state_dir:       "state"
  parquet_dir:     "parquet"
  index_file:      "reports/index.json"
  episodes_index:  "episodes/index.json"
  state_index:     "state/index.json"
```

**規約**：所有 `/core` / `/data` 模組必透過此配置讀路徑；禁止 hardcode。

---

## 7. 規模估算 (Storage Sizing)

假設 1800 檔、252 交易日 / 年：

| 資料 | 單檔大小 | 日量 | 年量 (uncompressed) | 年量 (zstd) |
|---|---|---|---|---|
| reports/<date>.json | ~11 MB | 1 | ~2.7 GB | ~300 MB |
| reports/*.audit.jsonl | ~50 MB | 1 | ~12 GB | ~1 GB |
| reports/*.transitions.jsonl | ~50 KB | 1 | ~12 MB | ~3 MB |
| episodes/*.json (active) | ~5 KB × 500 | — | 持平 | — |
| state/*.jsonl | ~500 bytes × 1800 = 900 KB | 1 | ~225 MB | ~30 MB |
| data/raw/* | ~50 MB | 1 | ~12 GB | ~1.5 GB |
| **總計** | | | **~27 GB / 年** | **~3 GB / 年** |

> 完全本地 SSD 可承受多年。雲端歸檔 (S3 IA / Glacier) 用 zstd 後成本可忽略。

---

## 8. CI 不變式（檔案系統層）

1. 每個 `reports/<date>.json` 必有對應 `.sha256` 與 `.audit.jsonl`
2. `reports/index.json.snapshots[date].current_hash` 必對應 `reports/<date>.json` 的 canonical SHA-256
3. `state/<ticker>.jsonl` 的最後一行 `snapshot_hash` 必對應 `reports/<latest_date>.json` 內該 ticker 的記錄
4. `episodes/<id>.json` 的 `trajectory[i].snapshot_hash` 必對應對應日的 snapshot
5. `episodes/index.json.by_status.active` 列出的 episode 必有 `status: active`
6. 所有 sidecar SHA-256 與檔案實際 canonical bytes 一致
7. 任何 freeze 後的檔案 (resolved episode / past day) 必為 read-only (chmod 444)

---

## 9. 與 P3a 落地的對應

P3a (TEMPORAL_ARCHITECTURE §13 S1-S5) 需要先建：

| Step | 建立的檔案 |
|---|---|
| S1 | `data/raw/2026-05-DD/*` × 5 天 + `_hashes.json` |
| S2 | `reports/2026-05-DD.json` × 5 天 + sidecar |
| S3 | `reports/index.json` 含 5 個 entry |
| S4 | 從第 2 天起含 `lookback_snapshots` |
| S5 | `state/<ticker>.jsonl` × N 檔 |

P3a 後 `episodes/` 與 `parquet/` 才陸續啟用。

---

## 10. 相關文件

- [TEMPORAL_ARCHITECTURE.md](TEMPORAL_ARCHITECTURE.md) — 為什麼這樣設計
- [EPISODE.md](EPISODE.md) — episodes/ 內容規格
- [REPLAY.md](REPLAY.md) — sha256 sidecar 規約、WORM raw data
- [CANONICAL_SCHEMA.md](CANONICAL_SCHEMA.md) — snapshot 內部結構
