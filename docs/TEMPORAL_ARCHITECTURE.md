# SCD Engine — Temporal Architecture (Market State Engine)

> Version: v1.0 (2026-05-22) — major architectural pivot
> Status: 規格凍結 — 不變動 v1.1 評分規則，只擴充時序維度
> Supersedes: ARCHITECTURE.md 的「daily screener」表述

---

## 0. 一句話 (TL;DR)

**SCD 的核心不是「每日靜態打分」，而是「市場狀態的時序推理」。snapshot 不是被動歸檔，而是主動記憶；prior snapshots 是當下計算的輸入。**
*SCD's core is not daily static scoring, but temporal reasoning over market state. Snapshots are not passive archives but active memory; prior snapshots are inputs to current computation.*

---

## 1. 為什麼要這個轉向

過去的設計把每日 snapshot 當「結帳」：raw → score → file → done。
真實的籌碼洞察需要的是：

| 訊號 | 為什麼需要時序 |
|---|---|
| state transitions | 「昨天 WATCH，今天 NEUTRAL」與「連續 5 天 NEUTRAL」是兩件事 |
| multi-day behavioral evolution | 同樣 chip = 72，是「從 50 加速到 72」還是「從 90 衰退到 72」？ |
| accumulation persistence | 主力連 8 天買 vs 連 3 天買，conviction 差距巨大 |
| score acceleration/deceleration | d(score)/dt 與 d²(score)/dt² 本身就是 alpha 線索 |
| institutional follow-through | FII 領先、MainForce 跟進、量能驗證的「序列」是 1+1+1 ≠ 3 的合奏 |
| regime transition detection | 同一個 chip 分在牛市與熊市的意涵不同 |
| failed breakout recovery | 假突破後 N 日二次站上 = T2 經典型；缺時序根本看不到 |
| temporal conviction modeling | 連續 5 日 GOLDEN 的可信度 ≠ 剛跳 GOLDEN 的可信度 |

**這些都是現有 v1.1 規則無法表達的維度。**

因此架構必須把「時序連續性 (temporal continuity)」當作 first-class primitive — 而不是「之後再 retrofit」。

---

## 2. Eight Temporal Primitives (架構必須原生支援)

| # | Primitive | 結構位置 | 範例 |
|---|---|---|---|
| TP1 | **Tier Transitions** | StockRecord.temporal_state + audit event `TIER_TRANSITIONED` | 3481: WATCH(2026-05-21) → NEUTRAL(2026-05-22) |
| TP2 | **Score Time-Series** | environment.lookback_snapshots + ScoreNode.temporal (optional) | composite [60.5, 62.8, 63.4] |
| TP3 | **Episode** | episodes/<id>.json + snapshot.episodes_active | accumulation episode 2026-05-15 → ongoing |
| TP4 | **Score Velocity / Acceleration** | StockRecord.temporal_state.velocity / acceleration | velocity = +0.7/day, accel = +0.2/day² |
| TP5 | **Cross-Factor Follow-Through** | episodes 中的 trajectory 跨 factor 事件 | FII@T0 → MF@T+1 → Vol@T+2 |
| TP6 | **Market Regime** | snapshot.market_regime (top-level) | regime: "bull_low_vol" / "bear_panic" |
| TP7 | **Episode Lifecycle** | EPISODE_STARTED / RESOLVED / FAILED events | breakout_attempt → failed → recovery_attempt |
| TP8 | **Temporal Conviction** | tier_in_current_state_days + episode.duration_days | "WATCH 連 6 日" vs "WATCH 第 1 日" |

**規約**：本文件**不定義**這些 primitive 各自的 alpha 含義（那是 P4 backtest 的事）。我們只保留結構槽位，讓未來定義能無縫填入。

---

## 3. Snapshot 的角色重新定義

### 3.1 Old definition (P0-P2)

```
snapshot(date T) = f(raw_data(T), config)              # 純函式，無記憶
```

### 3.2 New definition (T-pivot 之後)

