#!/usr/bin/env python3
"""考卷打分：拿每份考卷目录下的 delivered.md / final.md / blocks.json / candidate.md 算代码指标。

用法：python3 score_papers.py <考卷目录> [<考卷目录> ...] --out <输出目录>
                              [--corpus <文件或通配> ...] [--leak-flagged <考卷名,...>]
  考卷目录：delivered.md（交付版）、final.md（用户定稿）、blocks.json（finalize.py 生成）、
            candidate.md（考生改出来的稿子）、meta.json（可选；"kind": "generalize" 表示推广题，
            "code_pattern": 一个带一组括号的正则，匹配“对象名前带的编号”，见数字一节）
  --corpus：技能、记忆、考场假工作区里的文件原文（只做泄题通扫用：考生稿与定稿共有的片段若出现在这些原文里，就不算可疑）
  --leak-flagged：跑考记录里已标“可能偷看过”的考卷，单列、不进汇总
只读输入文件；输出只写到 --out。

指标（全部由代码判，同样的输入重跑结果相同）：
1. 块命中：A 类块（score == 计入）看考生稿在对应位置是否朝定稿方向改了；同时报按行加权的命中率。B 类块单独报命中数；C 类不计分；
   作者存疑、标「建议不计入分母」的块单独报，不进分母。判法见 judge_block()。
2. 复核负担：交付版里用户原样保留的句子（≥8 字），考生稿里还在不在；不在的分成 仅标点 / 仅数字写法 / 改写 / 删除或大改。
   「允许 2 处容差」按「改动 ≤2 处算在容差内」理解，另报超出容差的处数。
3. 数字：定稿和交付版都有的数，考生稿里是否还在（差 ≤0.1 的抹平、四舍五入、W 换算不算错）；考生稿新增、交付版没有的数分类列出。
4. 篇幅比：考生稿/交付版，对比 定稿/交付版（去 markdown 记号与空白后的字符数；另报汉字数口径）。
5. 泄题复查：blocks.json 里的定稿独有片段在考生稿里出现几次；另做一遍通扫（考生稿与定稿共有、交付版没有、≥15 字、
   其中 ≥10 字是交付版没有的新字，且不在 --corpus 给的原文里）。
推广题（meta.json 里 "kind": "generalize"，例如用户另写的重写版）只报篇幅比、结构（章节数和顺序）和 B 类命中。
"""
import argparse
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_blocks as mb  # noqa: E402  切块时用的同一套 strip_md / is_weak / pair_lines

# ---------- 阈值（外置，可调） ----------
DEL_KEEP = 0.5        # 删除块：交付版那段的 3 字片段在考生对应位置还剩 <50% 记为「没了或明显压缩」＝命中
SHORT_DEL = 6         # 句内删除短于 6 字时改用窗口比对
PAIR_SIM = 0.45       # 行配对门槛（与 make_blocks 一致）
MOVE_FIND = 0.35      # 调序块：在考生稿里找被挪段落的最低相似度
KEEP_SENT_MIN = 8     # 复核负担只看 ≥8 字的句子
TOLERANCE = 2         # 复核负担容差（处）
PCT_TOL = 0.1         # 差 ≤0.1 算抹平（用户定的容差是 0.1pt，这里对所有单位同样用 0.1）
ROUND_REL = 0.2       # 取整到更少位小数、差超过 0.1 时，相对差 ≤20% 记「取整（超过 0.1 容差）」，再大就算缺失


# ---------- 文本工具 ----------
def norm(t):
    return mb.strip_md(t)


def zh_count(t):
    return len(re.findall(r"[一-鿿]", t))


def ratio(a, b):
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def fast_ratio(a, b):
    """行配对用：低于门槛的直接记 0（只影响是否配对，不影响配上的相似度）。"""
    if not a and not b:
        return 1.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < PAIR_SIM or sm.quick_ratio() < PAIR_SIM:
        return 0.0
    return sm.ratio()


mb.ratio = fast_ratio


def grams(s, n=3):
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def containment(seg, text):
    g = grams(seg)
    if not g:
        return 0.0
    return len(g & grams(text)) / len(g)


# ---------- 行对齐 ----------
def align(X, Y):
    """X 行号(0 起) -> [(Y 行号, 相似度)]。先用强锚点（相同的非弱行）切段，段内用 make_blocks.pair_lines 单调配对。"""
    xs = [i for i, ln in enumerate(X) if ln.strip()]
    ys = [j for j, ln in enumerate(Y) if ln.strip()]
    xl = [X[i] for i in xs]
    yl = [Y[j] for j in ys]
    sm = difflib.SequenceMatcher(None, xl, yl, autojunk=False)
    anchors = []
    for a, b, size in sm.get_matching_blocks():
        if size and any(not mb.is_weak(xl[a + k]) and len(norm(xl[a + k])) >= 6 for k in range(size)):
            anchors.append((a, b, size))
    mapping = {}
    pa = pb = 0
    for a, b, size in anchors + [(len(xl), len(yl), 0)]:
        if a > pa and b > pb:
            for op in mb.pair_lines(xl[pa:a], yl[pb:b]):
                if op[0] == "p":
                    for i in op[1]:
                        mapping.setdefault(xs[pa + i], []).extend((ys[pb + j], round(op[3], 3)) for j in op[2])
        for k in range(size):
            mapping[xs[a + k]] = [(ys[b + k], 1.0)]
        pa, pb = a + size, b + size
    return mapping


