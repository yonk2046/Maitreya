# SCD Engine 欄位三態分類 + Domain 命名對照（Phase 0 規格）

> 配套 `DATA_CONTRACT_ASSESSMENT_2026-07-08.md`。本文是**規格產物，不含 code 改動**。
> 決策已定：**扁平前綴** domain 命名；本輪只寫規格（Phase 0）。
> 三態：**I**=Input(raw，adapter 讀入) · **O**=Observation(引擎算出) · **M**=Metadata(不參與 replay)。
> Replay：I+O 參與 canonical hash；M 應排除（現況未排除，見評估 §4，Phase 4 處理）。
> 🔴=correctness 地雷（語意錯/資料遺失）；🟡=誤導命名；🟢=命名正確。

---

## A. 頂層 snapshot 欄位

| 現名 | 三態 | Replay | 提議前綴名 | 註 |
|---|---|---|---|---|
| schema_version | M | N | (不變) | 版本識別 |
| date | I | Y | (不變) | 交易日，identity |
| generated_at | M | **N** | (不變) | 牆鐘，replay 比對時已抹 |
| config_hash | O | Y | (不變) | config 衍生完整性值 |
| core_version | M | N | (不變) | |
| environment | M | **N** | (不變) | 🔴 含 python/os/numpy → 目前污染 replay hash，Phase 4 修 |
| provenance | M | Y(lineage) | (不變) | raw_sha/archive 背書，lineage |
| config_snapshot | I | Y | (不變) | 凍結 config |
| universe_size | O | Y | (不變) | 衍生計數 |
| eligible_count | O | Y | (不變) | |
| fii_pending | O | Y | (不變) | 1.8.1 兩段式快照旗標 |
| market_regime | O | Y | obs_market_regime | 目前 stub |
| episodes_active_at_start | O | Y | obs_episodes_active | |
| episodes_changed_today | O | Y | obs_episodes_changed | |
| tier_transitions | O | Y | obs_tier_transitions | |
| stocks[] | I+O | Y | (不變) | 見 B/C/D |
| rankings | O | Y | obs_rankings | |
| audit_log | M | Y(lineage) | (不變) | 事件流水 |

---

## B. Stock record — Input（raw，命名/domain 問題集中區）

| 現名 | 三態 | 提議前綴名 | 標記 | 註（證據） |
|---|---|---|---|---|
| ticker | I | (不變) | 🟢 | identity |
| name / market / industry | I | (不變) | 🟢 | |
| current_price / open / prev_close | I | market_price / market_open / market_prev_close | 🟢 | |
| change_pct | I | market_change_pct | 🟢 | 來自 marketQuotes |
| **volume** | I | **mf_net_buy** | 🔴🟡 | 名叫「量」實為主力買超張數（ingest.py:155←buy_vol_lots） |
| market_volume | I | market_volume | 🟢 | 唯一正確的「量」(ingest.py:160) |
| fii_net_buy | I | foreign_net_buy | 🟡 | 外資淨買(張)，fii→foreign 統一 domain |
| fii_holding_pct | I(pending) | foreign_holding_pct | 🟡 | 目前恆 None |
| fii_brokers_buying | I | foreign_brokers_buying | 🟡 | |
| main_force_buy | I | mf_buy | 🟢 | branches 或 rollup |
| top5_branches | I | mf_top5_branches | 🟢 | |
| main_force_cost | I | mf_cost | 🟢 | |
| **dealer_net_buy** | I | **trust_net_buy** | 🔴 | **名叫自營商實裝投信**(ingest.py:182←investment_trust_net_buy) |
| (缺) 真自營商 prop | I | **dealer_net_buy(prop)** | 🔴 | adapter 算了(legacy.py:327)但**無欄位收→被丟棄** |
| is_day_trader_branch | I | mf_is_day_trader | 🟢 | |
| shareholder_count | I | tdcc_shareholder_count | 🟢 | TDCC 週資料 |
| large_holder_400_pct / _1000_pct | I | tdcc_large_holder_400_pct / _1000_pct | 🟢 | |
| margin_balance / margin_maintenance_ratio | I(pending) | margin_balance / margin_maintenance_ratio | 🟢 | 目前 None |
| pa_signals_30m / trend_2h / above_20ema_2h / ema_slope_2h | I | pa_* | 🟢 | 盤中，多為 stub |

---

## C. Stock record — Observation（引擎算出，必須 replay 可重建）

