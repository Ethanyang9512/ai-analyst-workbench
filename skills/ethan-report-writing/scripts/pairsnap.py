# -*- coding: utf-8 -*-
"""成对快照 —— 用户手改定稿之后，把"交付版 → 用户定稿"存一份副本并算手改比例。

用法:
  python3 pairsnap.py save --project <工作区或项目名> --doc <文档名> --delivered <交付版文件> --final <用户定稿文件>
                           [--source <飞书 token 或说明>] [--note <备注>] [--history] [--exam-candidate]
  python3 pairsnap.py list
  python3 pairsnap.py metrics [--project X]
  python3 pairsnap.py mark --id <id> --history --reason <为什么改>     （新稿存错了，改成历史回填）

存放: <根>/<项目>/<YYYYMMDD-HHMM>_<文档名>/ 下放 delivered.md、final.md（抽出来的正文）、diff.txt、meta.json，
  另存原样副本 delivered_src.<后缀>、final_src.<后缀>。
  总索引 <根>/index.jsonl，一行一份。根默认 ~/aaw-pairs，可用 --root 或环境变量 PAIRSNAP_ROOT 改。
考题: 非历史的成对稿按存入顺序，每 HELDOUT_EVERY 份的最后一份 heldout=true（留作考题）。手改照常提取，
  但从这份提取的改法写到哪里都标「考题来源：<id>」——台账、项目约定页、术语表、项目状态、记忆、本项目生成源都算，考试时这些地方一起遮掉（生成源整份挡掉）。
  --history 是历史回填：不参与计数，heldout=false、history=true；时间取定稿文件的修改时间。同一对（两个文件的 sha256 都相同）不许存两次。
  heldout 存的时候就定死、不重算；新稿存错了用 mark 改成历史，只许改最后一份新稿（后面再存过新稿就改不了），原来的标记记在 relabeled 里。
正文: .txt 原样；.md 化成和 XML 同一套纯文本写法（见 md_to_plain）；.json/.xml 做朴素的正文抽取（去标签、取文本字段），抽不出就报错退出。
  图片一律不算正文（占位 [[IMG:xx]]、【图】、md 图片、画板代码块都去掉）。
指标: edit_ratio = 用户改动涉及的行数 ÷ 交付版行数（difflib 按行比，空行不计；删掉的行、新增的行各算，
  替换块按两边行数的较大者算，所以大段新增时会超过 1）；另记删除块、新增块、替换块个数，两版字数（不含空白），篇幅比＝定稿字数÷交付版字数。
  format_changed = 只动格式、正文 diff 里看不见的行数（去掉代码块围栏、加粗、编号改项目符号、引用记号这类），从两份原件直接比；
  >0 时另写 format_diff.txt，diff.txt 第一行会提示。xml/json 按块比，标签属性（块 id、列宽）不算；图片、画板不算；
  两份原件格式不同（比如 xml 对 md）时记 null，格式改动要自己看两份 *_src。
只用 Python 标准库；不改原件。
"""
import argparse
import datetime
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
from html.parser import HTMLParser

DEFAULT_ROOT = os.path.expanduser("~/aaw-pairs")
HELDOUT_EVERY = 3          # 每几份新成对稿留 1 份当考题
RECENT_N = 3               # metrics 里"最近几份的均值"
TEXT_EXT = {".md", ".txt"}
MARKUP_EXT = {".json", ".xml"}
JSON_TEXT_KEYS = ("content", "markdown", "text")   # 找不到 data.document.content 时，按这些键取文本
UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


class PairsnapError(Exception):
    pass


# ---------- 正文抽取 ----------

