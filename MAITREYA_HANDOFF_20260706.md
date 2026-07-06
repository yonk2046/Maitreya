# Maitreya 交接文件 — 2026/07/06（資料正確性大修 + UI 定稿 + 排程自動化 · 完整整合版）

> 交接對象：任何下一個 AI session（Claude Cowork / Cursor / Claude Code）
> Repo：`yonk2046/Maitreya` · Viewer：Streamlit Cloud 自動部署（`viewer/cockpit.py`）
> 本機路徑：`/Users/yoncky/SCD engine/Ai stock/`
> 作者：Yonki + Claude Cowork · 整理日：2026-07-06（涵蓋 07/02 晚 → 07/06 的三個 session）
> **這份是最新整合版**——快速上手只讀這份；系統定位/紅線/架構見 `ARCHITECTURE.md`（已更新至現況）；更早細節見本文件 + `MAITREYA_HANDOFF_20260702.md`（歷史 handoff 在 `docs/handoffs/`）。
> 開工前先跑：`git log --oneline -20` + `make verify-all-replay`。

---

## 0. 目前狀態一句話

Schema 1.8.0。UI 定稿 7 tabs（P3.2）。A2 資料修復已驗收（7/06 market_volume 44/44）。T86 滯後 bug 三重防線上線並在實戰擋下 4 次滯後資料。排程自動化完成（Mac 開機→當晚更新；關機→隔晨 cronjob/GHA 自動補建）。四個月回測完成（B 策略 86% 勝率）。**7/02、7/03 快照的外資數據仍是滯後的，待重建（§5 待辦 #2）。**

---

## 1. 資料正確性修復（本輪最重要）

### 1A. A2 成交量張冠李戴 · commit `8f68dfe` ✅ 已驗收
- **真相**：快照 `volume` 欄其實是 Fubon 主力買超張數；真市場成交量 `market_volume` 只覆蓋成交量 Top20（3/22）。「外資買超 241%」是分母拿錯。T86 本來就已轉張，數字沒錯。
- **修法**：STOCK_DAY_ALL（原本就每天抓開盤價）同一次呼叫多產出 `marketQuotes`={code:{vol張,close,真chgPct,chgAmt}} 全市場 → adapter `market_volume`/`change_pct` 優先用它，舊 raw 走原路（replay 中立）。
- **順帶補刀**：`fetch_fubon.py` 的 chgPct 也是「漲跌元」誤標（730fd4d 只修了 TWSE 側）→ 已修。國巨 +100% 事件殘根到此清完。
- **驗收**：7/06 快照 market_volume 44/44 ✓。黃金卡片「量能比」空白的根因就是它——**約 7/08 起累積滿 3 天歷史後自動全亮，不用再改 code**。
- 快照裡同名欄位 `volume_ratio` 其實是「主力買超動能比」（被污染的 volume 算的）→ 1.9.0 正名。

### 1B. T86 滯後 bug（外資數據晚一天）· commits `488a7f7` + `deaed2a` ✅ 防線上線
- **發現**：HiNetCDN 對 datacenter IP（GitHub 機器）的「當日」T86 回 **HTTP 307（無 Location）**，昨日的（已進快取）誰都拿得到；系統靜默退回抓昨日 → **7/02 快照 fii=7/01 數據、7/03 快照 fii=7/02 數據**（實測 7/03 聯電 -12,538=7/02 值，實際當天 +35,293，方向相反）。
- **防線 1**（488a7f7）：fetch 記 `t86Date` → `daily.py _fii_published()` 驗 `t86Date==tradingDate`，不符一律不建快照（寧可晚幾小時等下一輪，絕不寫錯天的外資）+ T86 重試 3×5s + workflow_dispatch 也走防撞 guard。
- **防線 2**（deaed2a）：MI_INDEX20 盤後仍回前一交易日，step8 曾拿它的日期抓 T86 → 永遠滯後被 gate 擋死。改用 `derive_trading_date` 解析日。
- **實戰**：7/06 當天防線擋下 4 次滯後資料（雲端×3+Mac早跑×1），最後由 Mac 手動跑 `deploy/daily_and_push.sh` 建出正確快照（fii 44/44、parsed for 20260706）。
- **已查證死路**：openapi.twse.com.tw **沒有**逐股三大法人資料集（swagger 143 端點翻遍）——雲端當晚抓當日 T86 無解，只有台灣 IP 行。

