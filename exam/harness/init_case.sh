#!/bin/bash
# 给一道考题搭假工作区骨架：从真工作区只读复制设置和手册，换上只记录不发送的假脚本。
#
# 用法: init_case.sh <case目录> <真工作区名> [default 下的子项目名 ...]
#       init_case.sh <case目录> @example          不用真工作区，用本仓库的样例搭（跑 exam/example-paper 时用）
#   真工作区名: $AAW_WS_BASE 下的目录名，如 default、renewal-analysis
#   子项目名:   只在真工作区是 default 时有用，会在 ws/<子项目>/ 下复制该子项目的 CLAUDE.md、_CONVENTIONS.md、_glossary.md（有才复制）。
#
# 复制什么（都是只读复制，真文件不动）：
#   ws/.claude/settings.json    ← 真工作区的同名文件（钩子、模型、代理、技能开关和线上一致）
#   ws/CLAUDE.md                ← 真工作区的项目手册
#   ws/_CONVENTIONS.md、ws/_glossary.md ← 有才复制
#   群工作区还会建 <case>/default/CLAUDE.md（真 default 手册的副本），因为群手册里写的是 @../default/CLAUDE.md；
#   ws/bin 换成假脚本（群工作区和线上一样是指向 ../default/bin 的软链）。
# 不复制 _status.md、交付物、考卷：考卷和要不要放现状页，由出题的人自己放进 ws/。
set -euo pipefail
H="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(cd "$H/../.." && pwd -P)"
mkdir -p "${AAW_EXAM_ROOT:-/tmp/aaw-exam}"
ROOT=$(cd "${AAW_EXAM_ROOT:-/tmp/aaw-exam}" && pwd -P)
REAL_BASE="${AAW_WS_BASE:-$HOME/aaw-workspaces}"

[ $# -ge 2 ] || { sed -n '2,17p' "$0"; exit 2; }
CASE_IN=$1; WSNAME=$2; shift 2
mkdir -p "$CASE_IN"
CASE=$(cd "$CASE_IN" && pwd -P)
case "$CASE" in
  "$ROOT"/fakebin|"$ROOT"/fakebin/*|"$ROOT"/slots|"$ROOT"/slots/*) echo "case 目录不能放在 fakebin 或 slots 里" >&2; exit 2 ;;
  "$ROOT"/*) ;;
  *) echo "case 目录必须在 $ROOT/ 下面（别处在沙盒里读不到或会被挡）" >&2; exit 2 ;;
esac
printf '%s' "$CASE" | LC_ALL=C grep -q '[^A-Za-z0-9._/-]' && { echo "case 路径只能用英文、数字和 ._-/（会话记录目录名按字符换算）" >&2; exit 2; }
[ -e "$CASE/ws/.claude/settings.json" ] && { echo "已经有 $CASE/ws/.claude/settings.json，不覆盖" >&2; exit 2; }

LOG="$CASE/init.log"
: > "$LOG"
cp_log() {  # 源 目标
  cp -p "$1" "$2"
  printf '%s  %s  <-  %s\n' "$(shasum -a 256 "$2" | cut -c1-16)" "${2#$CASE/}" "$1" >> "$LOG"
}
fake_bin() {  # 目标 bin 目录
  mkdir -p "$1"
  for n in card.py p t newproject status-all; do
    cp "$H/fakebin/fake_tool.py" "$1/$n"; chmod +x "$1/$n"
  done
  echo "fake bin  ${1#$CASE/}/{card.py,p,t,newproject,status-all}" >> "$LOG"
}

mkdir -p "$CASE/ws/.claude"
if [ "$WSNAME" = "@example" ]; then
  # 用仓库里的样例：设置由 workspace_settings.py 生成（钩子登记指向要考的 runtime），手册用 runtime/manual/CLAUDE.md
  RT="${AAW_RUNTIME:-$REPO/runtime}"
  python3 "$RT/workspace_settings.py" apply --path "$CASE/ws" --kind project >> "$LOG"
  mkdir -p "$CASE/default"
  cp_log "$RT/manual/CLAUDE.md" "$CASE/default/CLAUDE.md"
  sed 's/{{群名}}/考场示例/; s/{{chatId}}/oc_examfake/' "$REPO/templates/workspace/CLAUDE.md" > "$CASE/ws/CLAUDE.md"
  echo "template  ws/CLAUDE.md  <-  templates/workspace/CLAUDE.md" >> "$LOG"
  for f in _CONVENTIONS.md _glossary.md; do
    [ -f "$REPO/examples/续费率下滑归因/$f" ] && cp_log "$REPO/examples/续费率下滑归因/$f" "$CASE/ws/$f"
  done
  fake_bin "$CASE/default/bin"
  ln -s ../default/bin "$CASE/ws/bin"
else
  REAL="$REAL_BASE/$WSNAME"
  [ -f "$REAL/.claude/settings.json" ] || { echo "找不到真工作区设置: $REAL/.claude/settings.json" >&2; exit 2; }
  cp_log "$REAL/.claude/settings.json" "$CASE/ws/.claude/settings.json"
  [ -f "$REAL/CLAUDE.md" ] && cp_log "$REAL/CLAUDE.md" "$CASE/ws/CLAUDE.md"
  for f in _CONVENTIONS.md _glossary.md; do
    [ -f "$REAL/$f" ] && cp_log "$REAL/$f" "$CASE/ws/$f"
  done
  if [ "$WSNAME" = default ]; then
    fake_bin "$CASE/ws/bin"
  else
    mkdir -p "$CASE/default"
    cp_log "$REAL_BASE/default/CLAUDE.md" "$CASE/default/CLAUDE.md"
    fake_bin "$CASE/default/bin"
    ln -s ../default/bin "$CASE/ws/bin"
    echo "symlink   ws/bin -> ../default/bin（线上群工作区也是软链到 default 的 bin）" >> "$LOG"
  fi
  for sub in "$@"; do
    [ "$WSNAME" = default ] || { echo "子项目只支持 default 工作区" >&2; exit 2; }
    [ -d "$REAL/$sub" ] || { echo "找不到子项目 $REAL/$sub" >&2; exit 2; }
    mkdir -p "$CASE/ws/$sub"
    for f in CLAUDE.md _CONVENTIONS.md _glossary.md; do
      [ -f "$REAL/$sub/$f" ] && cp_log "$REAL/$sub/$f" "$CASE/ws/$sub/$f"
    done
  done
fi

echo "real_ws=$WSNAME subprojects=$* at=$(date '+%F %T')" >> "$LOG"
cat "$LOG"
echo "下一步：把考卷放进 $CASE/ws/，把用户口吻的消息写进 $CASE/prompt.txt，再跑 $H/run_case.sh $CASE"