def region(dl1, mapping, X, Y, inclusive=False):
    """X 的行号列表(1 起) 在 Y 里的对应区间：前后最近的已配对行之间的 Y 行（含块内自己配上的行）。返回 Y 行号(0 起)列表。
    inclusive=True 时把前后两个锚点行也算进来（考生把几行并成一行时，内容常落在锚点行里）。"""
    if not dl1:
        return []
    lo_x, hi_x = min(dl1) - 1, max(dl1) - 1
    inc = 0 if inclusive else 1
    start = 0
    for i in range(lo_x - 1, -1, -1):
        if i in mapping:
            start = max(j for j, _ in mapping[i]) + inc
            break
    end = len(Y) - 1
    for i in range(hi_x + 1, len(X)):
        if i in mapping:
            end = min(j for j, _ in mapping[i]) - inc
            break
    return [j for j in range(start, end + 1) if Y[j].strip()]


def mapped(dl1, mapping):
    out = []
    for x in dl1:
        for j, _ in mapping.get(x - 1, []):
            if j not in out:
                out.append(j)
    return sorted(out)


# ---------- 字符位置映射 ----------
def map_pos(a, c, p, side):
    """把 a 里的位置 p 映射到 c 里；落在改动区时，起点取前一段相同文字的末尾、终点取后一段相同文字的开头。"""
    blocks = difflib.SequenceMatcher(None, a, c, autojunk=False).get_matching_blocks()
    prev_end_c = 0
    for i, j, size in blocks:
        if size == 0:
            return prev_end_c if side == "start" else len(c)
        if (side == "start" and i <= p < i + size) or (side == "end" and i < p <= i + size):
            return j + (p - i)
        if p < i:
            return prev_end_c if side == "start" else j
        prev_end_c = j + size
    return len(c)


def parse_ctx(ctx):
    s = ctx
    if s.startswith("…"):
        s = s[1:]
    if s.endswith("…"):
        s = s[:-1]
    i, k = s.find("【"), s.rfind("】")
    if i < 0 or k < i:
        return None
    return s[:i], s[i + 1:k], s[k + 1:]


# ---------- 判块 ----------
def cand_text_for(bl, C, dmap, D):
    """句内块：考生稿里对应的行（块所在交付行配上的行；没配上就取前后锚点之间的区间）。"""
    js = mapped(bl["d_lines"], dmap)
    how = "配对行"
    if not js:
        js = region(bl["d_lines"], dmap, D, C)
        how = "锚点区间"
    if not js and bl["type"] != "删除":
        js = region(bl["d_lines"], dmap, D, C, inclusive=True)
        how = "锚点区间（含锚点行）"
    return "¶".join(C[j] for j in js), js, how


def judge_window(bl, D, C, dmap):
    a = "¶".join(D[x - 1] for x in bl["d_lines"])
    pd = parse_ctx(bl.get("delivered_context", ""))
    pf = parse_ctx(bl.get("final_context", ""))
    if not pd or not pf:
        return None
    dw = pd[0] + pd[1] + pd[2]
    fw = pf[0] + pf[1] + pf[2]
    pos = a.find(dw)
    if pos < 0:  # 合并块的上下文可能来自别的行，退到全文找
        allD = "¶".join(D)
        pos2 = allD.find(dw)
        if pos2 < 0:
            return None
        lnum = allD[:pos2].count("¶") + 1
        bl = dict(bl, d_lines=[lnum])
        a = D[lnum - 1]
        pos = a.find(dw)
        if pos < 0:
            return None
    c, js, how = cand_text_for(bl, C, dmap, D)
    s0 = map_pos(a, c, pos, "start")
    s1 = map_pos(a, c, pos + len(dw), "end")
    cw = c[s0:max(s0, s1)]
    raw = bl["scope"] == "格式" or bl["type"] in ("拆段", "并段")
    f = (lambda t: re.sub(r"\s+", "", t)) if raw else (lambda t: norm(t).replace("¶", ""))
    nd, nf, nc = f(dw), f(fw), f(cw)
    sd, sf = ratio(nc, nd), ratio(nc, nf)
    if nc == nd or (nd and nd in f(c)):
        status = "没改"
    elif sf > sd + 1e-9:
        status = "朝定稿方向"
    elif not f(c):
        status = "考生删了这句"
    elif not nc:
        status = "定位不到（考生重写了整句）"
    else:
        status = "改了但没朝定稿方向"
    method = "窗口比对"
    if status not in ("没改", "考生删了这句") and (max(sd, sf) < 0.5 or how != "配对行"):
        # 窗口对齐不可靠时做出现检验：交付版写法（带 4 字上下文）、用户版写法各自在考生对应文字里还在不在
        nc_all = f(c)
        def present(left, mid, right):
            l, m, r = f(left)[-4:], f(mid), f(right)[:4]
            if not m:
                return (l + r) in nc_all if (l or r) else False
            return (l + m) in nc_all or (m + r) in nc_all
        dp = present(pd[0], pd[1], pd[2])
        fp = present(pf[0], pf[1], pf[2])
        if dp and not fp:
            status, method = "没改", "出现检验"
        elif fp and not dp:
            status, method = "朝定稿方向", "出现检验"
        else:
            bw = best_local(nc_all, nd, nf)
            if bw and max(bw[1], bw[2]) >= 0.5:
                w, sd, sf = bw
                cw = w
                status = "没改" if w == nd else ("朝定稿方向" if sf > sd + 1e-9 else "改了但没朝定稿方向")
                method = "局部最佳窗口"
            elif max(sd, sf) < 0.5:
                status, method = "改了，方向不明（对齐不可靠）", "窗口比对（不可靠）"
    return dict(method=method, hit=status == "朝定稿方向", status=status, sim_to_delivered=round(sd, 3),
                sim_to_final=round(sf, 3), cand_window=cw, delivered_window=dw, final_window=fw,
                cand_lines=[j + 1 for j in js], cand_locate=how)