### 1C. 7/02 快照失蹤案（07/02 晚偵破）· commit `59e6475`
三層原因疊加：殭屍 launchd `com.scd.daily`（已拔）搶跑不 push → skip-guard 看檔案存在誤跳過（已改成查 origin/main）→ cronjob 觸發的 GHA run T86 被 307 只推半套。唯一完整快照被 stash 誤刪，靠 `git fsck --unreachable` 救回（sidecar hash 吻合）。教訓已進記憶：**叫使用者 stash drop 前先確認遠端真的有**。

---

## 2. 排程自動化（OPS 定稿）

| 觸發器 | 時間(台北) | 說明 |
|---|---|---|
| launchd `com.maitreya.daily` | 19:00 | 主力。Mac 醒著→當晚全套更新（台灣 IP 抓得到當日 T86） |
| cron-job.org → workflow_dispatch | 晚上 6 點多 + **早上 06:10（Yonki 待設第二條）** | 晚上那條會被 T86 防線擋（無害）；早上那條建「昨日」完整快照 |
| GHA cron | 20:00 + **08:35（T+1 補建,新）** | 備援；GH cron 常遲到 1-2h |

- 所有觸發器都有防撞 guard（查快照是否已發布），誰先做完其他人閃開。
- cronjob 用 fine-grained PAT（需 **Actions: Read and write**），**效期至 2026-09-04**——到期前要換。403=權限不足，204=觸發成功。
- 殭屍 `com.scd.daily` 已 unload+rm。

---

## 3. UI 大改版（P2.7 → P3.2 定稿）

**7 tabs**：`📰 市場敘事`（第一，開頁即今天全貌）→ 💼 持倉 → ★ 進場機會 → 🌱 潛力區 → 🔻 出場警示 → 🔬 個股顯微鏡 → 📈 模擬績效

| Tab | 內容 |
|---|---|
| 市場敘事 | 今日綜述(市場故事) → 市場體制 → 龍頭雷達 → 主題觀察 → 資金輪動(含族群走勢) → 全市場熱度 → 持續出現/重要轉換/可能假突破 |
| 進場機會 | 📖邏輯說明 + 黃金名單 + 黃金候補表（同引擎歸位） |
| 潛力區 | 📖 + 精選觀察表 + 今日變化(Δ排行+質變事件表) + 轉強全表(含「只看持續吸籌」過濾) |
| 出場警示 | 風險警報表 + 轉弱出貨 + 假突破 |
| 個股顯微鏡 | 多空體檢(溫度橫幅+泡泡圖+全市場體檢表) → 個股時序 |

