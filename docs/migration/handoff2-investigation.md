# Handoff #2 查證報告：2026-07-02 / 07-03 快照「滯後」

> 作者：Claude subagent(Opus) · 日期：2026-07-11 · 狀態：**唯讀查證，待 fable 裁定**
> 本輪零快照/index/資料變更。可行性驗證用 TWSE T86 API 打了 3 次(7/01–7/03)。

## TL;DR

- **「滯後」的真實定義（一句話）**：只有 **T86 三大法人欄位（外資/投信/自營）滯後一個交易日**——7/02 快照的法人數據其實是 7/01 的、7/03 快照的其實是 7/02 的；富邦榜單、股價、tradingDate 全部是**當日正確**的。
- **假說裁決**：假說 A（整份榜單抓到前一天）**否定**；假說 B（T86 是舊的）**證實**，且對 2303、2618 兩檔、兩天都精準對上前一交易日。
- **逐欄可修性**：唯一壞掉的欄位（T86）**正好是可回溯補抓的**——TWSE T86 API 現在就能拿到 7/02、7/03 的正確值（本報告已實測）。富邦榜單沒壞，不需修。
- **建議（一句話）**：**可修，且值得修**——與 7/10 殭屍事故（股價全滯後、不可修）不同，本案只有 T86 一組欄位壞、且 100% 可從 TWSE 按日補回；修法是「按日重抓 TWSE T86 → supersede t86 區塊 → 重新 derive 下游分數」，而非上一隻 agent 用過的「從 WORM re-ingest」（WORM 裡存的就是滯後值，重算只複製滯後）。

---

## 1. 「滯後」原始定義的出處

`MAITREYA_HANDOFF_20260706.md` §1B（commit `488a7f7`+`deaed2a`）：

> HiNetCDN 對 datacenter IP（GitHub 機器）的「當日」T86 回 HTTP 307（無 Location），昨日的（已進快取）誰都拿得到；系統靜默退回抓昨日 → **7/02 快照 fii=7/01 數據、7/03 快照 fii=7/02 數據**（實測 7/03 聯電 -12,538=7/02 值，實際當天 +35,293，方向相反）。

- 發現者：7/06 session（同時上線三重防線，實戰擋下 4 次）。
- 症狀：**T86（外資/投信/自營）晚一天**；症狀範圍僅限法人欄位，非整份快照。
- 注意：這與 §7A 的「branches 陳舊 bug」是**不同**的兩個滯後問題（那個是 `branches/<ticker>.json` 無 fetchDate、沿用舊分點值），本報告只處理 handoff §5 待辦 #2 的 T86 滯後。

## 2. 症狀驗證（file:line / 實際值）

### 2.1 榜單/日期是新鮮的（假說 A 否定）

`reports/2026-07-02.json`、`2026-07-03.json` 的 provenance：

| 欄位 | 7/02 快照 | 7/03 快照 |
|---|---|---|
| `provenance/sources/legacy_today_json/report_date` | 2026-07-02 | 2026-07-03 |
| `provenance/sources/legacy_today_json/fetched_at` | 2026-07-02T10:21Z | 2026-07-03T14:28Z |

WORM `reports/_raw_archive/<d>/legacy_today_json/today.json` 內部 `tradingDate`/`fetchedAt` 也都是當日（7/02→7/02、7/03→7/03）。

**殭屍鑑定（比照 7/10 事故法：陳舊=ticker 100% 重疊+股價全同前日）**：

| 指標 | 7/01→7/02 | 7/02→7/03 | 判讀 |
|---|---|---|---|
| buyList/mainForceBuy 名單重疊率 | 0.368 | 0.065 | 遠非 100%，**新鮮** |
| openPrices 與前日相同比例 | 6.3% | 5.9% | 正常換手，**非殭屍** |
| 2303 開盤價 | 169 / 170 / 164（逐日不同） | | **新鮮** |

→ 榜單、股價、日期皆為當日正確。假說 A 不成立。

### 2.2 T86 法人欄位滯後一天（假說 B 證實）

比對「WORM today.json 內 `t86.foreign`（張）」「快照 `fii_net_buy`」與「TWSE T86 API 實際 外陸資買賣超（不含外資自營商）/1000」：

**聯電 2303 外資淨買賣超（張）**

| 交易日 | TWSE 實際 | 快照當日存的值 | 判讀 |
|---|---|---|---|
| 7/01 | +65,874 | 35,206（7/01 快照） | — |
| 7/02 | **−12,538** | **65,874**（7/02 快照）= TWSE 7/01 | **滯後 −1 日** |
| 7/03 | **+35,293** | **−12,538**（7/03 快照）= TWSE 7/02 | **滯後 −1 日**（方向相反：實際買超、快照顯示賣超） |

**長榮航 2618 外資淨買賣超（張）**

| 交易日 | TWSE 實際 | 快照當日存的值 | 判讀 |
|---|---|---|---|
| 7/02 | **−7,358** | **−23,657**（7/02 快照）= TWSE 7/01 | **滯後 −1 日** |
| 7/03 | **−4,906** | **−7,358**（7/03 快照）= TWSE 7/02 | **滯後 −1 日** |

