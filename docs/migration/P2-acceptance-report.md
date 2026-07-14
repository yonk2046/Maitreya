# P2 整合驗收報告（P2-W7）— 1.9.0 落地完成

> **執行**：2026-07-15（W7 卡，`docs/migration/P2-EXECUTION-PLAYBOOK.md`）。
> **依據**：`P2-single-bump-design.md` §8 驗收清單＋fable 裁定節（D-1/D-3/D-4/D-5/D-7/W6-1）。
> **紀律**：唯讀驗收——全程未改動 `reports/` 任何資料檔、未改 core/tools/schema 程式碼；
> 凍結 hash 不變（7/13=`e17edf1e…`、7/14=`bfaf9375…`）。
> **驗收環境**：main @ `4bdc814`（W6 收尾後），python 3.9.6 / darwin-24.6.0-arm64。

---

## 0. 判定摘要

**Phase 2（1.9.0 單一 bump）驗收通過。** 22 欄全數落地、兩個自然生產日（7/13、7/14）
replay 可重算且 attested、31 天 I 欄回填冪等完成、全部 W1–W6 Review 卡重跑綠。
兩項發現（F-1 viewer 雙軌窗口分歧、F-2 W4 缺一個 market_family 單元測試）記錄於 §5，
均**不阻斷驗收**——F-1 的系統性修法本就是 Phase 3 viewer 薄化，F-2 有真實生產日行為佐證。
三項 known deviations（§6）為既成事實記錄，非 fail。

| 驗證 | 結果 |
|---|---|
| `make test` | **390 passed + 1 skipped**（基線一致；playbook 撰寫後 +12 dual-runner 防護） |
| `make verify-all-replay` | **33 full-replay-clean + 11 legacy-epoch-clean of 44；0 failure；2 ledger-attested**（7/13、7/14） |
| 落地值可重現性（決定性測試） | 7/13、7/14 兩日 41 檔 × 14 obs 欄，pipeline 路徑重算 **0 diff**（§3.1） |

---

## 1. design §8 驗收清單逐項結果

### §8a 落地前（前置閘門）
| 項 | 結果 | 證據 |
|---|---|---|
| Phase 1 五線全綠 | ✅ | `core/engine_params.py`／`data/market_pulse/<date>.json`（P1-2）／adapter staging（`data/adapters/legacy.py` 輸出 trust/prop/sell_raw）／`core/replay_contract.py`／`P1-version-pinned-replay.md` 皆在位 |
| market_pulse 對目標交易日存在且 breadth 解析成功 | ✅（7/13） | `data/market_pulse/2026-07-13.json` breadth={356,653,54,1078,twse_listed_stocks}，errors 空。7/14 檔存在但 breadth error → known deviation KD-1（§6），依 §6a 誠實 null 落地，非 gate 失敗 |
| make test 全綠 | ✅ | 390+1（W7 親跑） |
| verify-all-replay 0 fail（基線記錄） | ✅ | bump 前基線見 W1 commit 訊息；W7 親跑 33 full + 11 legacy / 44、0 failure |

### §8b bump 當日步驟
| 項 | 結果 | 證據 |
|---|---|---|
| 1. schema 22 欄宣告＋SCHEMA_VERSION 1.9.0＋registry active＋yaml meta 同步 | ✅ | W7 重驗：22 欄名逐一在 schema（15 record＋5 頂層＋obs_landing＋config_snapshot 結構）、全部非 required、registry planned 殘留=0、`SCHEMA_VERSION` 唯一定義於 `core/ingest.py:33`、`config/scd.example.yaml` meta=1.9.0 |
| 2. ingest 引擎移入＋config_snapshot 雙來源＋config_hash 覆蓋 | ✅ | `core/ingest.py:419-480`（obs_landing 掛點＋`{yaml, engine_params}`＋`canonical_sha256(config_snapshot)`） |
| 3. golden 改讀落地 sm／temperature 搬家改讀 obs_sm_transition_risk | ✅ | `core/obs_landing.py:188-189`（sm 先算、`golden.run(window, sm_states=…)` 不重跑）；`core/market_family.py`（temperature `risk_source: obs_sm_transition_risk`，7/14 快照實值可證） |
| 4. 首個 production 日 --check-replay PASS＋ledger append | ✅ | 7/13 attested（ledger 4 entries 含 supersede 鏈、終版 `e17edf1e…` passed=true）；7/14 同（`bfaf9375…`） |
| 5. I 欄回填（backfill 模式）＋抽驗 | ✅ | 31 天回填（27 full＋4 fii_pending）；抽驗 06-09：trust==dealer 雙寫、prop 非 None 36/36、零 obs_* 欄、obs_landing=false（§4 W6 卡詳） |

