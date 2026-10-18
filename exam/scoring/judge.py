#!/usr/bin/env python3
"""辅助评委：每份考卷按固定种子抽 N 个计分的 A 块，把（交付版、用户版、考生版）三元组交给另一个模型会话判方向。

这个评委只作参考，不替代 score_papers.py 的代码指标。用之前要先拿人工标注校准：
挑几十个块自己标一遍，看评委和你的一致率；一致率不够高，就只看代码指标。推广题不判 A 块。

先跑 score_papers.py（要用它定位到的考生稿行号）。
用法：python3 judge.py <考卷目录> [...] --scores <score_papers.py 的输出目录> [--model <模型>] [--n 10] [--seed 20261018] [--dry]
  --model  评委用的模型。建议和写稿、考试用的不是同一个型号（同一个模型给自己的改法打分会偏宽）。不给就用 Claude Code 的默认模型。
  --dry    只生成提示词（写到 <scores>/judge/prompt-*.txt），不调用模型。
调用：claude -p [--model M] --output-format json --no-session-persistence --tools "" --strict-mcp-config
（不带任何工具、不读写文件，只看提示里的三元组；同时最多跑 2 个）。
"""
import argparse
import json
import os
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

LABELS = ["同向", "部分", "没改", "反向", "改坏事实", "对不上"]


def clip(t, n):
    t = t.strip()
    return t if len(t) <= n else t[:n] + f"…（后略，共 {len(t)} 字）"


def mark(lines_txt, ctx):
    """在整行里用【】标出改动处（按 blocks.json 的上下文定位）；定位不到就原样返回。"""
    if not ctx:
        return lines_txt
    s = ctx[1:] if ctx.startswith("…") else ctx
    s = s[:-1] if s.endswith("…") else s
    i, k = s.find("【"), s.rfind("】")
    if i < 0 or k < i:
        return lines_txt
    left, mid, right = s[:i], s[i + 1:k], s[k + 1:]
    pos = lines_txt.find(left + mid + right)
    if pos < 0:
        return lines_txt
    a = pos + len(left)
    return lines_txt[:a] + "【" + mid + "】" + lines_txt[a + len(mid):]


