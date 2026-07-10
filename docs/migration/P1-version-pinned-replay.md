# P1 第 5 線 — Version-Pinned Replay 設計 ＋ Replay 參與權契約化

> **地位**：Phase 1 前置設計文件（遷移路線圖 §7 第 5 線）。憲法引用判例，本文件承載
> S06 三個 RC（RC-5/6/7）的**設計面**答案與**本輪落地**紀錄。
> **制定**：2026-07-10。**依據**：`docs/ARCHITECTURE_BLUEPRINT.md` §5（不變量 5/6）、§6（bump 規則）、
> `docs/architecture_research/sessions/S06-replay-contract.md`、CROSS-SESSION-NOTES #16–#23。
> **鐵律**：本輪零 canonical snapshot 內容變更；動快照內容的部分明列為 Phase 2 與 1.9.0 bump 同車。
> **誠實原則（#21）**：做不到的保證明說做不到——本文件對每個機制標「能到哪一級」，不許諾空頭。

---

## 0. 一頁摘要

| # | 問題 | 本文件的答案 | 本輪落地？ |
|---|---|---|---|
| RC-5 | replay 參與權硬編碼、兩份漂移 | strip 清單改由 `field_registry.yaml` 的 `replay: excluded-M` 派生，單一 SoT | ✅ 已落（純驗證層） |
| RC-6 | replay 保證是 HEAD-pinned，每次 bump 對全部歷史歸零 | 定義三級保證強度＋三個候選機制；誠實標示各級可達性與硬邊界 | 🔶 設計落地；機制實作待 Phase 2 |
| RC-7 | archive 無版本維度，superseded 版本不可從 archive 重建 | 查證 #23：standard flow 不會踩到；archive 版本維度屬 additive，留 Phase 2 | 🔍 查證落地；機制待 Phase 2 |
| #23 | verify-all-replay 會不會對 non-tip 版本嘗試 full-replay？ | **不會**——walker 是 tip-only；1.8.1 partial→supersede 不會撞 archive sha mismatch | ✅ 查證完成 |

**三句話核心決策**：
1. Replay 參與權從「驗證器內兩份黑名單」升格為「Registry 的欄位級契約宣告」；strip 集合是**派生物**不是**手維護清單**（RC-5，本輪落地，治「新增 metadata 欄無聲弄壞跨機驗證」）。
2. Version-pinned replay 的最強級（可重算）**現況做不到對全部歷史成立**：靠 `environment.core_commit_sha` 的 git-checkout 重算對 2026-06-04 以後可行、對更早的 zero-SHA 1.4.0 快照**永久做不到**；本輪只落「不需動快照內容」的部分（per-epoch 參與權凍結），真機制與 1.9.0 bump 同車。
3. RC-7 的 archive 覆寫坑**在 standard verify-all-replay 流程中踩不到**（walker 是 tip-only，經 code 查證），故 RC-7 維持 P1、不升 P0；archive 版本維度是 additive，留 Phase 2。

---

## 1. 保證強度三級詞彙（NOTES #21，本設計的量尺）

Replay 是「Snapshot = System of Record」得以被驗證的機制（#20）。同一份資料在不同時點可落在
不同的**保證強度**（與三態 I/O/M 正交的第二軸）：

| 級 | 名稱 | 定義 | 現況機制 |
|---|---|---|---|
| L3 | **可重算**（reproducible） | 從 WORM raw ＋ 當時 code ＋ 當時 config 能重算出 byte-identical 的 canonical hash | full-replay（僅對 current-epoch 快照） |
| L2 | **僅防竄改**（tamper-evident） | 無法重算，但能證明「磁碟上這份 bytes 未被事後改動」（disk-hash == index） | legacy-epoch check |
| L1 | **不可驗**（unverifiable） | 連 disk-hash 都失去意義（原始輸入已從 archive 消失，或 code pin 未記錄） | superseded non-tip / zero-SHA epoch |

