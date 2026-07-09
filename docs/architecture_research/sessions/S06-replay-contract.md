# Session 06 — Replay Contract（證據包）

> 蒐證者：opus（獨立 session，照 SESSION-TEMPLATE §0–§4 填草稿）。
> 前提：本報告只分析、蒐證，**未改任何 code/schema**；§5 裁定留給 fable。
> 承接：S05 §5 RC-4 把「replay 邊界」移交本 session；S05 立契約面（registry 必須帶 replay 等級欄），機制/等級定義/strip 白名單/跨機測試/lifecycle 歸 S06。
> 已鎖決策（不重議，見 CROSS-SESSION-NOTES #9 / 00-INDEX）：扁平前綴 domain、additive+alias 跨 minor、深 nested 留 2.0。

---

## §0 範圍與輸入

**只看：** snapshot 的可重建性契約層 —
- `core/hashing.py`（`canonical_bytes` / `canonical_sha256` 吃什麼、file_sha256、sidecar）
- `tools/run_pipeline.py`（`--check-replay` 同機二跑；`_update_index` 的 supersede 鏈不變量）
- `tools/verify_all_replay.py`（epoch-aware 分流：full-replay vs legacy-epoch；跨機正規化 strip 清單）
- `core/archive.py`（WORM 歸檔；`verify_only=True` 重 hash；per-date 覆寫語意）
- `tools/daily.py`（`_snapshot_is_partial`＋`_fii_published`＋補完/supersede 路徑）
- `data/adapters/legacy.py`（`paths_override` replay 從 archive 讀但 provenance 記 canonical 路徑；`fii_pending`）
- `core/ingest.py`（`_environment_block`、`SCHEMA_VERSION`、`fii_pending` 落頂層）
- 實測：`reports/index.json`、`make verify-all-replay`

**明確不看（留給哪個 session）：**
- 哪些 observation 該落地（落地清單）→ 各引擎 S01–S04 Q4 列舉；S05 已立法「準則」
- 欄位命名正本 / registry 表格結構 / schema additionalProperties → **S05 Data Contract**（已裁 RC-2）
- viewer render-time 計算、薄化後顯示層邊界 → **S08**
- backtest 對 snapshot 的消費 → **S09**
- 各引擎邏輯正確性 → S01/S02/S03/S04/S07

**實跑驗證：**

1. `make verify-all-replay 2>&1 | tail -3`：
   ```
   [verify-all] 0 full-replay-clean + 41 legacy-epoch-clean of 41 dates; 0 failure(s) (current schema 1.8.1)
   ```
   → **現況 0 份 full-replay、41 份 legacy-epoch**（交辦說 40，實測 41，多一天）。原因：`SCHEMA_VERSION="1.8.1"`（ingest.py:32）而磁碟上**無任何 1.8.1 快照**（見下）。

2. `reports/index.json` disk schema 分布（實跑）：`{'1.4.0': 23, '1.5.0': 1, '1.6.0': 6, '1.7.0': 4, '1.8.0': 7}`，最新是 1.8.0×7，**1.8.1×0**。→「full replay 保證」現況覆蓋 **0/41 份**。

3. supersede 鏈（history 長度>1）：**41 份中 20 份有 supersede 歷史**。例證：
   - `2026-05-25` history_len=**11**（同日多次 backfill/re-ingest，跨 13:45→22:22→次日 00:01）
   - `2026-05-22` history_len=6、`2026-06-05` history_len=4、`2026-06-08` history_len=2
   - **關鍵**：這 20 條鏈**全部來自 backfill / epoch bump 的 re-ingest**，**無一來自 1.8.1 partial→supersede**——磁碟上 `fii_pending` 快照 **0 份**（實跑確認）。→ 兩段式 partial→supersede 機制在 production **尚未跑過任何一次**（對照 NOTES #8「待驗收」、分支待合 main）。

---

## §1 這個模組真正要回答什麼問題？