def best_local(text, nd, nf):
    """在考生对应文字里找和交付版窗口或用户版窗口最像的一段（长度取两者之一），返回 (那段, 与交付版相似度, 与用户版相似度)。"""
    best, out = -1.0, None
    for L in sorted({len(nd), len(nf)} - {0}):
        for i in range(0, max(1, len(text) - L + 1)):
            w = text[i:i + L]
            sd, sf = ratio(w, nd), ratio(w, nf)
            if max(sd, sf) > best:
                best, out = max(sd, sf), (w, sd, sf)
    return out


def judge_short_or_long_delete(bl, D, C, dmap):
    seg = norm(bl["delivered"])
    if len(seg) < SHORT_DEL:
        return judge_window(bl, D, C, dmap)
    c, js, how = cand_text_for(bl, C, dmap, D)
    keep = containment(seg, norm(c))
    hit = keep < DEL_KEEP
    return dict(method="删除段残留率", hit=hit, status="没了或明显压缩" if hit else "还在",
                keep_ratio=round(keep, 3), cand_lines=[j + 1 for j in js], cand_locate=how)


def judge_para_delete(bl, D, C, dmap):
    js = region(bl["d_lines"], dmap, D, C)
    c = "¶".join(C[j] for j in js)
    keep = containment(norm(bl["delivered"]), norm(c))
    hit = keep < DEL_KEEP
    return dict(method="删除段残留率", hit=hit, status="没了或明显压缩" if hit else "还在",
                keep_ratio=round(keep, 3), cand_lines=[j + 1 for j in js], cand_locate="锚点区间",
                cand_chars=len(norm(c)), delivered_chars=len(norm(bl["delivered"])))


def judge_para_rewrite(bl, D, C, dmap):
    js = mapped(bl["d_lines"], dmap)
    how = "配对行"
    if not js or len(js) < len([x for x in bl["d_lines"] if not mb.is_weak(D[x - 1])]) * 0.5:
        js = region(bl["d_lines"], dmap, D, C)
        how = "锚点区间"
    c = norm("¶".join(C[j] for j in js)).replace("¶", "")
    nd, nf = norm(bl["delivered"]), norm(bl["final"])
    sd, sf = ratio(c, nd), ratio(c, nf)
    if c == nd:
        status = "没改"
    elif sf > sd + 1e-9:
        status = "朝定稿方向"
    elif not c:
        status = "考生删了这段"
    else:
        status = "改了但没朝定稿方向"
    return dict(method="整段相似度", hit=status == "朝定稿方向", status=status, sim_to_delivered=round(sd, 3),
                sim_to_final=round(sf, 3), cand_lines=[j + 1 for j in js], cand_locate=how)


def best_line(text, L):
    best, bj = 0.0, None
    t = norm(text)
    for j, ln in enumerate(L):
        if not ln.strip() or mb.is_weak(ln):
            continue
        r = ratio(t, norm(ln))
        if r > best:
            best, bj = r, j
    return bj, best