**RC-6 的病**：現況把「保證強度」焊死在 schema epoch 這**一個開關**上——
`snap_schema == SCHEMA_VERSION → L3；否則 → L2`（`verify_all_replay.py:177`）。每次 bump，
全部既存快照從 L3 掉到 L2，**且無任何訊號**。實測（2026-07-10）：`SCHEMA_VERSION=1.8.1`、
43 份中僅 2 份 1.8.1 → **L3 覆蓋 2/43，其餘 41 份全 L2**。

Version-pinned replay 的目標＝**把「保證強度」從 epoch 開關解耦**：讓一份舊 epoch 快照
不必因為「HEAD 不是它的 code」就一定掉到 L2，而是「用它自己的 code pin 重算」保住 L3。

---

## 2. Version-pinned 的可行定義 — 三個候選機制，誠實分級

### 前置事實（查證所得，2026-07-10）

- **快照已記錄 version-pin 的原料**：每份快照的 `environment` 區塊已含 `core_commit_sha`、
  `python`/`numpy`/`pandas`/`pyyaml`/`jsonschema` 版本、`os`、`locale`、`timezone`、`decimal_context`
  （見 `reports/2026-07-09.json`）。REPLAY.md §1 早已把「checkout `core_commit_sha` ＋ pin 依賴版本」
  寫為理想定義——**原料在，缺的是機制**。
- **硬邊界（做不到的明說）**：2026-06-04 **之前**的 1.4.0 快照（約 17 份）`core_commit_sha`
  是 `0000...`（zero-SHA，當時未記錄）。→ 這批**永久無法** version-pin 重算，最高只能到 L2。
  這不是可修的 bug，是歷史資訊缺失（as-was，C10 精神：讀不到的 code pin 就是不存在）。

### 候選 A — git-checkout + rerun（真 version-pin）

**機制**：對 epoch < HEAD 的快照，checkout `environment.core_commit_sha`，在 pin 的依賴環境下
重跑 adapter+ingest（吃該版本 archive raw），比對 canonical hash。

| 面向 | 評估 |
|---|---|
| 能到的級 | **L3（真可重算）**——對有真 SHA ＋ archive 完整 ＋ 依賴可重建的快照 |
| 阻塞 1 | zero-SHA 的 17 份 1.4.0 **做不到**（上述硬邊界） |
| 阻塞 2 | 依賴 RC-7：archive 需保住**該版本**的 raw（superseded 版本現況已被覆寫，見 §4） |
| 阻塞 3 | 依賴環境可重建性——跨年後 python/numpy 舊版可能已不可 pip 安裝；`decimal`/`locale` 可控但 BLAS 數值路徑不保證跨版位元一致 |
| 成本 | 高：per-epoch checkout ＋ per-epoch venv ＋ CI 時間膨脹 |
| 動快照內容？ | 否（純驗證層），但**需要 bump 同車的 CI 機制**，非本輪 |
| 裁決 | **最強但最重、且部分永久做不到**；不在本輪落地，留 Phase 2 與 1.9.0 同車評估 |

### 候選 B — attestation-at-creation（凍結證明，非凍結 code）

**機制**：快照**生成當時** HEAD 就是它的 code，pipeline 已跑 `--check-replay`（同機二跑 byte-identical）。
把「此 hash 在生成當時通過重算驗證」連同 `core_commit_sha`＋hash 記成一份**旁側證明帳**
（additive：擴 `index.json` 或新增 `reports/_replay_ledger.json`，**不動快照內容**）。

| 面向 | 評估 |
|---|---|
| 能到的級 | **L2.5**——「曾在生成當時被重算驗證過」。強於裸 disk-hash（L2：只證沒被改），弱於隨時可重算（L3：現在還能跑） |
| 誠實界線 | 它證明的是「生成當時同輸入→同輸出成立」，**不**證明「今天用今天的機器還能重算」——不許諾 L3 |
| 成本 | 低（additive ledger），無需 per-epoch checkout |
| 動快照內容？ | 否（旁側帳）；但屬**新機制**，宜與 bump 同車設計避免半套 |
| 裁決 | **推薦作為 Phase 2 的務實中間態**——在 L3 全面 checkout 機制成熟前，先把「歸零」補成「歸 L2.5」。本輪不落（避免半套 ledger 漂成第二份真本，違反不變量 #1 精神）|

