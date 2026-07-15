#!/bin/bash
# 憲法機械執行層：擋 AI 對 canonical 資料的手改（pipeline 用 Python 寫檔不經此路）。
# 規範正本＝docs/ARCHITECTURE_BLUEPRINT.md；本 hook 不新增規範，只執行既有禁令。
input=$(cat)
fp=$(printf '%s' "$input" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
[ -z "$fp" ] && exit 0

case "$fp" in
  */reports/*.json|*/reports/*.sha256|*/reports/index.json)
    echo "憲法禁令：reports/ 快照/index/ledger 永不手改（O 態不手編）。修正走 pipeline supersede（裁定 C 修正案 SOP，見 docs/FORWARD-RISK-REGISTER.md）。" >&2
    exit 2 ;;
  */core/engine_params.py|*/config/scd.example.yaml)
    echo "提醒：判斷參數變更會改 config_snapshot hash，屬修正案級變更——確認這是 Yonki 核准的調整再繼續。" >&2
    exit 0 ;;
esac
exit 0
