# SCD Engine 資料契約評估 — 2026-07-08

> 觸發：Bug 2「量比 2.3 vs 0.85」被判定為命名地雷後，Yonki 要求停手，改從 Data
> Contract / Data Model 角度做長期(2–3 年)架構評估，而非只修這一行。
> 本文只做**評估與提案**，不改任何 code。決策後才進入遷移。
> 作者：Claude Code (opus)。狀態：待 Yonki 裁示。

---

## 0. 一句話判斷

**是 Data Model 問題，而且比命名更深**：現況同時存在(a)誤導性命名、(b)domain 錯置
（自營商欄位裝投信、真自營商資料被丟棄）、(c)整個 observation 層不落 snapshot。
**但不要現在大改 schema。** 你有 40 份 replay-locked 快照 + WORM 契約，任何 rename 都是
跨 epoch 遷移，錯一步毀 replay。Evidence Collection Phase 的正確第一步是：**先凍結一份
資料契約規格 + 欄位三態分類（本文），再用 additive+alias 分階段遷移。**

---

## 1. 現況盤點：欄位的三種病（全附證據）

### 病 A — 誤導性命名（讀名字會誤解語意/單位）
| 欄位 | 名字讓人以為 | 實際是 | 證據 |
|---|---|---|---|
| `volume` | 市場成交量 | 主力買超張數(Fubon) | [ingest.py:155](../core/ingest.py) ← `buy_vol_lots` |
| `volume_ratio` | 成交量比 | 主力買超動能比(today_mfb / 5日均 mfb) | [market_context.py:208](../core/market_context.py) |
| `volume_5d_avg` | 成交量5日均 | 主力買超5日均 | 同上 |
| `market_volume` | (正確) | 真市場成交量(張) | [ingest.py:160](../core/ingest.py) ✅ 唯一命名正確的量 |

單位也不透明：多數「張數」欄位沒在名字/schema 標單位；金額(cost)與比率(ratio)混在同層。

### 病 B — Domain 錯置（比命名嚴重，是 correctness）
| 現象 | 證據 | 後果 |
|---|---|---|
| `dealer_net_buy`(自營商)實際裝**投信**淨買 | [ingest.py:182](../core/ingest.py) ← `investment_trust_net_buy` | resonance「投信」參與者讀 `dealer_net_buy`，碰巧資料對但名字是地雷 |
| 真**自營商**(prop)資料算了卻**沒任何欄位收** | adapter 有 [legacy.py:327](../data/adapters/legacy.py) `prop_dealer_net_buy`，ingest record 無此欄位 | 自營商訊號永久遺失，未來要用得重抓 |
| 投信**沒有**自己正名的欄位 | grep `trust_net_buy` = 0 命中 | 想加真自營商訊號的人會讀 `dealer_net_buy` → 拿到投信 |

這正是你擔心的「同一份資料在不同地方有不同語意」，且已實際發生。

### 病 C — Observation 不落 snapshot（見 §2，這是根病）

---

## 2. 根本病灶：Snapshot 是「半成品」

P3a 是 ingest-only：snapshot 只存 raw，**所有評分/觀察都是 abstain**。實測 2026-07-07：
- 39 檔 `tier` 全 = `IGNORE`，`composite_score` 全 = 0。
- 頂層**沒有** golden / confidence / resonance / distribution 任何 key。

也就是說，你在網站上看到的**每一個判斷**——黃金名單、State、Confidence、Distribution、
共振、量能比、Sector 輪動——**全是 viewer 在 render-time 呼叫 core 模組即時算的**，
不在 snapshot 裡。後果三條：

1. **replay 只保證 raw 可重建，不保證 observation 可重建。** 改一行 golden.py，昨天的
   「可執行名單」就變了，而歷史 snapshot 完全無法證明「當時系統到底判了什麼」。
2. **「UI == snapshot」天然不成立**——因為 observation 根本不在 snapshot。Bug 2/Bug 3 的
   前後端不一致，本質都是這條：viewer 現算的東西 JSON 裡沒有。
3. **backtest 與 viewer 可能對同一份 snapshot 算出不同 observation**（各自呼叫、版本漂移）。

→ 這是你 Q3 的答案：**契約現在被系統性違反，但不是 bug，是 P3a 的階段設計。**
Evidence Collection Phase 的核心動作，就是把 observation 層「沉澱(sink)」進 snapshot。

---

## 3. 提案：Data Domain 結構（回答 Q2）

你提的 `market.* / main_force.* / foreign.* / trust.* / dealer.* / derived.* / observation.*`
方向對。但**深 nested JSON vs 扁平命名空間前綴**要取捨：

| | 深 nested (`market:{volume,ratio}`) | 扁平前綴 (`market_volume`,`mf_net_buy`) |
|---|---|---|
| Domain 清晰度 | 高 | 高(前綴即 domain) |
| replay 遷移成本 | **高**：結構改動=全 40 epoch 遷移，canonical key 排序雖穩定但巢狀重組風險大 | 低：加欄位不動結構 |
| provenance / field_to_source | **要重寫**（現在是 flat map [ingest.py:256](../core/ingest.py)） | 幾乎不動 |
| 容納 per-domain metadata | 好(可放 `market:{_source,_lag}`) | 差 |
| 多市場/多資料源擴充 | 好 | 尚可 |

