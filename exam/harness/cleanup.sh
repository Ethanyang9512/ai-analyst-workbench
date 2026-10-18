#!/bin/bash
# 考完清理考场留在考场目录以外的东西。
# 用法: cleanup.sh          只列出会删什么
#       cleanup.sh --yes    真删
# 删：
#   1. run_case.sh 在 ~/.claude/projects 下新建或用到的目录（清单 $AAW_EXAM_ROOT/created_project_dirs.txt；
#      里面是记忆软链和考场会话记录）。只删以考场目录换算出的前缀开头的；rm 软链只删链接本身，共享记忆不受影响。
#   2. /tmp 下考场假群号的进度卡状态文件（.claude_card_*fake*）和考场会话的 .aaw_turn_<会话号>.json。
# 不动：
#   - ~/.claude.json 里 Claude Code 自动记下的假工作区条目（这个文件同时被别的会话在写，手改有风险；条目无害）；
#   - 考场目录本身（考试记录先拷到你自己的存档处，再自己删）。
set -u
mkdir -p "${AAW_EXAM_ROOT:-/tmp/aaw-exam}"
ROOT=$(cd "${AAW_EXAM_ROOT:-/tmp/aaw-exam}" && pwd -P)
PREFIX="$HOME/.claude/projects/$(printf '%s' "$ROOT" | sed 's/[^a-zA-Z0-9]/-/g')-"
DO=${1:-}
list=()
while IFS= read -r d; do
  case "$d" in
    "$PREFIX"*) [ -e "$d" ] && list+=("$d") ;;
    "") ;;
    *) echo "跳过（不在考场前缀下）: $d" >&2 ;;
  esac
done < "$ROOT/created_project_dirs.txt" 2>/dev/null
for f in /private/tmp/.claude_card_*fake*; do [ -e "$f" ] && list+=("$f"); done
for done in "$ROOT"/*/done.txt "$ROOT"/*/*/done.txt; do
  [ -f "$done" ] || continue
  sid=$(sed -n 's/^session_id=//p' "$done")
  [ -n "$sid" ] && [ -e "/private/tmp/.aaw_turn_$sid.json" ] && list+=("/private/tmp/.aaw_turn_$sid.json")
done
[ ${#list[@]} -eq 0 ] && { echo "没有要清理的"; exit 0; }
printf '%s\n' "${list[@]}"
if [ "$DO" = --yes ]; then
  rm -rf -- "${list[@]}" && echo "已删 ${#list[@]} 项"
else
  echo "（只是列出；加 --yes 才删）"
fi
