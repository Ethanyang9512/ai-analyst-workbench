#!/bin/bash
# 把 Claude Code 的配置备份到本地目录，并用本地 git 记版本。
#
# 用法：
#   bash backup.sh            备份并提交（提交只在本地，不推送）
#   bash backup.sh --dry-run  只列出会备份什么，不复制、不提交
#
# ⚠ 备份里有你的记忆、设置和工作台运行时，可能含代理地址、令牌等敏感信息。
#   备份目录只能留在本机或私有存储里，绝不要给它加公开的远程仓库、绝不要推到 GitHub 等公开位置。
#
# 可选环境变量：
#   AAW_BACKUP                      备份目标（默认 ~/Backups/claude-config）
#   AAW_RUNTIME                     工作台运行目录（设了才备份）
#   AAW_WS_BASE                     各项目工作区的总目录（设了才备份共享手册）
#   AAW_BACKUP_WORKSPACE_SETTINGS=1 连各工作区的 .claude/settings.json 一起备份（默认不备：代理、令牌常写在里面）
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
DEST="${AAW_BACKUP:-$HOME/Backups/claude-config}"

say() { echo "  $*"; }
if [ "$DRY" -eq 1 ]; then
  echo "将备份到：$DEST（只列出，不复制）"
  for f in CLAUDE.md settings.json keybindings.json; do [ -f "$HOME/.claude/$f" ] && say "~/.claude/$f"; done
  [ -d "$HOME/.claude/skills" ] && say "~/.claude/skills/（真实目录；符号链接只记清单）"
  ls -d "$HOME"/.claude/projects/*/memory 2>/dev/null | sed "s#^$HOME#  ~#" || true
  [ -d "$HOME/.claude/agents" ] && say "~/.claude/agents/"
  [ -n "${AAW_RUNTIME:-}" ] && [ -d "$AAW_RUNTIME" ] && say "$AAW_RUNTIME（运行时，不含 hook.log）"
  [ -n "${AAW_WS_BASE:-}" ] && say "$AAW_WS_BASE/default/CLAUDE.md"
  [ "${AAW_BACKUP_WORKSPACE_SETTINGS:-0}" = "1" ] && say "${AAW_WS_BASE:-<未设>}/*/.claude/settings.json"
  exit 0
fi

mkdir -p "$DEST"
cd "$DEST"
[ -d .git ] || git init -q
if git remote -v | grep -q .; then
  echo "⚠ 备份目录配置了远程仓库（git remote -v 有输出）。备份含个人记忆和配置，请确认远程是私有的，或删掉远程。" >&2
fi
# 本地兜底：.env 一类的文件不进版本
[ -f .gitignore ] || printf '# 备份目录只留本机，不要推到公开远程\n*.env\n.env\n' > .gitignore

# 核心配置
cp -f "$HOME/.claude/CLAUDE.md" ./CLAUDE.md 2>/dev/null || true
for f in settings.json keybindings.json; do
  if [ -f "$HOME/.claude/$f" ]; then cp -f "$HOME/.claude/$f" "./$f"; fi
done

# 真实目录的技能。--delete 只作用于备份副本：源里删掉的技能，副本里也删，旧版本仍在 git 历史里。
# 符号链接的技能跳过，真身在各自的仓库或安装源里。
mkdir -p skills
rsync -a --delete --no-links \
  --exclude 'node_modules' --exclude 'venv' --exclude '.venv' --exclude '.git' \
  "$HOME/.claude/skills/" ./skills/
ls -l "$HOME/.claude/skills" | awk '/->/{print $9, "->", $11}' > ./skills-symlinks.txt

# 各项目的持久记忆
for d in "$HOME"/.claude/projects/*/memory; do
  [ -d "$d" ] || continue
  name=$(basename "$(dirname "$d")")
  mkdir -p "./memory/$name"
  rsync -a --delete "$d/" "./memory/$name/"
done

# 工作台：运行目录、共享手册；工作区设置默认不备
if [ -n "${AAW_RUNTIME:-}" ] && [ -d "$AAW_RUNTIME" ]; then
  mkdir -p workbench
  rsync -a --delete \
    --exclude 'node_modules' --exclude 'venv' --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
    --exclude 'hook.log' --exclude 'config.env' \
    "$AAW_RUNTIME/" ./workbench/runtime/
fi
if [ -n "${AAW_WS_BASE:-}" ] && [ -d "$AAW_WS_BASE" ]; then
  mkdir -p workbench/default
  cp -f "$AAW_WS_BASE/default/CLAUDE.md" ./workbench/default/CLAUDE.md 2>/dev/null || true
  if [ "${AAW_BACKUP_WORKSPACE_SETTINGS:-0}" = "1" ]; then
    for s in "$AAW_WS_BASE"/*/.claude/settings.json; do
      [ -f "$s" ] || continue
      ws=$(basename "$(dirname "$(dirname "$s")")")
      mkdir -p "./workbench/workspace-settings/$ws"
      cp -f "$s" "./workbench/workspace-settings/$ws/settings.json"
    done
  fi
fi

# 子代理（验收员等）
if [ -d "$HOME/.claude/agents" ]; then
  mkdir -p agents
  rsync -a --delete "$HOME/.claude/agents/" ./agents/
fi

git add -A
if git commit -qm "backup $(date +%F_%H%M)"; then
  echo "备份完成并已在本地提交 → $DEST（不要推到公开远程）"
else
  echo "备份完成（内容没有变化，没有新提交）→ $DEST"
fi
