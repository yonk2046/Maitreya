# SCD Engine — Audit Log Events 登記表

> Version: v1.1 (2026-05-26) — P3a-Hardening phase
> Schema: canonical_schema v1.4.0 — `audit_log[].event` enum
>
> Changelog:
> - v1.1 (2026-05-26) — added P3a-Hardening events (RAW_ARCHIVED, WORM_VIOLATION)
>   plus the v1.4 temporal events that were previously only in schema enum
>   (BOOTSTRAP_SNAPSHOT, LOOKBACK_VERIFIED, etc.).
> - v1.0 (2026-05-22) — P2 phase initial release.

---

## 0. 為何需要這份登記

事件曾散落於 schema enum、AUDIT_FINDINGS.md、AUDIT_v1.0.md、REPLAY.md。**單一登記表**才能：
- CI 規範化檢查
- AI 解讀層引用時有統一語彙
- 新增事件時不會與舊的撞名或重疊

---

## 1. 事件全名單

| Event | 引入版本 | 範疇 | 必填 `data` 欄位 |
|---|---|---|---|
| `ELIMINATED`              | v1.0 | per-stock | `{gate, raw_inputs, threshold}` |
| `DATA_WARNING`            | v1.0 | per-stock | `{field, issue}` |
| `TIE_RESOLVED`            | v1.0 | per-stock | `{tied_with, breaker_used}` |
| `INFO`                    | v1.0 | any | free-form |
| `REPLAY_VERIFIED`         | v1.2 (P1) | snapshot | `{target_hash, actual_hash}` |
| `HASH_MISMATCH`           | v1.2 (P1) | snapshot | `{target_hash, actual_hash, first_diff_path}` |
| `RAW_DATA_HASH_MISMATCH`  | v1.2 (P1) | snapshot | `{source_id, expected_sha256, actual_sha256}` |
| `CONFIG_HASH_MISMATCH`    | v1.2 (P1) | snapshot | `{expected, actual}` |
| `ENVIRONMENT_DRIFT`       | v1.2 (P1) | snapshot | `{key, snapshot_value, runtime_value}` |
| `SCHEMA_VERSION_MISMATCH` | v1.2 (P1) | snapshot | `{snapshot_version, runtime_version}` |
| `SUBFACTOR_COMPUTED`      | v1.3 (P2) | per-leaf | `{node_path, raw_inputs, config_keys_resolved, normalization, output_value}` |
| `FACTOR_LINEAGE`          | v1.3 (P2) | per-internal | `{node_path, child_paths, weights, formula}` |
| `CONFIG_RESOLVED`         | v1.3 (P2) | any | `{config_key, value, default_used: bool}` |
| `NORMALIZATION_APPLIED`   | v1.3 (P2) | per-node | `{node_path, op_chain, input_value, output_value}` |
| `FEATURE_FLAG_RESOLVED`   | v1.3 (P2) | snapshot | `{flag, value, default, took_effect_at}` |
| `ABSTAIN_PROPAGATED`      | v1.3 (P2) | per-node | `{node_path, abstained_children, redistributed_weights}` |
| `TIER_TRANSITIONED`       | v1.4 (T)  | per-stock | `{ticker, from_tier, to_tier, reason_code}` |
| `EPISODE_STARTED`         | v1.4 (T)  | per-episode | `{episode_id, ticker, started_at, kind}` |
| `EPISODE_UPDATED`         | v1.4 (T)  | per-episode | `{episode_id, change_summary}` |
| `EPISODE_RESOLVED`        | v1.4 (T)  | per-episode | `{episode_id, outcome, holding_days}` |
| `EPISODE_FAILED`          | v1.4 (T)  | per-episode | `{episode_id, failure_reason}` |
| `EPISODE_ABANDONED`       | v1.4 (T)  | per-episode | `{episode_id, abandon_reason}` |
| `REGIME_DETECTED`         | v1.4 (T)  | snapshot | `{label, classifier, confidence}` |
| `LOOKBACK_VERIFIED`       | v1.4 (T)  | snapshot | `{lookback_snapshots: {date: sha256}}` |
| `LOOKBACK_VERIFICATION_FAILED` | v1.4 (T) | snapshot | `{date, expected_sha256, actual_sha256}` |
| `LOOKBACK_PARTIAL`        | v1.4 (T)  | snapshot | `{found_window_days, requested_window_days}` |
| `BOOTSTRAP_SNAPSHOT`      | v1.4 (T)  | snapshot | `{affected_universe_size}` |
| `RAW_ARCHIVED`            | v1.4.1 (P3a-H) | snapshot | `{archived: [{source_id, kind, archived_copy_path}]}` |
| `WORM_VIOLATION`          | v1.4.1 (P3a-H) | snapshot | `{path, before, after}` (before/after = sha256 or null) |