```
snapshot(date T) = f(
  raw_data(T),
  config,
  prior_snapshots[T-N, ..., T-1],                      # ← 新增：lookback dependency
  episodes_active[at start of T]                       # ← 新增：跨日狀態
)
```

但仍然**決定論**：同一份 (raw_data, config, prior_snapshots, episodes) 必產同一份 snapshot。

### 3.3 為了維持 replay safety 的不變式

1. snapshot 必須在 `environment.lookback_snapshots` 內列出每個被引用的 prior snapshot 的 `{date: sha256_hash}`
2. replay 時這些 prior snapshots 必須能被取得且 hash 一致；否則 emit `LOOKBACK_VERIFICATION_FAILED`
3. snapshot 必須在 `episodes_active_at_start` 列出當日開始時的所有 active episodes（含 episode_id + 該 episode 的當前 hash）
4. 任一 prior snapshot 失效（檔案損毀 / hash 改變）= 當日 snapshot 失效，必須重生 v2

---

## 4. 主資料流 (Updated)

```
T-N ... T-1                              T (今日)
┌──────────┐    ┌──────────┐            ┌─────────────────────────────┐
│snapshot  │    │snapshot  │  ─────►    │ /data adapter               │
│  T-N     │    │  T-1     │            │   raw_data(T)               │
│ hash:... │    │ hash:... │            └──────────┬──────────────────┘
└────┬─────┘    └────┬─────┘                       │
     │               │                              ▼
     │               │            ┌─────────────────────────────────┐
     └───────────────┴────────────► /core temporal pipeline         │
                                  │   step 1: load lookback         │
                                  │   step 2: verify lookback hashes│
                                  │   step 3: load episodes         │
                                  │   step 4: filters + scoring     │
                                  │   step 5: derive temporal state │
                                  │   step 6: detect transitions    │
                                  │   step 7: update episodes       │
                                  │   step 8: detect regime         │
                                  └──────────┬──────────────────────┘
                                             ▼
                                  ┌─────────────────────────────────┐
                                  │ reports/T.json (snapshot)       │
                                  │ reports/T.audit.jsonl           │
                                  │ reports/T.json.sha256           │
                                  │ episodes/<id>.json (updated)    │
                                  │ episodes/index.json (updated)   │
                                  │ state/<ticker>.jsonl (appended) │
                                  └─────────────────────────────────┘
```

---

## 5. Cold-Start & Bootstrap

第一個 snapshot 沒有 prior 可參考。規約：

| 情況 | 處理 |
|---|---|
| 完全冷啟動 (沒有任何 prior snapshot) | `lookback_snapshots = {}`；所有 temporal 欄位 abstain；emit `BOOTSTRAP_SNAPSHOT` event |
| 部分 lookback (有 T-1 ~ T-3 但要求 T-5) | lookback_snapshots 只記實際拿到的；temporal 欄位 abstain 若不足最小樣本；emit `LOOKBACK_PARTIAL` |
| 缺中間日 (有 T-3, T-1 缺 T-2) | 同上 — 不可線性內插；abstain 寧可保守 |
| 第一個 episode | episode.previous_state = "bootstrap" |

**禁止造假**：不可用線性內插或回填補洞。要嘛資料齊全要嘛 abstain。

---

## 6. Episode：跨日的一級實體 (見 EPISODE.md)

Episode 是「跨多日的連續事件」。例如：
- accumulation episode：連續 N 日符合某條件
- breakout_attempt episode：某日突破，後續觀察是否站穩
- recovery episode：先 fail 後二次嘗試

**Episode 不是 snapshot 的子欄位**。它有自己的生命週期、ID、persistence 檔。
snapshot 只引用 episode_id；episode 自己存 `episodes/<id>.json`。

詳細規格見 [EPISODE.md](EPISODE.md)。

---

## 7. Storage Layout（見 STORAGE_LAYOUT.md）

新增三大資料夾：

