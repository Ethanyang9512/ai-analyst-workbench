# -*- coding: utf-8 -*-
"""语体 lint —— 交付前必跑。

用法: python3 style_lint.py 稿件.md [稿件2.xml ...]
硬禁词从技能目录 references/style-lexicon.md 的「硬禁」表解析（脚本同目录另有一份时用同目录那份），台账追加即生效。
禁用列写法: 「A / B」「A／B」＝几个禁词分别匹配（所以本身带斜杠的词写不进这一列）；
  省略号「…」「……」「...」＝中间可夹 0–MAX_GAP 个字（空格算字，不跨标点和表格竖线）；
  「X」＝一个数，阿拉伯或中文数字（如「第X章」拦「第3章」「第十二章」；UX 这类英文词里的 X 照字面）。
退出码: 有硬禁命中=1，否则=0（警告不拦）。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def default_lexicon():
    """台账位置：脚本同目录有 style-lexicon.md 就用它，否则用技能目录下的 references/style-lexicon.md。"""
    same = os.path.join(HERE, "style-lexicon.md")
    return same if os.path.exists(same) else os.path.join(HERE, os.pardir, "references", "style-lexicon.md")

SEP = re.compile(r"\s*[/／]\s*")                    # 一格里分隔几个禁词
ELLIPSIS = re.compile(r"…+|\.{3,}")                # 省略号：中间可夹字
MAX_GAP = 6                                         # 省略号处最多夹几个字
GAP = r"[^，。；：！？、,.;:!?|\n]{0,%d}" % MAX_GAP
NUM_X = re.compile(r"(?<![A-Za-z])X+(?![A-Za-z])")  # 占位 X：一个数
NUM = r"[ \t]*[0-9０-９零〇一二三四五六七八九十百千]+[ \t]*"


def term_pattern(term):
    """一个禁词写法 → 正则串；只剩占位、没有实字的返回 None（免得每行都命中）。"""
    if not NUM_X.sub("", ELLIPSIS.sub("", term)).strip():
        return None
    chunks = [c.strip() for c in ELLIPSIS.split(term)]
    while not chunks[0]:               # 首尾的省略号不起作用
        chunks.pop(0)
    while not chunks[-1]:
        chunks.pop()
    return GAP.join(NUM.join(re.escape(p.strip()) for p in NUM_X.split(c)) for c in chunks)


def load_banned(path=None):
    """解析 style-lexicon.md「## 一、硬禁」表的第一列 → [(禁用原文, 改成, 正则)]。"""
    rows, in_hard = [], False
    for line in io.open(path or default_lexicon(), encoding="utf-8"):
        if line.startswith("## "):
            in_hard = "硬禁" in line
            continue
        if in_hard and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[0] != "禁用" \
                    and not set(cells[0]) <= set("-— :"):
                pats = [p for p in map(term_pattern, SEP.split(cells[0])) if p]
                if pats:
                    rows.append((cells[0], cells[1], re.compile("|".join(pats))))
    return rows


HEURISTICS = [
    (re.compile(r"(?:影响值|提升|下降|跌幅|高出|低于|拖累|差距|回落|收窄|扩大)"
                r"[^。；\n%]{0,10}?\d+(?:\.\d+)?%"),
     "核对单位：比率绝对差用 pt，相对变化用 %，金额差用原单位；不要按关键词自动替换"),
    (re.compile(r"\$[^$\n]{1,80}\$"), "LaTeX 源码不能直接粘贴；复杂公式使用飞书 equation 块，简单公式用可读文字"),
    (re.compile(r"(?<!迷)你(?!们)"), "第二人称「你」——业务文档应写角色名"),
]


def lint_file(path, banned):
    hard, warn = [], []
    for ln, line in enumerate(io.open(path, encoding="utf-8"), 1):
        for _term, fix, pat in banned:
            m = pat.search(line)
            if m:
                hard.append((ln, m.group(0), fix, line.strip()[:60]))
        for pat, msg in HEURISTICS:
            m = pat.search(line)
            if m:
                warn.append((ln, m.group(0)[:30], msg))
    return hard, warn


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    banned = load_banned()
    total_hard = 0
    for path in sys.argv[1:]:
        hard, warn = lint_file(path, banned)
        total_hard += len(hard)
        print(f"== {path}  硬禁 {len(hard)} / 警告 {len(warn)} ==")
        for ln, term, fix, ctx in hard:
            print(f"  [硬禁] L{ln} 「{term}」→ {fix}   | {ctx}")
        for ln, frag, msg in warn:
            print(f"  [警告] L{ln} 「{frag}」 {msg}")
    sys.exit(1 if total_hard else 0)


if __name__ == "__main__":
    main()
