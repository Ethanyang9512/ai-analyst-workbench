#!/bin/sh
# 分析助手钩子统一入口。用法: run-hook.sh <脚本名(不带 .py)>
# 设计原则：任何异常都放行（exit 0）。只有脚本主动输出拦截 JSON 才会拦。
#   - 不是分析助手（桥传进来的 LARK_CHANNEL_PROFILE 不等于 AAW_PROFILE，默认 aaw）→ 不做任何事。
#     同一台电脑上别的机器人、你自己在终端里开的 Claude Code 都不受影响。
#   - 总开关：本目录（hooks/）下存在 DISABLED 文件 → 全部钩子不做任何事。
#   - 脚本不存在、找不到 python3 → 放行。
[ "${LARK_CHANNEL_PROFILE:-}" = "${AAW_PROFILE:-aaw}" ] || exit 0
DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || exit 0
[ -e "$DIR/DISABLED" ] && exit 0
S="$DIR/$1.py"
[ -f "$S" ] || exit 0
PY=/usr/bin/python3
[ -x "$PY" ] || PY="$(command -v python3 2>/dev/null)"
[ -n "$PY" ] && [ -x "$PY" ] || exit 0
true 2>/dev/null > "${AAW_HOOK_STATE:-$DIR}/.alive-$1"   # 体检看钩子是不是真的在跑（测试时写到临时目录）；写不了也照常往下（不用“:”是因为它写失败会让 sh 直接退出）
"$PY" "$S"
# 脚本自己保证只用 JSON 表达拦截；这里把任何非 0 退出码都当成放行
exit 0
