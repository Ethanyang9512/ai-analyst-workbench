#!/bin/bash
# 分析助手体检。只读：不改文件、不启停进程、不调用模型、不发消息。按需手动跑，不是自动告警。
# 用法：bash doctor.sh
# 查五样：Claude CLI 和登录状态、代理端口（给了 AAW_PROXY_PORT 才查）、各工作区设置是否一致、
#         钩子是否齐全并真的在跑（含全部自测）、桥进程在不在（给了 AAW_BRIDGE_PGREP 才查）。
set -uo pipefail
export LC_ALL=C  # 系统自带 bash 3.2 在 UTF-8 终端里会把 "$变量：" 后面的全角字符并进变量名，报 unbound variable

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RT="${AAW_RUNTIME:-$SELF_DIR}"
HOOKS="$RT/hooks"
STATE="${AAW_HOOK_STATE:-$HOOKS}"
PY=/usr/bin/python3; [ -x "$PY" ] || PY="$(command -v python3 || true)"

case "${1:-}" in
  -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
  "") ;;
  *) echo "不认识的参数：${1}（--help 看用法）"; exit 64 ;;
esac

SERIOUS=0; ATTN=0
say()     { printf '%s\n' "$*"; }
ok()      { printf '  %s\n' "$*"; }
serious() { printf '  [严重] %s\n' "$*"; SERIOUS=$((SERIOUS + 1)); }
attn()    { printf '  [关注] %s\n' "$*"; ATTN=$((ATTN + 1)); }

say "== 分析助手体检（$(date '+%F %T')，只读）=="
say "runtime 目录：$RT"

say ""
say "1. Python 与 Claude CLI"
if [ -n "$PY" ]; then ok "python3：$PY（$("$PY" -c 'import sys;print("%d.%d" % sys.version_info[:2])')）"; else
  serious "找不到 python3：钩子会全部静默放行"; fi
if CLAUDE_BIN="$(command -v claude)"; then
  ok "claude：$CLAUDE_BIN（$(claude --version 2>/dev/null | head -1)）"
  if [ -n "$PY" ]; then
    LOGGED=$(claude auth status --json 2>/dev/null | "$PY" -c 'import sys,json
try: print("yes" if json.load(sys.stdin).get("loggedIn") else "no")
except Exception: print("unknown")' 2>/dev/null)
    case "$LOGGED" in
      yes) ok "已登录" ;;
      no) serious "Claude CLI 没有登录，分析助手每条消息都会失败" ;;
      *) attn "看不出登录状态（这个版本的 claude 可能不支持 auth status --json），请手动确认" ;;
    esac
  fi
else
  serious "PATH 里找不到 claude（桥启动模型要用它）"
fi

say ""
say "2. 代理"
if [ -n "${AAW_PROXY_PORT:-}" ]; then
  if lsof -nP -iTCP:"$AAW_PROXY_PORT" -sTCP:LISTEN >/dev/null 2>&1; then ok "端口 $AAW_PROXY_PORT 在监听"; else
    serious "端口 $AAW_PROXY_PORT 没在监听，模型请求可能出不去"; fi
else
  ok "没设 AAW_PROXY_PORT，跳过（不走代理就不用管）"
fi

say ""
say "3. 工作区设置"
WS_TOOL="$RT/workspace_settings.py"
if [ ! -f "$WS_TOOL" ]; then
  attn "缺 workspace_settings.py，无法核对各工作区设置"
elif WS_OUT=$("$PY" "$WS_TOOL" check 2>&1); then
  ok "各工作区设置一致（关后台运行、推理强度、钩子登记、写入门槛）"
else
  attn "有工作区的设置与预期不一致，或还没有工作区（重新写入：python3 ${WS_TOOL} apply --all）"
  printf '%s\n' "$WS_OUT" | grep -v "\] 一致 " | sed 's/^/      /' || true
fi

say ""
say "4. 钩子"
if [ -e "$HOOKS/DISABLED" ]; then
  attn "钩子总开关处于关闭状态（${HOOKS}/DISABLED 存在），护栏等钩子都不生效"
