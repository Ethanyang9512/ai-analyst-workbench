#!/usr/bin/env python3
"""把 delivered.md → final.md 的用户改动切成「改动块」，输出草稿 blocks_draft.json（分类另行人工填）。

切法：
1. 按行（每行＝一个标题 / 段落 / 列表项 / 表格行）做 difflib 行级比对。
2. 相邻的非相等片段之间只隔着「弱行」（---、[图片]、[画板]、表格分隔行、图题表格的图片行）时合并。
3. 改写片段里，按相似度把交付版的行与定稿的行一一配对（允许一行拆两段、两段并一行）；
   配上的行再做字符级比对，相距 ≤ GAP 个字的改动并成一处，每处一块；配不上的行按整段删除 / 新增成块。
4. 纯删除的片段若以标题开头、覆盖到下一个同级或更高级标题为止，记为「整章删除」，算 1 块。
5. 删除块与新增块文字相近（相似度 ≥ MOVE_SIM）时合成一个「调序」块。
"""
import difflib
import json
import re
import sys

GAP = 8
COARSE = False
PAIR_SIM = 0.45
MOVE_SIM = 0.5


def is_weak(ln):
    s = ln.strip()
    return (s in ("---", "[图片]", "[画板]", "```", "")
            or re.fullmatch(r"\|(---\|)+", s) is not None
            or re.fullmatch(r"\|(\s*\[图片\]\s*\|)+", s) is not None)


def strip_md(t):
    t = re.sub(r"\[图片\]|\[画板\]|<title>|</title>", "", t)
    t = re.sub(r"[*#|>`]", "", t)
    t = re.sub(r"^\s*(\d+\.|-)\s", "", t, flags=re.M)
    t = re.sub(r"-{3,}", "", t)
    return re.sub(r"\s+", "", t)


def ratio(a, b):
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def heading_level(ln):
    m = re.match(r"^(#{1,6}) ", ln)
    return len(m.group(1)) if m else None


def section_of(lines, idx):
    """返回 idx 所在的标题路径（最近的 h1 / h2 / h3）。"""
    path = {}
    for i in range(0, min(idx + 1, len(lines))):
        lv = heading_level(lines[i])
        if lv:
            path[lv] = lines[i].lstrip("# ").strip()
            for k in list(path):
                if k > lv:
                    del path[k]
    return " > ".join(path[k] for k in sorted(path))


def is_pseudo_heading(ln):
    t = ln.strip()
    return heading_level(t) is None and re.fullmatch(r"\*\*[^*].*\*\*", t) is not None and len(strip_md(t)) <= 60


def split_segments(lines):
    """纯删除 / 纯新增的连续行按标题切开（同级或更高级标题另起一块；章内的子标题不切），
    不以标题开头的片段再按整行加粗的「小标题」（如问答的问句）切开。"""
    segs, cur, top = [], [], None
    for k, ln in lines:
        lv = heading_level(ln)
        if lv:
            if cur and (top is None or lv <= top):
                segs.append(cur)
                cur = []
            if not cur:
                top = lv
            cur.append((k, ln))
        elif is_pseudo_heading(ln) and top is None and any(not is_weak(x[1]) for x in cur):
            segs.append(cur)
            cur = [(k, ln)]
        else:
            cur.append((k, ln))
    if cur:
        segs.append(cur)
    return segs


def pair_lines(dl, fl):
    """单调配对（DP），允许 1:2 / 2:1 合并；返回 [(d_idx_list, f_idx_list, sim)]，未配上的单独返回。"""
    n, m = len(dl), len(fl)
    ds = [strip_md(x) for x in dl]
    fs = [strip_md(x) for x in fl]
    wd = [is_weak(x) for x in dl]
    wf = [is_weak(x) for x in fl]
    NEG = -1e9
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if best[i][j] == NEG:
                continue
            cur = best[i][j]
            cands = []
            if i < n:
                cands.append((i + 1, j, 0.0, ("d", [i], [])))
            if j < m:
                cands.append((i, j + 1, 0.0, ("f", [], [j])))
            if i < n and j < m:
                if wd[i] or wf[j]:
                    r = 1.0 if dl[i].strip() == fl[j].strip() else 0.0
                else:
                    r = ratio(ds[i], fs[j])
                if r >= PAIR_SIM:
                    cands.append((i + 1, j + 1, r * 2, ("p", [i], [j], r)))
            if i < n and j + 1 < m and not (wd[i] or wf[j] or wf[j + 1]):
                r = ratio(ds[i], fs[j] + fs[j + 1])
                if r >= PAIR_SIM:
                    cands.append((i + 1, j + 2, r * 2 + 0.05, ("p", [i], [j, j + 1], r)))
            if i + 1 < n and j < m and not (wd[i] or wd[i + 1] or wf[j]):
                r = ratio(ds[i] + ds[i + 1], fs[j])
                if r >= PAIR_SIM:
                    cands.append((i + 2, j + 1, r * 2 + 0.05, ("p", [i, i + 1], [j], r)))
            for ni, nj, gain, op in cands:
                if cur + gain > best[ni][nj]:
                    best[ni][nj] = cur + gain
                    back[ni][nj] = (i, j, op)
    ops = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, op = back[i][j]
        ops.append(op)
        i, j = pi, pj
    ops.reverse()
    return ops