Replay Contract 回答：**歷史上任何一天的 snapshot，今天能否被逐位元重建；重建失敗時代表什麼**。它是 Observation-First 系統把 snapshot 升格為 System of Record（NOTES #10）的**可信度機制**——snapshot 要當「系統當天相信什麼」的唯一權威紀錄，前提是「這份紀錄不是事後被竄改/漂移的」能被密碼學作證。

具體它保證三件事的可分辨性：(a) **byte-tampering / index drift**（有人改了磁碟上的快照或 index）；(b) **邏輯漂移**（ingest/adapter/canonical hash 規則變了，同輸入產出不同）；(c) **archive 完整性**（WORM 原始輸入未被上游 re-fetch 竄改）。下游拿它作三種決定：verify-all 每日綠燈放行、稽核回溯「那天到底判了什麼」、以及未來 registry 的 replay-level 契約。**它目前的結構性弱點是：這個保證每次 schema bump 就對全部歷史快照歸零**（§3-b），且「什麼參與 hash」沒有欄位級宣告、只有散落在驗證器裡的 ad-hoc strip 清單（§3-a）。

---

## §2 它屬於哪一層？

用三態詞彙（I/O/M，NOTES #11）描述 replay **目前實際覆蓋哪一態**：

- **Input(I)—覆蓋**：raw 輸入透過 WORM archive（`core/archive.py`）+ `raw_sha256`/`archived_sha256` 完整參與 hash 與重建。replay-from-archive（verify_all_replay.py:2-8）就是為了「I 態不受 live `data/` 被上游覆寫影響」而存在。I 態是 replay contract 目前**最紮實**的一態。
- **Observation(O)—部分覆蓋、且是幻覺**：snapshot 落地的 O（velocity/volume_ratio/streak 家族、abstain stubs）**在 full-replay 模式下**會被 ingest 重算比對——但**現況 0 份 full-replay**（§0），所以 O 態的「可重算」保證**實際覆蓋 0 份快照**，全部只靠 legacy-epoch 的 disk-hash（等於「這份 O 有沒有被事後改動」，**不等於「這份 O 能被重算出來」**）。而 render-time observation（golden/resonance/confidence，NOTES #2）根本不在 snapshot，replay 完全不覆蓋。
- **Metadata(M)—本應排除卻進了 hash，靠驗證器事後補救**：`environment`（python/numpy/os…）、`generated_at`、`audit_log`、mtime 衍生 provenance 全進 `canonical_sha256`（hashing.py:52 吃整份物件）。M 態**在契約層沒有被宣告為「不參與 replay」**；是 `verify_all_replay.py:213-242` 用**硬編碼 strip 清單**把它們逐一從磁碟版覆蓋回來才不 false-fail（§3-a）。

**分層是否清楚：不清楚。** replay 的「參與/不參與」在 code 裡沒有欄位級的宣告，只有兩份**互不相同、位置分散**的 strip 清單（run_pipeline 一份、verify_all_replay 一份）。三態中唯有 I 態被結構性保護（archive），O 態的 full-replay 保證形同虛設（0 份），M 態靠 ad-hoc 補救。這正對應 S05 RC-4 移交的「replay 等級需進 registry」。

---

## §3 目前有哪些設計混亂或責任重疊？

逐條附 `檔案:行號`。標「✔ 復現」＝與 NOTES 既有認知一致，「⚠ refine」＝細化/部分修正既有認知，「＋新增」＝本輪新發現。

### (a) hash 邊界：M 態污染 hash，靠兩份不一致的 ad-hoc strip 清單補救（🔴 replay，refine NOTES #3）