class _TextOut(HTMLParser):
    """飞书 docx XML / HTML 去标签：块级元素换行，表格一行一行、格子之间用 " | " 隔开，标签属性（含图片 alt）一律不取。"""
    BLOCK = {"title", "p", "li", "ul", "ol", "table", "thead", "tbody", "tr", "blockquote", "quote",
             "callout", "pre", "hr", "br", "div", "section", "grid", "column", "figure", "figcaption",
             "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.cur, self.cell_depth, self.cells_in_row = [], [], 0, 0

    def _flush(self):
        line = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if line:
            self.lines.append(line)
        self.cur = []

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            if self.cells_in_row:
                self.cur.append(" | ")
            self.cells_in_row += 1
            self.cell_depth += 1
        elif tag == "tr":
            self._flush()
            self.cells_in_row = 0
        elif tag in self.BLOCK:
            if self.cell_depth:
                self.cur.append(" ")
            elif not re.fullmatch(r"-|#+", "".join(self.cur).strip()):   # 列表项里套段落时不另起一行
                self._flush()
                if re.fullmatch(r"h[1-9]", tag):
                    self.cur.append("#" * int(tag[1]) + " ")
                elif tag == "li":
                    self.cur.append("- ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cell_depth = max(0, self.cell_depth - 1)
        elif tag in self.BLOCK and not self.cell_depth:
            self._flush()

    def handle_data(self, data):
        self.cur.append(data)

    def text(self):
        self.close()
        self._flush()
        return "\n".join(self.lines)


def strip_markup(s):
    p = _TextOut()
    p.feed(s)
    return p.text()


MD_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)")
MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")   # 也吃掉 --- 分隔线
MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
MD_ESC = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|<>])")
MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
DIAGRAM_LANGS = {"mermaid", "plantuml"}
PLACEHOLDER = re.compile(r"\[\[IMG:[^\]]*\]\]|【图】")


def md_to_plain(text):
    """Markdown 化成和 XML 抽取同一套写法，免得同一篇稿子 md 和 xml 一比全是格式差：
    表格一行一行、格子用 " | " 隔开（分隔行不要），列表一律 "- "，去掉加粗记号、转义反斜杠、行内 HTML 标签和引用记号；
    mermaid 这类画板代码块整块不要（XML 里画板没有文字），其他代码块只去掉 ``` 那两行。"""
    out, fence = [], None
    for ln in text.splitlines():
        m = MD_FENCE.match(ln)
        if fence:
            if m and not m.group(2):
                fence = None
            elif fence == "code":
                out.append(ln)
            continue
        if m:
            fence = "diagram" if m.group(2).lower() in DIAGRAM_LANGS else "code"
            continue
        ln = re.sub(r"<[A-Za-z/][^>]*>", "", MD_IMG.sub("", ln))
        if "-" in ln and MD_TABLE_SEP.match(ln):
            continue
        s = ln.strip()
        if s.startswith("|"):
            s = " | ".join(c.strip() for c in re.split(r"(?<!\\)\|", s.strip("|")))
        elif s.startswith(">"):
            s = s.lstrip("> ")
        s = MD_LIST.sub("- ", s).replace("**", "").replace("__", "")
        out.append(MD_ESC.sub(r"\1", s))
    return "\n".join(out)


def drop_placeholders(text):
    """图片不算正文：去掉图片占位（[[IMG:xx]]、【图】），去完只剩表格竖线的行整行不要。
    图多半是 Claude 交付后另插的，算进来会把它自己插图当成用户手改。"""
    out = []
    for ln in text.splitlines():
        ln = PLACEHOLDER.sub("", ln)
        if ln.strip(" \t|"):
            out.append(ln.rstrip())
    return "\n".join(out)


def _json_text(obj):
    data = obj.get("data") if isinstance(obj, dict) else None
    doc = data.get("document") if isinstance(data, dict) else None    # 读取失败时 data 可能是 null 或列表
    if isinstance(doc, dict) and isinstance(doc.get("content"), str):
        return doc["content"]                      # lark-cli docs +fetch 的输出
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in JSON_TEXT_KEYS and isinstance(v, str):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return "\n".join(found) if found else None


TAG = re.compile(r"<[A-Za-z/][^>]*>")


