# SCD Engine — Canonical Schema 統一資料結構

> Version: v1.0 (2026-05-22)
> JSON Schema 機器檔: `schema/canonical_schema.json`
> **所有 `/core`、`/reports`、`/ui`、`/research` 模組必須讀寫此 schema。違反 = build 失敗。**

---

## 0. 設計原則

1. **欄位扁平化 (flat)**：避免深巢狀；查詢成本可預期。
2. **欄位名英文 snake_case；註解中英對照。**
3. **每欄須有 `data_source` 與 `data_timestamp`**：寫在頂層 `provenance` 區塊，按來源分組。
4. **數值缺失用 `null`**，禁用 `-999`、`-1` 等魔術數。
5. **新增欄位需 bump schema version**：`schema_version` 為 SemVer。

---

## 1. 頂層結構 (Top-level)

```jsonc
{
  "schema_version": "1.0.0",         // schema 版本 / Schema version (SemVer)
  "date": "2026-05-22",              // 交易日 / Trading date (ISO 8601)
  "generated_at": "2026-05-22T23:59:00+08:00",
                                     // snapshot 凍結時間 / Snapshot freeze timestamp
  "config_hash": "sha256:ab12...",   // 該日所用 config 的雜湊 / Hash of config used
  "core_version": "core@1.0.0",      // /core 引擎版本 / Engine version
  "provenance": { ... },             // 資料來源與時間戳 / Data source & timestamp
  "config_snapshot": { ... },        // 該日完整 config 凍結副本 / Frozen copy of config
  "universe_size": 1800,             // 當日篩選母體大小 / Initial universe count
  "eligible_count": 142,             // 通過三道 gate 的檔數 / Count passing all gates
  "stocks": [ { /* StockRecord */ } ],
  "rankings": { /* RankingsBlock */ },
  "audit_log": [ /* AuditEntry */ ]
}
```

---

## 2. `provenance` 區塊

```jsonc
{
  "fii_data":         { "source": "TWSE_OpenAPI",   "fetched_at": "2026-05-22T15:30:12+08:00" },
  "broker_branch":    { "source": "BrokerChip_CSV", "fetched_at": "2026-05-22T16:05:33+08:00" },
  "margin":           { "source": "TWSE_Margin",    "fetched_at": "2026-05-22T15:35:00+08:00" },
  "shareholder":      { "source": "TDCC_Weekly",    "fetched_at": "2026-05-17T00:00:00+08:00" },
                                     // 集保週報 / TDCC weekly (note: lags trading day)
  "price_volume":     { "source": "TWSE_Daily",     "fetched_at": "2026-05-22T15:00:05+08:00" },
  "intraday_kline":   { "source": "Realtime_30min", "fetched_at": "2026-05-22T13:30:00+08:00" }
}
```

> ⚠️ **TDCC 股權分散是週報，會有 lag。** core 必須以 `fetched_at` 而非 `date` 為時序基準計算 delta。

---

## 3. `StockRecord` — 個股紀錄

### 3.1 身分欄 (Identity)

| 欄位 (key) | 型別 | 說明 (zh) | Description (en) |
|---|---|---|---|
| `ticker` | string | 股票代號 | Ticker symbol (e.g., "3481") |
| `name` | string | 公司名 | Company name |
| `market` | enum | TWSE / TPEx / Emerging | Listing venue |
| `industry` | string | 產業別 | Industry classification |

### 3.2 量價欄 (Price & Volume)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `current_price` | number | 收盤價 | Closing price (TWD) |
| `prev_close` | number | 前收盤 | Previous close |
| `change_pct` | number | 漲跌幅 % | Day change % |
| `volume` | integer | 成交張數 | Volume (lots) |
| `volume_5d_avg` | integer | 5 日均量 | 5-day avg volume |
| `volume_ratio` | number | 當日量/5日均量 | Today vs 5d avg |

