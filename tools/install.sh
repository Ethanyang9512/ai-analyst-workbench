#!/usr/bin/env bash
# 把本仓库的技能和两位验收员装到 Claude Code 的用户目录。
# 用法：bash tools/install.sh            安装（同名的旧目录、旧文件先挪到备份目录，不直接覆盖）
#       bash tools/install.sh --dry-run  只列出会装什么、会备份什么
# 目标目录默认 ~/.claude，可用环境变量 CLAUDE_HOME 改（测试时用）。
# 只复制 skills/ 下的技能目录和 agents/*.md；不碰你的 CLAUDE.md、设置、记忆。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CLAUDE_HOME:-$HOME/.claude}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
STAMP="$(date +%Y%m%d-%H%M%S)"
BK="$DEST/backup-ai-analyst-workbench-$STAMP"

do_or_say() { if [ "$DRY" -eq 1 ]; then echo "  [演练] $*"; else "$@"; fi; }

do_or_say mkdir -p "$DEST/skills" "$DEST/agents"
n=0
for d in "$ROOT"/skills/*/; do
  name="$(basename "$d")"
  [ -f "$d/SKILL.md" ] || continue
  if [ -e "$DEST/skills/$name" ]; then
    do_or_say mkdir -p "$BK/skills"
    do_or_say mv "$DEST/skills/$name" "$BK/skills/$name"
  fi
  do_or_say cp -R "$d" "$DEST/skills/$name"
  n=$((n + 1))
done
m=0
for f in "$ROOT"/agents/*.md; do
  name="$(basename "$f")"
  if [ -e "$DEST/agents/$name" ]; then
    do_or_say mkdir -p "$BK/agents"
    do_or_say mv "$DEST/agents/$name" "$BK/agents/$name"
  fi
  do_or_say cp "$f" "$DEST/agents/$name"
  m=$((m + 1))
done

if [ "$DRY" -eq 1 ]; then
  echo "演练结束：会装 $n 个技能、$m 个子代理到 $DEST；同名的旧版本会挪到 $BK"
else
  echo "已装 $n 个技能、$m 个子代理到 $DEST"
  [ -d "$BK" ] && echo "同名的旧版本挪到了 $BK（确认没问题后可以自己删掉）"
  echo "下一步：把 templates/global-CLAUDE.md 里你认可的部分合进 $DEST/CLAUDE.md；再跑 bash tools/run_all_tests.sh 验证"
fi
