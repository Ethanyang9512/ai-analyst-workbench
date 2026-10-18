#!/bin/bash
# 在沙盒里按桥的方式跑一遍分析助手（一道考题 = 一个 case 目录）。只在 macOS 上能用（靠系统自带的 sandbox-exec）；
# Windows / Linux 的替代办法见 exam/README.md「不是 macOS 怎么办」。
#
# 用法:
#   run_case.sh <case目录>                 正式跑：产出 <case>/out.jsonl、err.txt、done.txt
#   run_case.sh <case目录> --shell '<命令>' 在同一个沙盒、同一套环境变量里跑一条 shell 命令（自检用，不起分析助手）
#                                          harness 目录在沙盒里读不到，脚本要从标准输入喂：--shell 'sh -s' < 脚本
#                                          输出要接管道（| cat > 文件）：沙盒里派生的子进程写不进直接重定向到考场目录的文件
#
# case 目录（必须在 $AAW_EXAM_ROOT 下，默认 /tmp/aaw-exam；路径只用英文数字和 ._-/）：
#   prompt.txt          模拟用户口吻的一条消息（只写正文，桥的三段外壳由 prep.py 套）
#   ws/                 假工作区（分析助手的 cwd）：考卷 + 从真工作区复制来的 .claude/settings.json、CLAUDE.md 等（用 init_case.sh 搭）
#   context.json        可选，覆盖 bridge_context 字段（如群聊）；群号永远是假的
#   paper_sources.txt   可选，考卷是从哪些真实项目目录取的（一行一个），沙盒整片挡读
#
# 和桥一样的地方：claude -p --output-format stream-json --verbose --permission-mode bypassPermissions
#   --append-system-prompt-file <桥的运行约定+身份段+runtime/workflow.md>；
#   环境只有桥进程有的那几个变量 + LARK_CHANNEL / LARK_CHANNEL_PROFILE；ws 里的设置和钩子照常加载。
# 和线上不同的地方（都为了隔离）：
#   - 整个进程在 sandbox-exec 里（规则见 deny_base.sb.template + run/sandbox.sb）；
#   - PATH 最前面是假 lark-cli（$AAW_EXAM_ROOT/fakebin）；AAW_WS_BASE / AAW_HOOK_STATE / AAW_CARD_PY 指向本题目录；
#     钩子状态目录里照线上放 GATE_ENFORCE（线上验收门是强制模式时）；
#   - LARK_CHANNEL_HOME、LARK_CHANNEL_CONFIG、LARKSUITE_CLI_CONFIG_DIR 指向空的假目录；TMPDIR、CLAUDE_CODE_TMPDIR 指向 run/；
#   - 默认加 --disallowedTools：WebFetch、WebSearch（不联网、业务材料不外发），PushNotification、RemoteTrigger、
#     SendMessage、ListAgents（不推送、不起云端任务、不给本机别的 Claude 会话——包括线上分析助手——发消息）；
#     另可用 EXTRA_DISALLOWED 追加（逗号分隔，例如你装的联网类 MCP 工具名）；NET_TOOLS=1 时一个都不关，命令行和桥完全一致。
#   - 沙盒里 shell 的 cd 要能“看”上级目录的属性，所以被挡目录里放开的子目录的上级只放开看属性。
# 收尾 finish.py 写 done.txt（可单独重跑）；考后用 audit.py <case> 列读过的路径；cleanup.sh 清考场在外面留下的东西。
# 其他开关：MODEL（默认不传 --model，用 Claude Code 的默认模型）、TIMEOUT_MIN（默认 120，超时杀掉并在 done.txt 记 timeout=yes）、
#           AAW_SHARED_MEMORY（给了就和真工作区一样，把本题的记忆位置软链到共享记忆）。
# 并发：全机最多 2 个考场会话（$AAW_EXAM_ROOT/slots/ 两个槽），满了就等。
set -u
H="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(cd "$H/../.." && pwd -P)"
die() { echo "run_case: $*" >&2; exit 2; }