### 3.3 籌碼欄 — 外資 (FII / Foreign Institutional)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `fii_net_buy` | integer | 外資當日淨買超張 | FII net buy (lots) |
| `fii_buy_ratio` | number | 外資買超 / 成交量 | FII share of volume |
| `fii_holding_pct` | number | 外資持股比例 | FII holding % |
| `fii_holding_trend_5d` | enum | up / flat / down | 5-day holding trend |
| `fii_sync_count` | integer | 同步買進的指標分點數 | # of indicator brokers buying |
| `fii_brokers_buying` | array<string> | 買超指標分點清單 | List of buying indicator brokers |
| `fii_consecutive_buy_days` | integer | 外資連買天數 | FII consecutive buying days |

### 3.4 籌碼欄 — 主力分點 (Main Force / Broker Branches)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `main_force_buy` | integer | 買超前 5 分點累計買張 | Top-5 branches net buy (lots) |
| `top5_branches` | array<object> | `[{branch, buy, sell, net}]` | Top-5 branch details |
| `main_force_cost` | number | 主力近 5 日買進均價 | 5-day buy VWAP |
| `main_force_consecutive_days` | integer | 主力連買天數 | Consecutive net-buy days |
| `main_force_volume_trend` | array<integer> | 每日買超張數陣列（時序） | Daily net-buy series |
| `volume_increasing_streak` | integer | F(n)>F(n−1) 連續段數 | Increasing volume streaks |
| `top5_concentration` | number | 前5分點買超佔總買超 | Top-5 share of total buys |
| `dealer_net_buy` | integer | 自營商淨買超（區分長/短線） | Dealer net buy |
| `is_day_trader_branch` | boolean | 是否含隔日沖分點（如凱基-台北） | Contains short-cycle dealers? |

### 3.5 行為背離欄 (Behavioral Divergence)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `shareholder_count` | integer | 當前股東總人數 | Current shareholder count |
| `shareholder_count_delta_pct` | number | 較上週變化 % | Weekly delta % (negative = good) |
| `broker_count_diff` | integer | 買家數 − 賣家數 | Buy − sell broker count |
| `broker_count_diff_negative_streak` | integer | 連負天數 | Consecutive days negative |
| `large_holder_400_pct` | number | 400 張以上大戶持股 % | ≥400-lot holder share |
| `large_holder_400_delta_pct` | number | 較上週變化 % | Weekly delta |
| `large_holder_1000_pct` | number | 1000 張以上大戶持股 % | ≥1000-lot holder share |
| `large_holder_1000_delta_pct` | number | 較上週變化 % | Weekly delta |

### 3.6 融資心理欄 (Margin Psychology)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `margin_balance` | integer | 融資餘額（張） | Margin balance (lots) |
| `margin_change` | integer | 融資增減 | Margin daily change |
| `margin_maintenance_ratio` | number | 融資維持率 % | Margin maintenance ratio % |
| `price_down_margin_down_days_10d` | integer | 10 日內價跌融資減的天數 | Healthy washout days |
| `price_down_margin_up_days_10d` | integer | 10 日內價跌融資增的天數 | Unhealthy resistance days |
| `margin_panic_signal` | boolean | 是否觸發 140% 絕望點 | 140% panic-buy signal |

### 3.7 價格行為欄 (Price Action)

| 欄位 | 型別 | 說明 | Description |
|---|---|---|---|
| `pa_signals_30m` | array<enum> | `[pin_bar, engulfing, terminal, retest]` | 30-min PA signals |
| `trend_2h` | enum | up / flat / down | 2-hour trend |
| `above_20ema_2h` | boolean | 站上 2H 20EMA | Above 2H 20-EMA |
| `ema_slope_2h` | enum | positive / flat / negative | 2H EMA slope |

### 3.8 評分欄 (Scoring — 由 /core 寫入)

