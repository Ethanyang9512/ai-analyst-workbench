#!/usr/bin/env python3
"""合成一份考卷的 blocks.json：自动切块（make_blocks）＋ 人工分类（spec.json）＋ 统计、数字清单、定稿独有片段。

用法：
  python3 finalize.py --paper <考卷目录> [--spec spec.json] [--rules rules.json]
                      [--corpus <文件或通配> ...] [--lexicon style-lexicon.md] [--sources <项目目录> ...]

考卷目录里要有：
  delivered.md   交付版（考生拿到的那份）
  final.md       用户定稿（答案，考生绝不能读到）
  spec.json      人工分类（默认就在考卷目录里），写法见 exam/README.md「出考卷」
  meta.json      可选：{"name": 考卷名, "kind": "normal" | "generalize", "note": 成对稿的来历, "coarse": false}
  rules.json     可选（默认就在考卷目录里）：规则出处 {key: {"file": 相对 rules.json 的路径, "quote": 原句片段}}。
                 A 类块必须引用至少一条规则；生成时逐条核对原句确实在规则文件里，对不上就报错退出。

--corpus  规则和记忆的原文（技能 md、台账、记忆文件），用来剔除“考生照规则改也写得出来”的片段；不给就只用 rules.json 引到的文件。
--lexicon 写作台账（如 skills/ethan-report-writing/references/style-lexicon.md）：给了就统计“一、硬禁”表里的词在交付版、定稿里各出现几次。
--sources 考卷所在的真实项目目录：每条“定稿独有片段”会列出这些目录里哪些文件也含这段字（多是定稿回读、改稿后的构建脚本），
          开考前要把这些文件一并挡住，否则这条片段不能当泄题证据。

没有 spec.json 时，只写 blocks_draft.json（自动切出来的块），供你逐块分类。
只读输入，只写考卷目录里的 blocks.json / blocks_draft.json。
"""
import argparse
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_blocks as mb  # noqa: E402

UNITS = ("万元|美元|工时|小时|分钟|pt|pp|kg|KG|km|cm|‰|%|W|万|亿|元|倍|天|日|单|件|张|套|个|人|箱|次|仓|周|月|年|点|城|家|份|项|条|档|层|行|处|列|位|名|只|支|瓶|贴|包|盒|袋|台|轮|期|批|组|对|款|种|类|段|步|号|D|h|g|L")
NUM_RE = re.compile(r"(?<![A-Za-z0-9.,])(?<![A-Za-z]-)([+−]?\d[\d,]*(?:\.\d+)?(?:[/\-:]\d+(?:\.\d+)?)*)\s?(" + UNITS + r")?")
CATEGORY_DEF = {
    "A": "规则覆盖：现行规则（写作技能、台账、图表规范、故事线技能、写作类记忆、用户明确定过的规矩）有明写的规则能推出这处改法",
    "B": "规则没写到的写法改动（含规则方向相反的）",
    "C": "事实或口径改动、非写法改动，不计分",
}


def norm(t):
    return mb.strip_md(t)


def zh_count(t):
    return len(re.findall(r"[一-鿿]", t))


def numbers(text):
    out = []
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"^\s*\d+\.\s", "", ln)                 # 有序列表编号
        ln = re.sub(r"^(#+\s*)\d+(\.\d+)*\s", r"\1", ln)     # 小节编号 2.1 / 5.2
        ln = re.sub(r"见\s?\d+(\.\d+)*", "见", ln)              # （见 2.3）交叉引用
        ln = re.sub(r"\*\*\d+\.\*\*", "", ln)                # **1.** 这类加粗编号
        lines.append(ln)
    body = "\n".join(lines)
    for m in NUM_RE.finditer(body):
        out.append(m.group(1).replace("−", "-") + (m.group(2) or ""))
    return out


def count_list(tokens):
    seen, res = {}, []
    for t in tokens:
        if t not in seen:
            seen[t] = 0
            res.append(t)
        seen[t] += 1
    return [(t, seen[t]) for t in res]