兩檔、兩天，全部精準對上「前一交易日」的 TWSE 值。假說 B 定案。
（快照 `fii_net_buy` 與 WORM `t86.foreign` 完全相等，證明滯後源頭在抓取端 today.json 的 t86 區塊，非後續 pipeline。）

### 2.3 附帶發現（非滯後、但同屬 T86 欄位的獨立 bug）

快照 `dealer_net_buy` 存進了**投信**的值、`investment_trust_net_buy` 為 `None`：
- 7/03 快照 2303：`fii_net_buy=-12538`(=WORM foreign)、`dealer_net_buy=-17511`(=WORM **trust**)、`investment_trust_net_buy=None`。

這是欄位對映錯置，與滯後無關；若日後重抓 T86 重建，建議一併修正對映（TWSE 有明確的 投信買賣超 / 自營商買賣超 兩欄）。

## 3. 逐欄可行性表

| 欄位群 | 來源 | 滯後? | 可回溯補抓? | 結論 |
|---|---|---|---|---|
| T86 外資 `fii_net_buy` | today.json `t86.foreign`（源自 TWSE T86） | **是** | **可**（TWSE T86 API 按 `date=YYYYMMDD` 補，已實測 7/02、7/03 stat=OK） | **可修** |
| T86 投信 `investment_trust_net_buy` | TWSE T86 | 是（且對映錯置） | 可 | **可修** |
| T86 自營 `dealer_net_buy` | TWSE T86 | 是（且對映錯置） | 可 | **可修** |
| `fii_sync_count` 及下游 fii 衍生分/gate | derive（權重 fii=0.5） | 隨 T86 連帶錯 | 隨 T86 重抓後重新 derive | **可修（需重算）** |
| 富邦買賣超/主力榜單 `buyList`/`mainForceBuy` | 富邦（僅供當日） | **否**（新鮮） | 不適用 | **無需修** |
| `openPrices` 股價 | 富邦 | 否（新鮮） | 不適用 | 無需修 |
| `branchData` 分點 | 富邦 | 否（本案範圍內新鮮） | — | 無需修 |

## 4. 建議與價值評估

**分級結論：可修（affected 欄位全可修）。**

本案是「部分欄位壞」，但關鍵在於——**壞掉的那組欄位（T86）正好是唯一可回溯補抓的那組**，而不可回溯的富邦榜單根本沒壞。因此不存在 handoff 提示的「只修 T86 但榜單仍滯後、修了沒意義」的困境：榜單本來就是對的，補上正確 T86 後，7/02、7/03 快照即可恢復完整正確。

- **與 7/10 殭屍事故的差異**：那次是股價全體滯後（富邦源、不可回溯）→ 誠實不可修。本案是 T86 滯後（TWSE 源、可按日補）→ 可修。兩者不可混為一談。
- **與上一隻 agent 失敗做法的差異**：上一隻從 WORM re-ingest，產出與原版幾乎相同——因為 **WORM 的 today.json 裡存的 t86 本身就是滯後值**，重算只複製滯後。正確修法必須**繞過 WORM、直接按日重抓 TWSE T86**，supersede t86 區塊後重新 derive 下游 fii 分數/gate。
- **修的價值**：高。T86 外資是 fii 權重 0.5 的核心輸入，7/03 聯電甚至方向相反（實際買超卻記成賣超），會直接汙染回測/選股訊號。修復成本低（TWSE API 免費、按日可得），效益明確。

**若要動手（下一輪、待裁定後）建議路徑**：
1. 對 7/02、7/03 重抓 TWSE T86（`https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL&response=json`）。
2. supersede 快照 t86 三欄（並修正 trust/dealer 對映），保留 provenance 標記為 TWSE-backfill。
3. 重新 derive fii 衍生欄位/gate/分數，走 replay 驗證（schema 版本相容性需確認）。
4. 富邦榜單、股價、branchData **不動**。

## 附錄：TWSE T86 實測原始值（外陸資買賣超股數，股）

- 7/01 2303 = 65,873,616；2618 = −23,657,152
- 7/02 2303 = −12,537,989；2618 = −7,358,156
- 7/03 2303 = 35,293,240；2618 = −4,905,554

(API 均回 `stat: OK`、`date` 與請求日一致，證明歷史 T86 可按日補抓。)

---

## 重建執行紀錄（2026-07-11，fable 裁定後執行）

> 執行者：Claude subagent(Opus) · 依 Handoff #2 fable 裁定四約束。

### 修法（實際採用）

按日補抓 TWSE T86（7/02、7/03，`selectType=ALL`，皆 `stat=OK`；7/03 一度遭 CDN 限流回錯誤，retry 後取得 14,351 筆）→ **以 WORM 的 today.json 為底、僅替換 `t86` 區塊 + 補上 `t86Date`**（用與 `tools/fetch_twse_t86.py` 相同的欄位索引/張數換算構造修正版 raw）→ 以 `paths_override` 指向不可變 archive 的**修正版 today.json + 該日封存 branches**，走**標準 adapter/ingest/archive(verify_only)/index**（即 `verify_all_replay.py` 的 replay-from-archive 機制，改為 WRITE 模式）→ supersede 鏈落地。**未對快照做任何手工欄位手術**，一切經 adapter/ingest。