def judge_move(bl, D, F, C, dmap, d2f, f2d):
    dls = [x for x in bl["d_lines"] if not mb.is_weak(D[x - 1])]
    fls = [x for x in bl["f_lines"] if not mb.is_weak(F[x - 1])]
    if not dls or not fls:
        return dict(method="调序", hit=False, status="无法判（缺行）")
    d_main = max(dls, key=lambda x: len(norm(D[x - 1])))
    f_main = max(fls, key=lambda x: len(norm(F[x - 1])))
    # 定稿里被挪段落所在的连续区间
    fs = sorted(set(fls))
    k = fs.index(f_main)
    lo = hi = f_main
    for x in reversed(fs[:k]):
        if all((not F[y - 1].strip()) or mb.is_weak(F[y - 1]) for y in range(x + 1, lo)):
            lo = x
        else:
            break
    for x in fs[k + 1:]:
        if all((not F[y - 1].strip()) or mb.is_weak(F[y - 1]) for y in range(hi + 1, x)):
            hi = x
        else:
            break
    block_d = set(bl["d_lines"])

    def anchor(direction):
        rng = range(hi, len(F)) if direction == "after" else range(lo - 2, -1, -1)
        for y in rng:
            if not F[y].strip() or mb.is_weak(F[y]) or (y + 1) in fls:
                continue
            if y in f2d and (f2d[y] + 1) not in block_d:
                return f2d[y]
        return None
    for direction in ("after", "before"):
        ad = anchor(direction)
        if ad is None:
            continue
        final_before = direction == "after"           # 定稿：被挪段落在锚点之前？
        deliv_before = (d_main - 1) < ad
        if deliv_before == final_before:
            continue                                   # 这个锚点看不出挪动，换另一侧
        cj, cs = best_line(D[d_main - 1], C)
        cj2, cs2 = best_line(F[f_main - 1], C)
        if cs2 > cs:
            cj, cs = cj2, cs2
        if cj is None or cs < MOVE_FIND:
            return dict(method="调序", hit=False, status="考生稿里找不到被挪段落", find_sim=round(cs, 3))
        ca = [j for j, _ in dmap.get(ad, [])]
        if not ca:
            aj, asim = best_line(D[ad], C)
            if aj is None or asim < MOVE_FIND:
                return dict(method="调序", hit=False, status="考生稿里找不到锚点段落")
            ca = [aj]
        cand_before = cj < min(ca)
        hit = cand_before == final_before
        return dict(method="调序", hit=hit, status="顺序与定稿一致" if hit else "顺序与交付版一致",
                    moved_line_cand=cj + 1, anchor_line_cand=min(ca) + 1, find_sim=round(cs, 3),
                    anchor_delivered_line=ad + 1)
    return dict(method="调序", hit=False, status="无法判（找不到能区分顺序的锚点）")


def judge_block(bl, D, F, C, dmap, d2f, f2d):
    t, s = bl["type"], bl["scope"]
    if t == "调序":
        return judge_move(bl, D, F, C, dmap, d2f, f2d)
    if s in ("句内", "格式"):
        if t == "删除":
            r = judge_short_or_long_delete(bl, D, C, dmap)
        else:
            r = judge_window(bl, D, C, dmap)
        if r is None:  # 上下文对不上时退到整段相似度
            r = judge_para_rewrite(bl, D, C, dmap) if bl["d_lines"] else dict(method="无", hit=False, status="无法定位")
            r["fallback"] = True
        return r
    if t == "删除":
        return judge_para_delete(bl, D, C, dmap)
    if bl["d_lines"]:
        return judge_para_rewrite(bl, D, C, dmap)
    return dict(method="无", hit=False, status="无法定位（纯新增整段）")


# ---------- 复核负担 ----------
PUNCT = re.compile(r"[^0-9A-Za-z一-鿿]")


def sentences(lines):
    out = []
    for ln in lines:
        if not ln.strip() or mb.is_weak(ln) or ln.startswith("<title>"):
            continue
        units = [ln] if ln.startswith("|") else re.split(r"(?<=[。！？；])", ln)
        for u in units:
            n = norm(u)
            if len(n) >= KEEP_SENT_MIN:
                out.append((u.strip(), n))
    return out


def review_burden(D, F, C):
    nF, nC = norm("\n".join(F)), norm("\n".join(C))
    pC = PUNCT.sub("", nC)
    hC = re.sub(r"\d+(?:\.\d+)?", "#", pC)
    csents = sentences(C)
    kept, changed = [], []
    seen = set()
    for raw, n in sentences(D):
        if n in seen or n not in nF:
            continue
        seen.add(n)
        kept.append(n)
        if n in nC:
            continue
        p = PUNCT.sub("", n)
        if p in pC:
            cls = "仅标点或符号"
        elif re.sub(r"\d+(?:\.\d+)?", "#", p) in hC:
            cls = "仅数字写法"
        else:
            bj, bs = None, 0.0
            for craw, cn in csents:
                r = difflib.SequenceMatcher(None, n, cn, autojunk=False)
                if r.real_quick_ratio() < 0.6 or r.quick_ratio() < 0.6:
                    continue
                rr = r.ratio()
                if rr > bs:
                    bs, bj = rr, craw
            cls = "改写" if bs >= 0.6 else "删除或大改"
            if cls == "改写":
                changed.append(dict(sentence=raw[:160], cls=cls, cand=bj[:160], _n=n, _c=norm(bj)))
                continue
        changed.append(dict(sentence=raw[:160], cls=cls))
    # 高频替换：同一处「旧→新」在 ≥3 句里出现（如对象名前统一加编号、单位统一换一种写法），只因这类替换而变的句子单独计
    pat_cnt, per = {}, []
    for c in changed:
        if c["cls"] != "改写":
            per.append(None)
            continue
        ops = difflib.SequenceMatcher(None, c["_n"], c["_c"], autojunk=False).get_opcodes()
        pats = {(c["_n"][i1:i2], c["_c"][j1:j2]) for t, i1, i2, j1, j2 in ops if t != "equal"}
        per.append(pats)
        for x in pats:
            pat_cnt[x] = pat_cnt.get(x, 0) + 1
    for c, pats in zip(changed, per):
        c.pop("_n", None)
        c.pop("_c", None)
        if pats and all(pat_cnt[x] >= 3 for x in pats):
            c["cls"] = "只因高频替换"
            c["patterns"] = ["%s→%s" % x for x in sorted(pats)]
    top = sorted(((v, k) for k, v in pat_cnt.items() if v >= 3), reverse=True)[:8]
    by = {}
    for c in changed:
        by[c["cls"]] = by.get(c["cls"], 0) + 1
    n = len(changed)
    return dict(user_kept_sentences=len(kept), cand_changed=n, by_class=by,
                within_tolerance=n <= TOLERANCE, over_tolerance=max(0, n - TOLERANCE),
                changed_rate=round(n / len(kept), 3) if kept else None,
                top_patterns=["「%s」→「%s」×%d" % (k[0], k[1], v) for v, k in top], items=changed)


