# Maitreya 交接文件 — 2026/06/12 Session 成果與後續任務

> 交接對象：Claude Code（本機開發環境）
> 來源：claude.ai 工作 session（Yonki 在公司透過 GitHub 網頁版部署）
> Repo：`yonk2046/Maitreya` · Viewer 部署於 Streamlit Cloud

---

## 0. 系統脈絡（必讀）

Maitreya = SCD 五階段漏斗的正式實作：決定論狀態引擎（core/）+ AI 解讀層 + Streamlit viewer。

**不可違反的架構紅線（AI_GOVERNANCE）：**
1. UI（viewer/）不准做業務邏輯——所有偵測/計分/分級在 core 計算，viewer 純渲染
2. AI 層不得改動 composite_score / tier / gates——只能並列展示（display-only, parallel layer）
3. Snapshot 不可變（sha256 校驗）；想加新指標 → 先進 schema → 再進 core → 最後才進 viewer
4. Gate-then-Score：閘門制是 SCD 的靈魂，任何「加分排名」功能只能放在雷達/觀察層，不得污染黃金名單

SCD 核心哲學：籌碼 > 心理 > 消息 > 預測；連買 <3 日不進場；現價 ≤ 主力成本 ×1.05；空手是獲利的一部分。

---

## 1. 本次 Session 已完成並部署的修改

### 1.1 `viewer/cockpit.py` — 轉強訊號 + 持續吸籌面板改造
- 新增共用 helpers（Panel 3 區塊前）：`_presence_dates()`、`_momentum_glyph()`、`_freshness_label()`、`_style_signal_df()`
- **轉強訊號**：新增「資料」欄（`NEW` 藍 / 當日日期 / `⚠ 日期` 灰 = 過期）、「動能」欄（▲▲ 加速 / ▲ 增溫 / ▼ 減速，渲染 core 既有的 `velocity_3d` + `acceleration`）；排序改為 動能方向 → 新鮮度 → 累計買超；速度/漲跌欄正綠負紅（pandas Styler.map）
- **持續吸籌**：同樣加「資料」「動能」欄；**刪除贊助分欄**（全名單同值 1.00 無鑑別度）；排序統一
- 動機：原本連買 12 日但速度 -12,140 的股票（2891）排轉強第一名——排序與語義矛盾

### 1.2 `core/market_context.py` — 新增 `weakening_profile()` 轉弱出貨偵測器
檔案末尾新增（與 `failed_breakout_memory` 同模式，決定論、不碰 score/tier/gates）：

**五旗標：**
| 旗標 | 條件 | 常數 |
|------|------|------|
| W1 動能衰竭 | streak ≥3 且 velocity_3d <0 且 F(n)<F(n-1) | — |
| W2 雙引擎分歧 | 主力買超 >0 但 fii_net_buy <0 且 \|fii\| ≥ 30% mfb | `_W2_FII_RATIO=0.30` |
| W3 主力消失 | 窗口內曾連買 ≥3 日、最新快照缺席 | — |
| W4 散戶接盤 | broker_count_diff >0 或 price_down_margin_up_days_10d ≥3 | — |
| W5 分點賣壓 | totalSellVol > totalBuyVol，或前三買點 sellVol/buyVol ≥60%（邊買邊倒） | `_W5_SELL_RATIO=1.0`、`_W5_CHURN_RATIO=0.60` |

**新鮮度閘門**：缺席 >3 個快照 → 回傳 none（陳舊訊號不上榜）。
**嚴重度**：紅 = (W3+至少1佐證) 或 ≥3旗標；橙 = 2旗標 或 W3單獨；黃 = 1旗標。
（註：W3 單獨只算橙，因為掉出買超榜一天可能只是輪動。）

### 1.3 `viewer/cockpit.py` — 新增「🔻 轉弱出貨」面板（第 12 個 tab）
- 位置：轉強訊號旁（攻守對照）；卡片式，左框按嚴重度上色，旗標 tag 懸停顯示明細
- 接線：import `weakening_profile`、tabs 註冊 `tab_weak`、dispatch `_render_weakening(snaps_to_date)`
- 分點資料來源：`_load_branches_for_ticker()`（data/branches/<ticker>.json，含 sellBranches/totalSellVol/avgSellCost）