**全 UI 統一詞彙**（顯示層,core 內部名不變）：贊助分→**主力回頭率**、信念→**黃金分**、信心→**多頭分**、風險→**警訊分**、疑似出貨（本來就是）。黃金分級=星級 ⭐進名單/⭐⭐增強/⭐⭐⭐可買進。分數降維成色點 🟢🟡⚪（警訊 🔴🟠🟢），回頭率樣本<3天顯示「樣本不足」（1/1=100% 假訊號防呆）。每個特殊用字區塊都有灰色(#969696,10px)說明行。

**去重複刪掉的**：持續吸籌獨立區（併轉強表過濾）、深度數據 tab（解散歸位）、市場敘事雙語長文（code 封存 `part="all"`）、數字條×3、市場結構事件卡、watch 卡片牆。
**修掉的**：搜尋慢（獨立搜尋框觸發整頁重算→改表格內建 🔍+轉強表計算加 st.cache）、雲端 SyntaxHighlighter TypeError（📖說明裡的 code fence 引起,cockpit 已無任何 fence——**別在 st.markdown 用 ``` code block**）。

---

## 4. 回測（P3b 實戰）

### 主 archive（真實資料,5/08–7/03,39 快照）
A v1: 4筆 75% +4.98%｜A v2: 10筆 70% +2.89%｜B v1: 8筆 75% +3.29%｜B v2: 9筆 78% +3.20%

### 歷史重建（3/02–7/03,90 天,只信 B 策略）
**B v1: 7筆 勝率86% 平均+15.13%/筆 中位+18.58% 最差-1.02%**｜B v2: 8筆 88% +13.16%。全部出場=轉弱偵測（出場器是獲利保全核心）。每月平均皆正。聯電兩段 +27.3%/+23.3%。
**報告**：`reports/backtest/BACKTEST_4M_REPORT_2026-07-04.md` + 同名 `.html`（SCD 深色風格）。
**誠實聲明**：樣本小、大多頭偏差（聯電76→172）、無交易成本、硬止損未被測試、重建主力=自營商代理。
**基建修復**：`fetch_history` 舊 TDCC import 炸掉→優雅降級；榜單過濾（權證/ETF 踢除,4碼普通股 15+15）；新工具 `tools/backfill_prices.py`（TWSE STOCK_DAY 歷史股價回填,月檔快取可續跑,`--cache-only` 沙箱離線用）。重建資料在 `data/backfill/`（沙盒,未 commit）。
**重要洞察**：重建 universe（外資買超 top15）報酬遠勝主 archive（Fubon 榜 40 檔）——**選股池品質決定報酬量級,是 1.9.0 擴 universe 的實證**。

---

## 5. 待辦（優先序,Yonki 已核）

1. **兩段式快照**（新,Yonki 想要）：Mac 關機時雲端晚上先建「部分快照」（價格+分點,雲端抓得到）標記 fii_pending → 早晨 T86 到手後 supersede 補完。動 fii_gate/兩道 guard/viewer 標示——資料防線手術,要完整 session 做。
2. **重建 7/02、7/03 快照**：兩天外資滯後一天（7/03 方向相反）。用正確歷史 T86 走 supersede 重建。
3. **1.9.0 打包**：branches fetchDate 治本（國巨陳舊根源,現靠 MEMORY_ANCHORS 止血）＋ universe 擴大（回測已證明價值）＋ fii_buy_ratio 寫進快照（V3 鎖碼>10% 自動判定,分母用 market_volume）＋ volume 欄位正名 ＋ sponsorship/failed_breakout 持久化。bump schema 1.9.0。
4. **B1 隔日沖分點標記**（V3 核心）→ 之後 B2 指標外資同步、B3 家數差、B5 融資、B6 PA 訊號（見 `Maitreya_系統問題清單_20260703.md` 查證版）。
5. 驗收檢查：~7/08 量能比全亮；明晨 cronjob/GHA 自動補建是否運作；**cronjob token 2026-09-04 到期**。
6. 個股顯微鏡的泡泡圖仍用 P3a 代理值（評分正式化後換真欄位,圖骨架不變）。

## 6. 給下一個 AI（增補,其餘同 0702 handoff §8）

- **絕不把非當日 T86 寫進快照**——t86Date gate 是底線,別繞過。
- 雲端(GH runner)抓「當日」rwd 資源會被 307,抓「昨日」永遠成功——設計任何雲端流程前先想這條。
- viewer 說明行用 `_EXPLAIN_DIV`(灰10px)、等級用 `_lvl/_lvl_risk/_lvl_sponsor`、星級用 `_dt_stars`;st.markdown 內禁 code fence。
- 沙箱 git 查詢一律 `git --no-optional-locks`,否則留下刪不掉的 index.lock。
- 交易記錄:2026-07-02 賣出長榮航 2618 100股 @43.8(成本42.66),持倉現為空。

**本輪 commits**：`20e8b2e`(docs整併) `65b0c25`(賣長榮航) `59e6475`(救回7/02+guard治本) `8f68dfe`(A2) `488a7f7`(T86防線) `c0b764a`→`b42363b`(P2.7→P3.2 UI) `f4d82f1`(回測+backfill工具) `deaed2a`(T86解析日) `5d2f59f`(GHA早班)
