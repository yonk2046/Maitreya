---
paths: ["viewer/**/*.py"]
---
# viewer/ 操作鐵則（規範正本＝docs/ARCHITECTURE_BLUEPRINT.md；薄化＝Phase 3，核准文件 docs/migration/P3-approval-checklist.md）

- 薄化三紅線：viewer **不算**（判斷已落地為 obs_*）、**不裝**（不組裝/搬運判斷輸入，C8）、**不寫**（磁碟寫入=違憲）。
- 呈現映射（顏色/中文/emoji/HTML）歸 viewer 單一擁有（C12）；色彩用 `:root` 的 SCD_STATUS tokens
  （--scd-gold #EBC92F 等，cockpit.py 頂部），不散落 hex。
- Phase 3 完成前 cockpit 仍有 render-time 引擎呼叫＝已知過渡態；改 viewer 時**不要新增**對 core 引擎的 import。
- 畫面 vs 快照對不上時先讀 `docs/migration/P2-acceptance-report.md` F-1：分歧多半是窗口差
  （viewer 餵全歷史 vs pipeline 20 日窗），不是資料錯。
- 部署＝Streamlit Cloud 讀 GitHub main；頁腳顯示 commit hash，可據此判斷部署漂移（R12）。
