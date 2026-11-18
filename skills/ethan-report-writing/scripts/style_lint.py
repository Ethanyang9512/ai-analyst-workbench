# -*- coding: utf-8 -*-
"""语体 lint —— 交付前必跑。

用法: python3 style_lint.py 稿件.md [稿件2.xml ...]
硬禁词从技能目录 references/style-lexicon.md 的「硬禁」表解析（脚本同目录另有一份时用同目录那份），台账追加即生效。
禁用列写法: 「A / B」「A／B」＝几个禁词分别匹配（所以本身带斜杠的词写不进这一列）；
  省略号「…」「……」「...」＝中间可夹 0–MAX_GAP 个字（空格算字，不跨标点和表格竖线）；
  「X」＝一个数，阿拉伯或中文数字（如「第X章」拦「第3章」「第十二章」；UX 这类英文词里的 X 照字面）。
退出码: 有硬禁命中=1，否则=0（警告不拦）。
另外三处：
  “其实”后面紧跟某几个字、其实是“其”加另一个词时不算（见 NOT_FOLLOWED：其实现目标、其实际损失、其实施细则）；
  一行超过 LONG_LINE 个字时（整篇只有一行的飞书回读稿、很长的段落都算）每一处命中都报，位置写成“L1 第 N 字”，
  上下文取命中处前后；不到这么长的行照旧每条规则只报第一处。
  分析文档的开头字数：文档标题后面的第一处标题是“结论、核心结论、摘要、总结”这类时（“一、结论与建议”
  “1. 结论与建议”“## 摘要”都认；“摘要耗时拆解”“总结报告”这类不认），从文档标题下面量到第一张图、第一张表或第二章标题之前
  有多少字（不算空白和标记；结论章之前的前言算进去，前言里就有图表时量到那张图表为止；结论章里的小标题不停），超过上限就按
  硬禁报。结论章不是第一处标题的稿子不查（方法论末尾的“总结”、某一章里的“结论”小节、项目日志）。上限从 SKILL.md
  里“第一张图或表之前不超过 N 字”读（脚本同目录有 SKILL.md 就读它，否则读上一级技能目录的），读不到用 OPENING_DEFAULT。
  飞书的纯文本回读稿（每行以 [h1 …] 开头的那种）认不出图和表，不要拿它跑这项检查。
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


def default_skill():
    """SKILL.md 位置（读开头字数上限用）：脚本同目录有就用它，否则用上一级技能目录的 SKILL.md。"""
    same = os.path.join(HERE, "SKILL.md")
    return same if os.path.exists(same) else os.path.join(HERE, os.pardir, "SKILL.md")

SEP = re.compile(r"\s*[/／]\s*")                    # 一格里分隔几个禁词
ELLIPSIS = re.compile(r"…+|\.{3,}")                # 省略号：中间可夹字
MAX_GAP = 6                                         # 省略号处最多夹几个字
GAP = r"[^，。；：！？、,.;:!?|\n]{0,%d}" % MAX_GAP
NUM_X = re.compile(r"(?<![A-Za-z])X+(?![A-Za-z])")  # 占位 X：一个数
NUM = r"[ \t]*[0-9０-９零〇一二三四五六七八九十百千]+[ \t]*"
# 禁词后面紧跟这几个字时是另一个词，不算命中。除外写在这里，不写进台账。
#   其实：“其实际、其实施、其实现”是“其”加“实际、实施、实现”；后面再跟“上、工、在、金、货……”时是“其实”加另一个词
#   （其实际上、其实施工方、其实现在、其实现金流），照拦。只排除了表里这些字，没列到的搭配会少报一次。
#   “几成”（三成、九成）不加除外：“流失九成员工”这种是真的比例，按“成本、成员”除外会漏。
NOT_FOLLOWED = {"其实": "际(?!上)|施(?!工)|现(?!在|实|有|阶段|场|行|状|金|货|成|今|存|象|代|时|任|价|值|况)"}
LONG_LINE = 300                                     # 一行超过这么多字：每一处命中都报
OPENING_DEFAULT = 350                               # 开头字数上限：SKILL.md 里读不到时用这个
OPENING_KEY = r"(?:核心结论|结论摘要|结论|摘要|总结)(?=\Z|[与和及先建（(：:、/&—\-\s<])"   # 后面要跟边界（“结论先行”“结论建议”算）：“摘要耗时”“总结报告”不算
OPENING_HEAD = re.compile(                          # 结论章的标题。带数字序号的（1. 结论）只认 # 标题和 <hN>，免得把编号列表当成标题
    r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?一、[ \t]*" + OPENING_KEY + r"[^\n<]*"
    r"|(?:^|\n)[ \t]*#{1,6}[ \t]*(?:[１1][、.．][ \t]*|[一１1][ \t]+)?" + OPENING_KEY + r"[^\n<]*"
    r"|<h[1-6][^>]*>[ \t]*(?:[一１1][、.．\s]?[ \t]*)?" + OPENING_KEY + r"[^<]*(?:</h[1-6]>)?")
OPENING_ANYHEAD = re.compile(r"(?:^|\n)[ \t]*#{1,6}[ \t]*[^#\s][^\n]*|<h[1-6][ >]|(?:^|\n)[ \t]*一、[^\n<]*")   # 任何一处标题
OPENING_FIG = re.compile(r"!\[|<img|<image|<table|<whiteboard|<grid|\n[ \t]*\|")                              # 图或表
OPENING_STOP = re.compile(OPENING_FIG.pattern + r"|\n[ \t]*(?:#{1,6}[ \t]*)?二、")                             # 第一张图、表，或“二、”
OPENING_TITLE = re.compile(r"\A\s*(?:<title>[^<]*</title>|#[ \t]+[^\n]*)")      # 文档标题：不算进开头的字数
OPENING_MARK = re.compile(r"<[^>]+>|[*#`>\-]|\s")    # 量字数时不算的：标签、Markdown 标记、空白


def term_pattern(term):
    """一个禁词写法 → 正则串；只剩占位、没有实字的返回 None（免得每行都命中）。"""
    if not NUM_X.sub("", ELLIPSIS.sub("", term)).strip():
        return None
    chunks = [c.strip() for c in ELLIPSIS.split(term)]
    while not chunks[0]:               # 首尾的省略号不起作用
        chunks.pop(0)
    while not chunks[-1]:
        chunks.pop()
    pat = GAP.join(NUM.join(re.escape(p.strip()) for p in NUM_X.split(c)) for c in chunks)
    return pat + ("(?!%s)" % NOT_FOLLOWED[term] if term in NOT_FOLLOWED else "")


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
    # 「值得注意的是」「仅供参考」已在台账硬禁表里，这里不重复；「原因待××确认」一行写清的不报
    (re.compile(r"把握程度|尚未(?:书面)?确认|需要?业务确认|请业务确认|(?<!原因)待业务确认|这并不是说|并不意味着|需要澄清的是"
                r"|尽管[^。；\n]{0,10}局限|初步尝试|只能提供有限参考"
                r"|现在还不能说|还不能下结论|有待进一步|视[^，。；\n]{1,6}而定|由[^，。；\n]{1,10}(?:再定|再行决定|酌情)"
                r"|可能更[多高大长]，也可能更[少低小短]"),
     "防御性写法：按 SKILL.md「限定、待确认、备选数：只留必要的」判定，删掉不改变读者决定的就删；"
     "“请业务确认”改成“按 X 测算；若为 Y，结果变为 Z”"),
]


def _hits(pat, ln, line):
    """这一行里这条规则的命中 → [(位置, 命中, 上下文)]。不长的行只取第一处，位置是行号，上下文是这一行开头 60 个字；
    很长的行每一处都取，位置写成“行号 第 N 字”，上下文取命中处前后各 20 个字。"""
    if len(line) <= LONG_LINE:
        m = pat.search(line)
        return [(ln, m, line.strip()[:60])] if m else []
    return [("%d 第 %d 字" % (ln, m.start() + 1), m, line[max(0, m.start() - 20):m.end() + 20].strip())
            for m in pat.finditer(line)]


def opening_limit(skill_path=None):
    """开头字数上限：从 SKILL.md 里读“第一张图或表之前不超过 N 字”，读不到用 OPENING_DEFAULT。"""
    try:
        with io.open(skill_path or default_skill(), encoding="utf-8") as f:
            text = f.read()
    except (IOError, OSError):
        return OPENING_DEFAULT
    m = re.search(r"第一张图或表之前不超过\s*(\d+)\s*字", text)
    return int(m.group(1)) if m else OPENING_DEFAULT


def opening_length(text):
    """文档标题后面的第一处标题是结论、摘要这类时，返回 (这处标题所在的行号, 开头的字数)；不是返回 None。
    开头＝文档标题下面到第一张图、第一张表或下一章标题之前：结论章前面的前言算（前言里就有图表时量到那张图表为止），
    结论章的标题不算，标记和空白不算。下一章＝“二、”，或者和结论章同级、更高一级的标题；结论章里更低一级的小标题不停。
    结论章不在最前面的稿子不查：方法论末尾的“总结”、某一章里的“结论”小节，都不是开头。"""
    first = OPENING_ANYHEAD.search(text)
    if not first:
        return None
    title = OPENING_TITLE.match(text)
    m = OPENING_HEAD.match(text, first.start())
    start = title.end() if title and title.end() <= first.start() else 0     # <title> 写的文档标题
    if not m and title and title.end() == first.end():                       # 第一处标题就是文档标题（第一行的 # 标题）：看它后面那一处
        second = OPENING_ANYHEAD.search(text, first.end())
        m = OPENING_HEAD.match(text, second.start()) if second else None
        if m and re.match(r"\n[ \t]*#[ \t]*[^#\s一１1]", m.group(0)):        # 和文档标题同是一级、又没有序号：分不清谁是第一章，不查
            return None
        start = title.end()
    if not m:
        return None
    head = m.group(0).lstrip("\n")
    line = text.count("\n", 0, m.end()) - head.count("\n") + 1
    fig = OPENING_FIG.search(text, start, m.start())
    if fig:                                                                  # 前言里就有图或表：量到那里
        return line, len(OPENING_MARK.sub("", text[start:fig.start()]))
    ends = [x.start() for x in [OPENING_STOP.search(text, m.end())] if x]
    level = len(head.lstrip(" \t")) - len(head.lstrip(" \t").lstrip("#"))      # Markdown 标题的级别；不是 # 标题时为 0
    if level:
        nxt = re.compile(r"\n[ \t]*#{1,%d}[ \t]+\S" % level).search(text, m.end())
        if nxt:
            ends.append(nxt.start())
    tag = re.match(r"<h([1-6])", head)
    if tag:
        nxt = re.compile(r"<h[1-%s][ >]" % tag.group(1)).search(text, m.end())
        if nxt:
            ends.append(nxt.start())
    body = text[start:m.start()] + text[m.end():min(ends) if ends else len(text)]
    return line, len(OPENING_MARK.sub("", body))


def lint_file(path, banned):
    hard, warn = [], []
    for ln, line in enumerate(io.open(path, encoding="utf-8"), 1):
        for _term, fix, pat in banned:
            hard += [(where, m.group(0), fix, ctx) for where, m, ctx in _hits(pat, ln, line)]
        for pat, msg in HEURISTICS:
            warn += [(where, m.group(0)[:30], msg) for where, m, _ctx in _hits(pat, ln, line)]
    with io.open(path, encoding="utf-8") as f:
        opening = opening_length(f.read())
    limit = opening_limit()
    if opening and opening[1] > limit:
        hard.append((opening[0], "开头 %d 字" % opening[1],
                     "标题下到第一张图或表之前不超过 %d 字：只留一句话结论和 2–4 条要点，背景不写，"
                     "口径、数据来源、适用范围改成图下的灰色小字注释" % limit,
                     "第一章（结论、摘要）"))
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
