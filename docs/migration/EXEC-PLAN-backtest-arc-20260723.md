# 回測弧執行計畫 — fable 裁定書 + 派工卡集(2026-07-23)

> 對 `MAITREYA_CHECKLIST_20260723.md` 的憲法對齊裁定與執行架構。
> **fable 額度將盡:本文件是繼任條款——後續由 opus 4.8 擔任調度與審查,不需 fable 在場。**
> 規範正本仍是 docs/ARCHITECTURE_BLUEPRINT.md;本文件只是執行計畫,兩者衝突時憲法勝。

---

## 一、結構裁定(五條,覆蓋清單與憲法的衝突點)

**R1 策略標示的落地形式:sidecar 落地檔,不進快照(2.0 前)。**
清單 1.2 的標示資料由 pipeline 於快照建成後產生 `reports/strategy_tags/<date>.json`
(deterministic,來源=共用 `would_enter`)。viewer 讀檔渲染——不新增 render-time 引擎
import(遵守 .claude/rules/viewer-presentation.md「不要新增」條款)。
Schema 2.0 時遷入快照 obs_*。**禁止**為此做 1.9.x minor bump(單一 bump 紀律)。

**R2 交易成本參數放 core/engine_params.py 新 BACKTEST_* 區,不放 scd.yaml。**
scd.yaml 進 config_snapshot 判斷雜湊;回測成本是研究層參數,不得污染判斷 hash。
清單 2.1 的 yaml 位置**修正**為 engine_params.py(可 diff、可審計,同 C11 精神)。

**R3 Schema 2.0 = 一次性事件,現在只集不動。**
待併項:OHLC 快照欄(4.4)+ 策略標示遷入(R1)+ P3 死欄移除(temporal_state/
market_regime stub/rankings)。**OHLC 資料採集現在就可開始**(data/ohlc/ 原始檔,
不動 schema);快照整合等 2.0。ATR 修正(3.1)先用收盤代理+標籤修正。

**R4 TAIEX 基準回填來源:內部 pulse 只有 7/08 起(缺 7/10),5/08–7/07 用 TWSE
MI_INDEX 公開日資料回填。** 落 `data/taiex_history.json`(fetch 層原始資料,含來源註記)。

**R5 體制標記(2.4)讀落地欄,不重算。** 快照已有 obs_market_breadth/regime/
temperature;回測為每筆交易記進場日落地體制值即可。

## 二、清單逐項裁定

| 項 | 裁定 | 附註 |
|---|---|---|
| Part 1 策略標示 | **照做**,經 R1 修正落地形式 | 核心=共用 would_enter,回測重構為最重要步 |
| 2.1 成本模型 | 照做,經 R2 修正位置 | |
| 2.2 權益曲線/max_dd | 照做 | worst_single_trade 分欄,佳 |
| 2.3 TAIEX 基準 | 照做,經 R4 | ⭐ 優先序最高的 P0,同意 |
| 2.4 體制標記 | 照做,經 R5 | |
| 2.5 industry 靜態表 | 照做 | 已查證:最新快照 29/29 全空 |
| Part 3 四 bug | 照做 | 3.1 先驗證「移動停利標籤錯置」假說再改碼 |
| Part 4 v3+OHLC | 照做,經 R3 拆分 | 「交換鬆緊」設計健全;TP1 暫移除同意 |
| Part 5 參數掃描 | 照做,**最後** | 防過擬合紀律照清單全文執行,無修正 |
| 6.1 新鮮度狀態列 | 併入 Part1 viewer 卡 | sidebar 已有日期,補「距今+過期警示」即可 |
| 6.2 daily_briefing | **延後**(backlog) | 新功能,讓位 P0/P1 |
| 6.3 ETF adapter | **延後**(v3 之後) | 新資料工程 |
| 6.4 fii_follow_through | **延後**(v3 之後) | 判斷參數級,需獨立成案 |
| 6.5 tab 整併 | **關閉** | 已查證:現為 6 tabs,清單資訊過時 |
| 6.6 路徑清理 | **關閉** | 2026-07-23 已裁定:26/37 處在凍結快照不可改;repo 已轉私有,風險≈0 |