---

## 2. 事件詳細規格

### `SUBFACTOR_COMPUTED`
**何時 emit**：每次計算一個 LeafScoreNode 時，記錄該葉節點的完整計算上下文。
**典型 reason**：`"leaf computed: chip.fii.sync_score = 0.0000"`
**範例**：
```jsonc
{
  "ticker": "3481",
  "event":  "SUBFACTOR_COMPUTED",
  "step":   "scoring.chip.fii.sync_score",
  "node_path": "composite.chip_score.fii_sub.sync_score",
  "reason": "linear[3,6] -> base[0,100] applied to fii_sync_count=3",
  "data": {
    "raw_inputs": { "fii_sync_count": 3 },
    "config_keys_resolved": {
      "stage_1.fii.sync_count.linear_range": [3, 6],
      "stage_1.fii.sync_count.base_at_min": 0,
      "stage_1.fii.sync_count.base_at_max": 100
    },
    "normalization": [
      { "op": "linear", "r_min": 3, "r_max": 6, "base_min": 0, "base_max": 100 },
      { "op": "clamp", "min": 0, "max": 100 },
      { "op": "quantize", "dp": 4, "rounding": "ROUND_HALF_EVEN" }
    ],
    "output_value": "0.0000",
    "clamped": false,
    "abstained": false
  }
}
```

### `FACTOR_LINEAGE`
**何時 emit**：每次計算一個內部 ScoreNode（factor 或 sub-factor）時，記錄子節點貢獻。
**典型 reason**：`"internal computed: chip_score = 50.9166"`
**範例**：
```jsonc
{
  "ticker": "3481",
  "event":  "FACTOR_LINEAGE",
  "step":   "scoring.chip",
  "node_path": "composite.chip_score",
  "reason": "weighted_sum of {fii_sub: 48.0000, mainforce_sub: 53.8333} = 50.9166",
  "data": {
    "child_paths":  ["composite.chip_score.fii_sub", "composite.chip_score.mainforce_sub"],
    "weights":      ["0.5", "0.5"],
    "child_values": ["48.0000", "53.8333"],
    "formula":      "0.5*fii_sub + 0.5*mainforce_sub",
    "output_value": "50.9166"
  }
}
```

### `CONFIG_RESOLVED`
**何時 emit**：當 core 讀取一個 config 鍵時。
> 量大；建議只在 `--audit-level=verbose` 時 emit，預設只記未命中（fallback to default）。

### `NORMALIZATION_APPLIED`
**何時 emit**：當一個 NormalizationStep 對節點 value 套用前後變化時。
> 量更大；通常合併入 `SUBFACTOR_COMPUTED` 的 `data.normalization`，獨立 emit 僅在 debug 模式。

### `FEATURE_FLAG_RESOLVED`
**何時 emit**：snapshot 啟動時，對所有 feature flag 讀取一次並 emit。
**典型 reason**：`"feature flag resolved: day_trader_exclusion=false (default)"`
**範例**：
```jsonc
{
  "ticker": null,
  "event":  "FEATURE_FLAG_RESOLVED",
  "step":   "core.feature_flags.resolve",
  "reason": "feature_flags.day_trader_exclusion=false (default)",
  "data": {
    "flag":           "day_trader_exclusion",
    "value":          false,
    "default":        false,
    "took_effect_at": "2026-05-22T15:59:00Z",
    "downstream_paths": ["composite.chip_score.mainforce_sub.concentration_score"]
  }
}
```

### `ABSTAIN_PROPAGATED`
**何時 emit**：當某子節點 abstain 導致父節點重新分配權重。
**範例**：
```jsonc
{
  "ticker": "9999",
  "event":  "ABSTAIN_PROPAGATED",
  "step":   "scoring.behavior.margin",
  "node_path": "composite.behavior_score.margin_sub",
  "reason":  "wash_score abstained (missing margin history); redistribute_within_siblings",
  "data": {
    "abstained_children":     ["wash_score"],
    "original_weights":       { "maintenance_score": 0.5, "wash_score": 0.3, "penalty_score": 0.2 },
    "active_weights":         { "maintenance_score": 0.714286, "penalty_score": 0.285714 },
    "active_sum_before_norm": "0.7"
  }
}
```

---

## 3. 體積與儲存策略