| 欄位 | 型別 | 說明 |
|---|---|---|
| `gates` | object | `{G1: bool, G2: bool, G3: bool, eliminated_by: string\|null}` |
| `stage_1` | number | 雙引擎子分 0-100 |
| `stage_1_breakdown` | object | `{fii_sub, main_force_sub, ...}` 計分明細 |
| `stage_2` | number | 行為背離子分 0-100 |
| `stage_2_breakdown` | object | 同上 |
| `stage_3` | number | 執行觸發子分 0-100 |
| `stage_3_breakdown` | object | 同上 |
| `composite_score` | number | 加權合分 0-100 |
| `tier` | enum | GOLDEN / WATCH / NEUTRAL / IGNORE |
| `trade_type` | enum | T1 / T2 / null |
| `safety_margin_pct` | number | (cost − price)/cost；負值代表已超過 5% |

### 3.9 檢核清單欄 (Daily Checklist — V3 §六)

```jsonc
"checklist": {
  "dual_engine_aligned":  true,    // 外資跟主力站同一邊？
  "cost_within_5pct":     true,    // 我現在買有沒有貴超過 5%？
  "shareholders_dropping": true,   // 股東人數有變少？
  "margin_healthy":       true,    // 融資減少 (好) 還是增加 (壞)？
  "margin_ratio":         138.0,   // 維持率幾 %？
  "pa_signal_present":    true     // 有沒有 Pin Bar / Engulfing？
}
```

---

## 4. `rankings` 區塊

```jsonc
{
  "golden":  ["3481", "2454", "2330"],   // composite ≥ 85，已套用 tie-breaker
  "watch":   ["6669", "5274", ... ],     // 70 ≤ composite < 85
  "neutral": [...],                       // 50 ≤ composite < 70
  "ignored": [...],                       // < 50 或被 gate 剔除
  "sort_keys_used": [                     // 排序鍵紀錄（用於除錯）
    "composite_score desc",
    "stage_1 desc",
    "main_force_consecutive_days desc",
    "fii_sync_count desc",
    "ticker asc"
  ]
}
```

---

## 5. `audit_log` 區塊

每次 core 運行的決定論證據鏈，記錄每筆「為何被剔除」與「資料異常」。

```jsonc
[
  {
    "ticker": "2317",
    "event":  "ELIMINATED",
    "reason": "G1 violated: current_price=124.0 > main_force_cost=117.0 × 1.05 = 122.85",
    "step":   "filters.cost_safety_gate"
  },
  {
    "ticker": "3481",
    "event":  "DATA_WARNING",
    "reason": "fii_buy_ratio is null; FII buy_ratio sub-score recorded as 0",
    "step":   "scoring.stage_1.fii_buy_ratio"
  }
]
```

---

## 6. 不變式 (Invariants)

CI 必須驗證以下任一被破壞 → build fail：

1. `0 ≤ stage_1, stage_2, stage_3, composite_score ≤ 100`
2. `composite_score == round(0.40*s1 + 0.35*s2 + 0.25*s3, 2)` 容差 < 0.01
3. `tier == "GOLDEN"` ⇔ `composite_score >= 85 AND gates.G1 AND gates.G2 AND gates.G3`
4. `eliminated_by` 非空 → `stage_1 == stage_2 == stage_3 == 0`
5. `rankings.golden` 必為依 `composite_score` 降序、tie 由 `sort_keys_used` 鏈解決
6. `len(stocks) == universe_size`
7. `len(rankings.golden) + len(rankings.watch) + len(rankings.neutral) + len(rankings.ignored) == universe_size`

---

## 7. AI 可讀區段 (AI-readable Subset)

`/research` 的 AI 只應該讀以下欄位，**禁止讀 `audit_log` 與 `config_snapshot`**（避免 prompt 把 config 當輸入做推論）：

```
date, generated_at, stocks[].{ticker, name, industry, current_price, change_pct,
  composite_score, tier, stage_1, stage_2, stage_3, trade_type, checklist,
  fii_sync_count, main_force_consecutive_days, margin_maintenance_ratio,
  pa_signals_30m, top5_branches[:3]}
rankings.{golden, watch}
```

詳見 [AI_GOVERNANCE.md](AI_GOVERNANCE.md)。