**建議：先採「扁平 + domain 前綴」**（`market_`/`mf_`/`foreign_`/`trust_`/`dealer_`/`derived_`/`obs_`），
達成同樣的 domain 清晰，遷移成本低一個數量級；**深 nested 留給真的要做多市場時的 2.0 major**。
命名表草案：

```
market_volume, market_volume_ratio, market_change_pct
mf_net_buy, mf_buy_ratio, mf_cost, mf_strict_streak_days, mf_positive_days_20d, mf_net_accum_20d
foreign_net_buy, foreign_consecutive_buy_days, foreign_holding_pct
trust_net_buy            # ← 修正:投信正名(現 dealer_net_buy)
dealer_net_buy           # ← 修正:真自營商(現被丟棄的 prop)
derived_velocity_3d, derived_acceleration
obs_golden_tier, obs_confidence, obs_resonance_level, obs_distribution_grade   # ← §2 sink 進來
```

---

## 4. Observation vs Metadata + Replay Contract（回答 Q4）

**定義三態**（建議寫進 ARCHITECTURE.md）：

- **Input（raw）**：adapter 從外部讀進來的原始值 → 參與 replay，由 provenance + `_raw_archive` 背書。
- **Observation（derived）**：引擎算出來的(score/tier/golden/ratio/velocity) → **必須參與 replay，
  且必須落 snapshot**（現在違反：見 §2）。
- **Metadata**：`generated_at`/`fetched_at`/`report_date`/`data_lag_days`/`environment(python/os/numpy)`
  → **不該參與 replay hash**。

**現況風險（需驗證後修）**：`canonical_sha256` 吃**整份** snapshot（[hashing.py:52](../core/hashing.py)），
含 `environment` 的 python/os/numpy 版本。replay 只在比對時抹掉 `generated_at`
（[run_pipeline.py:235](../tools/run_pipeline.py)），**沒抹 environment**。推論：換機器 / 升 numpy
可能讓 full-replay 假失敗（legacy-epoch 靠 disk-hash 鎖定不受影響，但 current-schema 的
full-replay 會）。**建議：canonical 前先 strip 一個明確的 metadata 白名單**，讓 replay 只吃
Input+Observation。此點請先寫一個跨機器 replay 測試驗證，再決定修法。

完整欄位三態分類清單：待本提案方向核可後，作為第一個產物補上（约 60 欄位逐一標記）。

---

## 5. Migration Strategy（回答 Q5）

**確認 additive+alias 是對的，而且你已有先例**：1.8.0 把 `main_force_consecutive_days`
保留為 `main_force_strict_streak_days` 的 alias（[ingest.py:174-178](../core/ingest.py)）。

**遷移 SOP 五步（立為鐵律）**：
1. 新增正名欄位，與舊欄位**並存**（舊欄位值不變）。
2. viewer / 每個 consumer **逐一**改讀新欄位（一次一個，跑 replay+test）。
3. 新欄位進 schema + bump **minor**；舊欄位在 schema description 標 `DEPRECATED since 1.x, remove in 2.0`。
4. 全 consumer 遷完後，舊欄位轉為純 alias（仍寫入，維持舊 epoch replay）。
5. 下個 **major** 才移除 alias。

**關鍵護欄**：deprecated 欄位在 replay 生命週期內**必須繼續寫入**——否則重跑舊 epoch
會少欄位、hash 破。rename 一律「加新不刪舊」跨至少一個 minor。

---

## 6. 長期契約原則（回答 Q6）— 建議寫進 ARCHITECTURE.md AI_GOVERNANCE

- **C1 命名即語意**：欄位名不需讀 source 就懂 domain + 單位。量→標單位(張/股)，金額/比率不同層不混名。
- **C2 Observation 必落 snapshot**：任何 UI 顯示的判斷值，必須寫進 snapshot、replay 可重建；
  viewer **純渲染**，禁 render-time 衍生。（現有紅線 #1 的強化版：從「不重算衍生欄位」升級為
  「observation 一律先落地」。）
- **C3 三態分離**：Input / Observation / Metadata；replay hash 只吃前兩者。
- **C4 一份資料一個語意**：禁止同值兩處不同名或同名不同義（dealer/trust 事故）。
- **C5 rename = additive migration**：跨 minor，deprecated 標明移除版本，replay 期間持續寫入。
- **C6 每個 observation 標 producer**：欄位旁註哪個 core 模組算的 + replay 等級，便於追溯與凍結。

---

## 7. 建議執行順序（Evidence Phase 的正確第一步）

不是「改哪幾行」，是分階段把契約補穩：

1. **先只寫規格**（本文核可後）：產出「60 欄位三態分類表 + domain 命名對照表」進 repo，**不動 code**。
2. **修 domain 錯置的正確資料**（correctness 優先於命名）：additive 加 `trust_net_buy` / 真
   `dealer_net_buy(prop)`，舊 `dealer_net_buy` 標 deprecated。這是找回被丟棄的自營商訊號 + 修語意。
3. **sink observation 進 snapshot**：先挑 UI 最常看、最容易前後端不一致的幾個
   （`market_volume_ratio`、`obs_golden_tier`、`obs_resonance_level`），落地 + viewer 改讀。
4. **最後**才做 `volume→mf_*` 大 rename，走 §5 alias。
5. **補跨機器 replay 測試**（§4 metadata 風險），決定 canonical strip 白名單。

> 每一步都是 additive + 跨 minor + replay 綠 才進下一步。先契約、後遷移、絕不一次翻。
