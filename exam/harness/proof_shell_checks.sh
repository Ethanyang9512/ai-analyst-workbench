#!/bin/sh
# 沙盒自检（在 run_case.sh --shell 里跑，环境和正式考试一模一样）。只打印“挡住/读到”和字节数，不打印任何文件内容。
# 用法（harness 目录在沙盒里读不到，所以从标准输入喂脚本）：
#   run_case.sh <case> --shell "sh -s <答案文件> $(command -v lark-cli) [<别的该挡读的路径> ...]" < proof_shell_checks.sh | cat
#   <答案文件>：这道题的用户定稿（考生绝不能读到的那份）；后面再列真 lark-cli、考卷来源目录、桥的配置文件等。
#   （沙盒里连真 lark-cli 在不在都探测不到，所以它的路径要从外面传进来。）
# 每次改沙盒规则、换了一台电脑、升级了 Claude Code，正式考试前都先跑一遍：一项 LEAK 都不能有。
A="${1:?第一个参数是答案文件的绝对路径}"; shift
SLUG=$(pwd | sed 's/[^a-zA-Z0-9]/-/g')
PASS=0; FAIL=0
expect_block() {  # 说明 命令 —— 命令应失败且报 Operation not permitted / PermissionError（node 读不到文件时报 Cannot find module）
  out=$(sh -c "$2" 2>&1); rc=$?
  if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q -E 'Operation not permitted|PermissionError|EPERM|Cannot find module'; then
    PASS=$((PASS+1)); printf 'BLOCKED  %-44s | %s\n' "$1" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)"
  else
    FAIL=$((FAIL+1)); printf '!!LEAK!! %-44s | rc=%s %s\n' "$1" "$rc" "$(printf '%s' "$out" | wc -c | tr -d ' ') bytes of output"
  fi
}
expect_ok() {  # 说明 命令 —— 命令应成功
  out=$(sh -c "$2" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then PASS=$((PASS+1)); printf 'OK       %-44s | %s\n' "$1" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)"
  else FAIL=$((FAIL+1)); printf '!!FAIL!! %-44s | rc=%s %s\n' "$1" "$rc" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)"; fi
}

echo "== 1. 四种读法读答案（应全部挡住）"
expect_block "Bash cat 答案"                 "cat \"$A\" > /dev/null"
expect_block "python open() 答案"            "python3 -c 'import sys; open(sys.argv[1]).read()' \"$A\""
expect_block "ls -la 答案文件"               "ls -la \"$A\""
expect_block "ls 答案所在目录"               "ls \"$(dirname "$A")\""

echo "== 2. PATH 里的 lark-cli 是假的（真 lark-cli 的路径作为额外参数传进来，在第 3 段检查挡读）"
expect_ok    "PATH 里的 lark-cli 是假的"      "lark-cli docs +fetch --doc x | grep -q 'fake lark-cli' && echo fake"

echo "== 3. 其他该挡的地方（应全部挡住）"
for p in "$@"; do
  expect_block "挡读 $p" "ls \"$p\" > /dev/null 2>&1 || cat \"$p\" > /dev/null"
done
J=""
for T in $(ls -1 "$HOME/.claude/projects" 2>/dev/null | grep -v -- "$SLUG"); do   # 只列目录名（不 stat 文件），找一份别的会话记录
  N=$(ls -1 "$HOME/.claude/projects/$T" 2>/dev/null | grep '\.jsonl$' | head -1)
  [ -n "$N" ] && { J="$HOME/.claude/projects/$T/$N"; break; }
done
if [ -n "$J" ]; then expect_block "别的会话的记录 *.jsonl" "cat \"$J\" > /dev/null"; else echo "SKIP     没找到别的会话记录"; fi
[ -f "$HOME/.claude/history.jsonl" ] && expect_block "~/.claude/history.jsonl" "cat \"$HOME/.claude/history.jsonl\" > /dev/null"
expect_block "考场根目录（别的考题）"          "ls \"$(dirname "$(dirname "$PWD")")\""

echo "== 4. 线上文件不许写（应全部挡住；万一写成会立刻删掉并标 LEAK）"
for d in "$HOME/.claude/skills" "$HOME/.claude/agents" "$HOME/Documents" "$AAW_RUNTIME/hooks"; do
  [ -d "$d" ] || continue
  expect_block "写 $d" "touch \"$d/.sbx_write_probe\" || exit 1; rm -f \"$d/.sbx_write_probe\"; echo WROTE; exit 0"
done

echo "== 5. 不许动桥（应挡住；kill -0 只探测不真发信号）"
expect_block "给沙盒外的进程发信号 (kill -0 1)" "kill -0 1"
expect_block "执行 launchctl"                   "/bin/launchctl list"

echo "== 6. 该能用的（应全部成功）"
expect_ok "钩子 run-hook.sh 可读可执行"   "test -x \"$AAW_RUNTIME/hooks/run-hook.sh\" && echo yes"
expect_ok "cd 进钩子目录（run-hook.sh 第一句）" "cd \"$AAW_RUNTIME/hooks\" && pwd"
expect_ok "cd 进假工作区绝对路径"         "cd \"$PWD\" && pwd"
expect_ok "钩子真跑一次（remind）"         "echo '{\"prompt\":\"x\",\"session_id\":\"proofshell\",\"cwd\":\"'\$PWD'\"}' | \"$AAW_RUNTIME/hooks/run-hook.sh\" remind > /dev/null; ls -la \$AAW_HOOK_STATE/.alive-remind"
expect_ok "workflow.md 可读"               "wc -c < \"$AAW_RUNTIME/workflow.md\""
expect_ok "技能目录可读"                   "ls \"$HOME/.claude/skills\" | wc -l"
expect_ok "假工作区可读写"                 "touch ./.sbx_ws_probe && rm ./.sbx_ws_probe && echo rw"
[ -e "$HOME/.claude/projects/$SLUG/memory" ] && expect_ok "共享记忆（经本题软链）可读" "ls \"$HOME/.claude/projects/$SLUG/memory/\" | wc -l"

echo "== 合计：符合预期 $PASS 项，不符合 $FAIL 项"