`dealer_net_buy` 仍裝投信值、`investment_trust_net_buy` 仍為 None（NOTES #1 對映錯置，統一 1.9.0 修）——標準 adapter 自然維持同映射，未順手改（遵約束 #2，epoch 內語意一致）。

### WORM 原始證據保留（約束 #3，additive）

- `reports/_raw_archive/2026-07-0{2,3}/legacy_today_json/today.stale-original.json` — 原始滯後 today.json 複本（C7 歷史證據，不覆蓋）。
- `reports/_raw_archive/2026-07-0{2,3}/t86_twse_backfill/T86_2026070{2,3}.json` — 補抓的 TWSE T86 原始回應。
- archive 的 `today.json` 已被修正版覆寫（已知 RC-7 缺陷；原始值由上述 stale-original 複本保全）。

### 下游 cascade（strict 連續性 + supersede 鏈落地的必然結果）

7/02、7/03 被 supersede 後，其 hash 變動使 20 日 lookback 內的下游快照 embedded lookback pin 失配（`test_lookback_hash_matches_current_strict` 轉紅）。依本 repo 既有慣例（20 條 supersede 鏈全來自 backfill/epoch re-ingest；strict 測試訊息本身指明 cascade re-ingest 為 sanctioned 解法），按時序 cascade re-ingest **7/06→7/07→7/08→7/09**（**不改各日 raw**，只以修正後 priors 重新 derive）。內容變動經逐日 diff 確認**有界且合理**：僅 `fii_consecutive_buy_days`（外資連買天數）與少量 `weakening` 欄位隨修正後 FII 變動；並附帶 1.8.0→1.8.1 epoch 遷移（`schema_version`、`fii_pending` 旗標）。7/06+ 自身 T86 未受滯後 bug 影響（7/06 起三重防線已上線），故 raw 不動。

### 驗收四項（逐項）

| 項 | 結果 |
|---|---|
| ① rebuilt 7/02、7/03 full-replay | **PASS**（`verify_all_replay.py` replay-from-archive 對拍 index.current_hash 相等；兩日皆 ✅） |
| ② `make verify-all-replay` 0 failure | **0 failure**。計數變化：full-replay-clean **1→6**（7/02,03,06,07,08,09 轉 1.8.1），legacy-epoch-clean **41→36**，共 42 日（如 fable 預期「重建日轉 1.8.1」） |
| ③ 2303/2618 fii 修正 | 見下表，全部對上 TWSE 當日值 |
| ④ index supersede 鏈完整 | 六日鏈 invariant 全 valid（原版 hash 留 history[0]、`superseded_by` 指新版；current==history[-1]）。7/02–08 各 2 版，7/09 3 版（先隨 7/02/03 補完、再隨 7/06–08 re-pin） |

**③ 抽驗前後值（`fii_net_buy`，張）：**

| 快照 | 檔 | 重建前（滯後） | 重建後（＝TWSE 當日） | TWSE 當日實際 |
|---|---|---|---|---|
| 7/02 | 2303 聯電 | 65,874（＝7/01 值） | **−12,538** | −12,537,989 股 → −12,538 |
| 7/02 | 2618 長榮航 | （不在 mainForceBuy 宇集，兩版皆無） | — | −7,358,156 股 |
| 7/03 | 2303 聯電 | −12,538（＝7/02 值，方向相反） | **+35,293** | 35,293,240 股 → +35,293 |
| 7/03 | 2618 長榮航 | −7,358（＝7/02 值） | **−4,906** | −4,905,554 股 → −4,906 |

**④ supersede 鏈 hash（原版 → 現行 tip）：**

- 7/02 `525bc4e4…` → `e84f435b…`
- 7/03 `a47caf90…` → `d568beca…`
- 7/06 `50028f94…` → `33d95a82…`
- 7/07 `16ad82fd…` → `c27846d0…`
- 7/08 `569b80f3…` → `f5a688f0…`
- 7/09 `66ebdbc3…` → `9ce904c3…`（中繼 `bac7d049…`）

### 測試

`make test` = **339 passed, 1 skipped**（與基線一致）；`make verify-index` 16 passed（含先前轉紅的 strict 連續性測試已恢復綠）。

### 殘留 known issue（誠實聲明）

- **7/06–7/08 隨 cascade 由 1.8.0 遷至 1.8.1**：這是「supersede 鏈落地 + strict 連續性 + make test 全綠」三者的必然結果（下游 pin 必須 re-pin，而 HEAD 只能產 1.8.1），非額外主動遷移；各日 raw 未動、dealer/trust 映射未動。若視為超出「僅重建 7/02-03」範圍，可回退這三日（但 strict 測試會再轉紅）。
- **dealer/trust 對映錯置**未修（NOTES #1，留 1.9.0），epoch 內一致。
- 更早 (<7/02) 的 1.8.0/更舊 epoch 快照其視窗內若曾引用滯後 FII，其衍生值凍結於各自 epoch bytes，本輪不動（epoch-freeze）。
