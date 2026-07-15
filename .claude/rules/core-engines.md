---
paths: ["core/**/*.py"]
---
# core/ 引擎操作鐵則（規範正本＝docs/ARCHITECTURE_BLUEPRINT.md，法條 C8-C12）

- 引擎輸出**語意 enum**，不吐 hex 色碼/雙語文案/HTML——呈現映射歸 viewer 單一擁有（C12）。
- 判斷參數（門檻/權重/名單）不寫死在函式裡——進 `core/engine_params.py`（C11：改參數只影響新產出）。
- 新判斷要不要落地為 obs_* 欄？走判定樹 C2/C8→C9→C11→C10（憲法 §5）；純派生不落地（C9）。
- 路徑依賴狀態逐日落地「當日認定」（C10 as-was），history 由落地序列派生，不回頭改。
- sm_state 是生命週期概念唯一 SoT；風險唯一 SoT＝obs_sm_transition_risk（confidence 獨立分數已廢）。
- 同一語意值只能有一個取值來源——複製實作＝漂移事故（研究期收案 10 例）。
