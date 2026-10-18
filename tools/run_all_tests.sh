#!/usr/bin/env bash
# 一次跑完整个仓库的测试：仓库自查、skills/ 的检查程序、runtime/ 的钩子和工具、两个示例的重算脚本。
# 用法：bash tools/run_all_tests.sh
# 可选环境变量和 run_skill_tests.sh 相同：AAW_PY、PULP_PY。runtime 的测试只用标准库，用 python3 跑。
# 所有测试都在临时目录里现造夹具，不碰你真实的工作区、知识库和 ~/.claude。
set -u
export PYTHONDONTWRITEBYTECODE=1   # 不在仓库里留 __pycache__
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python3}"
fail=0

step() {  # step <名字> <命令…>，在仓库根目录跑
  local name="$1"; shift
  printf '\n== %s\n' "$name"
  if (cd "$ROOT" && "$@"); then echo "   通过"; else echo "   失败"; fail=1; fi
}

step "仓库自查 tools/check_repo.py" "$PY" tools/check_repo.py
bash "$ROOT/tools/run_skill_tests.sh" || fail=1

for t in runtime/hooks/test_guard.py runtime/hooks/test_gate.py runtime/hooks/test_remind.py \
         runtime/hooks/test_progress.py runtime/tools/test_accept_record.py runtime/test_status_preview.py; do
  step "$t" "$PY" "$t"
done

step "示例：续费率下滑归因的重算脚本" "$PY" "examples/续费率下滑归因/analysis/recompute.py" --json
step "示例：新手引导改版评估的读数脚本" "$PY" "examples/新手引导改版评估/analysis/readout.py"

echo
if [ "$fail" -eq 0 ]; then echo "全部通过（跳过的组见上）"; else echo "有失败，见上"; fi
exit "$fail"