def load_source(path):
    """→ (写法, 原文)。写法是 md / markup（xml，或带标签的 json 正文）/ txt；json 的原文是取出来的文本字段。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXT | MARKUP_EXT:
        raise PairsnapError(f"不支持的文件类型 {ext or '（无后缀）'}：{path}（只收 .md/.txt/.json/.xml）")
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        raise PairsnapError(f"不是 UTF-8 文本：{path}")
    if ext == ".json":
        try:
            obj = json.loads(raw)
        except ValueError as e:
            raise PairsnapError(f"JSON 解析失败：{path}（{e}）")
        raw = _json_text(obj)
        if raw is None:
            raise PairsnapError(f"JSON 里找不到正文字段（data.document.content 或 {'/'.join(JSON_TEXT_KEYS)}）：{path}")
        return ("markup" if TAG.search(raw) else "txt"), raw
    return {".md": "md", ".xml": "markup", ".txt": "txt"}[ext], raw


def extract_text(path):
    """→ (正文, 抽取方式)。抽不出就抛 PairsnapError。"""
    kind, raw = load_source(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        text, how = raw, "原文"
    elif ext == ".md":
        text, how = md_to_plain(raw), "md 化成纯文本"
    elif ext == ".xml":
        text, how = strip_markup(raw), "xml 去标签"
    elif kind == "markup":
        text, how = strip_markup(raw), "json 取文本字段 + 去标签"
    else:
        text, how = raw, "json 取文本字段"
    text = drop_placeholders(text)
    if not text_lines(text):
        raise PairsnapError(f"抽不出正文（去掉空行后一行也没有）：{path}")
    return text, how


# ---------- 只动格式的改动 ----------

EMPTY_ELEM = re.compile(r"<(?!hr>)([A-Za-z][\w:-]*)>\s*</\1>")


class _MarkedOut(HTMLParser):
    """格式比对用：标签去掉属性留下（块 id、列宽这类属性不算），块级标签各起一行；图片、画板不要。"""
    SKIP = {"img", "whiteboard"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.SKIP:
            self.parts.append(("\n" if tag in _TextOut.BLOCK else "") + f"<{tag}>")

    def handle_endtag(self, tag):
        if tag not in self.SKIP:
            self.parts.append(f"</{tag}>" + ("\n" if tag in _TextOut.BLOCK else ""))

    def handle_data(self, data):
        self.parts.append(re.sub(r"\s+", " ", data))


def marked_lines(kind, raw):
    """保留格式记号的逐行写法：md 是原文行（画板代码块、图片去掉），markup 按块拆行，txt 原样。"""
    if kind == "markup":
        p = _MarkedOut()
        p.feed(raw)
        p.close()
        s, prev = PLACEHOLDER.sub("", "".join(p.parts)), None
        while s != prev:          # 空段落、去掉图片后空下来的格子和行，一层层去掉（分隔线 hr 留着）
            prev, s = s, EMPTY_ELEM.sub("", s)
        lines = [ln.strip() for ln in s.splitlines()]
    elif kind == "md":
        lines, fence = [], None
        for ln in raw.splitlines():
            m = MD_FENCE.match(ln)
            if fence:
                was, fence = fence, (None if m and not m.group(2) else fence)
                if was == "diagram":
                    continue
            elif m:
                fence = "diagram" if m.group(2).lower() in DIAGRAM_LANGS else "code"
                if fence == "diagram":
                    continue
            elif "|" in ln and MD_TABLE_SEP.match(ln):     # 表格分隔行跟着列数变，不算格式
                continue
            lines.append(MD_IMG.sub("", ln))
    else:
        lines = raw.splitlines()
    lines = [PLACEHOLDER.sub("", ln).rstrip() for ln in lines]
    return [ln for ln in lines if ln.strip(" \t|")]


def _plain(kind, lines):
    s = "\n".join(lines)
    if kind == "md":
        s = md_to_plain(s)
    elif kind == "markup":
        s = strip_markup(s)
    return text_lines(drop_placeholders(s))


def format_changes(kind_a, raw_a, kind_b, raw_b):
    """→ (只动格式的行数, [(交付版那几行, 定稿那几行), ...])。两份写法不同时没法比，→ (None, [])。
    逐行比保留格式记号的写法；不一样的行，化成纯文本后一样（或两边都化没了，比如代码块围栏、列表外壳）就算只动格式。"""
    if kind_a != kind_b:
        return None, []
    a, b = marked_lines(kind_a, raw_a), marked_lines(kind_b, raw_b)
    n, hunks = 0, []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        ka = [tuple(_plain(kind_a, [ln])) for ln in a[i1:i2]]
        kb = [tuple(_plain(kind_a, [ln])) for ln in b[j1:j2]]
        for op2, p1, p2, q1, q2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
            da, db = a[i1 + p1:i1 + p2], b[j1 + q1:j1 + q2]
            if op2 == "equal":
                k = sum(x != y for x, y in zip(da, db))
            elif not any(ka[p1:p2] + kb[q1:q2]):
                k = max(len(da), len(db))
            else:
                continue
            if k:
                n += k
                hunks.append((da, db))
    return n, hunks


def format_diff_text(hunks):
    out = ["# 只动格式的改动：化成纯文本一样，写法不同（代码块围栏、加粗、列表记号、引用记号这类）。",
           "# xml/json 按块逐行比，标签属性不算；图片、画板不算。"]
    for da, db in hunks:
        out.append("@@")
        out += ["-" + x for x in da] + ["+" + y for y in db]
    return "\n".join(out) + "\n"


# ---------- 指标 ----------

def text_lines(text):
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def char_count(text):
    return len(re.sub(r"\s", "", text))


def compute_metrics(delivered_text, final_text):
    a, b = text_lines(delivered_text), text_lines(final_text)
    blocks = {"delete": 0, "insert": 0, "replace": 0}
    changed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        blocks[op] += 1
        changed += max(i2 - i1, j2 - j1)
    dc, fc = char_count(delivered_text), char_count(final_text)
    return {
        "edit_ratio": round(changed / len(a), 4) if a else None,
        "changed_lines": changed,
        "delivered_lines": len(a),
        "final_lines": len(b),
        "delete_blocks": blocks["delete"],
        "insert_blocks": blocks["insert"],
        "replace_blocks": blocks["replace"],
        "delivered_chars": dc,
        "final_chars": fc,
        "length_ratio": round(fc / dc, 4) if dc else None,
    }


def diff_text(delivered_text, final_text):
    return "\n".join(difflib.unified_diff(text_lines(delivered_text), text_lines(final_text),
                                          "delivered.md", "final.md", lineterm="")) + "\n"


# ---------- 存放 ----------

def safe_name(s, what):
    s = UNSAFE.sub("_", s.strip())
    s = re.sub(r"\s+", " ", s).strip(" ._-")[:60].strip()
    if not s:
        raise PairsnapError(f"{what}安全化之后是空的，换个名字")
    return s


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_index(root):
    path = os.path.join(root, "index.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for no, ln in enumerate(f, 1):
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except ValueError as e:
                raise PairsnapError(f"index.jsonl 第 {no} 行坏了（{e}），先把这一行修好：{path}")
            if not isinstance(r, dict) or not re.fullmatch(r"P\d+", str(r.get("id", ""))):
                raise PairsnapError(f"index.jsonl 第 {no} 行不是成对稿记录（没有 P 开头的 id），先把这一行修好：{path}")
            rows.append(r)
    return rows


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def save(root, project, doc, delivered, final, source="", note="", history=False, exam_candidate=False, now=None):
    for p in (delivered, final):
        if not os.path.isfile(p):
            raise PairsnapError(f"文件不存在：{p}")
    d_text, d_how = extract_text(delivered)
    f_text, f_how = extract_text(final)
    n_fmt, fmt_hunks = format_changes(*load_source(delivered), *load_source(final))
    proj, docname = safe_name(project, "项目名"), safe_name(doc, "文档名")
    d_sha, f_sha = sha256(delivered), sha256(final)
    if history:
        when = datetime.datetime.fromtimestamp(os.path.getmtime(final))
    else:
        when = now or datetime.datetime.now()
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)           # 几个群的会话同时存时，考题计数不乱
        rows = read_index(root)
        for r in rows:
            if r.get("delivered_sha256") == d_sha and r.get("final_sha256") == f_sha:
                raise PairsnapError(f"这一对已经存过：{r['id']}（{r['path']}）")
        seq = None
        if not history:
            seq = sum(1 for r in rows if not r.get("history")) + 1
        rel = os.path.join(proj, f"{when:%Y%m%d-%H%M}_{docname}")
        k = 2
        while os.path.exists(os.path.join(root, rel)):
            rel = os.path.join(proj, f"{when:%Y%m%d-%H%M}_{docname}-{k}")
            k += 1
        row = {
            "id": f"P{max([int(r['id'][1:]) for r in rows] or [0]) + 1:04d}",
            "project": project,
            "doc": doc,
            "time": f"{when:%Y-%m-%d %H:%M}",
            "saved_at": f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
            "heldout": bool(seq and seq % HELDOUT_EVERY == 0),
            "history": bool(history),
            "seq": seq,
        }
        row.update(compute_metrics(d_text, f_text))
        row["format_changed"] = n_fmt
        row.update({"source": source, "note": note, "delivered_sha256": d_sha, "final_sha256": f_sha, "path": rel})
        if exam_candidate:
            row["exam_candidate"] = True
        out = os.path.join(root, rel)
        os.makedirs(out)
        for name, text in (("delivered.md", d_text), ("final.md", f_text)):
            with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
        with open(os.path.join(out, "diff.txt"), "w", encoding="utf-8") as f:
            if n_fmt:
                f.write(f"# 另有 {n_fmt} 行只动了格式（代码块围栏、加粗、列表记号这类），下面的正文 diff 里看不见，见 format_diff.txt\n")
            f.write(diff_text(d_text, f_text))
        if n_fmt:
            with open(os.path.join(out, "format_diff.txt"), "w", encoding="utf-8") as f:
                f.write(format_diff_text(fmt_hunks))
        for tag, src in (("delivered", delivered), ("final", final)):
            shutil.copy2(src, os.path.join(out, f"{tag}_src{os.path.splitext(src)[1].lower()}"))
        meta = dict(row, delivered_file=os.path.abspath(delivered), final_file=os.path.abspath(final),
                    delivered_extract=d_how, final_extract=f_how, heldout_every=HELDOUT_EVERY)
        _write_json(os.path.join(out, "meta.json"), meta)
        with open(os.path.join(root, "index.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def mark_history(root, pid, reason, now=None):
    """把存错的新稿改成历史回填：heldout=false、seq=null，时间改成定稿的修改时间，目录跟着改名，原标记记进 relabeled。
    只许改最后一份新稿：后面的新稿的 heldout 是存的时候按序号定的，改前面的会让它们对不上。"""
    if not reason.strip():
        raise PairsnapError("要写 --reason：为什么改成历史")
    with open(os.path.join(root, ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read_index(root)
        hit = [i for i, r in enumerate(rows) if r["id"] == pid]
        if not hit:
            raise PairsnapError(f"没有 {pid} 这一份")
        r = rows[hit[0]]
        if r.get("history"):
            raise PairsnapError(f"{pid} 已经是历史回填")
        later = [x["id"] for x in rows if not x.get("history") and (x.get("seq") or 0) > (r.get("seq") or 0)]
        if later:
            raise PairsnapError(f"{pid} 后面又存过新稿（{'、'.join(later)}），它们的考题序号是存的时候定的，改了会对不上；要改先和用户商量")
        old_dir = os.path.join(root, r["path"])
        src = [n for n in os.listdir(old_dir) if n.startswith("final_src.")]
        if len(src) != 1:
            raise PairsnapError(f"{old_dir} 里找不到唯一的 final_src 原件，没法定历史时间")
        when = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(old_dir, src[0])))   # 存的时候 copy2 保留了修改时间
        proj = r["path"].split(os.sep)[0]
        rel = os.path.join(proj, f"{when:%Y%m%d-%H%M}_{safe_name(r['doc'], '文档名')}")
        k = 2
        while os.path.exists(os.path.join(root, rel)) and rel != r["path"]:
            rel = os.path.join(proj, f"{when:%Y%m%d-%H%M}_{safe_name(r['doc'], '文档名')}-{k}")
            k += 1
        change = {
            "history": True, "heldout": False, "seq": None, "time": f"{when:%Y-%m-%d %H:%M}", "path": rel,
            "relabeled": {"at": f"{now or datetime.datetime.now():%Y-%m-%d %H:%M}", "reason": reason,
                          "from": {key: r.get(key) for key in ("history", "heldout", "seq", "time", "path")}},
        }
        if rel != r["path"]:
            os.rename(old_dir, os.path.join(root, rel))
        meta_path = os.path.join(root, rel, "meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        _write_json(meta_path, dict(meta, **change))
        rows[hit[0]] = dict(r, **change)
        idx = os.path.join(root, "index.jsonl")
        with open(idx + ".tmp", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
        os.replace(idx + ".tmp", idx)
    return rows[hit[0]]


# ---------- 查看 ----------

def _fmt(x):
    return "—" if x is None else f"{x:.3f}"


def _flags(r):
    fl = []
    if r.get("history"):
        fl.append("历史")
    if r.get("heldout"):
        fl.append("考题")
    if r.get("exam_candidate"):
        fl.append("推广考题候选")
    return "、".join(fl) or "—"


def list_rows(rows):
    if not rows:
        return "还没有成对稿。\n"
    out = ["id\t时间\t项目\t文档\t标记\tedit_ratio\t篇幅比"]
    for r in rows:
        out.append(f"{r['id']}\t{r['time']}\t{r['project']}\t{r['doc']}\t{_flags(r)}\t"
                   f"{_fmt(r.get('edit_ratio'))}\t{_fmt(r.get('length_ratio'))}")
    return "\n".join(out) + "\n"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def metrics_report(rows, project=None):
    if project is not None:
        rows = [r for r in rows if r["project"] == project]
    if not rows:
        return f"没有{'项目 ' + project + ' 的' if project else ''}成对稿。\n"
    out = []
    new = sorted((r for r in rows if not r.get("history")), key=lambda r: (r["time"], r["id"]))
    projects = list(dict.fromkeys(r["project"] for r in new))
    out.append(f"== 新成对稿（按时间；最近 {RECENT_N} 份均值）==")
    if not new:
        out.append("（还没有）")
    for p in projects:
        rs = [r for r in new if r["project"] == p]
        out.append(f"[{p}] 共 {len(rs)} 份，最近 {RECENT_N} 份 edit_ratio 均值 "
                   f"{_fmt(_mean(r.get('edit_ratio') for r in rs[-RECENT_N:]))}（这几份里有 {min(len(rs), RECENT_N)} 份）")
        for r in rs:
            out.append(f"  {r['time']}  {r['id']}  edit_ratio {_fmt(r.get('edit_ratio'))}  "
                       f"篇幅比 {_fmt(r.get('length_ratio'))}  {_flags(r)}  {r['doc']}")
    if project is None and len(projects) > 1:
        out.append(f"[全部项目] 最近 {RECENT_N} 份 edit_ratio 均值 {_fmt(_mean(r.get('edit_ratio') for r in new[-RECENT_N:]))}")
    hist = sorted((r for r in rows if r.get("history")), key=lambda r: (r["project"], r["time"], r["id"]))
    out.append("== 历史回填（单列，不进上面的序列）==")
    if not hist:
        out.append("（没有）")
    for r in hist:
        out.append(f"  [{r['project']}] {r['time']}  {r['id']}  edit_ratio {_fmt(r.get('edit_ratio'))}  "
                   f"篇幅比 {_fmt(r.get('length_ratio'))}  {r['doc']}" + ("  推广考题候选" if r.get("exam_candidate") else ""))
    if hist:
        out.append(f"  历史 {len(hist)} 份 edit_ratio 均值 {_fmt(_mean(r.get('edit_ratio') for r in hist))}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="成对快照：交付版 → 用户定稿")
    ap.add_argument("--root", default=os.environ.get("PAIRSNAP_ROOT") or DEFAULT_ROOT,
                    help="存放根目录（默认 ~/aaw-pairs，或环境变量 PAIRSNAP_ROOT）")
    root_too = argparse.ArgumentParser(add_help=False)        # 子命令后面也认 --root，写在 save 前后都行
    root_too.add_argument("--root", default=argparse.SUPPRESS, help="同上，可以写在子命令后面")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="存一对", parents=[root_too])
    s.add_argument("--project", required=True)
    s.add_argument("--doc", required=True)
    s.add_argument("--delivered", required=True)
    s.add_argument("--final", required=True)
    s.add_argument("--source", default="")
    s.add_argument("--note", default="")
    s.add_argument("--history", action="store_true", help="历史回填：不参与考题计数")
    s.add_argument("--exam-candidate", action="store_true", help="在 meta 和索引里标 exam_candidate=true")
    sub.add_parser("list", help="列出全部成对稿", parents=[root_too])
    m = sub.add_parser("metrics", help="各项目 edit_ratio 时间序列", parents=[root_too])
    m.add_argument("--project")
    k = sub.add_parser("mark", help="把存错的新稿改成历史回填（只许改最后一份新稿）", parents=[root_too])
    k.add_argument("--id", required=True)
    k.add_argument("--history", action="store_true", required=True, help="改成历史回填（目前只支持这一种改法）")
    k.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "save":
            row = save(a.root, a.project, a.doc, a.delivered, a.final, a.source, a.note, a.history, a.exam_candidate)
            print(json.dumps(row, ensure_ascii=False))
            if row["heldout"]:
                print(f"pairsnap：{row['id']} 留作考题。从这份提取的改法，写到哪里都标「考题来源：{row['id']}」"
                      "——台账、项目约定页、术语表、项目状态、记忆、本项目生成源都算。", file=sys.stderr)
        elif a.cmd == "mark":
            print(json.dumps(mark_history(a.root, a.id, a.reason), ensure_ascii=False))
        elif a.cmd == "list":
            sys.stdout.write(list_rows(read_index(a.root)))
        else:
            sys.stdout.write(metrics_report(read_index(a.root), a.project))
    except PairsnapError as e:
        print(f"pairsnap：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