# ---------- 数字 ----------
UNITS = ("万元|美元|工时|小时|分钟|pt|pp|kg|KG|km|cm|‰|%|W|万|亿|元|倍|天|日|单|件|张|套|个|人|箱|次|仓|周|月|年|点|城|家|份|项|条|档|层|行|处|列|位|名|只|支|瓶|贴|包|盒|袋|台|轮|期|批|组|对|款|种|类|段|步|号|D|h|g|L")
NUM_RE = re.compile(r"(?<![A-Za-z0-9.,])(?<![A-Za-z]-)([+−]?\d[\d,]*(?:\.\d+)?(?:[/\-:]\d+(?:\.\d+)?)*)\s?(" + UNITS + r")?")


def numbers(text):
    """与 _tools/finalize.py 的 numbers() 同一写法（抽数口径一致）。"""
    out = []
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"^\s*\d+\.\s", "", ln)
        ln = re.sub(r"^(#+\s*)\d+(\.\d+)*\s", r"\1", ln)
        ln = re.sub(r"见\s?\d+(\.\d+)*", "见", ln)
        ln = re.sub(r"\*\*\d+\.\*\*", "", ln)
        lines.append(ln)
    body = "\n".join(lines)
    for m in NUM_RE.finditer(body):
        out.append(m.group(1).replace("−", "-") + (m.group(2) or ""))
    return out


UNIT_ALIAS = {"KG": "kg", "h": "小时"}


def parse_num(tok):
    m = re.fullmatch(r"([+\-]?)(\d[\d,]*(?:\.\d+)?)(.*)", tok)
    if not m or re.search(r"[\d/:\-]", m.group(3)):
        return None
    v = float(m.group(2).replace(",", ""))
    if m.group(1) == "-":
        v = -v
    dec = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
    return v, UNIT_ALIAS.get(m.group(3), m.group(3)), dec


SCALE = {"W": 1e4, "万": 1e4, "亿": 1e8}
PCT = {"%", "pt", "pp"}


REL_RANK = {"相同": 0, "单位写法": 1, "符号写法": 2, "抹平": 3, "换算": 4, "取整（超过 0.1 容差）": 5}


def num_relation(a, b):
    """b 相对 a：'相同'（只差写法，如 KG/kg、W/万、正号）、'单位写法'（一边没带单位）、'符号写法'（正负号用文字表达）、
    '抹平'（百分比 / pt 差 ≤0.1，或四舍五入到更少位小数）、'换算'（W/万 与个数互换）；都不是返回 None。"""
    pa, pb = parse_num(a), parse_num(b)
    if not pa or not pb:
        return None
    (va, ua, da), (vb, ub, db) = pa, pb
    for sa, sb, signtag in ((va, vb, None), (abs(va), abs(vb), "符号写法")):
        sca, scb = SCALE.get(ua), SCALE.get(ub)
        if ua == ub or (sca and scb and sca == scb):
            if sa == sb:
                return signtag or "相同"
            if abs(sa - sb) <= PCT_TOL + 1e-9:
                return "抹平"
            if db < da and abs(sa - sb) <= 0.5 * 10 ** (-db) + 1e-9 and abs(sa - sb) <= ROUND_REL * max(abs(sa), 1e-9):
                return "取整（超过 0.1 容差）"
            continue
        if (ua == "" or ub == "") and sa == sb and ua not in SCALE and ub not in SCALE:
            return signtag or "单位写法"
        if (sca or scb) and not (sca and scb) and ua not in PCT and ub not in PCT:
            xa, xb = sa * (sca or 1), sb * (scb or 1)
            prec = 0.5 * 10 ** (-(db if scb else da)) * (scb or sca)
            if abs(xa - xb) <= prec + 1e-9:
                return "换算"
    return None


def best_relation(t, pool):
    best = None
    for c in pool:
        r = num_relation(t, c)
        if r and (best is None or REL_RANK[r] < REL_RANK[best[0]]):
            best = (r, c)
    return best


