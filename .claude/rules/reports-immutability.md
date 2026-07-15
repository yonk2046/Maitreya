---
paths: ["reports/**", "data/market_pulse/**"]
---
# reports/ 與 market_pulse 操作鐵則（規範正本＝docs/ARCHITECTURE_BLUEPRINT.md）

- 快照/index/ledger **只能由 pipeline 產生**（`python3 -m tools.run_pipeline --date …`），永不手改。
- 修正資料走修正案 SOP（裁定 C，`docs/FORWARD-RISK-REGISTER.md`）：I-only、cascade 範圍預宣告、
  兩版皆留（supersede 鏈 append-only）、O 欄一律引擎重算。活樣本＝修正案 C-1（7/14 breadth）。
- WORM raw archive（`reports/_raw_archive/`）既有檔 byte-identical 不可動——錯誤觀測也是歷史事實。
- market_pulse per-date 檔：乾淨檔受 WORM 保護；帶 error 的檔可被乾淨抓取升級（error→clean）。
- 2026-07-10 快照永不重建（颱風假殭屍，已裁定撤下）。
- 新增 audit event 要同步 `schema/canonical_schema.json` enum ＋ 跑 `make test`。
- 重建/回填類任務：**先查證後動手**；re-ingest 一律走 archive raw（paths_override），絕不讀 `data/today.json`。
