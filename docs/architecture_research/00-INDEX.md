# Architecture Research — Session 登記表

> 規則正本：`00-WORKING-PROTOCOL.md`（Yonki 2026-07-08 立）。
> 每 session 獨立完成、只答四問（見 `SESSION-TEMPLATE.md`）、報告放 `sessions/`。
> **全部 session 完成前：不改名、不動 schema、不加評分、不重構 UI、不動 replay contract。**
> 跨 session 事項記 `CROSS-SESSION-NOTES.md`，不提前展開。

## 執行順序（2026-07-08 定，理由見 assessment §7 與 plan）

先 S05/S06 立分層詞彙與驗證機制，其他 session 的 Q2（屬於哪一層）才有共同語言；
S08 前端要等「哪些 observation 會落地」明朗；S09 消費一切故最後。

| 序 | Session | 主題 | 狀態 | 證據包(opus/sonnet) | 裁定(fable) | 報告 |
|---|---|---|---|---|---|---|
| 1 | S05 | Data Contract | **✅ 完成** | ✅ opus 2026-07-09 | ✅ fable 2026-07-09（3 RC＋P0-P2 verdict） | `sessions/S05-data-contract.md` |
| 2 | S06 | Replay Contract | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（3 RC＋P0-P2 verdict） | `sessions/S06-replay-contract.md` |
| 3 | S01 | Golden Layer | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（RC-8/9＋C8/C9＋落地六欄核准） | `sessions/S01-golden-layer.md` |
| 4 | S04 | State Machine | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（C10 as-was＋六欄核准＋殭屍裁定） | `sessions/S04-state-machine.md` |
| 5 | S02 | Chip Momentum | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（C11＋chip落地/resonance解散） | `sessions/S02-chip-momentum.md` |
| 6 | S03 | Distribution & Risk（distribution+confidence） | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（存廢級：confidence 降級/distribution 拆解重生，零新法） | `sessions/S03-distribution-risk.md` |
| 7 | S07 | Market Context | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（market_state 判死/三欄核准/grain 維度新立，零新法） | `sessions/S07-market-context.md` |
| 8 | S08 | Frontend Presentation | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（新法 C12＋薄化定案＋sidecar 判死） | `sessions/S08-frontend-presentation.md` |
| 9 | S09 | Backtest Logic | **✅ 完成** | ✅ opus 2026-07-10 | ✅ fable 2026-07-10（回測不具決策效力宣告＋落地清單定稿，零新法＝法典閉合） | `sessions/S09-backtest-logic.md` |

## 🏁 研究階段收官（2026-07-10）

**9/9 session 完成。** 總帳：12 條契約法（C1–C12）、9 個 root causes（RC-1–RC-9）、55 條 NOTES、
**17 欄落地清單定稿**（#54）、4 個引擎處置（resonance 解散/confidence 降級/distribution 拆解重生/
market_state 判死）、3 個 artifact 判死（sidecar/checklist_history/cockpit_v2）、雙實作漂移 10 例收案、
「落不落」判定樹 C2/C8→C9→C11→C10、三個正交契約軸（I/O/M × Replay Guarantee Strength × grain）。

**Working Protocol 凍結條件已達成**（全部 session 完成）→ 下一階段＝遷移總計畫
（registry 建立＋#33 門檻 config 化＋#41 母體修正＋17 欄落地排程＋S06 version-pinned replay 設計），
**開工與否由 Yonki 裁定**。凍結期間裁定＝立約順序，非修復排程（各 session §5 語意不變）。

## S05 pre-work（2026-07-08 已完成，直接作為證據包輸入）
- `docs/DATA_CONTRACT_ASSESSMENT_2026-07-08.md` — 三種病的證據、domain 結構取捨、遷移 SOP
- `docs/DATA_CONTRACT_FIELD_MAP_2026-07-08.md` — 60 欄位三態分類 + 扁平前綴命名對照 + C1–C6

## 已鎖決策（session 裁定時的前提，不重議）
- Domain 結構：**扁平前綴**（market_/mf_/foreign_/trust_/dealer_/derived_/obs_）；深 nested 留 2.0。
- 遷移策略：**additive + alias 跨 minor**；deprecated 欄位 replay 生命週期內續寫；major 才移除。
- fii_alignment cap 維持連賣 2 天（Yonki 2026-07-08 裁定）。
- 前端：**不另建乾淨前端**。路徑=observation 落地後薄化 cockpit.py；重寫與否 S08 再裁。

## 模型調度
證據蒐集=opus/sonnet 獨立 session（照 SESSION-TEMPLATE 填草稿）；四問綜合+責任邊界裁定=fable
（只讀證據包+CROSS-SESSION-NOTES，不重讀全 repo）。fable 額度 7/13(台北)重置，斷點續作以本表為準。