# 整个主体包在函数里：bash 会先把函数整段读完再执行，跑的过程中有人改这个文件也不会读到半截
main() {
[ $# -ge 1 ] || { sed -n '2,33p' "$0"; exit 2; }
command -v sandbox-exec >/dev/null 2>&1 || die "找不到 sandbox-exec（只有 macOS 有）；替代办法见 exam/README.md"
CLAUDE_BIN=$(command -v claude) || die "PATH 里找不到 claude"
mkdir -p "${AAW_EXAM_ROOT:-/tmp/aaw-exam}"
ROOT=$(cd "${AAW_EXAM_ROOT:-/tmp/aaw-exam}" && pwd -P)
case "$ROOT" in "$REPO"|"$REPO"/*) die "考场目录不能放在仓库里（仓库里的 exam/ 在沙盒里整片挡读）" ;; esac
RUNTIME=$(cd "${AAW_RUNTIME:-$REPO/runtime}" && pwd -P) || die "找不到 runtime 目录"
[ -d "$1" ] || die "没有这个目录: $1"
CASE=$(cd "$1" && pwd -P)
MODE=claude; SHELL_CMD=
if [ "${2:-}" = "--shell" ]; then MODE=shell; SHELL_CMD=${3:?--shell 后面要跟命令}; fi
case "$CASE" in
  "$ROOT"/fakebin|"$ROOT"/fakebin/*|"$ROOT"/slots|"$ROOT"/slots/*) die "case 目录不能放在 fakebin 或 slots 里" ;;
  "$ROOT"/*) ;;
  *) die "case 目录必须在 $ROOT/ 下面" ;;
esac
printf '%s' "$CASE" | LC_ALL=C grep -q '[^A-Za-z0-9._/-]' && die "case 路径只能用英文、数字和 ._-/"
WS=$CASE/ws; RUN=$CASE/run
[ -f "$WS/.claude/settings.json" ] || die "缺 $WS/.claude/settings.json（先用 init_case.sh 搭假工作区）"
if [ $MODE = claude ]; then
  [ -s "$CASE/prompt.txt" ] || die "缺 $CASE/prompt.txt"
  [ -e "$CASE/done.txt" ] && die "这一题已经跑过（有 done.txt）；要重跑先把 out.jsonl、err.txt、done.txt、run/ 挪走"
fi
# 假脚本放进考场目录（沙盒里只放开这一份，仓库里的 exam/ 整片挡读）
mkdir -p "$ROOT/fakebin"
for f in "$H"/fakebin/*; do cmp -s "$f" "$ROOT/fakebin/$(basename "$f")" || cp -p "$f" "$ROOT/fakebin/"; done
chmod +x "$ROOT"/fakebin/*
mkdir -p "$RUN/state" "$RUN/tmp" "$RUN/ctmp" "$RUN/fake-lark-channel"
chmod 700 "$RUN/ctmp"
# 线上验收门是强制模式（钩子状态目录里有 GATE_ENFORCE）时，换成本题的状态目录以后要在这里照样放一个
[ -e "${AAW_HOOK_STATE:-$RUNTIME/hooks}/GATE_ENFORCE" ] && : > "$RUN/state/GATE_ENFORCE"

SLUG=$(AAW_EXAM_ROOT="$ROOT" AAW_RUNTIME="$RUNTIME" python3 -I "$H/prep.py" "$CASE" "$MODE") || die "prep.py 失败"

# 可选：记忆软链，和真工作区一样让 ~/.claude/projects/<编码路径>/memory 指向共享记忆。新建的目录记进清单，考完用 cleanup.sh 删
PROJ=$HOME/.claude/projects/$SLUG
if [ -n "${AAW_SHARED_MEMORY:-}" ] && [ ! -e "$PROJ/memory" ]; then
  mkdir -p "$PROJ" && ln -s "$AAW_SHARED_MEMORY" "$PROJ/memory" || die "建记忆软链失败: $PROJ/memory"
fi
grep -qxF "$PROJ" "$ROOT/created_project_dirs.txt" 2>/dev/null || echo "$PROJ" >> "$ROOT/created_project_dirs.txt"

ENVV=(
  "HOME=$HOME" "USER=${USER:-}" "LOGNAME=${LOGNAME:-}" "SHELL=${SHELL:-/bin/zsh}"
  "PATH=$ROOT/fakebin:$PATH"
  "TMPDIR=$RUN/tmp/"
  LARK_CHANNEL=1 "LARK_CHANNEL_PROFILE=${AAW_PROFILE:-aaw}" "AAW_PROFILE=${AAW_PROFILE:-aaw}"
  "LARK_CHANNEL_HOME=$RUN/fake-lark-channel"
  "LARK_CHANNEL_CONFIG=$RUN/fake-lark-channel/config.json"
  "LARKSUITE_CLI_CONFIG_DIR=$RUN/fake-lark-channel/lark-cli"
  "AAW_RUNTIME=$RUNTIME"
  "AAW_WS_BASE=$CASE" "AAW_HOOK_STATE=$RUN/state" "AAW_CARD_PY=$ROOT/fakebin/card.py"
  "AAW_EXAM_RUN=$RUN"
  "CLAUDE_CODE_TMPDIR=$RUN/ctmp"
)
[ -n "${AAW_KB:-}" ] && ENVV+=("AAW_KB=$AAW_KB")
[ -n "${AAW_PY:-}" ] && ENVV+=("AAW_PY=$AAW_PY")

if [ $MODE = shell ]; then
  cd "$WS" && exec env -i "${ENVV[@]}" /usr/bin/sandbox-exec -f "$RUN/sandbox.sb" /bin/sh -c "$SHELL_CMD"
fi

# ---- 抢并发槽（最多 2 个）----
mkdir -p "$ROOT/slots"
SLOT=
while [ -z "$SLOT" ]; do
  for s in 1 2; do
    d=$ROOT/slots/slot$s
    if mkdir "$d" 2>/dev/null; then echo $$ > "$d/pid"; echo "$CASE" > "$d/case"; SLOT=$d; break; fi
    p=$(cat "$d/pid" 2>/dev/null)
    if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then rm -rf "$d"; fi   # 占槽的进程已经没了，收回
  done
  [ -n "$SLOT" ] || { [ -n "${WAITED:-}" ] || echo "两个槽都在用，等待中……" >&2; WAITED=1; sleep 15; }
done
trap 'rm -rf "$SLOT"' EXIT

EXTRA=()
DIS="WebFetch,WebSearch,PushNotification,RemoteTrigger,SendMessage,ListAgents${EXTRA_DISALLOWED:+,$EXTRA_DISALLOWED}"
[ "${NET_TOOLS:-0}" = 1 ] || EXTRA=(--disallowedTools "$DIS")
[ -n "${MODEL:-}" ] && EXTRA+=(--model "$MODEL")
LIMIT=$(( ${TIMEOUT_MIN:-120} * 60 ))
printf '%q ' sandbox-exec -f "$RUN/sandbox.sb" "$CLAUDE_BIN" -p --output-format stream-json --verbose \
  --permission-mode bypassPermissions --append-system-prompt-file "$RUN/append-system-prompt.md" \
  ${EXTRA[@]+"${EXTRA[@]}"} > "$RUN/cmdline.txt"; echo >> "$RUN/cmdline.txt"
printf '%s\n' "${ENVV[@]}" > "$RUN/env.txt"

START=$(date '+%Y-%m-%dT%H:%M:%S%z'); T0=$(date +%s)
cd "$WS" || die "进不去 $WS"
env -i "${ENVV[@]}" /usr/bin/sandbox-exec -f "$RUN/sandbox.sb" "$CLAUDE_BIN" -p --output-format stream-json --verbose \
  --permission-mode bypassPermissions --append-system-prompt-file "$RUN/append-system-prompt.md" \
  ${EXTRA[@]+"${EXTRA[@]}"} < "$RUN/prompt_full.txt" > "$CASE/out.jsonl" 2> "$CASE/err.txt" &
CPID=$!
( t=0; while kill -0 $CPID 2>/dev/null; do sleep 5; t=$((t+5));
    if [ $t -ge $LIMIT ]; then : > "$RUN/timeout"; kill -TERM $CPID 2>/dev/null; break; fi; done ) &
wait $CPID; RC=$?
END=$(date '+%Y-%m-%dT%H:%M:%S%z'); T1=$(date +%s)

# ---- 收尾：done.txt（退出码、起止时间、会话号、花费）----
python3 -I "$H/finish.py" "$CASE" "$RC" "$START" "$END" $((T1-T0))
return $RC
}
main "$@"
exit $?