### §8c 落地後核對
| 項 | 結果 | 證據 |
|---|---|---|
| 當日快照含全部 22 欄且值與 viewer render-time 一致 | ⚠ **有條件通過**（發現 F-1） | 22 欄全在（7/14 實測）。值一致性：**同窗口下全欄 0 diff**（§3.1 決定性測試）；cockpit 實際顯示因餵入全檔案窗（44 快照）而對窗口敏感欄分歧（§3.3、F-1）。golden 名單成員與 tier 完全一致 |
| replay 對 1.9.0 快照達 L3 可重算＋ledger 記錄 | ✅ | 7/13、7/14 verify full-replay-clean＋📜 attested |
| verify-all-replay 仍 0 fail（1.9.0 full／既往 legacy） | ✅ | 33 full（=31 回填＋7/13＋7/14）＋11 legacy（10×1.4.0 rollup-only＋05-27），計數自洽 |
| C11 測試（雙來源 hash） | ✅ | `tests/test_config_extraction.py::test_config_hash_covers_engine_params`／`::test_config_hash_covers_yaml`／`::test_config_snapshot_is_two_source_without_strategies` 皆綠；W7 另做 in-memory 親測：改 `GOLDEN_TIER_PRIME` → hash 變、還原 → hash 復原；改 yaml 任一值 → hash 變；7/14 落地 config_hash == 以現行雙來源重算值 |
| fii_pending 交互（若首日 partial） | ✅（N/A＋替代樣本） | 7/13、7/14 首末皆 complete（fii_pending=false），條件未觸發。partial→supersede 真實樣本已由別處入手：7/14 GHA partial（`0b440e4b…`，linux 指紋）→ Mac complete（`bfaf9375…`）supersede，index history 兩版都留 |
| fable review 檢查點 | ✅（依 playbook 替代機制） | fable 5 不可用；依 playbook「Review 機制」以獨立 reviewer 逐卡執行過（W1–W6 各卡），W7 全數親自重跑（§4）。逐項：22 欄型別/grain/owner 對齊 registry ✅（CI 對拍綠）；O/I 分離無誤裝 ✅；C10 回填邊界（I 回填、O 不回填、obs_landing 旗標）✅；config_snapshot 雙來源 ✅；ledger 非 SoR（verify 軟核對、缺 ledger 不 fail，code+test 雙證）✅ |

---

## 2. 驗證基線詳情

```
make test               → 390 passed, 1 skipped in 10.45s
make verify-all-replay  → [verify-all] 33 full-replay-clean + 11 legacy-epoch-clean of 44 dates;
                          0 failure(s); 2 ledger-attested (soft) (current schema 1.9.0)
```

- 390+1 基線：playbook 寫 378，之後 dual-runner 防護 +12（既成事實，非偏差）。
- `test_lookback_hash_matches_current_strict` 已依 **fable 裁定 W6-1** 改窄 grandfather
  （strict 等式為 build-time 不變量；凍結引用方回溯降為 history-membership），
  補償性 build-time 斷言 `tools/run_pipeline._assert_lookback_fresh` 在位——驗收照新契約走，綠。

## 3. viewer 對照（cockpit 顯示值 vs 快照落地值）

