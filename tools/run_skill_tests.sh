#!/usr/bin/env bash
# 一次跑完 skills/ 下全部检查程序的测试。用法：bash tools/run_skill_tests.sh
# 可选：AAW_PY=<装了 PyMuPDF、python-pptx 的解释器>，用来跑 deckcheck 的 PDF 组和 check_deck；
#       PULP_PY=<装了 PuLP、OR-Tools 的解释器>，用来跑 ethan-optimization-modeling 的两个例子。
# 不设就用 python3；缺依赖的组会显示“跳过”，不算失败。
set -u
export PYTHONDONTWRITEBYTECODE=1   # 不在仓库里留 __pycache__
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python3}"
XPY="${AAW_PY:-$PY}"
OPY="${PULP_PY:-$PY}"
fail=0

run() {  # run <技能目录> <解释器> <命令…>
  local dir="$1" py="$2"; shift 2
  printf '\n== %s: %s\n' "$dir" "$*"
  if (cd "$ROOT/skills/$dir" && "$py" "$@"); then echo "   通过"; else echo "   失败"; fail=1; fi
}
skip() { printf '\n== %s\n   跳过（%s）\n' "$1" "$2"; }

run ethan-report-writing      "$PY"  tests/test_style_lint.py
run ethan-report-writing      "$PY"  tests/test_trace_scan.py
if "$PY" -c "import fcntl" 2>/dev/null; then
  run ethan-report-writing    "$PY"  tests/test_pairsnap.py
else
  skip "ethan-report-writing: tests/test_pairsnap.py" "这个系统没有 fcntl，pairsnap 只能在 macOS / Linux / WSL 上跑"
fi
if "$PY" -c "import matplotlib" 2>/dev/null; then
  run ethan-report-writing    "$PY"  tests/test_figcheck.py
else
  skip "ethan-report-writing: tests/test_figcheck.py" "$PY 没有 matplotlib"
fi
run ethan-report-writing      "$XPY" tests/test_deckcheck.py
run ethan-data-package-review "$PY"  tests/test_pkgcheck.py
if "$XPY" -c "import pptx" 2>/dev/null; then
  run ethan-slide-deck        "$XPY" tests/test_check_deck.py
else
  skip "ethan-slide-deck: tests/test_check_deck.py" "$XPY 没有 python-pptx"
fi
if "$OPY" -c "import pulp, ortools" 2>/dev/null; then
  run ethan-optimization-modeling "$OPY" examples/allocation_pulp.py
  run ethan-optimization-modeling "$OPY" examples/shift_cpsat.py
else
  skip "ethan-optimization-modeling: examples" "$OPY 没有 pulp / ortools；pip install -r skills/ethan-optimization-modeling/requirements.txt"
fi

echo
if [ "$fail" -eq 0 ]; then echo "技能测试全部通过（跳过的组见上）"; else echo "技能测试有失败，见上"; fi
exit "$fail"