def hardban_terms(path):
    """台账“## 一、硬禁”表第一列的词（同一格里用 / 分开的算几个）。"""
    txt = open(path, encoding="utf-8").read()
    if "## 一、硬禁" not in txt:
        return []
    sec = txt.split("## 一、硬禁")[1].split("## 二、")[0]
    terms = []
    for ln in sec.split("\n"):
        if ln.startswith("|") and not ln.startswith("|---") and "禁用" not in ln:
            cell = ln.split("|")[1].strip()
            terms += [t.strip() for t in re.split(r"\s*/\s*", cell) if t.strip()]
    return terms


def load_rules(path):
    """rules.json → {key: (绝对路径, 原句)}；逐条核对原句在文件里。"""
    if not path or not os.path.isfile(path):
        return {}
    base = os.path.dirname(os.path.abspath(path))
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        fp = v["file"] if os.path.isabs(v["file"]) else os.path.join(base, v["file"])
        fp = os.path.expanduser(fp)
        with open(fp, encoding="utf-8") as f:
            if v["quote"] not in f.read():
                raise SystemExit(f"规则原句找不到：{k}（{fp}）")
        out[k] = (fp, v["quote"])
    return out


def classification(entry):
    """spec.json 里一块的分类：{"category", "rules", "note", "author", "score", "coverage"}。"""
    if not isinstance(entry, dict) or entry.get("category") not in ("A", "B", "C"):
        raise SystemExit(f"分类写法不对（要有 category: A/B/C）：{entry}")
    return entry


def apply_spec(name, sp, rules, blocks, D, F):
    byid = {b["id"]: b for b in blocks}
    for bid, ov in sp.get("override", {}).items():
        b = byid[bid]
        for k, v in ov.items():
            if k == "prepend_delivered":
                b["delivered"] = v + "\n" + b["delivered"]
                b.pop("delivered_context", None)
            else:
                b[k] = v
                if k in ("delivered", "final"):
                    b.pop(k + "_context", None)
    for tgt, srcs in sp.get("merge", {}).items():
        t = byid[tgt]
        t["merged_from"] = list(srcs)
        for s in srcs:
            b = byid[s]
            same_line = (t["scope"] in ("句内", "格式") and b["scope"] in ("句内", "格式")
                         and t["d_lines"] == b["d_lines"] and t["f_lines"] == b["f_lines"])
            if same_line:
                # 同一句里被切开的一处改动：直接给整行对照
                t["delivered"] = "\n".join(D[x - 1] for x in t["d_lines"])
                t["final"] = "\n".join(F[x - 1] for x in t["f_lines"])
                t.pop("delivered_context", None)
                t.pop("final_context", None)
            elif b["scope"] in ("句内", "格式"):
                # 连带的小改（如章节重新编号）记成子改动，不拼进正文
                t.setdefault("sub_edits", []).append({
                    "draft_id": s, "delivered": b.get("delivered_context") or b["delivered"],
                    "final": b.get("final_context") or b["final"]})
            else:
                def join(a, a_lines, c, c_lines):
                    if not c:
                        return a
                    if not a:
                        return c
                    before = c_lines and a_lines and min(c_lines) < min(a_lines)
                    return c + "\n" + a if before else a + "\n" + c
                t["delivered"] = join(t.get("delivered", ""), t["d_lines"], b.get("delivered", ""), b["d_lines"])
                t["final"] = join(t.get("final", ""), t["f_lines"], b.get("final", ""), b["f_lines"])
                t.pop("delivered_context", None)
                t.pop("final_context", None)
            t["d_lines"] = sorted(set(t["d_lines"]) | set(b["d_lines"]))
            t["f_lines"] = sorted(set(t["f_lines"]) | set(b["f_lines"]))
            b["_gone"] = True
        if t["type"] in ("删除", "新增") and t.get("delivered") and t.get("final"):
            t["type"] = "改写"
    kept = [b for b in blocks if not b.get("_gone")]
    cls = sp["cls"]
    missing = [b["id"] for b in kept if b["id"] not in cls]
    extra = [k for k in cls if k not in {b["id"] for b in kept}]
    if missing or extra:
        raise SystemExit(f"{name}: 未分类 {missing}；多余 {extra}")
    out = []
    for n, b in enumerate(kept, 1):
        c = classification(cls[b["id"]])
        cat = c["category"]
        refs = []
        for k in c.get("rules") or []:
            if k not in rules:
                raise SystemExit(f"{name} {b['id']}：rules.json 里没有规则 {k}")
            f, q = rules[k]
            refs.append({"file": os.path.basename(f), "quote": q})
        if cat == "A" and not refs:
            raise SystemExit(f"{name} {b['id']} 是 A 但没有规则出处")
        d_txt, f_txt = b.get("delivered", ""), b.get("final", "")
        item = {
            "id": f"B{n:02d}",
            "draft_id": b["id"],
            "type": b["type"],
            "scope": b["scope"],
            "category": cat,
            "rules": refs,
            "note": c.get("note", ""),
            "author": c.get("author", "用户亲笔"),
            "score": c.get("score", "不计（非写法）" if cat == "C" else "计入"),
            "coverage": c.get("coverage", "全部" if cat == "A" else ""),
            "delivered": d_txt,
            "final": f_txt,
        }
        if b.get("delivered_context"):
            item["delivered_context"] = b["delivered_context"]
            item["final_context"] = b["final_context"]
        if b.get("merged_from"):
            item["merged_from_draft"] = b["merged_from"]
        if b.get("sub_edits"):
            item["sub_edits"] = b["sub_edits"]
        if b.get("moved_from_section"):
            item["moved_from_section"] = b["moved_from_section"]
        item["section_delivered"] = b.get("section_delivered", "")
        item["section_final"] = b.get("section_final", "")
        item["d_lines"] = b["d_lines"]
        item["f_lines"] = b["f_lines"]
        item["weight"] = {
            "d_lines": len(b["d_lines"]), "f_lines": len(b["f_lines"]),
            "d_chars": len(norm(d_txt)), "f_chars": len(norm(f_txt)),
        }
        out.append(item)
    return out