## 三、Wave 派工卡集(調度者:opus 4.8)

**通用紅線(每張卡都抄進 prompt)**:治理紅線照 CHECKLIST 開頭五條;顯式路徑
commit;push 前 pull --rebase;基線 `make test` 447 passed+1 skipped 起跳只增不減;
reports/ 既有檔 WORM;動 core 判斷=先讀 .claude/rules/core-engines.md。

### Wave A(平行,現在開跑)
- **A1(opus)Part 1 全套**:`would_enter` 純函數(core/strategies.py)→
  paper_trading.py:90 `_momentum_entry_ok` 重構改呼叫之(**回歸驗收:四策略回測
  交易筆數與報酬 byte-identical**)→ `strategy_tags_for_date` → pipeline 產
  `reports/strategy_tags/<date>.json`(R1)→ viewer 徽章 Ⓐ Ⓑ+健康度標頭(成本模型
  前標「未扣成本」)+共識計數+排序 → 6.1 新鮮度補強 → 一致性測試(1.4 三項全做)。
- **A2(sonnet)成本模型+權益曲線**:R2 位置;毛/淨雙報;真 max_drawdown+
  worst_single_trade 分欄;驗收 2.1/2.2 照清單。
- **A3(sonnet)TAIEX+industry**:R4 回填 data/taiex_history.json(5/08 起補齊+
  7/10 缺日)→ 每筆超額報酬/alpha 欄;TWSE 產業分類靜態表 data/industry_map.json
  +接線板塊面板。驗收 2.3/2.5 照清單。

### Wave B(A 收案後)
- **B1(opus)Part 3 四 bug**:3.1(先查證假說:獲利出場的 atr_stop 是否實為移動
  停利;修標籤或修算式,驗收=atr_stop 出場皆負)→ 3.2 entry_cost_anchor 三約束
  → 3.3 COOLDOWN_DAYS → 3.4 已實現/未實現分離+獨立標的數。重跑四策略,輸出
  修正前後對照表。2.4 體制標記(R5)順帶入此卡(同檔案區)。

### Wave C(B 收案後)
- **C1(opus)Part 4 v3**:照清單 4.1-4.3(交換鬆緊、三重止損、TP1 移除),
  參數全進 engine_params BACKTEST_*/StrategyConfig;完成後加 Ⓒ 標籤。
- **C2(sonnet)OHLC 採集**:TWSE 個股日成交資訊回填 data/ohlc/(R3:只採集,
  不動 schema)。

### Wave D(最後)
- **D1(sonnet 跑+opus 審)Part 5 參數掃描**:掃描矩陣照清單;紀律四條逐字執行
  (淨+超額排序/樣本內外切分/平坦最佳區);產出報告不自動改參數——**改參數=
  判斷參數級,需 Yonki 核准**。

### 審查協定(fable 缺席時)
每 Wave 收案由**另一個 opus 實例**做唯讀審查(不信實作回報:親跑驗收卡、抽 diff、
獨立跑測試+回測回歸)。審查通過才進下一 Wave。憲法衝突拿不準→停下問 Yonki,
不要猜。fable 最後一次額度保留給:**v3+參數掃描結果+Schema 2.0 設計的終審**。

## 四、驗證基線(2026-07-23 收盤時點)
- make test:447 passed, 1 skipped;replay:51 dates 0 failure(9 attested)
- origin/main HEAD:f9977a1;pipeline 連四日正常;canary 靜默=健康
- 明晚起觀察:分點 fetched_date 首批+回補槽運作(None 應 ~20% 遞減)

---

## 五、Wave D 收案(2026-07-28)

### D1 參數掃描:結論=不改任何參數
六參數實測狀態(旋鈕位置逐一查證,非推測):

