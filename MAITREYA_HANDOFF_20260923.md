# Maitreya 交接文件 — 2026/09/23(黃金名單稽核 → 引擎修正弧 → 訊號研究結論)

> **這是最新一份 handoff。** 前一份 `docs/handoffs/MAITREYA_HANDOFF_20260915.md`(9 月斷更事故全面檢修)內容仍有效,
> 但「回測數字」「黃金名單語意」「待辦 T1」等節已被本檔取代。規範正本 `docs/ARCHITECTURE_BLUEPRINT.md`;觸發器正本 `ARCHITECTURE.md §5`。
> 撰寫:Claude(Opus 5),2026-09-23 夜。

---

## 0. 一句話狀態

**9 月斷更已止血、資料層三個大洞已修並上線(開盤價/分點覆蓋/回測撮合),引擎語意修正寫好並掛在旗標後(10/5 生效);
但三年語料的研究結論是:現有訊號(籌碼、法人、趨勢、動能)沒有可重現的選股優勢 —— 回測數字修正後五支策略全部變差。**

---

## 1. 本輪(9/22–9/23)完成了什麼

| 主題 | 結果 | 出處 |
|---|---|---|
| **黃金名單稽核** | 9 項發現(G1–G9):轉弱方向相反、主力買超只算買方、缺席被當透明、三份不同的黃金名單、廣度閘恆成立…;獨立 opus 覆核過 | `docs/migration/AUDIT-golden-list-20260922.md` |
| **影子比對** | 同一批資料跑舊/新算法:修正後幽靈黃金 30%→0、警示雜訊 −93%,但**訊號超額仍 ≈ 0** | 同上 §7 |
| **資料缺漏盤點** | 最嚴重:分點 45% 非當天(→ 半數股票過不了黃金閘)、掉榜股完全無資料、`open` 32.5% 缺+95% 錯日、融資欄位從未寫入 | 同上 §8 |
| **A4 已上線** | 開盤/成交量/漲跌幅改抓 TWSE MI_INDEX 按日期。9/23 實測 25/26 檔相符(9/22 為 0/21) | `tools/fetch_twse.py` |
| **A5① 已上線** | 分點抓取涵蓋整個快照宇宙(原本上限 40 且主力買超排最後 → 只抓到 14/21) | `tools/fetch_daily.py` |
| **A5② 已寫好(掛旗標)** | 個股融資改抓 MI_MARGN?date=;W4「散戶接盤」首次可用 | 同上 |
| **A1–A3 已寫好(掛旗標)** | 轉弱含當天、缺席中斷連買、廣度閘改讀全市場 | `config/scd.example.yaml` `feature_flags.engine_correction_v1` |
| **A6 回測三修(已上線)** | ①窗口與 as-was 旗標(360s+ → 27s、成本線性)②撮合改真開盤(`data/prices/`)③掉榜持倉不再凍結 | `core/paper_trading.py`、`core/prices.py` |
| **A7 已上線(9/24)** | 畫面黃金名單改用 `golden.run_as_landed()`:88/88 天與快照相符(改前最近 40 天有 27 天不符)、113s → 5s | `core/golden.py`、`viewer/` |
| **T2 已上線(9/24)** | `derive_trading_date` 改純日曆推導(18:00 結算後才算今天)+ 台北牆鐘;不再採信落後的 TWSE 日期 —— D1 混日事故的根因 | `tools/fetch_daily.py` |
| **T9 已上線(9/24)** | 夜班 `git fetch` 失敗不再被 `set -e` 無聲吞掉;卡住的重複資料 commit 自動備份後丟棄(origin 先發布者為準) | `deploy/heal_stranded_commits.sh` |
| **訊號研究** | 三年語料:訊號無優勢,**無訊號對照組反而更好**;動能因子同樣被行情主導 | `_research/multiyear/FINDINGS.md` |

**回測數字(修正後,4.5 個月語料,僅供理解機制,不足以做決策)**:v3 由 11 筆/81.8% 勝率/+2.00% → 43 筆/46.5%/+0.36%;
其餘四支平均淨報酬 −0.06% ~ −0.91%。原本的高勝率來自「停損看不到主力倒貨那幾天」。

---

## 2. 現在的系統狀態

- **排程**:cron-job.org 18:05(主力)/08:35(T+1)、Mac launchd 19:00(備援)、GHA 原生(名義備援,過午夜會解錯日期)。與 9/15 相同。
- **9/23 實測**:雲端 18:05 建成 26 檔快照;開盤價 25/26 正確、分點 26/26 當天、主力成本 26/26(9/22 僅約半數)。
- **旗標**:`engine_correction_v1: false`。**10/2(五)收盤後改 true 並 push**,10/5 起新快照採新語意;
  同時要改 `tests/test_engine_correction_v1.py::test_example_config_ships_flag_off_until_go_live`。