SEP = re.compile(r"[/、与和及，,。；;：:（）()「」“”\"'—\-]")


def unique_fragments(D_text, blocks, corpus, k=15, max_n=12):
    """定稿独有片段：15 字以上、交付版里没有、规则与记忆原文里也没有、且至少 10 个字是用户新写的。考生稿里出现即疑似读过定稿。"""
    Dn = norm(D_text)
    corpus_alt = SEP.sub("", corpus) if corpus else ""
    cands = []
    for b in blocks:
        dt = norm(b["delivered"])
        for fl in (b["final"].replace("¶", "\n").split("\n") if b["final"] else []):
            ft = norm(fl)
            if len(ft) < k:
                continue
            ins = [True] * len(ft)
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, dt, ft, autojunk=False).get_opcodes():
                if tag == "equal":
                    for j in range(j1, j2):
                        ins[j] = False
            novel = [ft[p:p + k] not in Dn and ft[p:p + k] not in corpus for p in range(len(ft) - k + 1)]
            p = 0
            while p < len(novel):
                if novel[p]:
                    q = p
                    while q + 1 < len(novel) and novel[q + 1]:
                        q += 1
                    frag = ft[p:q + k]
                    n_ins = sum(ins[p:q + k])
                    if n_ins >= 10:
                        # 截到 ≤30 字，尽量把插入的字放在中间
                        if len(frag) > 30:
                            best, bs = 0, -1
                            for s in range(0, len(frag) - 30 + 1):
                                sc = sum(ins[p + s:p + s + 30])
                                if sc > bs:
                                    best, bs = s, sc
                            frag = frag[best:best + 30]
                            n_ins = bs
                        if frag not in Dn:
                            # 用户新写的部分里，6 字窗口有一半以上在规则/记忆原文里出现 → 考生照规则改也可能写出来
                            ins_txt = SEP.sub("", "".join(ch for ch, f_ in zip(ft[p:q + k], ins[p:q + k]) if f_))
                            grams = [ins_txt[i:i + 6] for i in range(max(1, len(ins_txt) - 5))]
                            cov = (sum(1 for g in grams if g in corpus_alt) / len(grams)) if (corpus and grams) else 0.0
                            if cov < 0.5:
                                cands.append({"fragment": frag, "inserted_chars": n_ins, "block": b["id"],
                                              "rule_text_overlap": round(cov, 2)})
                    p = q + 1
                else:
                    p += 1
    cands.sort(key=lambda x: (-x["inserted_chars"], -len(x["fragment"])))
    picked, used_blocks = [], {}
    for c in cands:
        if used_blocks.get(c["block"], 0) >= 2:
            continue
        if any(c["fragment"] in p["fragment"] or p["fragment"] in c["fragment"] for p in picked):
            continue
        picked.append(c)
        used_blocks[c["block"]] = used_blocks.get(c["block"], 0) + 1
        if len(picked) >= max_n:
            break
    return picked