1. **`canonical_sha256` 吃整份 snapshot（含 environment）** — `core/hashing.py:52` → `canonical_bytes`(hashing.py:32) 對傳入物件全體序列化；`environment` 由 ingest.py:118-133 `_environment_block` 填入 python/numpy/pandas/os 等**建置機器指紋**，ingest.py:372 落頂層。→ metadata 在 hash 層**未被排除**。✔ 復現 NOTES #3。
2. **⚠ refine NOTES #3：兩條 replay 路徑的 strip 清單不同，跨機風險其實已被 verify_all_replay 緩解——但緩解方式脆弱。**
   - `tools/run_pipeline.py:235` `--check-replay` **只抹 `generated_at`**（NOTES #3 指的就是這行）。但這是**同一次 run、同一台機器**二跑（run_pipeline.py:230-237），environment 天生相同 → 此路徑**本就不涉跨機**，NOTES #3「只抹 generated_at → 跨機假失敗」的因果**不成立於這條路徑**。
   - 真正的跨機 full-replay 在 `tools/verify_all_replay.py`（本機 macOS 建、CI linux 驗）——它 **already strips**：`generated_at`(:213)、`environment`+`audit_log`(:222-224)、mtime 衍生 provenance `fetched_at/report_date/data_lag_days`(:232-242)。→ **跨機 full-replay 假失敗現況已被這份 strip 清單擋住**。
   - **∴ NOTES #3 的結論方向對（M 態確實進 hash、契約層未排除），但「只抹 generated_at 導致跨機假失敗」的具體機制需修正**：跨機驗證器已補了完整 strip。真正的病不是「現在會 false-fail」，而是——
3. **＋新增（本輪最關鍵）：strip 清單是驗證器內的硬編碼，非契約層宣告，且兩份不同步。** 「哪些欄位不參與 replay」的真相散在兩個地方且**清單不同**（run_pipeline={generated_at} vs verify_all_replay={generated_at, environment, audit_log, fetched_at, report_date, data_lag_days}）。任何**新增的 metadata / volatile provenance 欄位**若沒被人手動加進 verify_all_replay 的清單，就會**無聲重新引入跨機 false-fail**。這正是 S05 RC-4「registry 帶 replay 等級欄」要解的結構問題：replay-participation 應是**欄位在契約層的宣告**，由單一正本派生，而非驗證器body 裡兩份漂移的黑名單。→ 歸屬本 S06 設計。

### (b) epoch 凍結策略：full-replay 保證隨每次 bump 歸零（🔴 replay，結構性）

4. **schema_version != current → 只驗 disk-hash 的 legacy-epoch 邏輯** — `tools/verify_all_replay.py:176-194`：`snap_schema != SCHEMA_VERSION` 時**不重跑 ingest**，只比 `canonical_sha256(on_disk_snap) == entry.current_hash`(:180-181)。設計理由正當（:22-31 註解：HEAD code 無法合法重建舊 epoch 的 O 態，那是 schema evolution 不是 corruption）。✔ 語意正確。
5. **＋新增：但這使「full replay 保證」的覆蓋面隨每次 minor bump 歸零。** 實測（§0）：`SCHEMA_VERSION=1.8.1`，磁碟 41 份**全 < 1.8.1**（最新 1.8.0×7）→ full-replay 覆蓋 **0/41**。每次 bump（1.4→1.5→…→1.8.1），全部既存快照瞬間掉進 legacy-epoch，full-replay 覆蓋重置為 0，要到新 version 下**新建**快照才回升。→ 結構後果：**「同輸入可重算出同 O」這個最強保證，在任一 bump 後對全部歷史都不成立，只剩「disk-hash 沒被竄改」這個弱保證**。legacy-epoch 檢測不到「若用當時的 code 重跑會不會產出不同結果」，因為當時的 code 已不在 HEAD。→ 對應 §2 的 O 態幻覺。歸屬本 S06（epoch bump 時保證如何不歸零）。

### (c) supersede 鏈語意 + partial 重算地位（🔴 replay，＋新增）

