# SPIKE — 全市場漲跌家數（Market Breadth）資料源調查

**日期**：2026-07-10（唯讀 spike，不改 repo code）
**對應**：`docs/ARCHITECTURE_BLUEPRINT.md` §7 Phase 1 工作線 2（判例 #41）
**目的**：驗證是否存在可落地到 `tools/fetch_market_pulse.py` 的「全市場漲跌家數」資料源，取代現行「主力買超 top-N 榜」偽母體（依構造恆 ≈1.0，判例 #41）。

---

## 結論（先講重點）

**推薦：TWSE `rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999` 回應中的 `漲跌證券數合計` 表（`tables[7]`，`股票` 欄）。**

這張表由 TWSE 官方直接計算好上漲/下跌/持平/未成交/無比價家數（含漲跌停細分），不需要自己逐檔加總；`_get_json` helper 與既有 `_fetch_taiex()` fallback #2（同一 base URL、同一 `date=` 參數格式）完全相容，可視為對現有 TAIEX 抓取加一個「順手多抓一張表」的擴充，不是新的抓取管線。實測對 2026-07-09（近期交易日）與 2025-07-09（回溯一年）皆回應 200 + `stat: OK`，schema 一致 → **歷史回溯能力良好**，可支援 WORM per-date I 態歸檔補抓過去日期。

**備援：無官方對等來源。** 若 TWSE 官方 endpoint 失效，唯一務實備援是自行從 TWSE `STOCK_DAY_ALL`（openapi，全部個股當日收盤，含漲跌欄）逐檔加總計算漲跌家數——但這只能取得「今天」，openapi 端點普遍不支援歷史日期查詢，回補過去日期需另尋逐日 CSV 下載端點，複雜度高很多。故備援只建議用於「今日抓取失敗時的當日 best-effort」，不建議承擔歷史回補職責。

---

## 1. 現有抓取模式（`tools/fetch_market_pulse.py`）

- 統一 HTTP helper `_get_json(url, timeout=12, referer=...)`：帶瀏覽器 UA + Referer + `Accept`，用 `utf-8-sig` decode（TWSE JSON 常帶 BOM）。
- 每個指標走「多源 fallback chain」：例如 `_fetch_taiex()` 依序試 Yahoo Finance → TWSE `MI_INDEX` tables → TWSE `STOCK_DAY_INDEX` → 本地 cache（`.taiex_cache.json`），任何一源失敗吃例外、印警告、往下一源降級，全部失敗才回傳 `{"error": ...}`。
- TAIFEX 部分另有 CSV/HTML 解析 fallback（openapi JSON 失敗時降級抓 CSV 表格）。
- 輸出統一寫 `data/market_pulse.json`，每個區塊帶 `source` 標記來源，頂層有 `errors: []` 收集所有降級/失敗訊息（不因單一來源失敗而整體失敗）。
- 這個模式的关键设计：**容錯即降級不即崩潰**、**每筆資料自報 source**——擴充漲跌家數應該複用同一套（`_get_json` + `date_str` 參數 + `errors` 累加），不是另立一套抓取邏輯。

## 2. 候選資料源與實測

### 候選 A（推薦）：TWSE `MI_INDEX?type=ALLBUT0999` → `漲跌證券數合計` 表

- **URL**：`https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date=YYYYMMDD&type=ALLBUT0999`
- **與既有 code 的關係**：與 `_fetch_taiex()` fallback #2 用的是**同一個 endpoint、同一個 base URL**，差別只在 `type` 參數（現用 `type=IND` 只回指數表；`type=ALLBUT0999` 回「指數表 + 大盤統計資訊 + 漲跌證券數合計 + 全部個股收盤行情」共 10 張 tables）。也就是說，只要把既有呼叫的 `type` 換掉或加一次呼叫，就能同時拿到 TAIEX 指數與漲跌家數，甚至可以用它取代現行 fallback #2，一次拿兩種資料。
- **實測**（2026-07-09，颱風假前最近交易日）：HTTP 200，`stat: OK`。回應含 10 張 `tables`，其中：
  - `tables[6]` title=`115年07月09日 大盤統計資訊`（成交金額/股數/筆數統計，非漲跌家數）
  - `tables[7]` title=`漲跌證券數合計`，`fields = ['類型', '整體市場', '股票']`，5 列：
    ```
    ['上漲(漲停)', '5,597(133)', '411(22)']
    ['下跌(跌停)', '4,719(128)', '552(2)']
    ['持平',       '814',        '74']
    ['未成交',     '16,359',     '0']
    ['無比價',     '3,094',      '41']
    ```
  - `tables[8]` title=`每日收盤行情(全部…)`，1369 列個股逐筆資料（可交叉驗證，但不必要——TWSE 已算好聚合數）。
- **欄位語意**：
  - `整體市場` 欄含蓋 TWSE 掛牌全部證券類型（股票、ETF、DR、權證、受益證券、牛熊證…），數字明顯遠大於實際股票檔數，**不適合當「全市場漲跌家數」母體**。
  - `股票` 欄才是純上市「股票」（不含 ETF/DR/權證），加總 411+552+74+0+41 = 1078，量級與 TWSE 上市股票檔數（約 1000～1100 檔）相符——**這才是憲法要的「全市場」母體**。
  - 括號內數字是該方向中的漲停/跌停家數子集（例：`411(22)` = 411 檔上漲，其中 22 檔漲停），若要精確對齊「漲跌家數」可直接取括號前數字，漲跌停細分可選擇性保留為額外欄位。