### 候選 C — per-epoch 參與權凍結（本輪落地的部分）

**機制**：legacy-epoch 的 L2 check（disk-hash == index）其正確性**依賴「當時 hash 什麼」的規則穩定**。
若 replay 參與權（哪些欄抹除）散在驗證器且隨 registry 演進漂移，未來對舊 epoch 重算 disk-hash 時
**排除集合可能已變**，L2 保證本身就不可信。RC-5 的契約化（§3）正是把參與權釘進 Registry，
使**任一 epoch 的 disk-hash 語意可被穩定復現**——這是 version-pin 的**地基**，不需動快照內容。

| 面向 | 評估 |
|---|---|
| 能到的級 | 穩固 **L2**（讓 L2 在 registry 演進下不退化）；為 A/B 的 L3/L2.5 鋪地基 |
| 動快照內容？ | **否**——純驗證層，本輪落地（§3） |

### 綜合裁決（誠實版）

- **能到 L3 的**：有真 SHA（≥2026-06-04）＋ archive 完整的快照，經候選 A 可保 L3——但機制重、待 Phase 2。
- **只能到 L2 的**：zero-SHA 的 17 份 1.4.0 快照，**永久封頂 L2**，明說做不到 L3。
- **本輪實得**：候選 C（參與權契約化），把 L2 從「registry 一改就可能失真」修成「穩定可復現」；
  並記錄候選 A/B 為 Phase 2 選項，B 為推薦的務實中間態。
- **不做**：本輪不建 attestation ledger、不建 per-epoch checkout CI（避免半套機制與快照內容變更）。

---

## 3. RC-5 落地 — Replay 參與權契約化（本輪，純驗證層）

### 病（S06 §3a / NOTES #16）

「哪些欄位不參與 replay 比對」散在兩處且**互不同步**：
- `run_pipeline.py:235`：只抹 `{generated_at}`。
- `verify_all_replay.py:213-242`：抹 `{generated_at, environment, audit_log}` ＋ provenance 子欄
  `{fetched_at, report_date, data_lag_days}`。

→ 任何**新增的 metadata 欄**若沒被人手動加進對的那份清單，就**無聲重引入跨機 false-fail**。
違反 BLUEPRINT 不變量 #5（「驗證器內不得硬編碼任何 strip 清單」）。

### 藥（單一 SoT，派生非手維護）

新增 `core/replay_contract.py`：strip 集合**派生自** `field_registry.yaml` 的 `replay` 等級。

- **`replay_normalized_toplevel()`** ＝ 全部 `replay: excluded-M` 的頂層欄，**扣掉** lineage 例外。
  現值 ＝ `{schema_version, generated_at, core_version, environment, audit_log}`。
- **lineage 例外**：`provenance` 雖 state=M，其完整性子欄（`raw_sha256`/`archived_sha256`/
  `archived_copy_path`）**必須留在比對 hash 內**——那是偵測 archive 漂移的唯一手段（見 §4）。
  故 provenance **不整欄抹**，registry 以新增的 `replay_role: lineage` ＋
  `replay_volatile_subfields: [fetched_at, report_date, data_lag_days]` 明文標注（additive，不改 schema）。
- **`normalize_for_replay_compare(snap, reference)`**：兩個 caller 共用同一函式。差異只在
  「跟誰比」（run_pipeline：run1 vs run2 同機；verify_all_replay：replay vs on-disk 跨機），
  「什麼是 replay-invariant」的契約**單一，來自 Registry**。

### 語意保持證明（為何零退步）