6. **`_update_index` 維護 supersede 鏈不變量** — `tools/run_pipeline.py:86-136`：`history[0].supersedes=None`、`history[-1].superseded_by=None`、`history[i].supersedes==history[i-1].hash`、`current_hash==history[-1].hash`；byte-identical re-ingest 是 no-op（:117-118）。✔ 不變量清楚。實測 20/41 有鏈，`2026-05-25` 長 11。
7. **＋新增（回答交辦懸置）：被 supersede 的版本 replay 地位＝「只剩 disk-hash，無法從 archive 重建」。** 根因在 `core/archive.py` 的**歸檔以 date 為鍵、非以 hash 為鍵**：`dest_base = archive_root/<date>`(archive.py:94)、`mkdir(exist_ok=True)`(:96)、`shutil.copy2` 覆寫(:112-114)。→ **同日重跑會覆寫該日 archive 原始 bytes**。所以當 partial(fii_pending, today.json 無 T86) 被早晨完整版 supersede 時，archive 裡的 today.json 被換成**含 T86 的新版**；舊 partial 記的 `raw_sha256`（無 T86 版）不再等於 archived bytes → 若對舊 partial 跑 full-replay，`archive_raw_inputs(verify_only=True)` 會在 archive.py:148-155 拋 sha mismatch。**∴ 被取代的版本只保住 index 裡的 hash 字串（legacy-epoch 可驗「沒被竄改」），但 archive 已無其原始輸入可重建它。** supersede 鏈記錄了「曾經存在過這個 hash」，卻**不保證那個 hash 能被復現**。
8. **＋新增：1.8.1 partial→supersede 重算語意在 production 零覆蓋、未驗證。** `tools/daily.py:108-122` `_snapshot_is_partial`（讀 fii_pending）＋`:306` 補完放行（`_snapshot_is_partial and _fii_published`）＋`data/adapters/legacy.py:322` `fii_pending = not t86` → ingest.py:379 落頂層。機制齊備，但實測**磁碟 fii_pending 快照 0 份**、20 條 supersede 鏈**無一是 partial→complete**。→ NOTES #8「待驗收」屬實，兩段式 replay 語意**尚無任何真實樣本可作證**。歸屬本 S06（partial/supersede 重算語意定義）＋操作軌（隔日驗收）。

### (d) verify_only replay 路徑：信任鏈完整但依賴「canonical 路徑 vs 物理路徑」的隱形約定（🟡 replay）

9. **replay 從 archive 讀、provenance 記 canonical `data/` 路徑** — `data/adapters/legacy.py:395-431`：`paths_override` 設定時（replay 對 archive），`raw_file` 仍寫死 `"data/today.json"`/`"data/branches/"`（:404,421），註解自承「raw_file 是 LOGICAL identifier，非讀取 bytes 的物理路徑…使 canonical hash 與『bytes 從哪讀』無關」(:395-398)。→ 信任鏈設計**完整**：hash 綁邏輯身份不綁物理位置，因此本機建、CI 從 archive 驗能得同 hash。
10. **＋新增：但這條鏈的完整性依賴「archive bytes == 當初 data/ bytes」這個由 `raw_sha256==archived_sha256` 守的等式**（archive.py:148-155 兩模式都驗）。一旦 (c)-7 的 per-date 覆寫發生，該等式對**被覆寫的舊版本**失效——即 (d) 的信任鏈只對「current tip」完整，對 superseded 版本斷裂。兩者是同一結構事實的一體兩面。verify_only 模式本身無 bug；缺口在「archive 沒有版本維度」。歸屬本 S06。

### (e) replay 等級概念缺位：全有或全無（🔴 replay，＝S05 RC-4 的 S06 設計面）

11. **現況 replay 是「整份 hash」的二元，沒有欄位級「參與/不參與」宣告** — `canonical_sha256` 吃整份（hashing.py:52），要排除某欄只能在**驗證器**手動 strip（§3-a-2 的兩份清單）。schema (`canonical_schema.json`) 與 ingest record 皆**無任何欄位標注 replay-level**（S05 §3-9/10 已證 schema 開放式、三處定義不一致）。→ 無法宣告「這欄是 I 態必參與 / 這欄是 M 態必排除 / 這欄是 O 態 epoch-scoped 可重算」。S05 §5 RC-4 已裁「registry 必須帶 replay 等級欄」；**等級如何定義、strip 白名單如何從 registry 派生取代兩份硬編碼清單、legacy-epoch 與 full-replay 的欄位差異如何表達**＝本 S06 設計產出。