- **歷史回溯**：對 2025-07-09（回溯一年）重測，同樣 HTTP 200 / `stat: OK` / 相同 5 列 schema（`上漲(漲停)/下跌(跌停)/持平/未成交/無比價` × `整體市場/股票`），數字合理變化（548 上漲 / 354 下跌 / 103 持平）。**確認可用 `date=` 參數逐日回補歷史**，與既有 `_fetch_taiex()` 用同一參數格式（`YYYYMMDD`），可直接沿用 WORM per-date 歸檔的抓取排程。
- **失敗風險**：
  - 欄位是字串（含千分位逗號、括號子項），需要額外 parse（例：`"5,597(133)"` → 拆成 up=5597, up_limit=133），比純數字欄位多一層解析成本，但與既有 code 已經在處理的 `"+1,234.56"` 這類字串是同構問題，可複用既有 `_n()` 正規化 pattern。
  - 遇到全市場停市（如今天 2026-07-10 颱風假）該日期查詢會回傳空/無效資料，需與既有「查無資料則不覆蓋、標記 error」邏輯一致處理（本次未對颱風假日期發請求，依指示改測近期交易日）。
  - `type=ALLBUT0999` 回應體比 `type=IND` 大（含 1369 檔個股逐筆行情，約 240KB），若只需要漲跌家數這一張表，頻寬/parse 成本會比現況多；但仍在單次請求可接受範圍內，且比另開一條抓取管線便宜。

### 候選 B：TWSE `MI_INDEX?type=IND`（現行 TAIEX 主力抓取用）

- 已實測（既有 code 邏輯 + 本次驗證）：只回 6 張指數/報酬指數表，**沒有漲跌證券數合計表**。
- **排除**：不含所需欄位，必須換成 `type=ALLBUT0999`（見候選 A）。

### 候選 C：`openapi.twse.com.tw/v1/exchangeReport/MI_INDEX`

- **URL**：`https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX`
- **實測**：HTTP 200，回傳 267 筆列表，每筆為單一指數的當日收盤/漲跌（與候選 B 的 `tables[0-2]` 內容同構，只是攤平成 list of dict）。**同樣沒有漲跌證券數欄位**。
- **額外限制**：openapi.twse.com.tw 端點普遍**不支援日期查詢參數**（回傳固定是「最新交易日」），無法用來回補歷史。
- **排除**：不含所需欄位，且無歷史回溯能力。

### 候選 D：既有 repo 內已抓資料（如成交量 Top20 / 主力買超榜）

- `tools/fetch_twse.py` 已用 `openapi.twse.com.tw/v1/exchangeReport/MI_INDEX20`（成交量前 20 名）與 `STOCK_DAY_ALL`（個股當日收盤，openapi、僅當日）。
- 成交量 Top20／买超榜類資料**依構造只涵蓋人為篩選出的子集合（top-N）**，不管怎麼派生都不可能還原「全市場」漲跌家數分母——這正是判例 #41 指出的問題本身（拿榜當母體，母體恆偏態），派生不出來，**不是資料完整度問題，是母體選取的結構性問題**，此路不通。
- `STOCK_DAY_ALL`（openapi）理論上可以自己逐檔比對漲跌後加總，覆蓋率是全部個股（非榜），可作為**候選 A 失效時的當日備援**（見下）。但它只回「最新交易日」，不支援歷史查詢參數，回補歷史需另尋 CSV 逐日下載端點（TWSE 有，但未在本次 spike 範圍內測試——不節制測試會超出「每端點數次」的指示）。

## 3. 推薦方案

**主力**：擴充 `tools/fetch_market_pulse.py`，新增 `_fetch_market_breadth(date_str)`：

- 呼叫 `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date}&type=ALLBUT0999`（沿用既有 `_get_json` helper，`referer="https://www.twse.com.tw/"`）。
- 從回應 `tables` 中依 `title == "漲跌證券數合計"` 找表（比依 index 位置抓更穩，index 位置可能隨 TWSE 改版飄移）。
- 取 `股票` 欄（非 `整體市場` 欄），解析 `"411(22)"` 格式為 `{up: 411, up_limit: 22}`，`"552(2)"` 為 `{down: 552, down_limit: 2}`，`持平/未成交/無比價` 為純數字。
- 建議輸出 schema（僅供未來實作參考，本 spike 不動 code）：
  ```json
  "market_breadth": {
    "up": 411, "up_limit": 22,
    "down": 552, "down_limit": 2,
    "flat": 74, "unmatched": 0, "no_comparison": 41,
    "total": 1078,
    "source": "twse-MI_INDEX-ALLBUT0999"
  }
  ```
- 可與現行 `_fetch_taiex()` 共享同一次 `type=ALLBUT0999` 請求（該回應同時含指數表），**省一次 HTTP round-trip**，是否合併請求屬實作階段決策，非 spike 範圍。

**備援**：候選 D 的 `STOCK_DAY_ALL`（openapi，全部個股當日）逐檔比對漲跌自行加總，**僅作當日 best-effort 備援**（TWSE 官方 endpoint 全部失效時），不承擔歷史回補職責；回補歷史失敗時應誠實記錄 `errors`，不得靜默用「今日資料」冒充過去日期（呼應 C10 as-was 原則，判例 #41/#54 脈絡下不得把缺值焊成假訊號）。

## 4. 風險彙總（一句話版）

主要風險是 TWSE `漲跌證券數合計` 欄位為逗號+括號複合字串格式，需要新的 parse 邏輯（非既有 `_n()` 可直接複用，需擴充），且該表本身無穩定的官方欄位鍵名保證（此次以 `title` 比對定位，較 index 位置穩健但仍可能隨 TWSE 改版失效）。