### 1.4 `viewer/cockpit.py` — 黃金名單交叉對質（display-only）
- `_render_golden` 內：`weak_map` 對黃金宇宙（all_entries + near_miss）跑 `weakening_profile`
- 卡片：紅/橙警示 pill（`🔴 出貨確認警示 W3·W5`，title=明細）；紅燈卡片 border-color 變紅
- 分組：紅燈股強制移入「動能衰退」組並排該組最前；統計列新增「🔴 出貨警示」計數
- **tier/conviction/gates 完全未動**——與既有 Distribution Intelligence Layer 同一架構契約

### 1.5 真實資料回測結果（22 個快照，05/08–06/10）
- 全市場：紅 14 / 橙 17 / 黃 13（共 44 檔轉弱）
- 黃金名單 11 檔 PRIME 交叉對質：**1 紅（2887 台新新光金 W3+W5）+ 4 橙（2890/2867/2884/3033 全 W3）**
- ⚠️ 重要發現：**金融股集體 W3**（6/10 同時從買超榜消失）→ 疑似板塊資金輪出，待板塊輪動功能驗證
- 偵測器正確命中歷史案例：3481 群創（Session 03 出貨確認）、1303 南亞（5/28 窗口關閉）

### 1.6 測試狀態
- `python -m pytest tests/`：72 passed / 12 failed——**12 個失敗在未修改的原始碼上同樣失敗**（FileNotFoundError，環境缺檔問題，與本次修改無關，已用 git stash 對照驗證）
- 注意：import viewer 模組會觸發寫入 `data/checklist_history.json`——**不要 commit 這個檔案的測試污染**

---

## 2. 待辦任務（優先序已定）

### P0 — TDCC 集保大戶資料 adapter ⭐ 最高優先
- **問題**：黃金名單卡片大量「籌碼集中度 TDCC 資料待補 0/8」「大戶持股變化 資料待補」——schema 欄位存在（large_holder 系列、shareholder_count_delta），pipeline 沒餵資料
- **資料源**：TDCC 集保戶股權分散表，公開 OpenData（opendata.tdcc.com.tw），每週五更新，免費
- **動作**：寫 `data/adapters/tdcc_adapter.py`，對應週資料 → 既有 schema 欄位；400張/1000張大戶比例 + 總股東人數
- **效益**：補掉系統最大資料缺口；策略層的「集保大戶增 + 股東人數背離」（SCD Stage 3 核心）原生可算
- 競品參照：tetsu811.com 的策略三（籌碼集中 16 分制）已落地此資料，是其唯一實質優勢

### P1 — Schema v1.5：信心等級 + 衍生狀態欄位
新欄位（core 計算，進 canonical schema）：
```yaml
data_completeness: float  # 0–1，有資料的 gate/factor 占比
confidence_tier: enum     # FULL(≥0.8) / PARTIAL(0.5–0.8) / SKELETON(<0.5)
momentum_direction: enum  # accelerating/steady/decelerating/reversing
signal_age_days: int
delta_vs_yesterday: str   # +3 / -2 / NEW / —（依賴歷史 snapshot diff）
```
**關鍵規則（進 SCORING_RUBRIC config，不是 viewer）**：SKELETON 級不得進 PRIME，最高 WATCH/STRONG。
動機：截圖實證 2887 僅憑連買一項資料就掛 PRIME + 籌碼動能 10/10——缺資料被當滿分算，危險。
（viewer 端的動能/新鮮度目前是 presentation-level 推導，P1 完成後改讀 schema 正式欄位。）

### P2 — 黃金名單完整重設計（依賴 P1）
- 頂部統計改「行動分組」：🟢 可執行 / 🟡 等回檔 / 🔵 資料待補 / 🔻 動能轉弱 / ⊘ 差一步
- 卡片瘦身：收合態只留 代號名稱 + 行動徽章 + 信心徽章 + 連買進度條 + 成本距離條；checklist 全部摺進展開區
- 排序 = 行動優先序（可執行最前，SKELETON 沉底），不是分數高低