---

## §4 如果今天重新設計，最合理的責任邊界是什麼？

（理想態描述，非藥方；每點附與現況差距。前提：扁平前綴、additive+alias、深 nested 留 2.0；且 replay 等級欄由 S05 registry 承載，本節只定「等級語意」。）

**replay 該保證什麼——按三態分級（對應 S05 RC-4 的等級欄語意）：**
- **I 態（raw）＝MUST replay**：必參與 hash、必可從 WORM archive 逐位元重建。這是唯一「跨 epoch 都必須成立」的保證（raw 不隨 code 版本變）。
  - 差距：現況已達成（archive + raw_sha256），是最紮實的一態。**唯一缺口＝archive 無版本維度**（§3-c/d）：supersede 後舊版本的 raw 被覆寫，其 I 態不可重建。理想態＝archive 以 (date, hash) 或 append-only 保存每個曾存在版本的輸入。
- **O 態（observation）＝MUST 可重算，但重算保證是 epoch-scoped**：在**產生它的那個 schema epoch 的 code** 下，同 I → 同 O。
  - 差距一：現況 full-replay 覆蓋 0 份（§3-b），O 態「可重算」對全部歷史形同虛設，只剩 disk-hash。理想態＝epoch bump 不該讓保證歸零——需要「用當時 code/version 重跑」的能力（釘選 epoch 對應的引擎版本），而非「只有 HEAD 能重算、非 HEAD 一律降級為 disk-hash」。
  - 差距二：render-time O（golden/resonance…）根本不在 snapshot（NOTES #2），replay 完全不覆蓋——**此差距的修復在 S05（落地準則）＋各引擎 S01–S04（落地清單），非本 S06**；S06 只負責「一旦落地，宣告其 replay 等級為 epoch-scoped O」。
- **M 態（metadata）＝MUST 排除於 replay hash**：environment/generated_at/audit_log/mtime 衍生 provenance 皆不參與。
  - 差距：現況 M 態進 hash（§3-a-1），靠驗證器兩份漂移的硬編碼 strip 補救（§3-a-3）。理想態＝M 態在 registry 宣告 `replay=excluded`，canonical hash **在計算前**就依 registry 排除 M 欄位，兩份 strip 清單消滅、由單一正本派生。

**epoch bump 時保證如何不歸零（本 S06 核心待解）：** 理想態＝full-replay 保證是「用**生成該快照的 version** 的 code 重算」，而非「用 HEAD 重算」。現況 legacy-epoch 只驗 disk-hash 是「放棄重算、退守防竄改」。差距＝需要 version-pinned replay（引擎/adapter 依 schema_version 可回溯到當時邏輯），否則「System of Record 可重建」在每次 bump 後對歷史都只剩防竄改等級。**此為結構性懸置，不開實作藥方，留裁定者定 P 級。**

**supersede / partial 的重算語意（本 S06 核心待解）：** 理想態＝(i) supersede 鏈的**每一個曾存在版本**都應可從 archive 重建（archive 加版本維度），或至少契約明文宣告「superseded 版本只保 disk-hash 防竄改、不保重建」——現況是後者但**未明文**，靠讀 code 才知（§3-c-7）。(ii) partial→complete 的重算語意：partial 與其 complete 版是**不同 I 態**（前者無 T86），非同輸入的重算，應以 supersede 記錄兩個獨立可驗版本而非「重算等價」。差距＝機制齊備但 production 零樣本（§3-c-8），語意未經驗證、未明文。