```
reports/        # 既有：每日 snapshot (point-in-time)
  <date>.json
  <date>.json.sha256
  <date>.audit.jsonl
  index.json

episodes/       # NEW: 跨日事件
  <episode_id>.json
  index.json

state/          # NEW: per-ticker 時序記憶 (append-only)
  <ticker>.jsonl
  index.json

transitions/    # NEW: 每日所有 tier transitions 集中
  <date>.jsonl

parquet/        # NEW (optional): 物化視圖，加速查詢；可由上面三者完全 regenerate
  scores/<date>.parquet
  episodes/<date>.parquet
```

詳細結構見 [STORAGE_LAYOUT.md](STORAGE_LAYOUT.md)。

---

## 8. Snapshot 結構新增欄位 (schema v1.4.0)

### 8.1 Top-level 新增

```jsonc
{
  /* ... existing fields ... */

  "market_regime": {
    "label":        "unknown",            // P2 結束時尚未定義；保留結構
    "classifier":   "stub_v0",            // 未來: trend_model_v1 等
    "confidence":   null,                 // null until classifier exists
    "features": {                          // 結構槽位，未來填
      "vix_proxy":      null,
      "breadth_index":  null,
      "regime_dwell":   null
    }
  },

  "episodes_active_at_start": [
    /* { episode_id, type, ticker (or 'market'), started_at, hash } */
  ],

  "episodes_changed_today": [
    /* { episode_id, change: 'started'|'updated'|'resolved'|'failed', delta } */
  ],

  "tier_transitions": [
    /* { ticker, from_tier, to_tier, primary_cause_node_path, score_delta } */
  ]
}
```

### 8.2 environment 新增

```jsonc
"environment": {
  /* ... existing ... */
  "lookback_snapshots": {
    "2026-05-21": "sha256:abc...",
    "2026-05-20": "sha256:def...",
    "2026-05-19": "sha256:..."
  },
  "lookback_window_days": 5
}
```

### 8.3 StockRecord 新增 `temporal_state`

```jsonc
"temporal_state": {
  "prior_tier":                "WATCH",          // 上一個 snapshot 的 tier
  "tier_in_current_state_days": 1,                // 進入當前 tier 已幾天 (含今日)
  "tier_history_lookback":     ["WATCH", "WATCH", "WATCH", "NEUTRAL"],
                                                  // 由舊到新；長度 = lookback_window_days
  "score_history_lookback":    ["72.11","70.20","68.10","63.48"],
                                                  // 同上；Decimal-as-string
  "score_velocity":            "-4.6300",         // (今日 - 上一日) Decimal
  "score_acceleration":        "-2.6300",         // 二階差分
  "trend":                     "decelerating",   // accelerating | flat | decelerating
  "current_episode_ids":       [],                // 此檔目前參與哪些 episodes
  "abstained": {
    "velocity":     false,
    "acceleration": false,
    "reason":       null                          // 若 abstain
  }
}
```

> **重要**：`temporal_state` 是**從 prior snapshots 衍生**的，必須在 `provenance.derived_fields` 註冊，含 `derived_from: ["snapshot@T-1", "snapshot@T-2", ...]` 與用到的 hash。

### 8.4 audit_log 新事件

加入 enum：
- `TIER_TRANSITIONED`
- `EPISODE_STARTED`
- `EPISODE_UPDATED`
- `EPISODE_RESOLVED`
- `EPISODE_FAILED`
- `REGIME_DETECTED`
- `LOOKBACK_VERIFIED`
- `LOOKBACK_VERIFICATION_FAILED`
- `LOOKBACK_PARTIAL`
- `BOOTSTRAP_SNAPSHOT`

---

## 9. ScoreNode 的時序擴充 (詳見 SCORE_NODE.md §13)

任何 ScoreNode 可選擇加 `temporal` 區塊：

```jsonc
{
  "path": "composite",
  "value": "63.4766",
  /* ... existing fields ... */
  "temporal": {
    "lookback_window_days": 5,
    "values_series":  ["72.11","70.20","68.10","65.00","63.48"],
    "series_dates":   ["2026-05-18","2026-05-19","2026-05-20","2026-05-21","2026-05-22"],
    "velocity":       "-1.6075",
    "acceleration":   "-0.0850",
    "ema_3":          "65.66",
    "lookback_snapshot_hashes": {
      "2026-05-21": "sha256:...",
      "2026-05-20": "sha256:..."
    }
  }
}
```

