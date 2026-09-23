#!/bin/bash
# T9(b):清掉卡在本機的每日資料 commit,讓夜班自己接上(F-17,8/31 與 9/17 各發生一次)。
#
# 病徵:某晚 push 失敗(DNS/網路),本機留下 `data: daily pipeline` commit;
#       隔天起每晚開頭的 rebase 都撞衝突 → Mac 備援長期失效,只能人工清。
# 裁示:origin 先發布者為準。本機這份是重複產出,丟掉不損失資料。
#
# 只在**全部**條件成立時動手,否則原樣退出 1 交給人工:
#   1. 本機領先 origin/main 的 commit 全部是 "data: daily pipeline …"
#   2. 這些 commit 動到的 reports/*.json,origin/main 上都已經有
#      (若 origin 沒有 → 本機這份是唯一的一份,絕不能丟)
# 動手前先開 backup/stranded-<時間> 分支,丟掉的東西永遠找得回來。
set -uo pipefail

git rev-parse --verify origin/main >/dev/null 2>&1 || {
    echo "[heal] 沒有 origin/main 可比對"; exit 1; }

ahead=$(git rev-list --count origin/main..HEAD)
if [ "$ahead" = "0" ]; then
    echo "[heal] 本機沒有領先 origin/main 的 commit — 無事可做"
    exit 0
fi

while IFS= read -r subject; do
    case "$subject" in
        "data: daily pipeline "*) ;;
        *) echo "[heal] 本機獨有 commit 含非資料 commit:「$subject」— 不自動處理"; exit 1 ;;
    esac
done < <(git log origin/main..HEAD --format=%s)

while IFS= read -r f; do
    [ -n "$f" ] || continue
    git cat-file -e "origin/main:$f" 2>/dev/null || {
        echo "[heal] $f 只存在於本機,origin/main 沒有 — 不自動處理(丟掉會遺失資料)"; exit 1; }
done < <(git diff --name-only origin/main...HEAD -- reports/)

backup="backup/stranded-$(date +%Y%m%d-%H%M%S)"
git branch "$backup" HEAD || { echo "[heal] 建備份分支失敗,不動手"; exit 1; }
echo "[heal] $ahead 個卡住的資料 commit 已備份到 $backup,重設到 origin/main"
git reset --hard origin/main
