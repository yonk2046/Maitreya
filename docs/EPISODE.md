# SCD Engine — Episode 實體規格

> Version: v1.0 (2026-05-22)
> 對應 TEMPORAL_ARCHITECTURE.md TP3 / TP5 / TP7

---

## 0. 一句話

**Episode = 跨多個 snapshot 的「連續事件」，有自己的 ID、生命週期與獨立檔案。snapshot 引用它，但不擁有它。**

---

## 1. 為什麼需要 Episode

時序訊號的最自然單位往往不是「某日的某分」，而是「一段時間的某段行為」：

| 時序訊號 | 自然單位 |
|---|---|
| 主力連 8 天買進 | 一個 **accumulation episode**，duration = 8 days |
| 假突破後二次站上 | 一個 **breakout_attempt episode** (failed) + 一個 **recovery episode** |
| 連 5 日 GOLDEN | 一個 **golden_persistence episode**，duration = 5 days |
| 融資維持率從 145% 走到 138% | 一個 **margin_decompression episode** |
| 市場從牛轉熊 | 一個 **market regime episode** (ticker = 'market') |

把這些當「derived field 散落於每日 snapshot」非常彆扭：
- 跨日 join 困難
- duration / peak / trough 等 episode 屬性沒有自然歸宿
- 結束時要不要 propagate？要 propagate 到哪幾天？

**結論**：Episode 必須是第一級實體 (first-class entity)，獨立檔案、獨立 ID、獨立生命週期。

---

## 2. Episode 資料模型

```jsonc
{
  "schema_version":      "1.0.0",
  "episode_id":          "ep_3481_2026-05-15_accumulation_v1",
  "type":                "accumulation",            // enum, 見 §3
  "ticker":              "3481",                    // 或 "_market" 表示市場層級 episode
  "status":              "active",                  // active | resolved | failed | abandoned
  "started_at":          "2026-05-15",
  "ended_at":            null,                       // null = ongoing
  "duration_days":       8,                          // 自 started_at 起 (含端點)
  "last_updated_at":     "2026-05-22",

  "definition": {
    "trigger_rule":      "main_force_consecutive_days >= 3 AND fii_sync_count >= 2",
    "ongoing_rule":      "main_force_consecutive_days >= 1",   // 維持條件
    "resolve_rule":      "main_force_consecutive_days == 0",   // 結束條件
    "fail_rule":         null,                                  // 何種情況算 failed
    "rule_version":      "v1",                                  // 此 rule set 的版本
    "config_refs":       ["episodes.types.accumulation"],
    "config_hash":       "sha256:..."
  },

  "trajectory": [
    {
      "date":              "2026-05-15",
      "snapshot_hash":     "sha256:...",
      "composite":         "65.20",
      "tier":              "NEUTRAL",
      "key_metrics": {
        "main_force_consecutive_days": 3,
        "fii_sync_count":              2,
        "main_force_cost":             "18.10"
      }
    },
    /* ... one row per day from started_at to last_updated_at ... */
  ],

  "summary_metrics": {
    "peak_composite":          "72.11",
    "peak_composite_date":     "2026-05-19",
    "trough_composite":        "63.48",
    "trough_composite_date":   "2026-05-22",
    "mean_composite":          "68.30",
    "stdev_composite":          "3.20",
    "days_in_tier_GOLDEN":     0,
    "days_in_tier_WATCH":      4,
    "days_in_tier_NEUTRAL":    4
  },

  "linked_episodes": [
    /* { episode_id, relation: "preceded_by" | "split_from" | "merged_into" } */
  ],

  "provenance": {
    "created_by":   "core.episodes.detect",
    "created_at":   "2026-05-15T15:59:00Z",
    "last_changed_by": "core.episodes.update",
    "last_changed_at": "2026-05-22T15:59:00Z"
  },

  "audit_log": [
    /* in-episode audit (lighter than snapshot audit) */
  ]
}
```

---

## 3. Episode Type 登記 (架構槽位，semantics 未來定義)

> 本階段**只定結構，不定 alpha**。每個 type 都用「最直白的形狀描述」當預設 rule，未來 P4 backtest 確認後再調。

