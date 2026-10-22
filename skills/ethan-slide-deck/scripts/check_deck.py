# -*- coding: utf-8 -*-
"""PPT 交付前自检：① 文件完整性 ② 非法色值（另提示图表里配色表以外的颜色）③ 元素越界 ④ 文字块重叠
   ⑤ 术语黑名单 ⑥ 文字溢出 ⑦ 图表数据标签位置（dLblPos 按图表类型合法性——写错 PowerPoint 直接拒开文件）
   可选 ⑧ OpenXML schema 校验 + 全片拼图预览（需要 officecli：`npm i -g @officecli/officecli`）。
   母版用你自己的 .pptx；页面尺寸从文件里读，不写死。

用法::

    python check_deck.py 我的汇报.pptx
    python check_deck.py 我的汇报.pptx --footer-top 18.16  # 母版页脚色条上沿（cm）；给了才查"内容压页脚条"
    python check_deck.py 我的汇报.pptx --palette 1A1A1A,B9B9BC,C0392B   # 图表配色表；none = 不查
    python check_deck.py 我的汇报.pptx --terms 黑话1,黑话2,黑话3
    python check_deck.py 我的汇报.pptx --dump              # 打印全片文字供人工过一遍
    python check_deck.py 我的汇报.pptx --officecli         # 加跑 schema 校验（有 officecli 才生效）
    python check_deck.py 我的汇报.pptx --preview 预览.png   # 全片拼图预览（officecli，几秒钟）

退出码 0 = 全部通过，1 = 有问题。可以挂进 CI 或 pre-commit。

② 的两部分：色值写坏（不是 6 位十六进制）计入失败——PowerPoint 会拒绝打开文件；
   图表（ppt/charts/*.xml）里写死的颜色不在配色表里，只提示、不计入失败。
   默认配色表＝ethan-report-writing/references/chart-style-guide.md 的图表六色加白色（柱内白字）。

⑥ 文字溢出的原理：按字宽（中文 1em、西文 0.52em、空格 0.3em）折行，估算每个文本框真实需要的高度，
   超过框高 12% 即报。**python-pptx 写的 autofit 框在 PowerPoint 里打开时不会自动撑高**（只有在
   PowerPoint 里编辑过文字才会重算），所以溢出的文字会直接压到下面的元素上——③④ 两项也按估算高度判。

⚠️ 机器只能查这几项。**数值是否与数据源一致、有没有比喻和过度断言，机器查不出**，
必须另写一份针对本片的数值比对脚本（每个数字 assert 回数据源），并把 --dump 的输出逐句读一遍。
"""
import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter

from pptx import Presentation

# Windows 控制台默认 GBK，遇到 ➢ 之类会报 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EMU = 360000.0                 # 1 cm
PT2CM = 2.54 / 72              # 1 pt = 0.0353 cm
LINE = 1.2                     # PowerPoint 单倍行距 ≈ 字号 × 1.2
DEFAULT_PT = 12.0              # 没写字号的 run 按正文 12pt 估
SLIDE_W, SLIDE_H = 33.87, 19.05  # 16:9 默认值；main() 里按文件实际尺寸覆盖
# 图表六色（与 ethan-report-writing/references/chart-style-guide.md、chart_template.py 逐值对齐）＋白色
DEFAULT_PALETTE = ("1A1A1A", "B9B9BC", "DDE0E4", "C0392B", "2E9E5B", "D64545", "FFFFFF")
PICTURE = 13                   # MSO_SHAPE_TYPE.PICTURE（Logo 本就落在页脚条上）
OVERFLOW_TOL = 1.12            # 估算高度超过框高 12% 才算溢出（字宽估算有误差）
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
C_NS = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
# dLblPos 的合法值按图表类型不同（ECMA-376 ST_DLblPos）。写错的后果是 PowerPoint 弹「无法打开文件」，
# python-pptx / zip 校验 / officecli validate 都查不出（一次实测：堆积柱 base 系列写了 t，全片打不开）
DLBLPOS_OK = {
    "barChart":     {"ctr", "inBase", "inEnd", "outEnd"},
    "lineChart":    {"ctr", "l", "r", "t", "b"},
    "scatterChart": {"ctr", "l", "r", "t", "b"},
    "pieChart":     {"bestFit", "ctr", "inEnd", "outEnd"},
    "areaChart":    set(),                      # 面积图不允许写 dLblPos
}
STACKED_BAR_OK = {"ctr", "inBase", "inEnd"}     # 堆积 / 百分比堆积柱：连 outEnd 也不行