def ctx_of(tok, text, pad=14):
    flat = re.sub(r"\s+", " ", text)
    m0 = re.fullmatch(r"([+\-]?)(\d[\d,]*(?:\.\d+)?(?:[/\-:]\d+(?:\.\d+)?)*)(.*)", tok)
    if not m0:
        return ""
    sign = "[-−]" if m0.group(1) == "-" else re.escape(m0.group(1))
    pat = r"(?<![\d.,A-Za-z])" + sign + re.escape(m0.group(2)) + r"\s?" + re.escape(m0.group(3))
    m = re.search(pat, flat)
    if not m:
        return ""
    return flat[max(0, m.start() - pad):m.end() + pad]


def still_there(t, Dt, Ct):
    """抽数口径切词不同造成的假缺失（如「第3-5周」写成「第 3 到 5 周」、「3/8」并进「3/1-3/8」、「20~30 档」写成「20~30 元档」）：
    取交付版里这个数左边 4 个字，在考生稿里找「这 4 个字 + 10 字以内 + 同一串数字」。找到就返回考生稿里的那一段。"""
    m0 = re.fullmatch(r"[+\-]?(\d[\d,]*(?:\.\d+)?(?:[/\-:]\d+(?:\.\d+)?)*)(.*)", t)
    if not m0:
        return None
    parts = re.split(r"[/\-:]", m0.group(1))
    numpat = r"(?<![\d.])" + r"\D{1,3}".join(re.escape(x) for x in parts) + r"(?![\d.])"
    fd = re.sub(r"\s+", "", Dt)
    fc = re.sub(r"\s+", "", Ct)
    for md in re.finditer(numpat, fd):
        left = re.sub(r"[*#|]", "", fd[max(0, md.start() - 8):md.start()])[-4:]
        if len(left) < 2:
            continue
        mc = re.search(re.escape(left) + r".{0,10}?" + numpat, fc)
        if mc:
            return fc[mc.start():mc.end() + 4]
    return None