| Type | 預期語意 (placeholder) | 建議 trigger (v0) | 建議 resolve (v0) | 建議 fail (v0) |
|---|---|---|---|---|
| `accumulation` | 主力連續吸籌 | `main_force_consecutive_days >= 3` | `main_force_consecutive_days == 0 >= 2 days` | (none) |
| `distribution` | 主力連續出貨 | `main_force_consecutive_days <= -3` | `main_force_consecutive_days >= 0 >= 2 days` | (none) |
| `breakout_attempt` | 試圖突破盤整 | `current_price > rolling_high_20d` | `current_price > rolling_high_20d for 3 days` | `current_price < breakout_level - 3%` |
| `recovery_attempt` | 假突破後二次嘗試 | linked `breakout_attempt`.status == failed AND new breakout | 同 `breakout_attempt`.resolve | 同 `breakout_attempt`.fail |
| `golden_persistence` | 連續 GOLDEN | `tier == GOLDEN` | `tier != GOLDEN for 1 day` | (none) |
| `watch_persistence` | 連續 WATCH | `tier == WATCH` | `tier != WATCH for 1 day` | (none) |
| `margin_decompression` | 融資維持率走降 | `margin_maintenance_ratio` decreasing 3 days | reverses for 2 days | (none) |
| `regime_shift` | 市場 regime 切換 | regime classifier output changes | new regime stable 3 days | (none) |

> ⚠️ 上述條件**只是預設結構**。`config/scd.yaml` 的 `episodes.types.<type>.{trigger_rule, ongoing_rule, resolve_rule, fail_rule}` 才是真理之源，可被 override。**未啟用前 (`enabled: false`) 不會建立 episode**。

---

## 4. State Machine

```
            (trigger_rule met)
                │
                ▼
       ┌──────────────────┐
       │     active       │
       │  (ongoing_rule)  │◄────────────┐
       └──────┬───────────┘             │
              │                          │
   ┌──────────┼──────────────┐           │
   │          │              │           │ (ongoing_rule still met)
   ▼          ▼              ▼           │
resolve_rule  fail_rule    abandoned    (nothing — stays active)
   │          │              │
   ▼          ▼              ▼
┌────────┐ ┌────────┐    ┌──────────┐
│resolved│ │ failed │    │abandoned │
└────────┘ └────────┘    └──────────┘
   │
   └───► immutable; can be referenced from future recovery episodes
```

**規約**：
1. State 轉移必為**單向終態**：`active → {resolved, failed, abandoned}`。已終態的 episode 不能改回 active；要新事件就建新 episode（可 `linked_episodes` 指向舊的）。
2. 每次狀態變化必 emit audit event：`EPISODE_STARTED / EPISODE_UPDATED / EPISODE_RESOLVED / EPISODE_FAILED`。
3. `abandoned` 用於 rule_version 升級時把不再符合新規則的 episode 平和關閉，**不影響歷史 trajectory**。

---

## 5. 跨 Snapshot Identity

Episode ID 規約：

```
ep_<ticker>_<started_at>_<type>_<rule_version>
```

範例：
- `ep_3481_2026-05-15_accumulation_v1`
- `ep__market_2026-04-01_regime_shift_v1` (market-level episode, ticker = `_market`)

**為什麼 ID 含 rule_version**：規則升 v2 後，舊 episode 用 v1 規則完成生命週期；新 episode 用 v2 規則新建。歷史可比可審計。

---

## 6. 與 Snapshot 的耦合方式

### 6.1 Snapshot 內只引用 `episode_id`

```jsonc
"episodes_active_at_start": [
  {
    "episode_id":  "ep_3481_2026-05-15_accumulation_v1",
    "episode_hash": "sha256:..."     // hash of episode file AS OF start of this snapshot's day
  }
],
"episodes_changed_today": [
  {
    "episode_id":  "ep_3481_2026-05-15_accumulation_v1",
    "change":      "updated",
    "delta_summary": "duration_days: 7 -> 8; trough_composite: 65.00 -> 63.48"
  }
]
```

### 6.2 StockRecord 引用該檔目前參與的 episodes

```jsonc
"temporal_state": {
  /* ... */
  "current_episode_ids": ["ep_3481_2026-05-15_accumulation_v1"]
}
```

### 6.3 Episode 內反過來引用 snapshot

`episode.trajectory[].snapshot_hash` 鎖住該日 snapshot 的 hash。

**結果**：episode 與 snapshot 兩邊互鎖；任一邊被竄改 = 另一邊 replay 失敗。

---

## 7. Storage & Filesystem

```
episodes/
  ep_3481_2026-05-15_accumulation_v1.json
  ep_3481_2026-05-15_accumulation_v1.json.sha256
  ep_3481_2026-04-20_breakout_attempt_v1.json
  ...
  index.json
```

### 7.1 episodes/index.json

```jsonc
{
  "schema_version": "1.0.0",
  "by_ticker": {
    "3481": [
      "ep_3481_2026-04-20_breakout_attempt_v1",
      "ep_3481_2026-04-25_recovery_attempt_v1",
      "ep_3481_2026-05-15_accumulation_v1"
    ]
  },
  "by_status": {
    "active":   ["ep_3481_2026-05-15_accumulation_v1", "..."],
    "resolved": [...],
    "failed":   [...]
  },
  "by_type": {
    "accumulation": [...],
    "breakout_attempt": [...]
  }
}
```

