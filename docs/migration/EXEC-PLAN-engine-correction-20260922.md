# 執行計畫:引擎修正弧(2026-09-22 起)

> 依據:`AUDIT-golden-list-20260922.md`(G1–G9、影子比對、資料缺漏)、`PLAN-yearly-backtest-20260922.md`(B1–B3)。
> Yonki 2026-09-22 核准順序:**修正 → 重新凍結 → 多年期訊號研究**。撰寫:Claude(Opus 5)。
> 紅線:reports/ 只由 pipeline 產生;判斷語意改變走修正案;不在 18:00–19:30 推 main;每一步先 commit 再長驗證。

---

## 0. 兩條憲法限制決定了做法

1. **單一 bump 紀律**(`.claude/rules/schema-registry.md`、BLUEPRINT §6–§7):1.9.0 之後下一次 bump 就是 **2.0**,且 bump 會讓 7/13 起所有 1.9.0 快照的 full-replay 保證歸零(version-pinned replay 未實作)。
   → **新增欄位(S2 主力淨額)與新增追蹤紀錄(S4)需要 bump → 屬 2.0**。改既有欄位語意原則禁止(語意變=新欄+舊欄棄用)。
2. **replay 的新參數陷阱**:`tools/verify_all_replay.py::full_replay_hash` 會用 `engine_params.as_config_dict()` **重新產生 config_snapshot**(且 config_snapshot/config_hash 不在 replay 排除清單)。
   → 在 `core/engine_params.py` 新增任何非 `BACKTEST_*` 參數,都會讓全部 1.9.0 快照 replay 失敗 → pipeline 拒絕發布(7/16–17 同型)。**禁止用 engine_params 當開關。**
   → 改走既有的 **Feature Flag 規約**(`docs/FEATURE_FLAGS.md` F1–F7):`config/scd.example.yaml` 的 `feature_flags.engine_correction_v1`(預設 false)。
     replay 使用**快照自己記錄的 yaml**(`config_snapshot.yaml`)→ 舊快照沒有此旗標 = 舊邏輯,hash 不變;新快照記錄旗標值 = 參與 config_hash(C11 可見)。
     引擎保持純函數:旗標由呼叫端(ingest / obs_landing / 回測)讀取後以參數傳入,預設 False。**10/5 生效 = 在 10/2(五)收盤後把旗標改為 true 並 push**,10/5 起的新快照即採新邏輯。

## 1. Phase A — 不需 bump(立即開工)

| # | 內容 | 解 | 驗收 |
|---|---|---|---|
| A0 | 回歸基準:凍結現行輸出(每日黃金名單、轉弱、5 策略回測交易)為 fixture;影子比對腳本移入 `tools/research/`(唯讀工具,不進 pipeline) | 防無聲改數字 | fixture 可重現;`make test-fast` 綠 |
| A1 | 快照轉弱改用「前序 + 今天」計算(ingest 組完當日全部股票後再算) | G1 | 生效日前 replay 全綠;生效日後 W3 不再出現在「今天回榜」的股票 |
| A2 | 缺席不透明:連買/速度/狀態機改用含缺日的窗口序列(缺日 = 中斷) | G3、G4 | 黃金名單中「當天不在榜」= 0;影子比對數字重現 |
| A3 | 狀態機廣度閘改讀 `obs_market_breadth`(全市場母體) | G9 | 判斷改變;**Yonki 9/22 已核准** |
| A4 | `open` 改用 TWSE MI_INDEX 按日期的真開盤(原始檔進 archive;舊 archive 無此檔 → 沿用舊來源,replay 不變) | B1 | 生效日後 `open` 與 TWSE 當日開盤 100% 相符 |
| A5 | 資料修補:①分點約 45% 非當天 → 查抓取流程並修;②`margin_*`、`broker_count_diff` 從未寫入 → 接線(MI_MARGN 已在抓) | 缺漏 #1、#4 | 連續 5 個交易日:當天分點覆蓋 ≥ 95%、margin 非空 ≥ 95% |
| A6 | 回測(= T1):撮合用真開盤;黃金用 pipeline 同一 20 天窗口(成本變線性);掉榜持倉以價格 MTM、價格停損照常檢查 | B1–B3、T1 | 全語料回測 < 2 分鐘;黃金基準逐筆可解釋;掉榜持倉 0 凍結 |
| A7 | 畫面黃金名單改讀快照 `obs_golden_*`(BLUEPRINT Phase 3 的一部分) | G5 | 畫面 == 快照(逐日抽驗) |
| A8 | 生效日上線後宣告**新凍結**:記新 hash、前推重新計時;更新 EXEC-PLAN-backtest-arc §六、handoff、ARCHITECTURE | — | `tests/test_strategy_freeze.py` 更新並綠 |