- 舊 verify_all_replay 抹 `{generated_at, environment, audit_log}` ＋ provenance 3 子欄。
- 新集合多抹 `{schema_version, core_version}`——但 full-replay 只在 `snap_schema == SCHEMA_VERSION`
  時進行，故 replay 的 `schema_version`/`core_version` 與 on-disk **恆等**，抹除是 no-op，不改判定。
- provenance 的抹除範圍**逐字不變**（只抹 3 個 volatile 子欄，lineage 整合性欄照留比對）。
- **實測**：`make verify-all-replay` 前後皆 **2 full-replay-clean + 41 legacy-epoch-clean / 43，0 fail**。
  `make test` 320 passed / 1 skipped（新增 `tests/test_replay_contract.py` 6 tests 全綠）。

### RC-5 治後的性質

新增任何 `replay: excluded-M` 欄，strip 集合**零 code 改動自動擴充**（`test_replay_contract.py::
test_new_excluded_m_field_auto_extends_strip_set` 為證）；MUST-I / epoch-scoped-O 欄**永不被抹**
（另有測試把關）——「新 metadata 欄無聲弄壞跨機驗證」的結構病根除。

---

## 4. RC-7 ＋ #23 查證 — archive 版本維度在本設計中的角色

### #23 查證結論（實際查 code，寫進設計）

**問**：`make verify-all-replay` 的標準流程會不會對 non-tip（superseded）版本嘗試 full-replay？
1.8.1 partial→supersede 真發生時會不會撞 `archive.py:148-155` 的 sha mismatch？

**答：不會。** 證據：

1. **walker 是 tip-only**。`verify_all_replay.py` 對 `index["snapshots"]` 逐日只讀
   `entry["current"]`（:174）與 `entry["current_hash"]`（:181/:244），**從不迭代 `history[]`**。
   全 repo 唯一的 replay-verification walker 就是它（`tools/` 其餘 `history` 字樣皆指
   `data/history/` 價格回補，與 supersede 鏈無關，已查證）。
2. **partial→supersede 時 tip 與 archive 同步覆寫**。補完走 `run_pipeline`（`daily.py:304-314`），
   寫回**同檔名** `reports/{date}.json`（:213，磁碟上 partial 被 complete 覆蓋），`_update_index`
   把 partial hash 推進 `history[-2]`、complete 升為 `current`；`archive_raw_inputs` 以 date 為鍵
   覆寫 archive 內 `today.json` 成含 T86 的 complete 版。
3. **∴ current tip（complete）的 `raw_sha256` 與 archive bytes 匹配 → full-replay 乾淨（L3）**；
   被 supersede 的 partial 只在 `index.history` 留一串 hash，其檔案與 archive raw 皆已被覆寫，
   **但 walker 永不碰它 → 永不對它跑 full-replay → 永不觸發 archive.py sha mismatch**。

**推論**：RC-7 的 archive 覆寫坑是**真的**，但**只有「刻意去 replay 某個歷史 superseded hash」的工具**
才踩得到——而這種工具**現況不存在**。故 RC-7 維持 **P1**（真缺口、零 standard-flow 觸發、修法 additive），
不升 P0。fable 在 S06 §5 對 #23 的「先查證再論斷、不預設會炸」判斷成立：**不會炸**。

### archive 版本維度（RC-7 / NOTES #18）在本設計中的角色

- **對候選 A（L3 checkout replay）是前提**：要對**任一歷史版本**（含 superseded）重算，archive 必須
  以 `(date, hash)` 或 append-only 保存**每個曾存在版本**的 raw，而非 per-date 覆寫
  （`archive.py:94-114`）。無此，候選 A 只能對 current tip 成立，對 supersede 鏈中間版本仍 L1。
- **對本輪（候選 C）非前提**：本輪只釘參與權、不重算歷史版本，不需要 archive 版本維度。
- **修法屬 additive**（新增路徑層 `<date>/<hash>/`，不破既有 `<date>/` 路徑）→ 留 Phase 2，
  與 1.9.0 bump 同車（那時 partial→supersede 才會有真實樣本，見下）。