| 現名 | 提議前綴名 | 標記 | 註 |
|---|---|---|---|
| volume_5d_avg | mf_buy_5d_avg | 🟡 | 主力買超5日均，非成交量 |
| **volume_ratio** | **mf_buy_momentum_ratio** | 🔴🟡 | 主力買超動能比；**死欄位0消費者**(market_context.py:208) |
| velocity_3d / acceleration | derived_velocity_3d / derived_acceleration | 🟢 | |
| fii_sync_count | derived_participant_sync_count | 🟡 | 0–3 同向數 |
| fii_consecutive_buy_days | foreign_consecutive_buy_days | 🟡 | |
| main_force_consecutive_days | mf_consecutive_days（alias） | 🟡 | 1.8.0 起=strict 語意的相容別名 |
| main_force_strict_streak_days | mf_strict_streak_days | 🟢 | |
| main_force_positive_days_in_window | mf_positive_days_20d | 🟢 | |
| net_accumulation_in_window | mf_net_accum_20d | 🟢 | Bug4 誤報處，實已持久化 |
| main_force_volume_trend | mf_buy_trend_5d | 🟡 | 主力買超序列 |
| volume_increasing_streak | mf_buy_increasing_streak | 🟡 | |
| top5_concentration | mf_top5_concentration | 🟢 | |
| shareholder_count_delta_pct | tdcc_shareholder_delta_pct | 🟢 | |
| broker_count_diff / _negative_streak | tdcc_broker_diff / _neg_streak | 🟢 | |
| large_holder_400_delta_pct / _1000_delta_pct | tdcc_large_holder_400_delta / _1000_delta | 🟢 | |
| margin_change / price_down_margin_*_10d / margin_panic_signal | margin_* | 🟢 | 多為 stub |
| gates / stage_1..3(+breakdown) / composite_score / tier / trade_type / safety_margin_pct / checklist | obs_* | 🟢 | **P3a 全 abstain**(tier=IGNORE,score=0) |
| temporal_state | obs_temporal_state | 🟢 | |
| data_completeness / confidence_tier | obs_completeness / obs_confidence_tier | 🟢 | schema v1.5 |
| momentum_direction / signal_age_days / delta_vs_yesterday | obs_* | 🟢 | 多為 stub |

### C-未落地（現 render-time，Phase 2 要 sink 進來）
| viewer 現算的 observation | 證據 | 提議欄位 |
|---|---|---|
| 真·量能比(market_volume/20日均) | cockpit.py:2388 | market_volume_ratio |
| 黃金 tier / gates / conviction | _run_golden render-time | obs_golden_tier / obs_golden_gates |
| 共振 level / 成員 | resonance render-time | obs_resonance_level / obs_resonance_members |
| confidence / distribution / sector | 各 core 模組 render-time | obs_confidence / obs_distribution / obs_sector |

---

## D. Domain 命名對照（摘要）

```
market_*   價格與市場量：market_price, market_open, market_change_pct, market_volume, market_volume_ratio
mf_*       主力(Fubon)：mf_buy, mf_net_buy(舊volume), mf_cost, mf_buy_momentum_ratio(舊volume_ratio),
                        mf_strict_streak_days, mf_positive_days_20d, mf_net_accum_20d, mf_top5_*
foreign_*  外資(T86)：foreign_net_buy(舊fii_net_buy), foreign_consecutive_buy_days, foreign_holding_pct
trust_*    投信(T86)：trust_net_buy   ← 修正:現被錯放在 dealer_net_buy
dealer_*   自營商(T86)：dealer_net_buy(prop) ← 修正:找回被丟棄的資料
tdcc_*     集保週：tdcc_shareholder_count, tdcc_large_holder_*
margin_*   融資：margin_balance, margin_maintenance_ratio, ...
derived_*  純衍生：derived_velocity_3d, derived_acceleration, derived_participant_sync_count
obs_*      判斷層：obs_golden_tier, obs_resonance_level, obs_confidence, obs_distribution, ...
```

**命名鐵律**：量標語意（買超 vs 成交量）；比率標分子語意（mf_buy_momentum vs market_volume_ratio）；
participant domain 不混（foreign/trust/dealer 三分，禁一欄裝另一 domain）。

---

## E. 契約原則草案（提議併入 ARCHITECTURE.md AI_GOVERNANCE）

- **C1 命名即語意**：欄位名不需讀 source 就懂 domain + 單位。
- **C2 Observation 必落 snapshot**：UI 顯示的判斷值必須寫進 snapshot、replay 可重建；viewer 純渲染。
- **C3 三態分離**：Input / Observation / Metadata；replay hash 只吃 I+O。
- **C4 一份資料一個語意**：禁同值兩處不同名或同名不同義（dealer/trust 事故）。
- **C5 rename=additive migration**：跨 minor，deprecated 標移除版本，replay 期間持續寫入。
- **C6 每個 observation 標 producer**：註明哪個 core 模組算的 + replay 等級。

---

## F. 下一步（等 Yonki 指示，本輪不做）
Phase 1 修 dealer/trust correctness（找回自營商）→ Phase 2 sink observation → Phase 3 volume 大 rename
→ Phase 4 metadata/replay 白名單。每步 additive + replay 綠才進下一步。