生效日:**2026-10-05(一)**(Yonki 9/22 核准)。
- **旗標生效(判斷語意改變)**:A1/A2/A3,連同 A5②(融資,會改變資料完整度分級)於 10/2(五)收盤後打開旗標,10/5 起新快照採用。
- **資料修正、立即上線(不掛旗標)**:A4(開盤/成交量/漲跌幅改按日期)、A5①(分點涵蓋整個快照宇宙)——欄位語意不變、只是改成正確的值;每晚延後一天就多一天錯誤資料。已於 9/22 推上 main。

**進度(2026-09-22 晚)**:A0 ✅;A1–A3 ✅ 實作(旗標關閉,73 天黃金名單與修改前逐日相同,replay 0 失敗);
獨立 opus 審查通過並修正兩點:①缺席佔位不得觸發「連買崩塌→FAILED」當日硬狀態(否則在榜買超卻判失敗 27→220 股票日);
②`reports/strategy_tags` 改讀該快照記錄的旗標。已知接受:外資連買缺席日視為中斷(保守);8/25、8/31、9/4 的 market_pulse 廣度抓取失敗,旗標開啟時該類日子不放行 CONFIRMED。
A4 ✅(9/22 實測 1137 檔開盤與獨立快取 100% 一致;當晚正式快照 21/21 檔開盤錯誤);A5① ✅(dry-run 快照 21/21 檔取得當天分點,原 14/21)。
回測(paper_trading)的 would_enter 仍用預設 correction=False → 由 A6 一併處理(依各快照記錄的旗標)。

## 2. Phase B — Schema 2.0(需 Yonki 決定時機)

| # | 內容 | 解 |
|---|---|---|
| B-1 | 新 I 欄 `main_force_net`(買方前 15 大淨買 − 賣方前 15 大淨賣),賣方證據改讀它 | G2 |
| B-2 | 新增「追蹤紀錄」(近 20 天曾上榜/黃金/持倉但今天不在榜的股票):每天抓價格、分點、T86 | G6、G7、S4 |
| B-3 | 2.0 清場:deprecated 欄移除(`dealer_net_buy` 正名等) | — |

- 代價:bump 當天 7/13 起的 1.9.0 快照降級為「只防竄改」。
- 依既有安排,**Schema 2.0 設計終審保留給 fable**(記憶:回測弧繼任條款);若 Yonki 豁免則由 opus 審。
- 影子比對已證明 B-1/B-2 的價值無法用現有歷史驗證(掉榜股 92% 無當天分點)→ 需 Phase C 資料。

## 3. Phase C — 多年期訊號研究(FinMind)

依 `PLAN-yearly-backtest-20260922.md`:先測免費帳號可取得範圍 → 校準(5/8 起真實抓取當標準答案)→ 2021–2024 找訊號、2025–2026 驗證。
研究方向:「主力在買、價格未動」的早期吸籌;出場改價格風控。

## 4. 順序與期限

A0 → A1+A2+A4(同一生效日)→ A5(可平行)→ A6(**11 月底硬期限**)→ A7 → A8 → Phase C;Phase B 於 A 完成後決定。