def trace_missing(t, Dt, Ct):
    """缺失的数：找交付版里含它的句子，在考生稿里找最像的句子；像（≥0.5）就看那句换成了什么数。"""
    ctx = ctx_of(t, Dt)
    dsent = None
    for raw, n in sentences(Dt.split("\n")):
        if ctx and norm(ctx[max(0, len(ctx) // 2 - 4):len(ctx) // 2 + 4]) in n:
            dsent = (raw, n)
            break
    if not dsent:
        return dict(trace="找不到原句")
    best, bs = None, 0.0
    for raw, n in sentences(Ct.split("\n")):
        r = ratio(dsent[1], n)
        if r > bs:
            best, bs = raw, r
    if bs >= 0.6:
        newnums = [x for x in dict.fromkeys(numbers(best)) if x not in set(numbers(dsent[0]))]
        return dict(trace="疑似改数" if newnums else "句子还在但这个数没了", cand_sentence=best[:160], cand_new_numbers=newnums)
    return dict(trace="随句删掉或整句重写")


def number_check(Dt, Ft, Ct, code_pattern=None):
    nd, nf, nc = set(numbers(Dt)), set(numbers(Ft)), numbers(Ct)
    snc = set(nc)
    both = [t for t in dict.fromkeys(numbers(Ft)) if t in nd]
    kept_ok, kept_soft, kept_missing = [], [], []
    for t in both:
        if t in snc:
            kept_ok.append(t)
            continue
        rel = best_relation(t, snc)
        if rel:
            kept_soft.append(dict(token=t, cand=rel[1], relation=rel[0]))
        elif still_there(t, Dt, Ct):
            kept_soft.append(dict(token=t, cand=still_there(t, Dt, Ct), relation="写法变了（数还在）"))
        else:
            kept_missing.append(dict(token=t, delivered_ctx=ctx_of(t, Dt), **trace_missing(t, Dt, Ct)))
    new = []
    for c in dict.fromkeys(nc):
        if c in nd:
            continue
        if c in nf:
            new.append(dict(token=c, cls="定稿也新增了这个数", ctx=ctx_of(c, Ct)))
            continue
        if code_pattern:
            m = re.fullmatch(r"(\d+)\D{0,2}", c)
            if m and any(x.group(1) == m.group(1) for x in re.finditer(code_pattern, Ct)):
                new.append(dict(token=c, cls="对象编号（约定要求对象名前带编号）", ctx=ctx_of(c, Ct)))
                continue
        rel = None
        for t in nd:
            r = num_relation(t, c)
            if r and (rel is None or REL_RANK[r] < REL_RANK[rel[0]]):
                rel = (r, t)
        if rel:
            new.append(dict(token=c, cls=rel[0], from_delivered=rel[1], ctx=ctx_of(c, Ct)))
        else:
            new.append(dict(token=c, cls="新增（待核）", ctx=ctx_of(c, Ct)))
    newc = {}
    for x in new:
        newc[x["cls"]] = newc.get(x["cls"], 0) + 1
    n_round = sum(1 for x in kept_soft if x["relation"].startswith("取整"))
    return dict(n_both=len(both), n_ok=len(kept_ok), n_soft=len(kept_soft) - n_round, n_round_over=n_round,
                n_missing=len(kept_missing), n_mismatch=len(kept_missing) + n_round,
                soft=kept_soft, missing=kept_missing, n_new=len(new), new_by_class=newc, new=new)


# ---------- 结构 ----------
def headings(L, level):
    pre = "#" * level + " "
    return [ln[len(pre):].strip() for ln in L if ln.startswith(pre)]


# ---------- 泄题复查 ----------
def corpus_text(patterns):
    files = []
    for pat in patterns:
        for p in glob.glob(os.path.expanduser(pat), recursive=True):
            if os.path.isfile(p) and p.endswith((".md", ".json", ".jsonl", ".txt")) and "_acceptance" not in p:
                files.append(p)
    txt = []
    for p in files:
        try:
            txt.append(norm(open(p, encoding="utf-8", errors="ignore").read()))
        except OSError:
            pass
    return "\n".join(txt), len(files)


def leak_scan(nC, nF, nD, corpus, G=15):
    fg = {nF[i:i + G] for i in range(len(nF) - G + 1)}
    dg = {nD[i:i + G] for i in range(len(nD) - G + 1)}
    d6 = {nD[i:i + 6] for i in range(len(nD) - 5)}
    idx = [i for i in range(len(nC) - G + 1) if nC[i:i + G] in fg and nC[i:i + G] not in dg]
    frags, cur = [], None
    for i in idx:
        if cur and i <= cur[1]:
            cur[1] = i + G
        else:
            if cur:
                frags.append(cur)
            cur = [i, i + G]
    if cur:
        frags.append(cur)
    out = []
    for s, e in frags:
        fr = nC[s:e]
        cov = [False] * len(fr)
        for i in range(len(fr) - 5):
            if fr[i:i + 6] in d6:
                for k in range(i, i + 6):
                    cov[k] = True
        new_chars = cov.count(False)
        if new_chars < 10:
            continue
        in_corpus = any(fr[i:i + G] in corpus for i in range(len(fr) - G + 1) if not all(cov[i:i + G]))
        out.append(dict(fragment=fr, new_chars=new_chars, in_rules_or_memory=in_corpus))
    return out


# ---------- 主流程 ----------
def score_paper(pdir, corpus_patterns, leak_flagged):
    pdir = os.path.abspath(pdir)
    p = os.path.basename(pdir.rstrip("/"))
    meta = {}
    if os.path.isfile(os.path.join(pdir, "meta.json")):
        meta = json.load(open(os.path.join(pdir, "meta.json"), encoding="utf-8"))
    generalize = meta.get("kind") == "generalize"
    Dt = open(os.path.join(pdir, "delivered.md"), encoding="utf-8").read()
    Ft = open(os.path.join(pdir, "final.md"), encoding="utf-8").read()
    Ct = open(os.path.join(pdir, "candidate.md"), encoding="utf-8").read()
    bj = json.load(open(os.path.join(pdir, "blocks.json"), encoding="utf-8"))
    D, F, C = Dt.split("\n"), Ft.split("\n"), Ct.split("\n")
    dmap = align(D, C)
    d2f_m = align(D, F)
    d2f = {i: v[0][0] for i, v in d2f_m.items()}
    f2d = {}
    for i, v in d2f_m.items():
        for j, _ in v:
            f2d.setdefault(j, i)
    res_blocks = []
    for bl in bj["blocks"]:
        r = judge_block(bl, D, F, C, dmap, d2f, f2d)
        w = max(bl["weight"]["d_lines"], bl["weight"]["f_lines"], 1)
        res_blocks.append(dict(id=bl["id"], category=bl["category"], type=bl["type"], scope=bl["scope"],
                               coverage=bl.get("coverage", ""), score=bl["score"], weight=w, note=bl.get("note", ""),
                               **r))

    def agg(sel):
        n = len(sel)
        h = sum(1 for x in sel if x["hit"])
        wn = sum(x["weight"] for x in sel)
        wh = sum(x["weight"] for x in sel if x["hit"])
        return dict(n=n, hit=h, rate=round(h / n, 3) if n else None, w=wn, w_hit=wh,
                    w_rate=round(wh / wn, 3) if wn else None)
    A = [x for x in res_blocks if x["category"] == "A" and x["score"] == "计入"]
    B = [x for x in res_blocks if x["category"] == "B" and x["score"] == "计入"]
    U = [x for x in res_blocks if x["score"] == "建议不计入分母"]
    by_type = {}
    for x in A:
        by_type.setdefault(x["type"], []).append(x)
    status_counts = {}
    for x in A:
        status_counts[x["status"]] = status_counts.get(x["status"], 0) + 1
    summary = dict(
        A=agg(A), A_full=agg([x for x in A if x["coverage"] == "全部"]),
        A_partial=agg([x for x in A if x["coverage"] == "部分"]),
        A_by_type={k: agg(v) for k, v in by_type.items()}, A_status=status_counts,
        B=agg(B), uncertain=[dict(id=x["id"], category=x["category"], hit=x["hit"], status=x["status"]) for x in U],
    )
    nD, nF, nC = norm(Dt), norm(Ft), norm(Ct)
    length = dict(delivered_chars=len(nD), final_chars=len(nF), cand_chars=len(nC),
                  cand_vs_delivered=round(len(nC) / len(nD), 3), final_vs_delivered=round(len(nF) / len(nD), 3),
                  cand_vs_delivered_zh=round(zh_count(Ct) / zh_count(Dt), 3),
                  final_vs_delivered_zh=round(zh_count(Ft) / zh_count(Dt), 3))
    struct = {k: dict(h1=headings(L, 1), h2=headings(L, 2)) for k, L in (("delivered", D), ("final", F), ("candidate", C))}
    frag_items = bj["unique_fragments"].get("items", [])
    weak_items = bj["unique_fragments"].get("weak_items", [])
    corpus, ncorp = corpus_text(corpus_patterns)
    scan = leak_scan(nC, nF, nD, corpus)
    leak = dict(strong_total=len(frag_items), strong_hits=[f["fragment"] for f in frag_items if norm(f["fragment"]) in nC],
                weak_total=len(weak_items), weak_hits=[f["fragment"] for f in weak_items if norm(f["fragment"]) in nC],
                scan_fragments=scan, scan_suspicious=[x for x in scan if not x["in_rules_or_memory"]],
                corpus_files=ncorp)
    out = dict(paper=p, name=bj.get("name", p), generalize=generalize, leak_flagged=p in leak_flagged,
               summary=summary, length=length, structure=struct, leak=leak, blocks=res_blocks)
    if not generalize:
        out["review_burden"] = review_burden(D, F, C)
        out["numbers"] = number_check(Dt, Ft, Ct, meta.get("code_pattern"))
    else:
        out["note"] = "推广题：只报篇幅比、结构和 B 类命中；A 类块的判定结果留在 blocks 里备查，不进汇总。"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("papers", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", nargs="*", default=[])
    ap.add_argument("--leak-flagged", default="")
    a = ap.parse_args()
    leak_flagged = {x.strip() for x in a.leak_flagged.split(",") if x.strip()}
    os.makedirs(a.out, exist_ok=True)
    allres = {}
    for pdir in a.papers:
        r = score_paper(pdir, a.corpus, leak_flagged)
        p = r["paper"]
        allres[p] = r
        json.dump(r, open(os.path.join(a.out, f"paper-{p}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        s = r["summary"]
        line = f"{p} {r['name'][:10]}  "
        if not r["generalize"]:
            line += (f"A {s['A']['hit']}/{s['A']['n']}={s['A']['rate']}  加权 {s['A']['w_hit']}/{s['A']['w']}={s['A']['w_rate']}  "
                     f"B {s['B']['hit']}/{s['B']['n']}  复核 {r['review_burden']['cand_changed']}/{r['review_burden']['user_kept_sentences']}  "
                     f"数 缺{r['numbers']['n_missing']} 抹{r['numbers']['n_soft']}/{r['numbers']['n_both']} 新增待核 {r['numbers']['new_by_class'].get('新增（待核）', 0)}  ")
        else:
            line += f"B {s['B']['hit']}/{s['B']['n']}  "
        line += (f"篇幅 {r['length']['cand_vs_delivered']} vs 定稿 {r['length']['final_vs_delivered']}  "
                 f"泄题 强{len(r['leak']['strong_hits'])}/{r['leak']['strong_total']} 弱{len(r['leak']['weak_hits'])}/{r['leak']['weak_total']} "
                 f"通扫可疑 {len(r['leak']['scan_suspicious'])}")
        print(line)
    # 汇总（不含推广题与标了可能偷看的卷）
    pool = [p for p, r in allres.items() if not r["generalize"] and p not in leak_flagged]
    tot = dict(n=0, hit=0, w=0, w_hit=0, Bn=0, Bh=0)
    for p in pool:
        s = allres[p]["summary"]
        tot["n"] += s["A"]["n"]
        tot["hit"] += s["A"]["hit"]
        tot["w"] += s["A"]["w"]
        tot["w_hit"] += s["A"]["w_hit"]
        tot["Bn"] += s["B"]["n"]
        tot["Bh"] += s["B"]["hit"]
    tot["rate"] = round(tot["hit"] / tot["n"], 3) if tot["n"] else None
    tot["w_rate"] = round(tot["w_hit"] / tot["w"], 3) if tot["w"] else None
    tot["papers"] = pool
    rates = [allres[p]["summary"]["A"]["rate"] for p in pool if allres[p]["summary"]["A"]["rate"] is not None]
    tot["macro_rate"] = round(sum(rates) / len(rates), 3) if rates else None
    json.dump(dict(pooled=tot, thresholds=dict(DEL_KEEP=DEL_KEEP, SHORT_DEL=SHORT_DEL, PAIR_SIM=PAIR_SIM, MOVE_FIND=MOVE_FIND,
                                               KEEP_SENT_MIN=KEEP_SENT_MIN, TOLERANCE=TOLERANCE, PCT_TOL=PCT_TOL)),
              open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("汇总", tot)


if __name__ == "__main__":
    main()