方法：讀 `viewer/cockpit.py` 渲染路徑＋直接呼叫渲染前的資料組裝／引擎函式
（`golden.run`／`state_machine.run_all`／`chip_score.compute`／`confidence.run`／
`market_context.regime_shift`），與 7/14（及 7/13 breadth）快照落地值比對。未開 streamlit。

### 3.1 決定性測試：落地值 pipeline 路徑重現（0 diff）

以快照自身記錄的 lookback 窗（`environment.lookback_snapshots`，7/14=13 個 prior）重建
provisional window，呼叫 `core.obs_landing.compute_per_ticker_obs`：

| 日 | 窗 | 檔數 | obs 欄 diff（14 欄/檔） |
|---|---|---|---|
| 2026-07-13 | 13 priors（06-23…07-09） | 41 | **0**（obs_dist_consistency 1 檔因 buy_list 未存快照無法離線重算——由 attested check-replay 全路徑覆蓋） |
| 2026-07-14 | 13 priors（06-24…07-13） | 41 | **0** |

且**同一有界窗**下即使用 cockpit 的呼叫風格（`golden.run` 不帶 sm_states、含 near_miss
conviction）也是 **tier/conviction/sm/chip 全 0 diff**——落地值 = 引擎在其窗口上的確定性輸出，
分歧唯一來源是 cockpit 餵的窗口不同（§3.3）。

### 3.2 逐 tab 抽查表（7/14，cockpit 實際顯示路徑 = 全 44 快照窗）

**golden 名單 tab**（顯示 `e.tier`／`e.conviction`）：

| 檔 | 落地 obs_golden_tier / conviction / action_group | cockpit tier / conviction | 判定 |
|---|---|---|---|
| 2610 華航 | prime / 0.85 / executable | prime / **1.00** | tier 一致；conviction 分歧（F-1） |
| 2634 漢翔 | prime / 0.90 / executable | prime / 0.90 | 一致 |
| 2881 富邦金 | prime / 0.90 / executable | prime / **0.95** | tier 一致；conviction 分歧（F-1） |

golden 名單成員：落地 {2610,2634,2881,4958,5876} == cockpit {同}——**完全一致**。

**sm 狀態**（顯示 state/risk）：

| 檔 | 落地 obs_sm_state / risk / days | cockpit state / risk / days | 判定 |
|---|---|---|---|
| 2610 華航 | confirmed / low / 1 | confirmed / low / 1 | 一致 |
| 2634 漢翔 | strengthening / low / 1 | strengthening / low / 1 | 一致 |
| 1216 統一 | decelerating / elevated / 2 | decelerating / elevated / **4** | state/risk 一致；days 分歧（落地依 C10 landed-series 從 7/13 起算——**落地值才是 as-was 正解**） |

**chip 分**（顯示 grade；total 於評分明細）：

| 檔 | 落地 obs_chip_grade {grade,total} | cockpit {grade,total} | 判定 |
|---|---|---|---|
| 2610 華航 | 強 / 29 | 強 / 29 | 一致 |
| 2634 漢翔 | 強 / 27 | 強 / 27 | 一致 |
| 2881 富邦金 | 中 / 25 | **強 / 29** | 分歧（F-1：chip 輸入 streak/sponsorship 來自 sm 的窗口敏感內部值） |

**market banner / regime / 溫度**（grain=date，取三值代三檔）：

| 值 | 落地（7/14 快照） | cockpit 顯示路徑 | 判定 |
|---|---|---|---|
| obs_market_breadth | 7/13：0.3302（356/653/1078, twse_listed）== `data/market_pulse/2026-07-13.json` **逐值一致**；7/14：null-with-reason（KD-1） | 大盤脈搏 banner 讀 `data/market_pulse.json`（滾動檔，I 態 TAIEX 行情，非 obs 欄）——無同名可比欄，非分歧 | ✅（7/13 與母體檔逐值核對） |
| obs_market_temperature | 0.2807 / stable（risk_source=obs_sm_transition_risk） | 0.4544 / warm（`confidence.run` 全窗） | 分歧（F-1 之最大宗：cockpit 溫度仍走**已判死 confidence 引擎**＋全窗；#43 落地版才是 SoT） |
| obs_market_regime | 資金觀望 / transition=false（market_family，修正母體＋config 切點） | 強勢進攻 / transition=true（`market_context.regime_shift` 全窗＋舊 breadth 數學） | 分歧（F-1；#40/#41 落地版為唯一市場級生產者） |