_scan_cache = {}


def project_texts(root):
    if root in _scan_cache:
        return _scan_cache[root]
    res = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if not f.lower().endswith((".md", ".py", ".json", ".xml", ".txt", ".mmd", ".csv", ".html")):
                continue
            p = os.path.join(dp, f)
            try:
                if os.path.getsize(p) > 3_000_000:
                    continue
                raw = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            res.append((p, norm(re.sub(r"<[^>]+>", "", raw))))
    _scan_cache[root] = res
    return res


def where_found(frag, roots):
    return [p for root in roots for p, t in project_texts(root) if frag in t]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--rules")
    ap.add_argument("--corpus", nargs="*", default=[])
    ap.add_argument("--sources", nargs="*", default=[])
    ap.add_argument("--lexicon")
    a = ap.parse_args()
    paper = os.path.abspath(a.paper)
    name = os.path.basename(paper.rstrip("/"))
    dpath, fpath = os.path.join(paper, "delivered.md"), os.path.join(paper, "final.md")
    meta = {}
    if os.path.isfile(os.path.join(paper, "meta.json")):
        meta = json.load(open(os.path.join(paper, "meta.json"), encoding="utf-8"))
    mb.COARSE = bool(meta.get("coarse"))
    D, F, draft = mb.build(dpath, fpath)
    spec_path = a.spec or os.path.join(paper, "spec.json")
    if not os.path.isfile(spec_path):
        out = os.path.join(paper, "blocks_draft.json")
        json.dump(draft, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"没有 spec.json：只写了 {out}（{len(draft)} 块）。逐块分类后写 spec.json 再跑一次。")
        return
    sp = json.load(open(spec_path, encoding="utf-8"))
    rules = load_rules(a.rules or os.path.join(paper, "rules.json"))
    blocks = apply_spec(name, sp, rules, draft, D, F)

    corpus_files = sorted({p for pat in a.corpus for p in glob.glob(os.path.expanduser(pat), recursive=True)}
                          | {f for f, _ in rules.values()})
    corpus = "".join(norm(open(f, encoding="utf-8", errors="ignore").read()) for f in corpus_files if os.path.isfile(f))
    Dt = open(dpath, encoding="utf-8").read()
    Ft = open(fpath, encoding="utf-8").read()
    d_body = [i + 1 for i, ln in enumerate(D) if ln.strip() and not mb.is_weak(ln)]
    body_set = set(d_body)
    touched = set()
    for b in blocks:
        touched |= {x for x in b["d_lines"] if x in body_set}
    stats = {
        "delivered_chars": len(norm(Dt)), "final_chars": len(norm(Ft)),
        "length_ratio_chars": round(len(norm(Ft)) / len(norm(Dt)), 3),
        "delivered_zh": zh_count(Dt), "final_zh": zh_count(Ft),
        "length_ratio_zh": round(zh_count(Ft) / max(zh_count(Dt), 1), 3),
        "delivered_body_lines": len(d_body),
        "final_body_lines": len([1 for ln in F if ln.strip() and not mb.is_weak(ln)]),
        "delivered_lines_touched": len(touched),
        "delivered_lines_touched_ratio": round(len(touched) / max(len(d_body), 1), 3),
        "chars_def": "去掉 markdown 记号、[图片]/[画板] 占位和全部空白后的字符数；zh 只数汉字",
    }
    nf = count_list(numbers(Ft))
    nd = dict(count_list(numbers(Dt)))
    nf_d = dict(nf)
    num = {
        "note": "从 final.md 抽出的数字（含单位）及出现次数；added = 定稿有、交付版没有；removed = 交付版有、定稿没有。",
        "final": [{"token": t, "count": c} for t, c in nf],
        "added_vs_delivered": [t for t, _ in nf if t not in nd],
        "removed_vs_delivered": [t for t in nd if t not in nf_d],
    }
    frags = unique_fragments(Dt, blocks, corpus)
    weak = [f for f in unique_fragments(Dt, blocks, "", max_n=20)
            if not any(f["fragment"] in g["fragment"] or g["fragment"] in f["fragment"] for g in frags)][:10]
    roots = [os.path.abspath(os.path.expanduser(s)) for s in a.sources]
    for f in frags + weak:
        f["also_found_in_project"] = where_found(f["fragment"], roots) if roots else []
    cats = {c: sum(1 for b in blocks if b["category"] == c) for c in "ABC"}
    scored = [b for b in blocks if b["score"] == "计入"]
    counts = {
        "blocks": len(blocks), **cats,
        "A_full": sum(1 for b in blocks if b["category"] == "A" and b["coverage"] == "全部"),
        "A_partial": sum(1 for b in blocks if b["category"] == "A" and b["coverage"] == "部分"),
        "scored_blocks": len(scored),
        "scored_A": sum(1 for b in scored if b["category"] == "A"),
        "scored_B": sum(1 for b in scored if b["category"] == "B"),
        "author_uncertain": sum(1 for b in blocks if b["author"] != "用户亲笔"),
        "by_type": {t: sum(1 for b in blocks if b["type"] == t) for t in sorted({b["type"] for b in blocks})},
        "A_lines_weighted": sum(max(b["weight"]["d_lines"], b["weight"]["f_lines"]) for b in blocks if b["category"] == "A"),
        "all_lines_weighted": sum(max(b["weight"]["d_lines"], b["weight"]["f_lines"]) for b in blocks),
    }
    out = {
        "paper": name,
        "name": meta.get("name", name),
        "kind": meta.get("kind", "normal"),
        "sources": meta.get("sources", {}),
        "pair_note": meta.get("note", ""),
        "method": ("块由 make_blocks.py 切（行级 difflib → 改写行按字符级再切，相距 ≤8 字并成一处；整章/整节删除算 1 块；"
                   "同一张表里的改动合成 1 块；删除块与新增块文字覆盖 ≥0.65 记调序）"
                   + ("；本份按段落粗切（每个改动段落 1 块）" if mb.COARSE else "")
                   + "；分类与合并在 spec.json，规则原句在 rules.json，生成时逐条核对原句确实在规则文件里。"),
        "category_def": CATEGORY_DEF,
        "counts": counts,
        "stats": stats,
        "numbers": num,
        "unique_fragments": {"note": "15 字以上、交付版里没有、规则与记忆文本里也没有、且至少 10 个字是用户新写的片段；考生输出里出现即疑似读过定稿。"
                                     "比较时先去掉 markdown 记号与空白。also_found_in_project 列出项目目录里同样含这段字的文件，开考前要一并挡住，否则这条片段不能用。",
                             "items": frags,
                             "weak_note": "下面这些也是定稿独有、15 字以上，但片段里的用户新写部分在规则或记忆原文里出现过，考生照规则改也可能写出同样的字，只能当弱证据。",
                             "weak_items": weak},
        "blocks": blocks,
    }
    if a.lexicon:
        resid = [{"term": t, "delivered": Dt.count(t), "final": Ft.count(t)} for t in hardban_terms(a.lexicon)
                 if Dt.count(t) or Ft.count(t)]
        out["final_hardban_residuals"] = {"note": "台账硬禁词在交付版 / 定稿里的出现次数；定稿里仍有的，考生按规则改掉不算错，但要单独看（用户自己当时保留了）。",
                                          "items": resid}
    if meta.get("structure_note"):
        out["structure_note"] = meta["structure_note"]
    json.dump(out, open(os.path.join(paper, "blocks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(name, out["name"], counts["blocks"], "A/B/C", cats, "scored", counts["scored_blocks"],
          "ratio", stats["length_ratio_chars"], stats["length_ratio_zh"], "frags", len(frags))


if __name__ == "__main__":
    main()