def chart_dlblpos_issues(chart):
    """返回 [(图表类型, grouping, 非法值, 允许的值), ...]；不认识的图表类型跳过。"""
    plot = chart._chartSpace.find(".//" + C_NS + "plotArea")
    if plot is None:
        return []
    issues = []
    for el in plot:
        kind = el.tag.replace(C_NS, "")
        if kind not in DLBLPOS_OK:
            continue
        g = el.find(C_NS + "grouping")
        grouping = g.get("val") if g is not None else ""
        ok = STACKED_BAR_OK if (kind == "barChart" and grouping in ("stacked", "percentStacked")) else DLBLPOS_OK[kind]
        for d in el.iter(C_NS + "dLblPos"):
            if d.get("val") not in ok:
                issues.append((kind, grouping, d.get("val"), ok))
    return issues


def _char_em(c):
    o = ord(c)
    if o > 0x2E80:
        return 1.0                 # 中日韩全角 = 1em
    if c == " ":
        return 0.30
    return 0.52                    # 西文 / 数字（常见西文字体和微软雅黑的实测均值）


def _pt(length):
    return length.pt if length is not None else None


def est_text(shape):
    """估算文本框内容真实需要的高度。返回 (高度 cm, 总行数, 最大字号 pt, autofit 类型)。"""
    tf = shape.text_frame
    m = [(x if x is not None else 91440) / EMU
         for x in (tf.margin_left, tf.margin_right, tf.margin_top, tf.margin_bottom)]
    usable_w = shape.width / EMU - m[0] - m[1]
    wrap = tf.word_wrap is not False           # None（继承）按会折行处理
    body = tf._txBody.find(A_NS + "bodyPr")
    autofit = "fixed"
    if body is not None:
        for c in body:
            if c.tag == A_NS + "spAutoFit":
                autofit = "spAutoFit"
            elif c.tag == A_NS + "normAutofit":
                autofit = "normAutofit"
    total = m[2] + m[3]
    n_lines, max_pt = 0, 0.0
    for para in tf.paragraphs:
        pPr = para._p.pPr
        marL = int(pPr.get("marL", 0)) / EMU if pPr is not None else 0.0
        w_avail = max(0.5, usable_w - marL)
        sizes = [_pt(r.font.size) for r in para.runs if r.font.size is not None]
        pt = max(sizes) if sizes else (_pt(para.font.size) or DEFAULT_PT)
        max_pt = max(max_pt, pt)
        n = 0
        for seg in para.text.split("\v"):        # <a:br/> 在 para.text 里是 \v
            if not seg:
                n += 1
                continue
            w = sum(_char_em(c) for c in seg) * pt * PT2CM
            n += max(1, math.ceil(w / w_avail)) if wrap else 1
        n_lines += n
        ls = para.line_spacing
        mult = ls if isinstance(ls, float) else (ls.pt / pt if ls is not None else LINE)
        total += n * pt * PT2CM * mult
        for sp in (para.space_before, para.space_after):
            if sp is not None:
                total += sp.pt * PT2CM
    return total, n_lines, max_pt, autofit


def rects(slide):
    """返回 [(shape, left, top, right, bottom, overflow_info)]。
    标题按真实文字行数折算高度（占位符恒 2.18cm，按框高会误报重叠）；
    其它文本框取 max(框高, 估算高度)——溢出的文字会真的压到下面去。"""
    out = []
    for sh in slide.shapes:
        l, t = sh.left / EMU, sh.top / EMU
        w, h = sh.width / EMU, sh.height / EMU
        info = None
        if sh.has_text_frame and sh.text_frame.text.strip():
            est_h, n, pt, autofit = est_text(sh)
            if sh == slide.shapes.title:
                h = min(h, est_h)
            elif sh.is_placeholder:
                pass                # 母版占位符（封面副标题等）的内边距继承自版式，估不准，也不由代码定尺寸——不判溢出
            else:
                if est_h > h * OVERFLOW_TOL + 0.05:
                    info = (est_h, n, pt, autofit)
                h = max(h, est_h)
        out.append((sh, l, t, l + w, t + h, info))
    return out