def around(t, n=360):
    i = t.find("【")
    if i < 0 or len(t) <= n:
        return clip(t, n)
    a = max(0, i - n // 2)
    return ("…" if a else "") + t[a:a + n] + ("…" if a + n < len(t) else "")


def triples(pdir, scores, n_per, seed):
    p = os.path.basename(pdir.rstrip("/"))
    D = open(os.path.join(pdir, "delivered.md"), encoding="utf-8").read().split("\n")
    F = open(os.path.join(pdir, "final.md"), encoding="utf-8").read().split("\n")
    C = open(os.path.join(pdir, "candidate.md"), encoding="utf-8").read().split("\n")
    bj = {b["id"]: b for b in json.load(open(os.path.join(pdir, "blocks.json"), encoding="utf-8"))["blocks"]}
    sc = json.load(open(os.path.join(scores, f"paper-{p}.json"), encoding="utf-8"))
    if sc.get("generalize"):
        return p, []
    pool = [x for x in sc["blocks"] if x["category"] == "A" and x["score"] == "计入"]
    rnd = random.Random(f"{seed}-{p}")
    pick = sorted(rnd.sample(pool, min(n_per, len(pool))), key=lambda x: x["id"])
    out = []
    for x in pick:
        b = bj[x["id"]]
        if b["scope"] in ("句内", "格式"):
            dtx = around(mark("¶".join(D[i - 1] for i in b["d_lines"]), b.get("delivered_context", "")))
            ftx = around(mark("¶".join(F[i - 1] for i in b["f_lines"]), b.get("final_context", "")))
        else:
            dtx = clip(b["delivered"], 600) or "（交付版此处没有文字）"
            ftx = clip(b["final"], 600) or "（用户把这段整段删掉了）"
        cl = x.get("cand_lines") or []
        ctx = "¶".join(C[j - 1] for j in cl)
        if x.get("cand_window") and len(ctx) > 600:
            i = ctx.find(x["cand_window"][:12]) if x["cand_window"] else -1
            a = max(0, i - 200) if i >= 0 else 0
            ctx = ("…" if a else "") + ctx[a:a + 600] + "…"
        ctx = clip(ctx, 700) if ctx else "（考生稿在对应位置找不到这段文字，可能删掉了，也可能挪走或整段重写）"
        out.append(dict(id=x["id"], type=b["type"], scope=b["scope"], delivered=dtx, user=ftx, candidate=ctx,
                        code_hit=x["hit"], code_status=x["status"]))
    return p, out


PROMPT = """你是一个审稿评委。背景：一位分析师（下称“用户”）拿到 AI 写的业务分析文档初稿（交付版），亲手改成了定稿（用户版）。现在另一个 AI（下称“考生”）也拿同一份交付版做了一遍“交付前自查修改”，没有看过用户版。
下面每一条是同一位置的三段文字：交付版（【】里是用户改动的地方；整段删除或整段改写时给出整段）、用户版、考生版（考生稿里对应位置的整行或整段，可能比要比较的部分长，请自己找到对应的那一处）。

请判断：在这一处，考生的修改和用户的修改方向是否一致。只能从下面 6 个标签里选一个：
- 同向：考生做了和用户本质相同的改动（措辞不必一样，效果和意图一致，例如用户删掉的话考生也删了，用户换掉的说法考生也换成了意思相同的说法）。
- 部分：方向一致但只做了一部分，或者做法明显不同但部分达到了用户的效果。
- 没改：考生在这一处保留了交付版的写法。
- 反向：考生朝相反方向改（例如用户删减的地方考生反而扩写、用户去掉的说法考生加强了）。
- 改坏事实：考生在这一处改动了数字、口径或事实含义，而且改得和交付版、用户版都不一致，可能改错了。
- 对不上：考生版这段文字和交付版这一处明显不对应，无法判断。

每条必须在 reason 里用引号引出考生版的原话（找不到对应原话时说明），一句话说明判断依据。
只输出一个 JSON 数组，不要其他文字，格式：[{"id": "B01", "label": "同向", "reason": "…"}]

以下是 {n} 条：
{items}
"""


def build_prompt(trs):
    items = []
    for t in trs:
        items.append(f"### {t['id']}（{t['type']}，{t['scope']}）\n交付版：{t['delivered']}\n用户版：{t['user']}\n考生版：{t['candidate']}\n")
    return PROMPT.replace("{n}", str(len(trs))).replace("{items}", "\n".join(items))


def run(args, pdir, out_dir):
    p, trs = triples(pdir, args.scores, args.n, args.seed)
    if not trs:
        return p, trs, None
    prompt = build_prompt(trs)
    open(os.path.join(out_dir, f"prompt-{p}.txt"), "w", encoding="utf-8").write(prompt)
    if args.dry:
        return p, trs, None
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--tools", "", "--strict-mcp-config"]
    if args.model:
        cmd[2:2] = ["--model", args.model]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=out_dir, timeout=900)
    open(os.path.join(out_dir, f"raw-{p}.json"), "w", encoding="utf-8").write(r.stdout)
    res = json.loads(r.stdout)
    txt = res.get("result", "")
    m = re.search(r"\[.*\]", txt, re.S)
    labels = json.loads(m.group(0)) if m else []
    lab = {x["id"]: x for x in labels}
    for t in trs:
        j = lab.get(t["id"], {})
        t["judge_label"] = j.get("label") if j.get("label") in LABELS else None
        t["judge_reason"] = j.get("reason")
    return p, trs, dict(cost_usd=res.get("total_cost_usd"), duration_ms=res.get("duration_ms"), is_error=res.get("is_error"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("papers", nargs="+")
    ap.add_argument("--scores", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261018)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    out_dir = os.path.join(args.scores, "judge")
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        for p, trs, meta in ex.map(lambda d: run(args, d, out_dir), args.papers):
            results[p] = dict(items=trs, meta=meta)
            print(p, len(trs), meta)
    if args.dry:
        print("只生成了提示词：", out_dir)
        return
    agree = tot = 0
    summ = {}
    for p, r in results.items():
        if not r["items"]:
            continue
        c = {}
        a = n = 0
        for t in r["items"]:
            lb = t.get("judge_label")
            c[lb] = c.get(lb, 0) + 1
            if lb in ("同向", "部分", "没改", "反向", "改坏事实"):
                n += 1
                judge_hit = lb in ("同向", "部分")
                a += int(judge_hit == t["code_hit"])
        summ[p] = dict(labels=c, comparable=n, agree_with_code=a, cost_usd=(r["meta"] or {}).get("cost_usd"))
        agree += a
        tot += n
    out = dict(note="这个评委没经校准前只作参考；『一致』指评委判同向或部分 ↔ 代码判命中，评委判没改/反向/改坏事实 ↔ 代码判未命中；『对不上』不计。",
               model=args.model or "（默认）", seed=args.seed, per_paper=summ, agree=agree, comparable=tot,
               agree_rate=round(agree / tot, 3) if tot else None, results=results)
    json.dump(out, open(os.path.join(out_dir, "judge_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("一致", agree, "/", tot, summ)


if __name__ == "__main__":
    main()