**跨機決定性要靠什麼：** 理想態＝(a) I 態靠 archive bytes + raw_sha256（現況已達成）；(b) M 態靠 registry 宣告排除（取代硬編碼 strip）；(c) O 態靠 canonical hash 規則（NFC/sort/minify，hashing.py:32-49，現況穩健）＋ version-pinned 引擎。差距集中在 (b) 的「宣告化」與 (c) 的「version-pin」，非 canonical 規則本身。

**與已鎖決策 / S05 的交界（供裁定確認，不在此裁定）：** replay 等級欄是 S05 registry 的一欄（RC-4 已裁），本 S06 定的是**該欄的值域與語意**（MUST-replay-I / epoch-scoped-O / excluded-M）＋**強制機制**（canonical hash 依 registry 排除 M；full-replay 依 registry 決定比對欄位）。additive+alias 使 deprecated 欄位在其 replay 生命週期內續寫（00-INDEX 已鎖），與「epoch-scoped O」相容。archive 加版本維度屬 additive（新增路徑層，不破既有）。

---

## §5 裁定（fable，2026-07-10）

> 裁定框架：SESSION-TEMPLATE §5 的 Chief-Architect rubric（S05 已制度化）。

### 系統身份判準
Replay Contract 是「Snapshot = System of Record」這個主張**得以被驗證的密碼學/結構機制**，不是附加特性——沒有它，「System of Record」只是一個命名慣例，任何人都可以宣稱、無人能反駁或作證。本 session 的角色：定義這個機制目前實際保證到什麼程度、哪裡只是自稱。

### Root Causes — 11 條發現壓縮為 3 個（+1 併回、+1 修正既有認知）

**RC-5｜Replay 參與權未契約化，靠驗證器內兩份漂移的黑名單頂替（P0）**
吸收 §3(a)-1/2/3 與 (e)-11。§3(a)-2 的「refine」正確拆開了 NOTES #3——跨機假失敗現況已被 `verify_all_replay.py` 的 strip 清單擋住，不是活躍風險；但**真病更深**：哪些欄位參與 replay 是**驗證器內部的硬編碼判斷**，不是欄位在契約層的宣告，且兩份清單（run_pipeline 1 欄 vs verify_all_replay 6 欄）**互不同步**——任何新 metadata 欄位若沒被人手動加進對的那份清單，就無聲重新引入跨機 false-fail。
裁定（立法）：這是 S05 RC-4「registry 帶 replay 等級欄」移交回來的**設計面答案**——値域定為三級 **MUST-replay(I) / epoch-scoped(O) / excluded(M)**；canonical hash 的排除集合應由 registry **派生**，不是驗證器裡兩份各自維護的清單。本裁定只定值域語意與派生原則，不定 registry 表結構（仍屬 S05）。

**RC-6｜Replay 保證是 HEAD-pinned，不是 version-pinned——每次 bump 讓保證對全部歷史歸零（P0）**
吸收 §3(b)-4/5。legacy-epoch 的 disk-hash 退守邏輯本身正確（4，schema evolution 不是 corruption）；但後果被低估：實測 `SCHEMA_VERSION=1.8.1`、磁碟 41 份全 <1.8.1 → full-replay 覆蓋 **0/41**。每次 minor bump，「同輸入可重算出同 O」這個最強保證對**全部既存快照**瞬間蒸發，只剩「disk-hash 沒被竄改」的弱保證，而且**沒有任何訊號提示這件事發生了**。
**列 P0 的理由，是它對後續 session 的路線構成阻斷**：S05 RC-1 已核准「observation 逐步落地進 snapshot」，這代表 **S01–S04/S07 完成時會各自觸發 minor bump**——若不先在契約層承認「HEAD-only replay」的代價，就會在毫無察覺的情況下持續把歷史快照的可重建保證清零。這不是今天要修的 bug，是**排定後續 session 節奏前必須先立的認知**：bump 前應評估是否需要 version-pinned replay（依 schema_version 回溯對應版本的引擎邏輯），否則「System of Record 可重建」這句話對任何一天以前的歷史都只在下一次 bump 前成立。