def label(sh):
    if sh.has_text_frame and sh.text_frame.text.strip():
        return repr(sh.text_frame.text.strip().replace("\n", " / ")[:38])
    return str(sh.shape_type)


def _officecli():
    return shutil.which("officecli.cmd") or shutil.which("officecli")   # Windows 下 npm 装的是 officecli.cmd


def officecli_validate(pptx):
    """⑦ OpenXML schema 校验。返回 (错误数, 按类型计数)；没装 officecli 返回 (None, {})。"""
    exe = _officecli()
    if not exe:
        return None, {}
    r = subprocess.run([exe, "validate", pptx], capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"Found (\d+) validation error", out)
    n = int(m.group(1)) if m else 0
    kinds = Counter(line.strip()[:110] for line in out.splitlines() if line.strip().startswith("[Schema]"))
    return n, kinds


def officecli_preview(pptx, png, cols=4):
    exe = _officecli()
    if not exe:
        return None
    subprocess.run([exe, "view", pptx, "screenshot", "--grid", str(cols), "-o", png],
                   capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    return png if os.path.exists(png) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx")
    ap.add_argument("--terms", default="",
                    help="逗号分隔的术语黑名单（团队自造词、内部黑话）")
    ap.add_argument("--dump", action="store_true", help="打印全片文字")
    ap.add_argument("--officecli", action="store_true", help="加跑 OpenXML schema 校验（需要 officecli）")
    ap.add_argument("--strict", action="store_true", help="schema 错误也计入失败（默认只警告）")
    ap.add_argument("--preview", default="", help="全片拼图预览 PNG 路径（需要 officecli）")
    ap.add_argument("--footer-top", type=float, default=None,
                    help="母版页脚色条上沿（cm）；给了才查内容压页脚条，不给不查")
    ap.add_argument("--palette", default=",".join(DEFAULT_PALETTE),
                    help="图表允许的颜色，逗号分隔的 6 位十六进制（默认图表六色＋白色）；none = 不查")
    a = ap.parse_args()

    global SLIDE_W, SLIDE_H
    prs = Presentation(a.pptx)
    SLIDE_W, SLIDE_H = prs.slide_width / EMU, prs.slide_height / EMU
    z = zipfile.ZipFile(a.pptx)
    fails = 0

    broken = z.testzip()
    print("① 文件完整性:", "损坏 " + str(broken) if broken else "OK",
          "| 页数:", len(prs.slides))
    fails += bool(broken)

    bad = set()
    for n in z.namelist():
        if n.endswith(".xml"):
            for v in re.findall(r'srgbClr val="([^"]*)"', z.read(n).decode("utf-8")):
                if not re.fullmatch(r"[0-9A-Fa-f]{6}", v):
                    bad.add(v)
    # 非法色值不会报错，只会让 PowerPoint 拒绝打开文件，必须拦住
    print("② 非法色值:", bad or "无")
    fails += bool(bad)
    if a.palette.strip().lower() != "none":
        allowed = {c.strip().lstrip("#").upper() for c in a.palette.split(",") if c.strip()}
        off = Counter()
        for n in z.namelist():
            if re.match(r"ppt/charts/chart[^/]*\.xml$", n):
                for v in re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', z.read(n).decode("utf-8")):
                    if v.upper() not in allowed:
                        off[v.upper()] += 1
        print("   图表里配色表以外的颜色（提示，不计入失败）:",
              "、".join("#%s×%d" % kv for kv in off.most_common()) if off else "无")

    all_rects = [(i, rects(sl)) for i, sl in enumerate(prs.slides, 1)]

    print("③ 元素越界（页面 %.2f×%.2f / 页脚条 %s）:" % (SLIDE_W, SLIDE_H,
          "%.2f" % a.footer_top if a.footer_top is not None else "未给，不查"))
    hit = 0
    for i, rs in all_rects:
        for sh, l, t, r, b, _ in rs:
            if r > SLIDE_W + 0.05 or b > SLIDE_H + 0.05 or l < -0.05 or t < -0.05:
                print("   p%d 出血: %s (%.2f,%.2f)-(%.2f,%.2f)" % (i, label(sh), l, t, r, b))
                hit += 1
            elif a.footer_top is not None and b > a.footer_top and sh.shape_type != PICTURE:
                print("   p%d 压页脚条: %s 底沿 %.2f" % (i, label(sh), b))
                hit += 1
    print("   无越界" if not hit else "   共 %d 处" % hit)
    fails += hit

    print("④ 文字块重叠:")
    hit = 0
    for i, rs in all_rects:
        boxes = [x for x in rs if x[0].has_text_frame and x[0].text_frame.text.strip()]
        for x in range(len(boxes)):
            for y in range(x + 1, len(boxes)):
                _, l1, t1, r1, b1, _ = boxes[x]
                _, l2, t2, r2, b2, _ = boxes[y]
                ix = min(r1, r2) - max(l1, l2)
                iy = min(b1, b2) - max(t1, t2)
                if ix > 0.05 and iy > 0.05:
                    print("   p%d 重叠 %.1f×%.1fcm: %s × %s"
                          % (i, ix, iy, label(boxes[x][0]), label(boxes[y][0])))
                    hit += 1
    print("   无重叠" if not hit else "   共 %d 处" % hit)
    fails += hit

    texts = []
    for i, sl in enumerate(prs.slides, 1):
        for sh in sl.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append((i, sh.text_frame.text))
            if sh.has_chart:
                for pt in sh.chart.plots:
                    texts.append((i, " ".join(str(c) for c in pt.categories)))

    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    if terms:
        found = [(i, w) for i, t in texts for w in terms if w.lower() in t.lower()]
        print("⑤ 术语黑名单:", found or "无残留")
        fails += len(found)
    else:
        print("⑤ 术语黑名单: 未提供（用 --terms 传本团队的自造词清单）")

    print("⑥ 文字溢出（估算高度 > 框高 ×%.2f）:" % OVERFLOW_TOL)
    hit = info_n = 0
    for i, rs in all_rects:
        for sh, l, t, r, b, info in rs:
            if info:
                est_h, n, pt, autofit = info
                grow = autofit == "spAutoFit"       # 自动撑高的框：文字不会被裁，只是比代码里写的高——③④ 已按撑高后判过，这里只提示
                print("   p%d %s: %s 框高 %.2fcm，%d 行 %.0fpt 需要 %.2fcm（%s）→ 建议框高 ≥ %.2fcm 或精简文字"
                      % (i, "提示" if grow else "溢出", label(sh), sh.height / EMU, n, pt, est_h, autofit, est_h + 0.05))
                if grow:
                    info_n += 1
                else:
                    hit += 1
    print("   无溢出" if not (hit or info_n) else "   溢出 %d 处（计入失败）、自动撑高提示 %d 处（不计入）" % (hit, info_n))
    fails += hit

    print("⑦ 图表数据标签位置（dLblPos 按图表类型合法性）:")
    hit = 0
    for i, sl in enumerate(prs.slides, 1):
        for sh in sl.shapes:
            if sh.has_chart:
                for kind, grouping, v, ok in chart_dlblpos_issues(sh.chart):
                    print("   p%d %s: %s%s 写了 dLblPos=%s，只允许 %s → PowerPoint 会拒绝打开文件"
                          % (i, label(sh), kind, "(%s)" % grouping if grouping else "", v, "/".join(sorted(ok)) or "不写"))
                    hit += 1
    print("   无问题" if not hit else "   共 %d 处（计入失败）" % hit)
    fails += hit

    if a.officecli:
        n, kinds = officecli_validate(a.pptx)
        if n is None:
            print("⑧ schema 校验: 未安装 officecli（npm i -g @officecli/officecli），跳过")
        else:
            print("⑧ schema 校验（officecli validate）: %s" % ("通过" if not n else "%d 个错误" % n))
            for k, c in kinds.most_common(5):
                print("   %3d × %s" % (c, k))
            if n and a.strict:
                fails += n
            elif n:
                print("   （默认只警告；PowerPoint 一般能容忍，WPS / Keynote / 在线预览可能出问题。--strict 计入失败）")

    if a.preview:
        p = officecli_preview(a.pptx, a.preview)
        print("预览拼图:", p if p else "失败（officecli 未安装或渲染出错）")

    if a.dump:
        print("\n--- 全片文字（人工逐句过一遍：比喻 / 口语 / 过度断言 / 数值口径）---")
        for i, t in texts:
            print("p%d| %s" % (i, t.replace("\n", " / ")[:160]))

    print("\n结果:", "全部通过" if not fails else "%d 处待处理" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
