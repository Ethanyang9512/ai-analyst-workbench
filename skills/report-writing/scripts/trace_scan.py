# -*- coding: utf-8 -*-
"""内部痕迹扫描：给业务方或领导看的文档、PPT 里，不该出现的内部代号和协作痕迹。

用法: python3 trace_scan.py 稿件.md [片子.pptx ...] [--allow 词1,词2] [--names 词1,词2]
支持 .md .txt .xml .json .pptx .docx。
退出码: 有「命中」=1；只有「待判断」或没有=0。
--names 补充你自己的协作方名字（助手名、同事代号等），按「协作方」算命中；内置的只有通用的几个。

命中   = 基本可以确定不该出现（协作方名字、过程用词、本机路径）
待判断 = 像内部包号（S6、T1 这类），也可能是正常业务编号，要人看一眼。R20 这类轮次号算命中；确属业务编号时用 --allow 放行
"""
import io
import os
import re
import sys
import zipfile

HARD = [
    ("协作方", re.compile(r"分析助手|取数助手|Claude|Codex|ChatGPT")),
    ("AI 痕迹", re.compile(r"AI ?生成|AI_assisted|由 ?AI|大模型生成")),
    ("过程用词", re.compile(r"复盘包|补数包|回包|需求包|任务书|优化报告|审核报告|对抗式审查|验收员|取数需求")),
    ("本机路径", re.compile(r"/(?:Users|home)/|[A-Za-z]:\\Users\\|\.lark-channel|_status\.md|round\d+_")),
    # 轮次号（R20 这类）只有协作双方看得懂，读者看不懂
    ("内部轮次号", re.compile(r"(?<![A-Za-z0-9])R\d{1,3}(?![A-Za-z0-9%])")),
]
SOFT = [
    ("疑似内部包号", re.compile(r"(?<![A-Za-z0-9+])[ST]\d{1,3}(?![A-Za-z0-9%])")),
]
TEXT_EXT = {".md", ".txt", ".xml", ".json", ".csv"}


def units(path):
    """产出 (位置, 文本)。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                yield f"L{n}", line
    elif ext in (".pptx", ".docx"):
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if re.match(
                r"(ppt/(slides|notesSlides)/[^/]+\.xml|word/document\.xml)$", n))
            for name in names:
                xml = z.read(name).decode("utf-8", errors="replace")
                text = " ".join(re.findall(r"<(?:a|w):t[^>]*>([^<]*)</(?:a|w):t>", xml))
                m = re.search(r"(slide|notesSlide)(\d+)\.xml", name)
                where = (("第%s页" % m.group(2)) + ("备注" if m.group(1) == "notesSlide" else "")) if m else name
                yield where, text
    else:
        raise ValueError("不支持的文件类型: " + ext)


def names_rule(names):
    """--names 给的词 → 追加一条「协作方」规则；没给返回空表。
    纯字母数字的代号（如 BB）前后紧挨字母时不算，免得 ABBA 这类英文词误报；紧挨汉字照算。"""
    words = sorted({w for w in names if w}, key=len, reverse=True)
    pats = ["(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(w) if re.fullmatch(r"[A-Za-z0-9]+", w) else re.escape(w)
            for w in words]
    return [("协作方", re.compile("|".join(pats)))] if pats else []


def scan(path, allow, names=()):
    hard, soft = [], []
    rules = HARD + names_rule(names)
    for where, text in units(path):
        for kind, pat in rules:
            for m in pat.finditer(text):
                if m.group(0) in allow:
                    continue
                hard.append((where, kind, m.group(0), text[max(0, m.start() - 14): m.end() + 14].strip()))
        for kind, pat in SOFT:
            for m in pat.finditer(text):
                if m.group(0) in allow:
                    continue
                soft.append((where, kind, m.group(0), text[max(0, m.start() - 14): m.end() + 14].strip()))
    return hard, soft


def main(argv):
    allow, names, files = set(), set(), []
    it = iter(argv)
    for a in it:
        if a == "--allow":
            allow |= {x for x in next(it, "").split(",") if x}
        elif a == "--names":
            names |= {x.strip() for x in next(it, "").split(",") if x.strip()}
        else:
            files.append(a)
    if not files:
        print(__doc__)
        return 2
    total = 0
    for path in files:
        try:
            hard, soft = scan(path, allow, names)
        except Exception as e:
            print(f"== {path}  没扫成：{type(e).__name__}: {e}")
            continue
        total += len(hard)
        print(f"== {path}  命中 {len(hard)} / 待判断 {len(soft)} ==")
        for where, kind, word, ctx in hard[:60]:
            print(f"  [命中] {where} {kind}「{word}」 | {ctx}")
        for where, kind, word, ctx in soft[:30]:
            print(f"  [待判断] {where} {kind}「{word}」 | {ctx}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