elif [ ! -x "$HOOKS/run-hook.sh" ]; then
  attn "钩子入口 run-hook.sh 不存在或不可执行，护栏等钩子都不生效（不影响分析助手正常回复）"
else
  MISSING=""
  for h in guard remind gate progress progress_stop cmdparse; do [ -f "$HOOKS/$h.py" ] || MISSING="$MISSING $h"; done
  if [ -n "$MISSING" ]; then attn "钩子脚本缺失：${MISSING}"; else ok "钩子入口和脚本就位"; fi
  # run-hook.sh 每次真的启动钩子前会刷新 .alive-<名字>，据此看钩子是不是真的在跑；在下面跑自测之前读
  ALIVE=""
  for h in guard remind gate progress progress_stop; do
    M=$(stat -f %m "$STATE/.alive-$h" 2>/dev/null || stat -c %Y "$STATE/.alive-$h" 2>/dev/null || true)
    if [ -n "$M" ]; then ALIVE="${ALIVE}、${h} $(( ($(date +%s) - M) / 60 )) 分钟前"; else ALIVE="${ALIVE}、${h} 没有记录"; fi
  done
  ok "各钩子最近一次触发：${ALIVE#、}（全是“没有记录”多半是桥没带上 LARK_CHANNEL_PROFILE=${AAW_PROFILE:-aaw}）"
  FAILED=""
  for t in "$HOOKS/test_guard.py" "$HOOKS/test_remind.py" "$HOOKS/test_gate.py" "$HOOKS/test_progress.py" \
           "$RT/tools/test_accept_record.py" "$RT/test_status_preview.py"; do
    [ -f "$t" ] || continue
    ( cd "$(dirname "$t")" && env -u AAW_HOOK_STATE -u AAW_WS_BASE "$PY" "$t" >/dev/null 2>&1 ) || FAILED="$FAILED $(basename "$t" .py)"
  done
  if [ -n "$FAILED" ]; then
    attn "自测没通过：${FAILED}（看详情：python3 <对应的 test_*.py>）"
  else
    ok "自测通过（护栏、每轮提醒、验收门、进度卡、验收记录、状态预览）"
  fi
  if [ -e "$STATE/GATE_ENFORCE" ]; then ok "验收门：强制模式"; else ok "验收门：提醒模式（只提醒，不拦）"; fi
  HLOG="$STATE/hook.log"
  count() { if [ -f "$HLOG" ]; then grep -c "$1" "$HLOG" 2>/dev/null || true; else echo 0; fi; }
  say "  钩子日志累计：验收门拦下 $(count '"decision": "deny"') 次、写明理由跳过 $(count '"decision": "skip"') 次；护栏拦下 $(count '"hook": "guard"') 次"
  GERR=$(count '"decision": "error"')
  if [ "${GERR:-0}" -gt 0 ]; then attn "验收门自己出错 ${GERR} 次（出错时按放行处理；看 ${HLOG} 里 decision 为 error 的行）"; fi
fi
for f in workflow.md status_preview.py; do
  if [ -f "$RT/$f" ]; then ok "有 $f"; else
    serious "缺少 $RT/${f}（workflow.md 缺了规则不注入；status_preview.py 缺了新会话接不上 _status.md 的进度）"; fi
done

say ""
say "5. 桥进程"
if [ -n "${AAW_BRIDGE_PGREP:-}" ]; then
  N=$(pgrep -f "$AAW_BRIDGE_PGREP" 2>/dev/null | wc -l | tr -d ' ')
  case "$N" in
    0) serious "没找到桥进程（pgrep -f ${AAW_BRIDGE_PGREP}），分析助手不在线" ;;
    1) ok "桥进程在运行" ;;
    *) attn "找到 $N 个匹配的进程（同一个机器人起了多个桥会重复回复；也可能只是关键词太宽）" ;;
  esac
else
  ok "没设 AAW_BRIDGE_PGREP，跳过"
fi

say ""
if [ "$SERIOUS" -gt 0 ]; then
  say "结论：有 $SERIOUS 处严重问题（上面标 [严重] 的），需要先处理。"
elif [ "$ATTN" -gt 0 ]; then
  say "结论：可以用，但有需要关注的地方（上面标 [关注] 的）。"
else
  say "结论：一切正常。"
fi