| Event | 預估筆 / 日 / 1800 檔 | 儲存 |
|---|---|---|
| ELIMINATED               | ~1600 (大多被剔) | 內嵌 `audit_log` |
| SUBFACTOR_COMPUTED       | ~16 × 1800 = 28800 | **獨立 `reports/<date>.audit.jsonl`** |
| FACTOR_LINEAGE           | ~7  × 1800 = 12600 | 同上 |
| FEATURE_FLAG_RESOLVED    | ~N × 1 (N = # of flags) | 內嵌 `audit_log` |
| ABSTAIN_PROPAGATED       | sparse | 內嵌 `audit_log` |
| HASH_MISMATCH 等 replay  | sparse | 內嵌 |

**規約**：高量事件分流至 sidecar `.audit.jsonl`，主 snapshot 只留摘要與例外。具體切分：
- snapshot.audit_log: 例外類 (ELIMINATED / *_MISMATCH / DATA_WARNING / ABSTAIN_PROPAGATED / TIE_RESOLVED / FEATURE_FLAG_RESOLVED)
- `reports/<date>.audit.jsonl`: 大量類 (SUBFACTOR_COMPUTED / FACTOR_LINEAGE / CONFIG_RESOLVED / NORMALIZATION_APPLIED)

Sidecar 也需 SHA-256 sidecar 與 immutability 政策（同 REPLAY.md §3 I1-I3）。

---

## 4. CI 強制檢查

對每份 snapshot：
1. `audit_log[*].event` 必在 enum 內
2. `audit_log[*].step` 必為點分隔的小寫蛇形命名 (`scoring.chip.fii.sync_score`)
3. ELIMINATED 必有對應 `gate` in data
4. SUBFACTOR_COMPUTED 必有 `node_path` 對應 score_tree 內存在的 leaf
5. FACTOR_LINEAGE 必有 `node_path` 對應 score_tree 內 kind=internal 節點
6. 每個 FEATURE_FLAG_RESOLVED 對應 config.feature_flags 必有對應 flag key

---

## 4.1 P3a-Hardening 事件詳細規格

### `RAW_ARCHIVED`
**何時 emit**：每次 `core.archive.archive_raw_inputs()` 跑完後，把當天 ingest
讀過的原始檔（today.json / branches/*.json / snapshots/*.json）複製到
`reports/_raw_archive/<date>/<source_id>/` 並驗證 archive bytes 重算 sha 等於
provenance 紀錄的 raw_sha256。此事件代表 WORM 從「我們承諾不動」升級到
「我們也存了一份可驗證的副本」。

**典型 reason**：
`"Archived 2 raw source(s) under _raw_archive/2026-05-25/; all archived sha equal raw_sha (WORM cryptographic proof)"`

**範例**：
```jsonc
{
  "ticker": null,
  "event":  "RAW_ARCHIVED",
  "reason": "Archived 2 raw source(s)...",
  "step":   "core.archive.archive_raw_inputs",
  "data": {
    "archived": [
      {"source_id":"legacy_today_json", "kind":"file", "archived_copy_path":"_raw_archive/2026-05-25/legacy_today_json/"},
      {"source_id":"legacy_branches",   "kind":"dir",  "archived_copy_path":"_raw_archive/2026-05-25/legacy_branches/"}
    ]
  }
}
```

**Severity**: INFO. 若 archive sha ≠ raw_sha，pipeline 直接 raise — 不會 emit 這個事件。

### `WORM_VIOLATION`
**何時 emit**：pipeline 在 ingest 前後各取一次 `core.worm_check.snapshot_manifest()`，
比對任何被監控的原始檔（data/today.json、data/branches/、data/snapshots/、
data/history/）在 ingest 期間是否被修改、刪除或新增。任何一種異動都
emit 一個事件並 hard-abort pipeline（不寫 snapshot 不更新 index）。

**典型 reason**（三種 kind）：
- `"raw file modified during ingest: data/branches/2330.json"` — 內容被改
- `"raw file removed during ingest: data/branches/2454.json"` — 被刪
- `"new raw file appeared during ingest: data/branches/9999.json"` — 新增

**範例**：
```jsonc
{
  "ticker": null,
  "event":  "WORM_VIOLATION",
  "reason": "raw file modified during ingest: data/branches/2330.json",
  "step":   "core.worm_check.verify_manifest",
  "data": {
    "path":   "data/branches/2330.json",
    "before": "sha256:aaa...",
    "after":  "sha256:bbb..."
  }
}
```

**Severity**: FATAL. 出現此事件代表上游資料管線在我們 ingest 期間動了原始檔
（例如另一支抓取程式並行運作）。replay 合法性不可恢復，必須先排除上游再重跑。

---

## 5. 與其他文件交叉指引

- 事件 schema → `schema/canonical_schema.json` `audit_log[].event` enum
- 重現性事件 → [REPLAY.md](REPLAY.md) §8
- 評分事件 → [SCORE_NODE.md](SCORE_NODE.md)
- Feature flag → [FEATURE_FLAGS.md](FEATURE_FLAGS.md)