| 參數 | 旋鈕 | 生效策略 | 結果 |
|---|---|---|---|
| `COST_CAP` | engine_params 模組常數 | 僅 v3(momentum_veto) | 1.10 起平坦;1.05→1.10 有階躍但 n=4-6 |
| `ENTRY_STOP` | 同上 | 僅 v3 | **空掃**:三值 byte-identical |
| `COST_BREAK` | 同上 | 僅 v3 | **空掃**:三值 byte-identical |
| `TP1_SELL_MULT` | StrategyConfig | 僅 v2 家族 | **空掃**:四值 byte-identical |
| `ENTRY_STREAK_MIN` | StrategyConfig | **僅 momentum 分支**(見下) | n≤9,中間值凹陷=雜訊 |
| `COOLDOWN_DAYS` | engine_params 模組常數 | 全部 | 平坦/非單調,無結論 |

三格「空掃」為資料現象非工具 bug,雙向佐證:①極端值對照(ENTRY_STOP=1.5 → 出場暴增
至 12 筆,機制確認活著);②各格 max_drawdown 僅 0.00%~−0.18%,而 S2 需 −7%、S1 需
−10% 才觸發 → 數學上不可能觸發。

**更正**:`entry_streak_min` 只在 `core/strategies.py` 的 **momentum 分支**被讀取;
chip_anchored 分支(黃金名單+成本錨)完全不查它。A/A_V2/A_V3 雖設此欄位但為**死欄位**——
在 chip_anchored 家族上調它會量到零效果,易誤判為「參數無害」。

**結論:`core/engine_params.py` 維持現況值不動。** 各格獨立標的僅 3–11 檔(比原估
13–16 更少),多數格 trade count 壓在 10 筆門檻以下——現有資料量本質上不足以校準這批
參數。建議累積 3 個月以上再重掃。

### D2 v3 樣本內/外切分(2026-07-28,語料 2026-05-08→2026-07-27)
**⚠️ 本表更正 commit `46fc6ce` 訊息中的數字。** 該訊息轉述 Wave D 掃描格,稱 v3 樣本外
淨報酬 −0.17%／超額 −0.57%;在完整語料上直接量測為 **+0.25%／超額 +1.54%**,方向相反。
以本表為準。

淨=扣成本後;超額=逐筆扣同期(進場↔出場)大盤買入持有。

| 策略 | 切分 | n | 淨勝率 | 淨報酬 | 超額 | max_dd | 同期大盤 |
|---|---|---|---|---|---|---|---|
| v3 | 樣本內 05-08~06-30 | 6 | 100% | +5.14% | +4.59% | 0.00% | +10.87% |
| v3 | 樣本外 07-01~07-27 | 4 | 100% | +0.25% | +1.54% | 0.00% | **−4.61%** |
| v2 | 樣本內 | 10 | 70% | +2.28% | +0.45% | −0.25% | +10.87% |
| v2 | 樣本外 | 10 | 70% | −0.04% | +0.47% | −0.20% | −4.61% |
| momentum | 樣本內 | 9 | 55.6% | +2.69% | +2.48% | −0.64% | +10.87% |
| momentum | 樣本外 | 9 | 44.4% | −2.41% | −2.82% | −2.40% | −4.61% |

**關鍵:樣本外大盤 −4.61%,是 regime 反轉,不是多頭的延續**——最嚴格的樣本外檢驗。
該窗口內 momentum 塌陷(−2.41%/−2.82%),v2 打平,**v3 是唯一兩切分×兩指標皆正、
且兩段 max_dd 皆 0.00% 的策略**。絕對報酬確實衰減 95%(+5.14%→+0.25%),但超額只從
+4.59% 降到 +1.54% 並保持為正 → **未出現典型過擬合塌陷**。

### 終審必須一起看的保留(不構成上線建議)
1. **n=4**(樣本外)。四筆全贏與擲硬幣連四次正面無統計區別,不可當證據。
2. 兩段皆 100% 勝率、0.00% 回撤「太乾淨」,通常代表樣本太小或篩選過嚴。
3. **v3 在多頭段輸給大盤**(+5.14% vs +10.87%),空頭段護住(+0.25% vs −4.61%)
   → 這是**防禦型側寫**,不是 alpha 機器。要不要這個側寫是判斷,不是數字能決定的。

### 驗證基線(2026-07-28)
- make test:554 passed, 1 skipped;replay:53 dates 0 failure(11 attested)
- 五支策略語料已對齊 2026-05-08→2026-07-27(v3 於 `46fc6ce` 補跑)