### P3 — 雷達觀察頁「熱度分」（additive 排名層）
- 閘門制只說過/不過，缺「相對熱度」視角。在雷達頁（**不是黃金名單**）加 additive 熱度分
- 被閘門擋掉的股票照常顯示熱度 + 被擋原因 tag（如「❌ 超出成本上限 +18%」）
- 用途：消除「別人榜上有、我們沒有」的盲區焦慮——系統會明確說出為什麼沒選

### P4 — 板塊輪動強化
- schema 已有 `industry` 欄位；把轉強/轉弱偵測按產業聚合（淨流入/流出、W3 集中度）
- 直接驗證 1.5 節的金融股集體 W3 發現；與 P3 可一起設計

### P0.5 — 狀態機改革 ⭐ 與 P0 並列最高優先（2026/06/12 晚間新增）
**問題診斷（code 實證）**：`core/state_machine.py` 的 `_assign_state` 是無記憶每日分類器，導致 timeline 鋸齒（吸籌→疑似出貨→成熟確認 讀不通）。三個缺陷：
1. DISTRIBUTING 觸發條件（L333–341）只看 velocity_3d<0 / accel<-500——主力仍淨買入、僅買量縮小就誤標「疑似出貨」，**無任何賣方證據**
2. 每日從零重算、無遲滯（hysteresis），敏感閾值在邊界彈跳
3. 警示對升級無否決權——昨天疑似出貨、今天門檻過了直接跳成熟確認，違反 SCD「單一反轉日關窗」紀律

**五項修法**：
1. velocity 轉負但 mfb>0 → 新狀態 `S_DECELERATING 動能減速`（黃色中性警告）；`S_DISTRIBUTING 疑似出貨` 改為需要真實賣方證據：mfb<0 或 `weakening_profile` W3/W5 命中（與轉弱偵測器合流，單一事實來源）
2. Debounce：狀態轉換需連續 2 快照證據才提交；單日觸發記為事件。FAILED/EXITED 硬證據維持單日生效
3. 否決權：同日確認條件與出貨證據並存 → 出貨贏；進入疑似出貨後 K 日內禁升 CONFIRMED，除非 streak 從零重建 ≥3（編碼窗口紀律）
4. `state_flips_30d` 進 schema；≥2 翻轉 → 「⚡ 結構不穩」徽章；tier 封頂規則進 SCORING_RUBRIC config（**不是**扣分 magic number）
5. UI 雙軌 timeline：上軌狀態色帶（連續）、下軌事件標記（W旗標/外資轉向/HA轉色）

### P0.6 — 雙錨主力成本（外部 case study 觸發：4938 和碩）
- 短窗成本（近5日）系統性高估於連續上漲段，製造假安全感
- 改為雙錨：`cost_recent_5d`（最新批次進場位）+ `cost_episode_weighted`（episode 全程加權 = 真實賣壓來源）
- 兩者背離 >5% → 「⚠ 成本背離」徽章（後進者追高訊號）；進場閘門採保守錨（兩者取低）
- 進 schema → core → viewer，治理流程照常

### P0.7 — 外資同向改為 PRIME 硬閘門
- SCD 雙引擎框架 V3 原文要求「外資與主力同向」為必要條件；現行實作 2/3 法人軟通過是**偏離章程**
- 修正：外資反向（fii_net_buy<0 連續 ≥2 日）→ tier 封頂 STRONG，不得 PRIME；規則進 config
- 註：此為回歸 SCD 主軸，非外部意見採納

### P5 — weakening 寫進 daily pipeline snapshot
- 把 `weakening_profile` 輸出加入每日 snapshot（schema 加 `weakening` 欄位）
- 完成後黃金名單不需在 viewer 即時計算（目前每次 render 對 ~35 檔跑偵測，有 cache 壓力）

---

## 3. 已知注意事項
- `data/branches/*.json` 無日期欄位（最新批次快照）——W5 的時效性依賴上傳頻率，未來可加 `asof` 欄位
- 報表中 `reports/2026-05-22.json` 是空 stocks 的範例檔，載入時已被過濾
- Streamlit Cloud 自動部署：push 後 1–2 分鐘生效
- 競品比對結論（供策略參考）：對方為加分制（compensatory），Maitreya 為閘門制（non-compensatory）——名單不重疊是設計結果非缺陷；Maitreya 優勢在分點粒度/成本錨點/時序生命週期/可審計性，劣勢僅在 TDCC 資料覆蓋（P0 解決）
