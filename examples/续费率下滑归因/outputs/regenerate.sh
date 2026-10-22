#!/usr/bin/env bash
# 重新生成本目录里的全部输出：每个文件都是对应程序真实跑出来的结果（本例数字均为虚构）。
# 用法（在仓库根目录）：bash examples/续费率下滑归因/outputs/regenerate.sh
# 只用 Python 标准库；所有中间文件都放在临时目录，跑完删掉，不碰你的工作区和 ~/.claude。
set -u
export PYTHONDONTWRITEBYTECODE=1
OUT="$(cd "$(dirname "$0")" && pwd)"
EX="$(dirname "$OUT")"
ROOT="$(cd "$EX/../.." && pwd)"
RW="$ROOT/skills/ethan-report-writing/scripts"
DP="$ROOT/skills/ethan-data-package-review/scripts"
RT="$ROOT/runtime"
PY="${PY:-python3}"
T="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$T"' EXIT
cd "$ROOT"

run() {  # run <输出文件> <说明> <命令…>：把命令行、输出和退出码一起记下来
  local f="$1" what="$2"; shift 2
  { echo "# $what"; echo "\$ $*"; "$@" 2>&1; echo "（退出码 $?）"; } > "$OUT/$f"
}

# 1. 写作检查：交付版（exam/example-paper/delivered.md）里的硬禁词和内部痕迹
run 01_style_lint.txt "硬禁词检查：交付版里 4 处" \
    "$PY" "$RW/style_lint.py" exam/example-paper/delivered.md
run 02_trace_scan.txt "内部痕迹检查：交付版末尾那句提到了协作方和回包" \
    "$PY" "$RW/trace_scan.py" exam/example-paper/delivered.md
run 03_deckcheck_text.txt "按本项目约定页查：禁用词、同一个东西几种写法" \
    "$PY" "$RW/deckcheck.py" text exam/example-paper/delivered.md --conv "$EX/_CONVENTIONS.md"

# 2. 审包体检：第 2 轮说明里写“已修复”，数据文件却一个字节没变
mkdir -p "$T/round1" "$T/round2"
cp "$EX/data/weekly_by_segment.csv" "$T/round1/到期订阅汇总.csv"
cp "$EX/data/weekly_by_segment.csv" "$T/round2/到期订阅汇总.csv"
printf '# 说明\n第 1 轮交付。\n' > "$T/round1/说明.md"
printf '# 说明\nR1-01 已修复：核对值改成按本地时间切周，已重跑。\n' > "$T/round2/说明.md"
( cd "$T" && run 04_pkgcheck_说改了没重跑.txt "数据包体检：说明里写已修复，数据文件指纹没变（退出码 3）" \
    "$PY" "$DP/pkgcheck.py" round2 --prev round1 )

# 3. 验收门：没有验收记录就发 PDF（强制模式）→ 拦下；写了记录再发 → 放行
WSB="$T/workspaces"; WS="$WSB/renewal-analysis"; ST="$T/hook-state"
mkdir -p "$WS" "$ST"; touch "$ST/GATE_ENFORCE"
printf '%%PDF-1.4 本例为虚构的报告文件\n' > "$WS/报告_v1.pdf"
gate() {
  printf '{"tool_name":"Bash","tool_input":{"command":"lark-cli im +messages-send --as bot --chat-id oc_demo --file 报告_v1.pdf"},"cwd":"%s","session_id":"demo"}' "$WS" |
    LARK_CHANNEL_PROFILE=aaw AAW_PROFILE=aaw AAW_WS_BASE="$WSB" AAW_HOOK_STATE="$ST" "$RT/hooks/run-hook.sh" gate
}
{ echo "# 验收门（强制模式）：报告_v1.pdf 没有验收记录时，钩子输出的拦截说明（原文是一段 JSON，这里取出说明文字）"
  gate | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["hookSpecificOutput"]; print("决定：" + o["permissionDecision"]); print(o["permissionDecisionReason"])'
} > "$OUT/05_gate_拦下.txt"
( cd "$WS" && AAW_WS_BASE="$WSB" "$PY" "$RT/tools/accept_record.py" write --file 报告_v1.pdf --tier full --pages "全稿" \
    --reader "冷读通过，补了“首次续费”的首次解释" --visual "4 张图看过，核了 12 个数，无必须改" > /dev/null )
{ echo "# 验收记录（_acceptance/records.jsonl 里的一行；ts、epoch 是生成时的时间）"; cat "$WS/_acceptance/records.jsonl"; } > "$OUT/06_验收记录.txt"
{ echo "# 写了验收记录之后再发：验收门不输出任何东西，就是放行"; out="$(gate)"; echo "输出：${out:-（空）}"; } > "$OUT/07_gate_放行.txt"

# 4. 进度卡：用 card.py 的 build() 渲染一张进行中的卡（不发送，只打印卡片上的文字）
"$PY" - "$RT/bin/card.py" > "$OUT/08_进度卡.txt" <<'PYEOF'
import ast, sys, time, types
# card.py 在模块顶层就按命令行执行子命令，不能直接 import；这里只取出 build() 和它用到的函数、常量
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ("build", "elapsed"))
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("TICK", "MAX_MIN") for t in n.targets))]
card = types.SimpleNamespace(); ns = {"time": time}
exec(compile(ast.Module(body=keep, type_ignores=[]), "card.py", "exec"), ns); card.build = ns["build"]
d = {"t0": time.time() - 312, "name": "续费率报告", "cur": 3, "msg": "我的理解：查续费率 W6 起下降的原因，不分析新购，不做 PPT",
     "steps": ["开题", "审数据包", "定骨架", "写报告", "验收", "发文件"],
     "act": "按方案和首次/多次续费拆续费率", "act_ts": time.time() - 15}
c = card.build(d)
print("# 进度卡（card.py 的 build() 渲染结果；飞书里显示为一张卡片，这里只打印文字）")
print(c["header"]["title"]["content"])
for e in c["elements"]:
    if e["tag"] == "div": print(e["text"]["content"])
    elif e["tag"] == "hr": print("────────")
    elif e["tag"] == "note": print(e["elements"][0]["content"])
PYEOF

# 5. 报告里的数：重算脚本
run 09_recompute.txt "报告里的每个数，由 analysis/recompute.py 从 data/ 重算" "$PY" "$EX/analysis/recompute.py"

# 去掉输出里的临时目录路径，免得每次生成的结果都不一样
for f in "$OUT"/*.txt; do
  "$PY" - "$f" "$T" "$ROOT" <<'PYEOF'
import sys
p, tmp, root = sys.argv[1:4]
s = open(p, encoding="utf-8").read().replace(tmp, "<临时目录>").replace(root + "/", "").replace(root, ".")
open(p, "w", encoding="utf-8").write(s)
PYEOF
done
echo "已生成：$(ls "$OUT" | grep -c '\.txt$') 个输出文件 → $OUT"