def char_spans(a, b):
    """字符级改动处：返回 [(a_start, a_end, b_start, b_end)]，相距 ≤ GAP 的合并。"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    spans = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
    merged = []
    for s in spans:
        if merged and s[0] - merged[-1][1] <= GAP and s[2] - merged[-1][3] <= GAP:
            p = merged[-1]
            merged[-1] = (p[0], s[1], p[2], s[3])
        else:
            merged.append(s)
    return merged


def context(t, s, e, pad=12):
    return (("…" if s > pad else "") + t[max(0, s - pad):s] + "【" + t[s:e] + "】" + t[e:e + pad]
            + ("…" if e + pad < len(t) else ""))


def _table_id(lines, n):
    """返回第 n 行（1 起）所在表格的起始行号；不是表格行返回 None。"""
    if n < 1 or n > len(lines) or not lines[n - 1].startswith("|"):
        return None
    k = n
    while k > 1 and lines[k - 2].startswith("|"):
        k -= 1
    return k


def merge_table_blocks(blocks, D, F):
    """同一张表里的多处改动合成一块（列增删、表头改名常常一改一整列）。"""
    out = []
    for b in blocks:
        td = {_table_id(D, x) for x in b["d_lines"]} if b["d_lines"] else set()
        tf = {_table_id(F, x) for x in b["f_lines"]} if b["f_lines"] else set()
        key = None
        if td and None not in td and len(td) == 1 and (not tf or (None not in tf and len(tf) == 1)):
            key = ("t", next(iter(td)))
        elif not td and tf and None not in tf and len(tf) == 1:
            key = ("f", next(iter(tf)))
        b["_tkey"] = key
        if key and out and out[-1].get("_tkey") == key:
            p = out[-1]
            p.setdefault("_parts", [dict(p)])
            p["_parts"].append(dict(b))
            p["d_lines"] = sorted(set(p["d_lines"]) | set(b["d_lines"]))
            p["f_lines"] = sorted(set(p["f_lines"]) | set(b["f_lines"]))
            p["type"] = "改写" if (p["d_lines"] and p["f_lines"]) else p["type"]
            p["scope"] = "表格"
            p["delivered"] = "\n".join(D[x - 1] for x in p["d_lines"])
            p["final"] = "\n".join(F[x - 1] for x in p["f_lines"])
            p.pop("delivered_context", None)
            p.pop("final_context", None)
            continue
        out.append(b)
    for b in out:
        b.pop("_tkey", None)
        parts = b.pop("_parts", None)
        if parts:
            b["table_edits"] = len(parts)
    return out


def build(dpath, fpath):
    D = open(dpath, encoding="utf-8").read().split("\n")
    F = open(fpath, encoding="utf-8").read().split("\n")
    sm = difflib.SequenceMatcher(None, D, F, autojunk=False)
    ops = [o for o in sm.get_opcodes()]
    # 合并只隔弱行的非相等片段
    groups = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if groups and groups[-1]["open"] and all(is_weak(x) for x in D[i1:i2]) and (i2 - i1) <= 3:
                groups[-1]["pending"] = (i1, i2, j1, j2)
                continue
            if groups:
                groups[-1]["open"] = False
            continue
        if groups and groups[-1]["open"] and groups[-1].get("pending"):
            g = groups[-1]
            g["i2"], g["j2"] = i2, j2
            g["pending"] = None
            continue
        if groups and groups[-1]["open"] and groups[-1]["i2"] == i1 and groups[-1]["j2"] == j1:
            groups[-1]["i2"], groups[-1]["j2"] = i2, j2
            continue
        groups.append(dict(i1=i1, i2=i2, j1=j1, j2=j2, open=True, pending=None))

    raw_blocks = []
    for g in groups:
        dl = [(k, D[k]) for k in range(g["i1"], g["i2"]) if D[k].strip()]
        fl = [(k, F[k]) for k in range(g["j1"], g["j2"]) if F[k].strip()]
        # 纯删除 / 纯新增：整体一块（弱行不单独成块）
        if not fl or not dl:
            real_d = [x for x in dl if not is_weak(x[1])]
            real_f = [x for x in fl if not is_weak(x[1])]
            if not real_d and not real_f:
                # 只有弱行的变化（例如多 / 少一条分隔线、一张图）
                if dl or fl:
                    raw_blocks.append(dict(kind="del" if dl else "ins", d=dl, f=fl, weak_only=True))
                continue
            for seg in split_segments(dl or fl):
                weak = all(is_weak(x[1]) for x in seg)
                raw_blocks.append(dict(kind="del" if dl else "ins", d=seg if dl else [], f=seg if fl else [],
                                       weak_only=weak))
            continue
        pairs = pair_lines([x[1] for x in dl], [x[1] for x in fl])
        pend_d, pend_f = [], []

        def flush():
            if pend_d or pend_f:
                rd = [x for x in pend_d if not is_weak(x[1])]
                rf = [x for x in pend_f if not is_weak(x[1])]
                if rd and not rf:
                    for seg in split_segments(pend_d):
                        raw_blocks.append(dict(kind="del", d=seg, f=[], weak_only=all(is_weak(x[1]) for x in seg)))
                elif rf and not rd:
                    for seg in split_segments(pend_f):
                        raw_blocks.append(dict(kind="ins", d=[], f=seg, weak_only=all(is_weak(x[1]) for x in seg)))
                elif rd or rf:
                    raw_blocks.append(dict(kind="rep" if (pend_d and pend_f) else ("del" if pend_d else "ins"),
                                           d=list(pend_d), f=list(pend_f)))
                elif pend_d or pend_f:
                    raw_blocks.append(dict(kind="del" if pend_d else "ins", d=list(pend_d), f=list(pend_f), weak_only=True))
                pend_d.clear()
                pend_f.clear()

        for op in pairs:
            if op[0] == "d":
                pend_d.append(dl[op[1][0]])
            elif op[0] == "f":
                pend_f.append(fl[op[2][0]])
            else:
                flush()
                dd = [dl[k] for k in op[1]]
                ff = [fl[k] for k in op[2]]
                a = "¶".join(x[1] for x in dd)
                b = "¶".join(x[1] for x in ff)
                spans = char_spans(a, b)
                if COARSE and spans:
                    spans = [(spans[0][0], spans[-1][1], spans[0][2], spans[-1][3])]
                # 加粗 / 去粗：同一行里成对出现的 ** 插入（或删除）合成一处
                merged, k = [], 0
                while k < len(spans):
                    s = spans[k]
                    is_on = a[s[0]:s[1]] == "" and b[s[2]:s[3]] == "**"
                    is_off = a[s[0]:s[1]] == "**" and b[s[2]:s[3]] == ""
                    if (is_on or is_off) and k + 1 < len(spans):
                        t = spans[k + 1]
                        if (is_on and a[t[0]:t[1]] == "" and b[t[2]:t[3]] == "**") or \
                           (is_off and a[t[0]:t[1]] == "**" and b[t[2]:t[3]] == ""):
                            merged.append((s[0], t[1], s[2], t[3], "加粗" if is_on else "去粗"))
                            k += 2
                            continue
                    merged.append(tuple(s) + (None,))
                    k += 1
                for s in merged:
                    raw_blocks.append(dict(kind="span", d=dd, f=ff, a=a, b=b, span=s[:4], sim=op[3], fmt=s[4]))
        flush()

    # 组装块
    blocks = []
    for rb in raw_blocks:
        d_lines = [x[0] + 1 for x in rb["d"]]
        f_lines = [x[0] + 1 for x in rb["f"]]
        if rb["kind"] == "span":
            a, b, (s1, e1, s2, e2) = rb["a"], rb["b"], rb["span"]
            dt, ft = a[s1:e1], b[s2:e2]
            typ = "删除" if not ft.strip() else ("新增" if not dt.strip() else "改写")
            if "¶" in ft and dt.replace("¶", "") == ft.replace("¶", ""):
                typ = "拆段"
            if "¶" in dt and dt.replace("¶", "") == ft.replace("¶", ""):
                typ = "并段"
            if rb.get("fmt"):
                typ = "改写"
                fmt = rb["fmt"]
            else:
                fmt = None
            blk = dict(type=typ, scope="句内" if not fmt else "格式", delivered=dt, final=ft,
                       delivered_context=context(a, s1, e1), final_context=context(b, s2, e2),
                       d_lines=d_lines, f_lines=f_lines)
        else:
            dt = "\n".join(x[1] for x in rb["d"])
            ft = "\n".join(x[1] for x in rb["f"])
            typ = {"del": "删除", "ins": "新增", "rep": "改写"}[rb["kind"]]
            blk = dict(type=typ, scope="整段", delivered=dt, final=ft, d_lines=d_lines, f_lines=f_lines)
            if rb.get("weak_only"):
                blk["scope"] = "版式"
        blk["section_delivered"] = section_of(D, (d_lines or [1])[0] - 1) if d_lines else ""
        blk["section_final"] = section_of(F, (f_lines or [1])[0] - 1) if f_lines else ""
        blocks.append(blk)

    # 整章删除：删除块以标题开头且覆盖到下一个同级或更高级标题
    for blk in blocks:
        if blk["type"] == "删除" and blk["scope"] == "整段" and blk["d_lines"]:
            first = D[blk["d_lines"][0] - 1]
            lv = heading_level(first)
            if lv:
                k = blk["d_lines"][0]
                end = len(D)
                while k < len(D):
                    l2 = heading_level(D[k])
                    if l2 and l2 <= lv:
                        end = k
                        break
                    k += 1
                body = [x for x in range(blk["d_lines"][0], end + 1) if D[x - 1].strip() and not is_weak(D[x - 1])]
                covered = set(blk["d_lines"])
                if body and sum(1 for x in body if x in covered) / len(body) >= 0.9:
                    blk["scope"] = "整章" if lv == 1 else "整节"

    # 调序：删除块 ↔ 新增块文字相近
    used = set()
    dels = [i for i, b in enumerate(blocks) if b["type"] in ("删除",) and b["scope"] != "句内"]
    inss = [i for i, b in enumerate(blocks) if b["type"] in ("新增", "改写") and b["scope"] != "句内"]
    for i in dels:
        best, bi = 0, None
        di = strip_md(blocks[i]["delivered"])
        if len(di) < 20:
            continue
        for j in inss:
            if j in used or j == i:
                continue
            fj = strip_md(blocks[j]["final"])
            if len(fj) < 20:
                continue
            if min(len(di), len(fj)) / max(len(di), len(fj)) < 0.4:
                continue
            sm2 = difflib.SequenceMatcher(None, di, fj, autojunk=False)
            # 以较短一侧为分母的覆盖率，避免长段吞短段
            cover = sum(m.size for m in sm2.get_matching_blocks()) / min(len(di), len(fj))
            if cover > best:
                best, bi = cover, j
        if bi is not None and best >= MOVE_SIM + 0.15:
            used.add(bi)
            mv = blocks[bi]
            mv["type"] = "调序"
            mv["moved_from_d_lines"] = blocks[i]["d_lines"]
            mv["moved_from_section"] = blocks[i]["section_delivered"]
            mv["delivered"] = (blocks[i]["delivered"] + ("\n" + mv["delivered"] if mv["delivered"] else ""))
            mv["d_lines"] = blocks[i]["d_lines"] + mv["d_lines"]
            mv["move_cover"] = round(best, 3)
            blocks[i]["_drop"] = True
    blocks = [b for b in blocks if not b.get("_drop")]
    blocks = merge_table_blocks(blocks, D, F)
    for n, b in enumerate(blocks, 1):
        b["id"] = f"B{n:02d}"
    return D, F, blocks


if __name__ == "__main__":
    if "--coarse" in sys.argv:
        COARSE = True
        sys.argv.remove("--coarse")
    d, f, out = sys.argv[1], sys.argv[2], sys.argv[3]
    D, F, blocks = build(d, f)
    json.dump(blocks, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(out, len(blocks), "blocks")