- **新增資料檔**:`data/prices/<date>.json`(全市場 OHLCV,I 態;pipeline 逐日落地,已回補 5/08 起 88 天、5.4MB/年約 15MB)。

---

## 3. 剩下的事

| # | 事項 | 期限 |
|---|---|---|
| — | **10/2 收盤後打開旗標**;10/3–10/4 週末全量驗證 | **10/2** |
| A8 | 上線後宣告新凍結:記 hash、前推重新計時、更新 EXEC-PLAN-backtest-arc §六 | 10/5 後 |
| Phase B | Schema 2.0(`main_force_net` 新欄、掉榜追蹤紀錄)—— 需決定時機與審查人 | 待定 |
| Phase C | 10 年語料研究(進行中,見 §4) | — |
| T3 | cron-job.org PAT 換發 + heartbeat | **2026-12-14 前** |

---

## 4. 研究:結論與進行中的測試

**結論(已完成)**:2023-09~2026-09 三年語料,籌碼/法人/趨勢/動能訊號的橫斷面超額在設計期全負、保留期全正
= 行情差異而非優勢;投組回測中**無訊號對照組(只買成交額最大)每個變體都贏過訊號**。詳見 `_research/multiyear/FINDINGS.md`。

**十年語料判定(2026-09-24 結案)**:2016-01~2026-09、**2606 個交易日**完整語料,依
`_research/multiyear/PREREGISTRATION.md` 的事前判準測 H1(法人持續買超)、H2(中期動能)、H3(交集)——
**三個全部未通過**(結果 `PREREG_RESULT_FULL.txt`,細節 `FINDINGS.md`)。

- H1:兩期中位為負、勝率 40–44%;保留期較對照組僅 +0.27pp(門檻 +0.5pp)。
- H2:平均正但**中位深負**(少數大贏家拉抬),勝率 40–43%。
- H3:**保留期(2023–26 多頭)全數達標**(20 日 +3.98%、中位 +0.45%、勝率 51%、較對照 +4.05pp、n=2205),
  但設計期(含 2018/2020/2022)中位 −2.13%、勝率 44% → 是「行情相依」而非優勢。

**依事前寫死的停止規則:停止在這份語料上尋找選股 alpha,系統定位改為觀察與紀律工具。**
要追 H3 只能新開預先宣告、註明「已看過結果」,並用**未來真實前推**驗證。
(方法學備註:9/23 首跑因我的腳本提早休眠、語料僅 46% 而作廢;重跑的程式與判準完全未改,
但保留期已被看過一次,H3 日後若通過證據力要打折。)

---

## 5. 待 Yonki 決定

| # | 問題 |
|---|---|
| D2 | 9/14 救援資料是否組成正式快照(無時間壓力) |
| D3 | cron-job.org 用 classic 還是 fine-grained PAT |
| D4 | 前推紀錄缺口怎麼處理(10/5 重新凍結後自動重來) |
| N1 | 掉榜幾日視為籌碼證據消失(現為 2 日,`BACKTEST_OFFLIST_EXIT_DAYS`) |
| N2 | `data/prices/` 進 repo(每年約 15MB)是否接受 |
| N3 | Schema 2.0 審查人:fable 終審 or 豁免由 opus |
| N4 | 10 年研究若不通過:接受「觀察工具」定位,還是付費買分點再測 |

---

## 6. 驗證指令(給下一個 session)

```bash
cd "/Users/yoncky/SCD engine/Ai stock" && git pull
python3 "/Users/yoncky/SCD engine/_research/engine-correction/verify_a4a5.py" 2026-09-24   # A4/A5 每日驗證,四項應全 ✅
cat "/Users/yoncky/SCD engine/_research/multiyear/PREREG_RESULT.txt"                        # 10 年研究結果
make test-fast && python3 tools/verify_all_replay.py                                        # 578+ passed(14 已知失敗)、replay 0 failure
```

---

## 7. 給下一個 AI(今天踩到的)

1. **改檔前先確認它不存在**:我用 `cat >` 直接蓋掉既有的 `tools/backfill_prices.py`(已從 git 還原)。新檔先 `ls`。
2. **回測一定要有無訊號對照組**:對照組比訊號好,才發現部位帳沒限制現金 = 偷開 1.6 倍槓桿。
3. **判斷訊號用橫斷面超額,不要用絕對資金曲線** —— 後者只反映行情。
4. **replay 陷阱**:不要在 `core/engine_params.py` 新增非 `BACKTEST_*` 參數(`as_config_dict()` 會把新鍵帶進所有舊快照的 replay → 全面失敗)。開關一律走 `config/scd.example.yaml` 的 feature flag。
5. **`reports/2026-05-17.json` 是星期日的快照**(5 月回補批次),已加守門員凍結現況。
6. 9/15 handoff 的注意事項(不要相信未修正的回測、子代理工作目錄、cancelled≠沒觸發、15:00–18:00 與過午夜不得建前一日快照)**仍然有效**。