### 3.3 分歧定量分解（7/14，41 檔）

| 顯示粒度欄 | cockpit 全窗 vs 落地 diff 數 | 同有界窗 vs 落地 diff 數 |
|---|---|---|
| golden 名單成員＋tier | **0** | 0 |
| obs_golden_conviction | 13 | **0** |
| obs_sm_state | 12 | **0** |
| obs_sm_transition_risk | 8 | **0** |
| obs_chip_grade.grade | 13 | **0** |
| obs_chip_grade.total | 23 | **0** |

結論：分歧 100% 歸因於 cockpit `main()` → `_load_all_snapshots()` 餵**全部 44 份快照**
（含 1.4.0 舊 epoch）給路徑依賴引擎，而 pipeline 落地用 config 有界 lookback 窗
（`lookback_window_days: 20` 日曆日 → 7/14 實得 13 priors）。落地值是 replay-attested 的
canonical 真值；cockpit 顯示層是 Phase 3 薄化（改讀 obs_*）的既定修理對象。詳見 F-1。

## 4. W1–W6 Review 卡重跑結果（W7 親跑，不抄舊結果）

### W1（schema＋registry）
- [x] 18 個 obs 欄名逐一在 schema、與 registry 名單一致（15 record＋3 頂層；另 4 I 欄＋obs_landing）
- [x] 22 欄＋obs_landing 全部非 required（additive）
- [x] registry 無殘留 planned；obs_landing 已登記（O/date/epoch-scoped-O/Pipeline(ingest)/active）
- [x] SCHEMA_VERSION 唯一定義（`core/ingest.py:33`）；"1.8.1" 殘留僅歷史註解/文件
- [x] 親跑 make test＋verify-all-replay：390+1、33 full＋11 legacy／44、0 failure

### W2（骨架＋config＋I 欄）
- [x] config_hash 對 engine_params 敏感（in-memory 親測：改 GOLDEN_TIER_PRIME → 變、還原 → 復原；避免觸碰 core/ 檔案的等效測法）；對 yaml 敏感（改 lookback_window_days → 變）
- [x] config_snapshot 無 strategies 鍵（D-4；7/14 實查 `{yaml, engine_params}` 兩鍵、engine_params 66 常數）
- [x] I 欄 vs WORM：7/14 **全 41 檔**（超出 3 檔要求）trust/prop 與 `_raw_archive/2026-07-14/legacy_today_json/today.json` t86 逐檔一致；fii_sell_raw==sellList（空對空）、main_force_sell_raw==mainForceSell（27 筆 byte-equal passthrough）
- [x] trust_net_buy == dealer_net_buy 全 41 檔（雙寫）；prop_net_buy 41/41 非 null 且 41 檔皆 ≠ trust（新值非複本）
- [x] replay PASS：verify-all-replay full-replay-clean＋attested（等效於 --check-replay，唯讀執行；直接跑 `--check-replay` 會先寫盤，違反本驗收唯讀紅線，故以 verify 全路徑代）

### W3（per-ticker O 欄）
- [x] 落地路徑 golden 不重跑 sm：`obs_landing.py:188-189` sm 先算、`golden.run(window, sm_states=sm_states)`；golden.py 內 `sm_run_all` 僅剩 `sm_states is None` 的 render-time fallback
- [x] 對照測試存在且綠：`tests/test_obs_landing.py::test_two_track_consistency_all_fields`；另 §3.1 對真實生產日 41 檔 pipeline 路徑 0 diff
- [x] obs_golden_near_miss 不含 tier：7/13（21 筆）＋7/14（18 筆）逐筆檢查，全部只有 `missed_gate`
- [x] days_in_state 首日=1：7/13（bootstrap 日）全 41 檔 days=1、entered=2026-07-13
- [x] replay PASS（同上，verify 全路徑）