**RC-7｜Archive 沒有版本維度——supersede 是 index 的邏輯概念，archive 沒有對應的物理概念（P1）**
吸收 §3(c)-6/7/8 與 (d)-9/10（(d) 的信任鏈設計本身健全，只是揭示同一缺口的另一面，不算獨立根因，併入）。Archive 以 `date` 為鍵、per-date 覆寫（archive.py:94-114）；supersede 鏈記錄「曾經存在過這個 hash」，卻不保證能復現它——一旦同日重跑，舊版本的 raw bytes 被換掉，其 `raw_sha256` 不再匹配 archive 內容。這使 replay contract 最紮實的一態（I 態）在「非 tip 版本」上其實不成立，只是至今沒人踩到。
裁定：**歸屬待驗證，非緊急**——1.8.1 partial→supersede 目前 production **零真實樣本**（磁碟 fii_pending 快照 0 份），此缺口尚未被觸發過。列 P1 而非 P0，因為它不阻斷其他 session 的判斷，且修法明確是 additive（archive 加版本維度，不破現有路徑）。**操作面提醒（非本裁定範圍，供操作軌參考）**：`make verify-all-replay` 的標準流程是否會對非-tip 版本嘗試 full-replay、或只查 current tip——證據包未確認這點，屬廉價可查的懸置，建議先查證再論斷「會不會炸」，不預設立場。

### 雜訊分離（技術正確、架構不重要）
本輪雜訊很少——opus 證據包已把自我修正（§3(a)-2 的 refine）跟新發現分開處理，品質高於平均。唯一算「支持性細節而非獨立根因」的是 (d)-9/10（verify_only 的 logical/physical 路徑解耦設計），已如上併入 RC-7。

### 責任洩漏檢查
乾淨。§0「明確不看」正確地把 O 態落地清單推給 S01–S04、registry 表結構推給 S05、viewer 邊界推給 S08、backtest 消費推給 S09；§3/§4 每條新發現都就地標了歸屬。無跨 session 責任混淆。

### 缺失概念（只留真正有用的一個）
現況 I/O/M（NOTES #11）回答「這是什麼種類的資料」；但 replay 契約還需要一根**正交軸**：**保證強度**——同一份資料可以是「可重算驗證」（full-replay）、「僅防竄改」（legacy-epoch disk-hash）、或「不可驗」（archive 版本缺失後的 superseded I 態）。現況 legacy-epoch 邏輯把「保證強度」跟「schema epoch」焊死成同一個開關，這正是 RC-6 得以無聲發生的原因——epoch 一動，強度就跟著掉，沒有獨立表達的空間。命名為 **Replay Guarantee Strength**（與 I/O/M 正交），供 S06 未來設計、也供其他 session 判斷「這個 observation 落地後我能對它許諾到哪一級」時引用。不新增其他概念（避免過度抽象化一個已經聚焦的契約層）。

### 挑戰證據包
- 認可 opus 自我修正 NOTES #3 的因果——已核對 run_pipeline.py:235（同機二跑）與 verify_all_replay.py:213-242（跨機清單）兩處，refine 成立，非過度謹慎。
- **不認可**把 (d)-9/10 當獨立設計混亂條目列出——它本身沒有問題，只是從另一個角度重述 (c) 的缺口；已併入 RC-7，避免把一個根因拆成兩條（呼應 rubric Q1「挑戰是否一病拆多條」）。
- 無隱藏假設、無過度工程跡象；證據包克制，沒有在「只分析」的邊界內夾帶解法傾向。

### 需要改的（只記錄，不執行）
（見上三個 RC 的裁定段；已同步 append CROSS-SESSION-NOTES #20-23。）

