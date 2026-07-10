# Phase 1 WORM 回填覆蓋率報告

> 產生方式：`python3 -m tools.worm_backfill_coverage`（唯讀，掃 `reports/_raw_archive/<date>/` 全部歷史存檔 today.json）。
> 目的：量化 Phase 2（1.9.0）能把 trust_net_buy／prop_net_buy／賣方 raw 回填到多深——WORM 存檔缺的資料，backfill 無論如何都補不回來（誠實面對缺口，C10）。

## 摘要

- **日期範圍**：2026-05-08 ~ 2026-07-10（43 個已存檔日期）
- **prop（自營商）覆蓋率**：27/43 天（62.8%）至少 1 檔有值；逐檔覆蓋 388604/388604（100.0%，僅計有 today.json 存檔的天）
- **sellList／mainForceSell（賣方榜）覆蓋率**：32/43 天（74.4%） 至少一份非空榜
- **today.json 存檔本身**：32/43 天有 legacy_today_json 存檔（其餘 11 天只有 legacy_rollup——結構性不含 T86/賣方榜，backfill 無解，非缺陷）
- **有缺口的天數**：16/43（見下方缺口清單）

## 逐日明細

| 日期 | today.json 存檔 | T86 檔數 | prop 有值 | trust 有值 | sellList 列數 | mainForceSell 列數 | 備註 |
|---|---|---|---|---|---|---|---|
| 2026-05-08 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-13 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-14 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-15 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-17 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-18 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-20 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-21 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-22 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-25 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-26 | ✅ | 16293 | 16293 | 16293 | 41 | 39 |  |
| 2026-05-27 | ❌ rollup-only | 0 | 0 | 0 | 0 | 0 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-28 | ✅ | 0 | 0 | 0 | 45 | 38 | t86 empty in archived today.json (fii_pending day) |
| 2026-05-29 | ✅ | 0 | 0 | 0 | 0 | 30 | t86 empty in archived today.json (fii_pending day) |
| 2026-06-01 | ✅ | 16018 | 16018 | 16018 | 41 | 36 |  |
| 2026-06-02 | ✅ | 16059 | 16059 | 16059 | 33 | 29 |  |
| 2026-06-03 | ✅ | 0 | 0 | 0 | 45 | 33 | t86 empty in archived today.json (fii_pending day) |
| 2026-06-04 | ✅ | 15077 | 15077 | 15077 | 32 | 29 |  |
| 2026-06-05 | ✅ | 14902 | 14902 | 14902 | 36 | 30 |  |
| 2026-06-08 | ✅ | 14902 | 14902 | 14902 | 40 | 29 |  |
| 2026-06-09 | ✅ | 13664 | 13664 | 13664 | 42 | 34 |  |
| 2026-06-10 | ✅ | 14391 | 14391 | 14391 | 32 | 26 |  |
| 2026-06-11 | ✅ | 14917 | 14917 | 14917 | 39 | 25 |  |
| 2026-06-12 | ✅ | 14065 | 14065 | 14065 | 48 | 41 |  |
| 2026-06-15 | ✅ | 14031 | 14031 | 14031 | 48 | 41 |  |
| 2026-06-16 | ✅ | 14183 | 14183 | 14183 | 47 | 43 |  |
| 2026-06-17 | ✅ | 14183 | 14183 | 14183 | 42 | 33 |  |
| 2026-06-18 | ✅ | 13498 | 13498 | 13498 | 48 | 38 |  |
| 2026-06-22 | ✅ | 15666 | 15666 | 15666 | 43 | 36 |  |
| 2026-06-23 | ✅ | 15669 | 15669 | 15669 | 35 | 29 |  |
| 2026-06-24 | ✅ | 15099 | 15099 | 15099 | 30 | 19 |  |
| 2026-06-25 | ✅ | 0 | 0 | 0 | 46 | 34 | t86 empty in archived today.json (fii_pending day) |
| 2026-06-26 | ✅ | 13981 | 13981 | 13981 | 30 | 20 |  |
| 2026-06-29 | ✅ | 14361 | 14361 | 14361 | 38 | 29 |  |
| 2026-06-30 | ✅ | 14354 | 14354 | 14354 | 49 | 36 |  |
| 2026-07-01 | ✅ | 14359 | 14359 | 14359 | 45 | 44 |  |
| 2026-07-02 | ✅ | 14461 | 14461 | 14461 | 0 | 44 |  |
| 2026-07-03 | ✅ | 13999 | 13999 | 13999 | 42 | 34 |  |
| 2026-07-06 | ✅ | 14506 | 14506 | 14506 | 40 | 29 |  |
| 2026-07-07 | ✅ | 14523 | 14523 | 14523 | 32 | 25 |  |
| 2026-07-08 | ✅ | 13521 | 13521 | 13521 | 34 | 27 |  |
| 2026-07-09 | ✅ | 7922 | 7922 | 7922 | 49 | 36 |  |
| 2026-07-10 | ✅ | 0 | 0 | 0 | 49 | 36 | t86 empty in archived today.json (fii_pending day) |

## 缺口清單（prop 或賣方榜任一缺）

| 日期 | 缺什麼 | 原因 |
|---|---|---|
| 2026-05-08 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-13 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-14 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-15 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-17 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-18 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-20 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-21 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-22 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-25 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-27 | prop+賣方榜 | legacy_rollup only — pre-fetch_daily.py backfill shape, structurally no T86/sell data |
| 2026-05-28 | prop | t86 empty in archived today.json (fii_pending day) |
| 2026-05-29 | prop | t86 empty in archived today.json (fii_pending day) |
| 2026-06-03 | prop | t86 empty in archived today.json (fii_pending day) |
| 2026-06-25 | prop | t86 empty in archived today.json (fii_pending day) |
| 2026-07-10 | prop | t86 empty in archived today.json (fii_pending day) |

## Phase 2 回填深度結論

- 可回填 prop_net_buy 的最早日期：**2026-05-26**（27 天可回填，早於此的 rollup-only 天結構性無 T86，Phase 2 backfill 誠實放棄，不偽稱可回溯 — C10）
- 可回填賣方 raw 的最早日期：**2026-05-26**（32 天可回填）
- rollup-only 天（2026-05-08, 2026-05-13, 2026-05-14, 2026-05-15, 2026-05-17, 2026-05-18, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-25, 2026-05-27）：無 today.json 存檔，trust/prop/賣方 raw 三者皆結構性不存在，Phase 2 backfill 範圍上限即此清單。