### W4（market 家族）
- [x] obs_market_breadth ≠1.0 且源自 market_pulse：7/13=0.3302、分母 1078（twse_listed）；`market_family.py` 無買超榜母體殘留（breadth 全走 `_MARKET_PULSE_DIR`）
- [x] temperature 路徑無 confidence risk_level：`market_family.py` 僅註解提及（歷史說明）；落地值 `risk_source: "obs_sm_transition_risk"` 實證
- [⚠] market_pulse 缺檔情境**單元測試**：fetch 層錯誤測試齊（`test_market_pulse.py` missing_table/bad_stat/parse_failure 等），但 `market_family.compute_market_obs` 缺檔路徑**無專屬單元測試** → **發現 F-2**。行為面已由真實 7/14 證明：null-with-reason＋MARKET_DATA_GAP audit event＋無 fallback＋replay attested
- [x] market_state.py 未刪（36613 bytes 在位，留 Phase 3 處決清單）

### W5（attestation ledger）
- [x] replay 不依賴 ledger：以 code＋test 雙證代替「刪檔親測」（刪 `reports/_replay_ledger.json` 違反本驗收唯讀紅線）——`verify_all_replay.py:78-89` 缺 entry 回空字串永不 fail（D-5 鐵律內嵌註解）；`test_replay_ledger.py::test_load_missing_ledger_is_empty` 綠
- [x] ledger 無市場判斷欄位：實查 5 entries，欄位全集 = {date, schema_version, core_commit_sha, config_hash, canonical_hash, check_replay_passed, attested_at, env_fingerprint}——純 M 態
- [x] 冪等：`test_replay_ledger.py::test_idempotent_same_date_and_hash` 綠；實帳無 (date,hash) 重複；append-only 實證（7/13 三個 superseded hash 的舊 entry 都留存）

### W6（I 欄回填）
- [x] 抽 4 個回填日（06-09/05-28/07-01/05-26，超出 3 檔要求）：obs_*／sync_streak 殘留 **0**；I 欄照覆蓋表——正常日 trust/prop 全非 null、fii_pending 日（05-28）trust/prop 誠實 null 而賣方 raw 照落（fii=45/mf=38）
- [x] 冪等親測（唯讀 dry-run）：`python -m tools.backfill_i_columns --dry-run` → **31 already_backfilled＋1 skip_rollup_only（05-27）**，零寫盤需求；git status 乾淨
- [x] verify-all-replay：31 個回填日全部 full-replay-clean（verifier 認得 obs_landing=false 走 backfill 模式重算）、0 failure
- [x] index 供 supersede 鏈：06-09 history 3 版（05 epoch 原版 `ff587f6e…` → 06-11 版 → 07-14 回填版 `75e1a72d…`），supersedes/superseded_by 雙向完整，舊 hash 未覆滅
- [x] 紅線遵守：05-27 rollup-only 誠實跳過（磁碟仍 1.4.0）；**07-10 不存在**（檔案無、index 無——颱風假殭屍未重建）

## 5. 發現（Findings）

### F-1：cockpit render-time 顯示與落地值的窗口分歧（Phase 3 對象，非 Phase 2 缺陷）
- **現象**：§3.2/3.3。golden 名單成員與 tier 全一致；但 conviction 13/41、sm_state 12/41、
  transition_risk 8/41、chip grade 13/41、市場溫度（0.45/warm vs 0.28/stable）、regime 標籤
  （強勢進攻 vs 資金觀望）在 cockpit 顯示 vs 快照落地值之間分歧。