### 操作軌提醒（非本設計裁範圍）

實測（2026-07-10）磁碟 `fii_pending` 快照 **0 份**、20 條 supersede 鏈**無一是 partial→complete**——
1.8.1 兩段式 replay 語意在 production **仍零真實樣本**。archive 版本維度的迫切性待「隔日驗收」
真的產生一次 partial→supersede 後再評估；在那之前，#23 已證 standard flow 安全。

---

## 5. 落地清單與 Phase 2 交棒

### 本輪已落（零快照內容變更，純驗證層）

| 檔案 | 改動 |
|---|---|
| `core/replay_contract.py` | **新增**。strip 集合派生自 registry 的單一 SoT ＋ `normalize_for_replay_compare()` |
| `schema/field_registry.yaml` | **additive**。provenance 加 `replay_role: lineage` ＋ `replay_volatile_subfields`（不改 schema/快照） |
| `tools/run_pipeline.py` | `--check-replay` 改呼叫共用 helper（原 `{generated_at}` 單欄 → registry 派生集合） |
| `tools/verify_all_replay.py` | 刪 30 行硬編碼 strip → 改呼叫共用 helper（逐字語意保持，見 §3） |
| `tests/test_replay_contract.py` | **新增** 6 tests：strip 集合 = registry 派生、MUST-I/epoch-O 永不抹、provenance lineage 保護、新 excluded-M 欄自動擴充、竄改不被遮蔽 |

### 交棒 Phase 2（動快照內容 / 需 bump 同車）

1. **候選 B — attestation ledger（推薦中間態）**：additive 旁側帳記錄 per-snapshot 的
   check-replay 證明＋`core_commit_sha`＋hash，把 bump 後的「歸零」補成「歸 L2.5」。
2. **候選 A — per-epoch checkout replay（最強 L3）**：CI 依 `core_commit_sha` checkout ＋ pin venv
   重算；受 zero-SHA 硬邊界與依賴可重建性限制，誠實只對 ≥2026-06-04 承諾 L3。
3. **RC-7 — archive 版本維度**：archive 改 `(date, hash)`/append-only；候選 A 對 superseded 版本
   成立的前提。等 partial→supersede 有真實樣本後與 1.9.0 同車。
4. **BLUEPRINT 不變量 #6 修正**：`environment` 現況仍污染 canonical hash（本輪靠 normalize 於**比對時**
   排除，未從**計算時**排除）；徹底修法＝canonical hash 計算前依 registry 排除 M 欄，屬快照內容/
   hash 規則變更，留 Phase 2/4。

### 排程級認知（NOTES #22，交棒各 session）

S05 RC-1 已核准 observation 逐步落地；S01–S04/S07 完成各觸發 minor bump。依 RC-6，**每次 bump 讓
此前全部快照的 L3 保證瞬間歸零、無訊號**。故遷移路線圖 §7 的「單一 1.9.0 bump」原則不僅是省事——
是**把「歸零」這件事只付一次代價**的直接後果。在候選 A/B 機制上線前，1.9.0 之前的歷史在 bump 後
只保 L2（或 zero-SHA 那批的 L2 封頂）——這是已知且明說的代價，不是意外。

---

## 附錄：判例對照

| 本文件段落 | 判例 |
|---|---|
| §1 三級保證強度 | NOTES #21（Replay Guarantee Strength） |
| §2 version-pin 機制 | NOTES #17/#22、S06 RC-6、REPLAY.md §1 |
| §3 參與權契約化 | NOTES #16、S06 RC-5、BLUEPRINT 不變量 #5、S05 RC-4 |
| §4 #23 查證 ＋ archive 版本維度 | NOTES #18/#23、S06 RC-7 |
| §5 排程級代價 | NOTES #22、BLUEPRINT §6/§7 |
