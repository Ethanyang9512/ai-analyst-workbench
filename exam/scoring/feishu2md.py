#!/usr/bin/env python3
"""把飞书文档快照（XML / docs +fetch 的 JSON / 飞书导出的 md）统一转成可比对的纯文本 markdown。

用法：python3 feishu2md.py <源文件> <输出.md>

规则（两边用同一套，diff 才干净）：
- 去掉块 id、图片 token、飞书自动补的图片 alt 描述；图片一律写成一行 [图片]，画板写成 [画板]
- <b> → **，相邻加粗段（</b><b>）先合并；<em> → *
- h1/h2/h3 → # / ## / ###；<hr/> → ---；有序/无序列表 → "1. " / "- "（嵌套缩进两格）
- 表格逐行输出 | a | b |，表头后加分隔行；单元格内多段用 <br> 连接
- md 源只做空白规范化（去行尾空格、压缩连续空行）
"""
import json
import re
import sys
from html.parser import HTMLParser


class Conv(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []          # 输出块（每块一行或多行）
        self.inline = []         # 当前块的行内文本
        self.lists = []          # 栈：[类型, 计数]
        self.table = None        # 当前表格：行列表
        self.row = None
        self.cell = None         # 当前单元格的段落列表
        self.cell_inline = None
        self.block_tag = None
        self.title = None
        self.in_title = False
        self.heading = None

    # ---- 工具 ----
    def _target(self):
        return self.cell_inline if self.cell is not None else self.inline

    def _flush_block(self, prefix=None):
        text = "".join(self.inline)
        text = _clean_inline(text)
        if text.strip():
            if prefix is None:
                if getattr(self, "pending", None):
                    prefix = self.pending
                    self.pending = None
                elif self.lists:
                    prefix = "  " * len(self.lists)
                else:
                    prefix = ""
            self.lines.append(prefix + text.strip())
        self.inline = []

    def _flush_cell_para(self):
        if self.cell is None:
            return
        t = _clean_inline("".join(self.cell_inline)).strip()
        if t:
            self.cell.append(t)
        self.cell_inline = []

    # ---- 解析 ----
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
            self.inline = []
            return
        if tag == "table":
            self._flush_block()
            self.table = []
            return
        if self.table is not None:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th"):
                self.cell = []
                self.cell_inline = []
                self.cell_is_th = tag == "th"
            elif tag == "p":
                self._flush_cell_para()
            elif tag == "img":
                self._flush_cell_para()
                self.cell.append("[图片]")
            elif tag == "whiteboard":
                self._flush_cell_para()
                self.cell.append("[画板]")
            elif tag == "b":
                self.cell_inline.append("\x01")
            elif tag == "em":
                self.cell_inline.append("\x03")
            elif tag == "br":
                self.cell_inline.append("<br>")
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_block()
            self.heading = int(tag[1])
        elif tag == "p":
            self._flush_block()
        elif tag in ("ol", "ul"):
            self._flush_block()
            self.lists.append([tag, 0])
        elif tag == "li":
            self._flush_block()
            if self.lists:
                self.lists[-1][1] += 1
                kind, n = self.lists[-1]
                self.pending = "  " * (len(self.lists) - 1) + (f"{n}. " if kind == "ol" else "- ")
        elif tag == "hr":
            self._flush_block()
            self.lines.append("---")
        elif tag == "img":
            self._flush_block()
            self.lines.append("[图片]")
        elif tag == "whiteboard":
            self._flush_block()
            self.lines.append("[画板]")
        elif tag == "b":
            self.inline.append("\x01")
        elif tag == "em":
            self.inline.append("\x03")
        elif tag == "br":
            self.inline.append("\n")
        elif tag in ("blockquote", "callout"):
            self._flush_block()
            self.quote = True
        elif tag in ("pre", "code"):
            pass

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("img", "whiteboard", "hr", "br", "col"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self.title = _clean_inline("".join(self.inline)).strip()
            self.inline = []
            self.in_title = False
            return
        if self.table is not None:
            if tag in ("td", "th"):
                self._flush_cell_para()
                self.row.append(("<br>".join(self.cell), getattr(self, "cell_is_th", False)))
                self.cell = None
                self.cell_inline = None
            elif tag == "tr":
                self.table.append(self.row)
                self.row = None
            elif tag == "table":
                self._emit_table()
                self.table = None
            elif tag == "b":
                self.cell_inline.append("\x02")
            elif tag == "em":
                self.cell_inline.append("\x04")
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_block("#" * self.heading + " ")
            self.heading = None
        elif tag == "p":
            self._flush_block()
        elif tag == "li":
            self._flush_block()
            self.pending = None
        elif tag in ("ol", "ul"):
            self._flush_block()
            if self.lists:
                self.lists.pop()
        elif tag == "b":
            self.inline.append("\x02")
        elif tag == "em":
            self.inline.append("\x04")

    def handle_data(self, data):
        if self.table is not None and self.cell is not None:
            self.cell_inline.append(data)
        elif self.table is not None:
            pass
        else:
            self.inline.append(data)

    def _emit_table(self):
        rows = [r for r in self.table if r]
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        out = []
        for i, r in enumerate(rows):
            cells = [c for c, _ in r] + [""] * (ncol - len(r))
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
            if i == 0:
                out.append("|" + "---|" * ncol)
        self.lines.extend(out)


def _clean_inline(t):
    t = re.sub(r"\[\[IMG:[A-Za-z0-9_]+\]\]", "[图片]", t)
    # 合并相邻加粗、去空加粗
    t = re.sub("\x02(\\s*)\x01", r"\1", t)
    t = re.sub("\x04(\\s*)\x03", r"\1", t)
    t = re.sub("\x01(\\s*)\x02", r"\1", t)
    t = re.sub("\x03(\\s*)\x04", r"\1", t)
    t = t.replace("\x01", "**").replace("\x02", "**").replace("\x03", "*").replace("\x04", "*")
    t = t.replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def xml_to_md(xml):
    c = Conv()
    c.feed(xml)
    c.close()
    c._flush_block()
    out = []
    if c.title:
        out.append(f"<title>{c.title}</title>")
        out.append("")
    for ln in c.lines:
        out.append(ln)
    return _normalize("\n".join(out))


def _normalize(md):
    lines = [ln.rstrip() for ln in md.replace("\r\n", "\n").split("\n")]
    # 块之间统一一个空行，表格行之间不插空行
    res = []
    for ln in lines:
        if not ln.strip():
            if res and res[-1] != "":
                res.append("")
            continue
        if res and res[-1] != "" and not (ln.startswith("|") and res[-1].startswith("|")) \
                and not (re.match(r"^\s*(\d+\.|-) ", ln) and re.match(r"^\s*(\d+\.|-) ", res[-1])) \
                and not (ln.startswith("  ") and re.match(r"^\s*(\d+\.|-) ", res[-1])):
            res.append("")
        res.append(ln)
    while res and res[-1] == "":
        res.pop()
    return "\n".join(res) + "\n"


def md_normalize(md):
    md = md.replace("\r\n", "\n")
    # 图片：飞书 md 导出的 ![alt](url) 与【图】一律写成 [图片]（alt 是飞书自动补的描述，不算正文）
    md = re.sub(r"!\[[^\n]*?\]\((?:https?://|@)[^)\s]*\)", "[图片]", md)
    md = md.replace("【图】", "[图片]")
    md = md.replace("\\~", "~")
    lines = [ln.rstrip() for ln in md.split("\n")]
    res = []
    for ln in lines:
        if re.match(r"^\|(\s*:?-+:?\s*\|)+$", ln):
            n = ln.count("|") - 1
            ln = "|" + "---|" * n
        if not ln.strip():
            if res and res[-1] != "":
                res.append("")
            continue
        res.append(ln)
    while res and res[-1] == "":
        res.pop()
    return "\n".join(res) + "\n"


def mermaid_to_board(md):
    return re.sub(r"```mermaid\n.*?\n```", "[画板]", md, flags=re.S)


def drop_images(md):
    out = [ln for ln in md.split("\n") if ln.strip() not in ("[图片]", "[画板]")]
    return md_normalize("\n".join(out))


def load_any(path):
    raw = open(path, encoding="utf-8").read()
    if path.endswith(".json") or raw.lstrip().startswith("{"):
        d = json.loads(raw)
        return xml_to_md(d["data"]["document"]["content"])
    if path.endswith(".xml") or raw.lstrip().startswith("<title id=") or "<h1" in raw[:3000] or "<p>" in raw[:3000]:
        return xml_to_md(raw)
    return md_normalize(raw)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    src, dst = args[0], args[1]
    md = load_any(src)
    if "--mermaid-board" in flags:
        md = md_normalize(mermaid_to_board(md))
    if "--drop-images" in flags:
        md = drop_images(md)
    open(dst, "w", encoding="utf-8").write(md)
    print(f"{src} -> {dst}: {len(md)} chars, {md.count(chr(10))} lines")