- **根因**（已定位、可重現）：cockpit `main()` 餵**全部 44 份快照**（跨 1.4.0/1.8.x/1.9.0 epoch）
  給路徑依賴引擎；pipeline 落地用 config 有界 lookback（20 日曆日）。同窗即 0 diff（§3.1 決定性
  測試）。另兩個 tab 級別根因：溫度 tab 仍呼叫已判死的 confidence 引擎（#37/#43）、regime tab 仍
  呼叫 market_context.regime_shift 舊 breadth 數學（#40/#41）——皆為 Phase 3 處決/薄化清單既定項。
- **定性**：落地值是 replay-attested canonical 真值（不變量 #1）；分歧不是 1.9.0 落錯值，而是
  viewer 尚未薄化（憲法不變量 #2 的已知未達標，BLUEPRINT §7 Phase 3 的存在理由）。W3 的雙軌
  一致性保證（同窗同值）成立且經真實生產日重驗。
- **處置**：不修（紅線）；記錄至此。Phase 3 viewer 薄化（改讀 obs_*）為系統性修法。
  在那之前，cockpit 對窗口敏感欄的顯示**不應被當成 SoT** 引用。

### F-2：`market_family.compute_market_obs` 缺檔路徑無專屬單元測試（W4 卡一項缺口）
- **現象**：W4 Review 卡「market_pulse 缺檔情境測試存在（null＋error，無 fallback）」——fetch 層
  錯誤測試齊備，但 market_family 模組層的缺檔/錯誤檔情境無 dedicated test。
- **緩解**：真實 7/14 生產日完整演練了此路徑（per-date 檔帶 breadth error → obs_market_breadth
  null-with-reason、MARKET_DATA_GAP audit event、無買超榜 fallback、replay attested）。
- **處置**：不在驗收中補寫（唯讀紀律）；建議後續以 7/14 為 fixture 補一個模組層測試。

## 6. Known deviations（既成事實，非 fail）

| # | 內容 | 記錄 |
|---|---|---|
| KD-1 | **7/14 obs_market_breadth 全 null**：7/14 上午 11:46 盤中誤觸發 fetch 佔住 market_pulse WORM 檔位，per-date 檔帶 breadth error（`stat != OK`）→ 依 §6a 誠實 null-with-reason 落地 | 快照 audit_log `MARKET_DATA_GAP` 1 筆；修正案另案排程 |
| KD-2 | **7/14 obs_market_temperature 在 breadth 缺席下算出**：`breadth_signal: null`（誠實揭露）、breadth 風險成分取中性 0.5；elev/dist 成分照常讀當日 obs_sm_transition_risk | 溫度值 0.2807/stable 的 breadth 維度信度降低，快照內欄位自帶揭露 |
| KD-3 | **07-10 快照不存在**：颱風假殭屍已撤下（檔案與 index 皆無），嚴禁重建——回填範圍終點 07-09 | W6 紅線遵守實查 ✅ |
| KD-4 | 基線位移：make test 378→390+1（dual-runner 防護）；strict lookback 契約改依 fable 裁定 W6-1（窄 grandfather＋build-time `_assert_lookback_fresh`） | 均為裁定過/記錄過的既成事實 |

## 7. 收尾動作（本驗收隨附提交）

1. `P2-single-bump-design.md` §8 清單逐項勾選（含 ⚠ 項註記指向本報告）。
2. `docs/ARCHITECTURE_BLUEPRINT.md` §7 Phase 2 標題行標注完成狀態（只改狀態行，不改條文）。
3. `schema/field_registry.yaml` meta.notes 收尾同步：清除「ingest 尚未消費」等 W2/W4 之後的過時陳述；
   counts（24/87/0）已在 W4 收尾時同步，W7 核實無誤。

## 8. Review 卡 W7（留給 Yonki / 隔日回看）

- [x] P2-acceptance-report.md 的 viewer 對照表無「未解釋的」不一致（分歧全數定位到窗口/Phase 3 對象，落地值 0 diff 可重現）
- [ ] 隔日（下一交易日）production 跑完後回頭看一眼：新快照 22 欄有值、replay 0 fail、ledger +1