### 7.2 Immutability

- Episode JSON 為 **append-only inside `trajectory`** until terminal state。
- 一旦進入 `resolved / failed / abandoned`，整檔 freeze (chmod 444)。
- 任何後續修正 → 新 episode 檔，舊檔 superseded（同 REPLAY.md §11 的 raw data correction 規約）。

---

## 8. Audit Events

對應 AUDIT_LOG_EVENTS.md 新增 enum：

| Event | 何時 emit | 例 |
|---|---|---|
| `EPISODE_STARTED` | trigger_rule 首次滿足 | `"accumulation triggered for 3481 (mf_consec=3)"` |
| `EPISODE_UPDATED` | active 中且 trajectory 加一筆 | `"duration 7→8 days; trough 65.00→63.48"` |
| `EPISODE_RESOLVED` | resolve_rule 滿足 | `"main_force_consec returned to 0 for 2 days"` |
| `EPISODE_FAILED` | fail_rule 滿足 | `"price dropped 3% below breakout level"` |
| `EPISODE_ABANDONED` | rule_version 升級時 | `"v1 rules retired; new v2 episode will start tomorrow if conditions met"` |

---

## 9. CI 不變式

CI 必驗：

1. 每個 active episode 在 `episodes/index.json.by_status.active` 必出現
2. 每個 snapshot 的 `episodes_active_at_start[*].episode_id` 必在 `episodes/index.json` 找到
3. `episode.trajectory[i].snapshot_hash` 必對應 `reports/<date>.json.sha256` 內容
4. `episode.status == "resolved"|"failed"|"abandoned"` → `ended_at != null` 且 `episodes/<id>.json` 為 read-only
5. `ep_<ticker>_<date>_<type>_<rule_version>` 命名格式必須符合 regex `^ep_[A-Z0-9_]+_\d{4}-\d{2}-\d{2}_[a-z_]+_v\d+$`
6. 每個 episode 的 `definition.config_hash` 必與其 trajectory 第一日的 snapshot.config_hash 相符（episode 建立時的 config 必須 snapshot 也有用同一份）

---

## 10. Replay 含義

Episode 是「跨 snapshot 推導」的成品。Replay 一個 snapshot @ T 需要：

1. 對應日的 raw_data + config + prior snapshots（同 REPLAY.md §17 window replay）
2. 載入 `episodes_active_at_start` 列的所有 episode 檔，驗 hash
3. 重跑 `/core` 後產出的 `episodes_changed_today` 必與目標 snapshot 一致

**Episode 的決定論**：給定 `(prior_snapshots, raw_today, cfg, current_episode_states)`，新 episode 狀態必唯一。

---

## 11. 配置範例 (config/scd.example.yaml 將新增此段)

```yaml
episodes:
  enabled: false                    # default OFF — bootstrap 階段不啟用
  index_file: "episodes/index.json"
  storage_dir: "episodes/"

  types:
    accumulation:
      enabled: false
      rule_version: "v1"
      trigger_rule:  "main_force_consecutive_days >= 3"
      ongoing_rule:  "main_force_consecutive_days >= 1"
      resolve_rule:  "main_force_consecutive_days == 0 for 2 days"
      fail_rule:     null

    breakout_attempt:
      enabled: false
      rule_version: "v1"
      # ... see §3 table for defaults

    # other types: enabled: false until P4 validates
```

> 全部 `enabled: false`。等 P3a 真實資料管線跑通、P4 確認 type 有 IC 後再開。

---

## 12. AI 解讀層的 Episode 引用

AI_GOVERNANCE.md 規約延伸：AI 可以**引用** episode_id 與 trajectory，但不可：
- 改 episode.status
- 改 trajectory
- 提出 schema 外的新 episode type

正確的引用形式：
> 「3481 目前處於 `ep_3481_2026-05-15_accumulation_v1`，已持續 8 日；今日 composite 達近 8 日低 (63.48) 但 episode 未進入 resolve 條件 (mf_consec 仍 ≥ 1)。」

---

## 13. 相關文件

- [TEMPORAL_ARCHITECTURE.md](TEMPORAL_ARCHITECTURE.md) §6
- [STORAGE_LAYOUT.md](STORAGE_LAYOUT.md) — 檔案位置
- [REPLAY.md](REPLAY.md) §17 — Window Replay
- [AUDIT_LOG_EVENTS.md](AUDIT_LOG_EVENTS.md) — EPISODE_* events
- [AI_GOVERNANCE.md](AI_GOVERNANCE.md) — AI 引用規範