> **本階段不為任何 ScoreNode 啟用 temporal block**；只在 schema 預留結構。等 P3 真實資料管線跑起來後，由 P4 決定哪些 node 該攜帶 temporal。

---

## 10. Replay Semantics 更新 (詳見 REPLAY.md §17)

從 **single-shot replay** 升級為 **window replay**：

```
1. 載入目標 snapshot @ T
2. 從 environment.lookback_snapshots 取所有 (date, hash)
3. 對每個 (date, hash):
     load reports/<date>.json
     compute canonical sha256
     assert == hash; 否則 emit LOOKBACK_VERIFICATION_FAILED
4. 載入 episodes_active_at_start 列出的 episode 檔，驗 hash
5. 重跑 /core temporal pipeline (含 raw_data + cfg + lookback + episodes)
6. 對 result canonical sha256，比對目標 snapshot 的 hash
```

「整段歷史」可由首日 snapshot 沿著 lookback chain 重建。

---

## 11. Provenance 升級

`provenance.derived_fields` 新增模式：

```jsonc
"score_velocity": {
  "derived_from": [
    "composite_score@T-1",
    "composite_score@T-0"
  ],
  "formula":      "today - yesterday",
  "step":         "core.temporal.score_velocity",
  "temporal":     true,                       // NEW flag
  "lookback":     { "T-1": "sha256:..." }     // hash of required prior snapshot
}
```

`temporal: true` 表示這個 derived field 跨 snapshot。CI 驗證時必須確認 lookback hash 在 environment 內列過。

---

## 12. 約束 (本階段不可越界)

對應使用者明示：

- ❌ 不調 weight、threshold、ranking
- ❌ 不引入新 alpha 假設（不要選「velocity > X 就是好」這種規則）
- ❌ 不 overfit 一週資料
- ✅ 只設計結構槽位
- ✅ 確保未來 P4 / P5 落地時零 retrofit
- ✅ 維持 P0 Numeric Policy / P1 Replay Safety / P2 Score Tree 的所有規約

---

## 13. P3a 落地步驟（建議下一動作）

| Step | 動作 | 產出 |
|---|---|---|
| S1 | 寫最小 `/data` adapter，把你一週的 raw 資料正規化進 `data/raw/<date>/` (WORM + sha256) | 6 個 sources × 5 天 = 30 個 immutable 檔 |
| S2 | 寫最小 `/core` ingest，僅做 schema v1.4.0 必填欄位 (不算 score 也行) | 5 份初步 snapshot |
| S3 | 跑 replay check：每份 snapshot 兩次跑 hash 一致 | CI 通過 |
| S4 | 加入第 5 天時，T-1~T-4 的 lookback chain 必須能驗證 | LOOKBACK_VERIFIED 事件 |
| S5 | 開始累積 state/<ticker>.jsonl | 每檔 5 列 |
| S6 | 用 correlation_analyzer.py 跑 cross-section 觀察 | observability 報告 (n=不夠但流程驗過) |
| S7 | 等資料累積到 60 個交易日，啟動 P4 walk-forward | 真實 IC |

S1–S5 用一週資料就能跑；S6 同步進行；S7 等夠數量再說。

---

## 14. 相關文件

- [EPISODE.md](EPISODE.md) — Episode 實體完整規格
- [STORAGE_LAYOUT.md](STORAGE_LAYOUT.md) — 時序儲存目錄結構
- [REPLAY.md](REPLAY.md) §17 — Window Replay
- [SCORE_NODE.md](SCORE_NODE.md) §13 — Temporal Extension
- [ARCHITECTURE.md](ARCHITECTURE.md) — 五層架構（state engine 化）
- [AUDIT_LOG_EVENTS.md](AUDIT_LOG_EVENTS.md) — 新增 10 個 temporal events
- [AI_GOVERNANCE.md](AI_GOVERNANCE.md) — AI 解讀層需引用 temporal_state 與 episode_id