### 不需要改的（現況即合理，防未來誤重構）
`canonical_sha256` 的正規化規則本身（NFC/sort_keys/minify，hashing.py:32-49）——問題不在「怎麼 hash」，在「hash 什麼」，正規化邏輯穩健不動。legacy-epoch 的 disk-hash 退守機制本身（給定「HEAD 無法合法重建舊 epoch」的前提，這個降級是對的設計，不要拿掉——RC-6 要補的是「前提本身可以被 version-pinned 打破」，不是拆掉這層安全網）。verify_only 的 logical/physical 路徑解耦（legacy.py:395-398）——信任鏈設計完整，缺口在 archive 版本維度不在這條路徑本身。

### 對已鎖決策的相容性檢查
扁平前綴 ✓（replay 等級是 registry 的一欄，不涉結構）。additive+alias ✓（archive 加版本維度＝新增路徑層，不破既有；replay 等級宣告化＝新增機制，兩份舊 strip 清單可並存到派生機制上線再退場）。C1–C7 ✓，且與 S05 RC-2（registry 正本）、RC-4（registry 帶 replay 欄）直接銜接，無衝突。三態詞彙 I/O/M（NOTES #11）不受影響，本裁定新增的是與之正交的「保證強度」軸，非替代。

### Architecture Verdict
| 級 | 項 | 理由 |
|---|---|---|
| P0 | RC-5 Replay 參與權契約化（值域：MUST-I/epoch-scoped-O/excluded-M） | 是 S05 RC-4 移交的設計答案；registry 一旦真的建，需要這個值域才能派生排除集合，否則兩份黑名單問題原樣搬進新機制 |
| P0 | RC-6 Replay 保證需 version-pinned，非僅 HEAD-pinned | 阻斷後續 session 節奏——S01–S04 落地 observation(S05 RC-1 已核准)必觸發 bump，不先立此認知，會持續無聲清零歷史保證 |
| P1 | RC-7 Archive 版本維度缺失 | 已證實缺口但零真實樣本觸發、修法明確 additive；不阻斷其他 session 判斷 |
| P2 | 操作面查證：夜間 verify-all-replay 是否觸及非-tip 版本 | 廉價、可在不違反凍結的前提下先查證，降低 RC-7 的不確定性 |

### Executive Summary（兩分鐘版）
1. Replay Contract 是「Snapshot=System of Record」得以被驗證的機制，不是裝飾——沒有它，SoR 只是自稱。（定位）
2. 参與 replay hash 的欄位集合現在不是契約宣告，是驗證器裡兩份互不同步的黑名單；新欄位隨時可能無聲弄壞跨機驗證。需要 registry 帶 replay 等級欄，值域三級（MUST-I/epoch-scoped-O/excluded-M）。（P0）
3. 最深的結構問題：replay 保證是 HEAD-pinned，每次 schema bump 讓全部既存快照的「可重算」保證歸零，只剩「沒被竄改」。這對即將到來的 S01–S04 observation 落地（會觸發多次 bump）是排程級風險，須先認知才能安心繼續。（P0）
4. Archive 以日期為鍵、supersede 覆寫——被取代的版本只保住 hash 字串，原始輸入已不可從 archive 復原。1.8.1 partial→supersede 尚無真實樣本踩過這個坑，但坑確實存在。（P1）
5. 新增一根缺失概念：「保證強度」（可重算/僅防竄改/不可驗）與「資料型態 I/O/M」正交——現況把兩者焊死在 schema epoch 這一個開關上，是 RC-6 得以無聲發生的根因。

---

## §6 收尾 checklist
- [x] CROSS-SESSION-NOTES 已 append 本 session 新發現（見下方 append 區塊；跨 session 項：O 態落地清單→S01–S04、schema/registry 結構→S05、viewer 薄化→S08 已在 §3/§4 就地標歸屬）
- [x] 00-INDEX 狀態列已更新（S06：證據包完成，待 fable 裁定；報告連結 `sessions/S06-replay-contract.md`）
- [x] 未執行任何 code/schema 改動
