#!/usr/bin/env python3
"""验收记录工具的回归测试：python3 test_accept_record.py
全部在临时目录里跑（AAW_WS_BASE 指向假的工作区总目录），不碰正式工作区。
分档上线时间（AAW_TIER_START）设成 2026-01-14 20:00（UTC+8）来测“中途才开始分档”的情况；最后另起进程测不设它的情况。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "accept_record.py")
TMP = os.path.realpath(tempfile.mkdtemp(prefix="aaw-accept-"))
BASE = os.path.join(TMP, "workspaces")          # 假的工作区总目录
WS = os.path.join(BASE, "ws1")                  # 假的工作区
WS2 = os.path.join(BASE, "ws2")                 # 还没有任何记录的工作区
WS3 = os.path.join(BASE, "ws3")                 # 测页数阈值用
SUB = os.path.join(WS, "out", "ppt")
OUTSIDE = os.path.join(TMP, "outside")
RECS = os.path.join(WS, "_acceptance", "records.jsonl")
TIER = "2026-01-14T20:00:00+08:00"
ENV = dict(os.environ, AAW_WS_BASE=BASE, AAW_TIER_START=TIER)
RA = ["--reader", "冷读通过", "--visual", "看过 3 页，核了 2 个数"]
os.environ["AAW_WS_BASE"] = BASE             # 进程内调用也只碰临时目录
os.environ["AAW_TIER_START"] = TIER
sys.path.insert(0, HERE)
import accept_record as rec  # noqa: E402

T0 = rec.TIER_START.timestamp()                 # 分档上线时间；造记录时按它前后放


def ws_with(name, *items):
    """新建一个只有给定记录的假工作区，返回它的目录。"""
    root = os.path.join(BASE, name)
    put(os.path.join(root, "_acceptance", "records.jsonl"), "")
    append(os.path.join(root, "_acceptance", "records.jsonl"), *items)
    return root


def item(ts, epoch, tier=None, pages=None):
    r = {"ts": ts, "epoch": int(epoch), "files": [], "doc": "x", "reader": "ok", "visual": "ok", "note": ""}
    if tier:
        r["tier"] = tier
    if pages is not None:
        r["pages"] = pages
    return r


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run(args, cwd=WS):
    p = subprocess.run([sys.executable, TOOL] + args, cwd=cwd, capture_output=True, text=True, env=ENV)
    return p.returncode, p.stdout + p.stderr


def status(cwd=WS, extra=()):
    code, out = run(["status", "--json"] + list(extra), cwd=cwd)
    return json.loads(out) if code == 0 else {"exit": code}


def lines(root=WS):
    return rec.load(root)       # 跳过坏行


def append(path, *items):
    with open(path, "a", encoding="utf-8") as f:
        for x in items:
            f.write((x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) + "\n")


def main():
    res = []
    ok = lambda name, got, want: res.append((name, got, want))
    put(os.path.join(SUB, "deck.pptx"), "deck v1")
    put(os.path.join(WS3, "d.pptx"), "d")
    os.makedirs(WS2)
    os.makedirs(OUTSIDE)

    # ---- write：旧写法照常，新参数写进记录
    ok("旧写法（不带 --tier）照常写入", run(["write", "--file", "out/ppt/deck.pptx"] + RA)[0], 0)
    ok("旧写法记为 unspecified、页为空", (lines()[-1]["tier"], lines()[-1]["pages"]), ("unspecified", ""))
    ok("带 --tier small --pages", run(["write", "--file", "out/ppt/deck.pptx", "--tier", "small", "--pages", "5,6"] + RA)[0], 0)
    ok("档位和页写进记录", (lines()[-1]["tier"], lines()[-1]["pages"]), ("small", "5,6"))
    n = len(lines())
    ok("--tier 只认 small/page/full", (run(["write", "--file", "out/ppt/deck.pptx", "--tier", "big"] + RA)[0],
                                        len(lines())), (2, n))
    ok("带档位的记录 check 照样认", run(["check", "--file", "out/ppt/deck.pptx"])[0], 0)
    ok("list 照常列出", "deck.pptx" in run(["list"])[1], True)

    # ---- status：还没有全稿记录
    s = status(WS2)
    ok("没有记录：说没有、不建议", (s["total_records"], s["suggest_full"], s["old_records"]), (0, False, 0))
    ok("没有记录：文字版说没有", "还没有验收记录" in run(["status"], cwd=WS2)[1], True)
    ok("没有记录：分档上线 10 天后也不催", rec.status(WS2, now=T0 + 10 * 86400)["suggest_full"], False)
    s = status()
    ok("不写档位的记录不算全稿", (s["last_full_ts"], s["counted_from"], s["records_since"]), (None, "tier_start", 2))
    ok("没有全稿时文字版说明", "以来还没有全稿验收（--tier full）" in run(["status"])[1], True)

    # ---- 没有 tier、pages 两个字段的记录，分档上线前的旧记录，坏行
    append(RECS, item("2026-01-14 20:30:00", T0 + 1800),
           item("2026-01-05 10:00:00", T0 - 9 * 86400, pages="1-20"),
           "not json", "[]", '"abc"', "123", "null")
    s = status()
    ok("没有 tier、pages 字段的记录照样计数，坏行跳过", (s["total_records"], s["records_since"], s["last_full_ts"]), (4, 3, None))
    ok("分档上线前的记录只算旧记录，它的页也不算", (s["old_records"], s["page_count_since"]), (1, 2))
    ok("文字版说明旧记录不参与判断", "分档上线前另有 1 条旧记录，不参与判断" in run(["status"])[1], True)

    # ---- 全稿之后重新计数
    ok("写全稿记录", run(["write", "--file", "out/ppt/deck.pptx", "--tier", "full"] + RA)[0], 0)
    s = status()
    ok("全稿之后：计数清零、不建议", (s["counted_from"], s["records_since"], s["page_count_since"], s["suggest_full"]),
       ("last_full", 0, 0, False))
    ok("全稿之后：记下全稿时间", s["last_full_ts"] == lines()[-1]["ts"], True)
    run(["write", "--file", "out/ppt/deck.pptx", "--tier", "small", "--pages", "5,6"] + RA)
    run(["write", "--file", "out/ppt/deck.pptx", "--tier", "page", "--pages", "6、第24页"] + RA)
    s = status()
    ok("此后的页合并去重", (s["records_since"], s["pages_since"], s["page_count_since"]), (2, [5, 6, 24], 3))
    run(["write", "--file", "out/ppt/deck.pptx", "--tier", "small"] + RA)
    run(["write", "--doc", "飞书文档", "--tier", "small", "--pages", "5"] + RA)
    ok("此后 4 条：不建议", (status()["records_since"], status()["suggest_full"]), (4, False))
    out = run(["status"])[1]
    ok("不建议时文字版写明暂不需要", "建议：暂不需要全稿通读" in out and "此后 4 条记录" in out, True)
    run(["write", "--file", "out/ppt/deck.pptx", "--tier", "small", "--pages", "5"] + RA)
    s = status()
    ok("此后 5 条：建议全稿通读", (s["records_since"], s["suggest_full"], "5 条" in "；".join(s["reasons"])), (5, True, True))
    out = run(["status"])[1]
    ok("建议时文字版写明 --tier full", "建议：下一次改稿后全稿通读一次（--tier full）" in out, True)

    # ---- 页数阈值（另一个工作区）
    run(["write", "--file", "d.pptx", "--tier", "full"] + RA, cwd=WS3)
    run(["write", "--file", "d.pptx", "--tier", "page", "--pages", "1-7"] + RA, cwd=WS3)
    ok("此后 7 页：不建议", (status(WS3)["page_count_since"], status(WS3)["suggest_full"]), (7, False))
    run(["write", "--file", "d.pptx", "--tier", "small", "--pages", "封面"] + RA, cwd=WS3)
    s = status(WS3)
    ok("此后 8 页：建议", (s["pages_since"], s["suggest_full"], s["records_since"]), ([1, 2, 3, 4, 5, 6, 7, "封面"], True, 2))

    # ---- 天数阈值（进程内指定“现在”）
    full_epoch = [r for r in lines(WS3) if r.get("tier") == "full"][-1]["epoch"]
    put(os.path.join(BASE, "ws4", "_acceptance", "records.jsonl"), "")
    ws4 = os.path.join(BASE, "ws4")
    append(os.path.join(ws4, "_acceptance", "records.jsonl"),
           {"ts": "t0", "epoch": full_epoch, "files": [], "doc": "x", "tier": "full", "pages": ""},
           {"ts": "t1", "epoch": full_epoch + 60, "files": [], "doc": "x", "tier": "small", "pages": "3"})
    ok("全稿 2.9 天前：不建议", rec.status(ws4, now=full_epoch + 2.9 * 86400)["suggest_full"], False)
    s = rec.status(ws4, now=full_epoch + 3.1 * 86400)
    ok("全稿 3.1 天前：建议", (s["suggest_full"], s["days_since"], "最近一次全稿验收已是 3.1 天前" in "；".join(s["reasons"])),
       (True, 3.1, True))
    ws5 = ws_with("ws5", item("t0", T0 + 3600, "small", "2"))
    ok("没有全稿：分档上线 2.9 天时不建议", rec.status(ws5, now=T0 + 2.9 * 86400)["suggest_full"], False)
    s = rec.status(ws5, now=T0 + 3.1 * 86400)
    ok("没有全稿：天数从分档上线算，3.1 天时建议", (s["suggest_full"], s["counted_from"], s["days_since"],
                                          "分档上线已 3.1 天，还没有全稿验收" in "；".join(s["reasons"])),
       (True, "tier_start", 3.1, True))

    # ---- 上线后第一次跑：旧记录再多也不逼出全稿通读（35 条没分档的旧记录，跨 11 天）
    ws6 = ws_with("ws6", *[item("旧", T0 - 11 * 86400 + i * 7 * 3600, pages="1-30") for i in range(35)])
    s = rec.status(ws6, now=T0 + 3600)
    ok("上线后第一次跑：35 条旧记录不逼出全稿", (s["suggest_full"], s["records_since"], s["old_records"], s["page_count_since"]),
       (False, 0, 35, 0))
    text = rec.status_text(s)
    ok("上线后第一次跑：文字版说明旧记录、暂不需要", "分档上线前另有 35 条旧记录，不参与判断" in text and "暂不需要全稿通读" in text,
       True)

    # ---- 起点取“最近一次全稿”和“分档上线”中较晚的那个
    ws7 = ws_with("ws7", item("a", T0 - 7200, "full"), item("b", T0 - 3600, "small", "9"), item("c", T0 + 3600, "small", "5"))
    s = rec.status(ws7, now=T0 + 7200)
    ok("全稿早于分档上线：从分档上线算", (s["counted_from"], s["last_full_ts"], s["records_since"], s["pages_since"],
                                s["old_records"]), ("tier_start", None, 1, [5], 2))
    ws8 = ws_with("ws8", item("a", T0 - 3600), item("b", T0 + 600, "small", "3"), item("c", T0 + 1200, "full"),
                  item("d", T0 + 1800, "small", "4"))
    s = rec.status(ws8, now=T0 + 3600)
    ok("全稿晚于分档上线：从全稿算", (s["counted_from"], s["last_full_ts"], s["records_since"], s["pages_since"],
                              s["old_records"]), ("last_full", "c", 1, [4], 1))

    # ---- 找工作区的方式和 write 一样
    ok("在子目录里运行：找到工作区最上层", status(SUB)["workspace"], WS)
    ok("--file：用文件所在的工作区", status(OUTSIDE, ["--file", os.path.join(SUB, "deck.pptx")])["workspace"], WS)
    ok("--file 找不到文件：报错", run(["status", "--file", "nope.pptx"], cwd=OUTSIDE)[0], 2)
    s = status(OUTSIDE)
    ok("工作区外运行（JSON）：说明不在工作区里", (s.get("in_workspace"), "当前目录不在分析助手的工作区里" in s.get("message", "")),
       (False, True))
    out = run(["status"], cwd=OUTSIDE)[1]
    ok("工作区外运行（文字）：不说“还没有验收记录”", "当前目录不在分析助手的工作区里" in out and "还没有验收记录" not in out, True)
    ok("工作区里运行：JSON 标明在工作区里", status()["in_workspace"], True)

    # ---- 其他
    ok("--pages 的各种写法", rec.page_items("5,6，7、第9页 P10 p.11 3 - 4 第12-13页 5到6 封面 7-5"),
       [5, 6, 7, 9, 10, 11, 3, 4, 12, 13, 5, 6, "封面", "7-5"])
    ok("--pages 带空格的写法不拆开", (rec.page_items("第 3 页"), rec.page_items("第 3 页、第 5 - 6 页, P 7, 9 页, SOP 3")),
       ([3], [3, 5, 6, 7, 9, "SOP", 3]))
    ok("阈值写成常量", (rec.FULL_AFTER_RECORDS, rec.FULL_AFTER_PAGES, rec.FULL_AFTER_DAYS), (5, 8, 3))
    ok("分档上线时间从 AAW_TIER_START 读：2026-01-14 20:00（UTC+8）", (rec.TIER_START.isoformat(), T0),
       ("2026-01-14T20:00:00+08:00", 1768392000.0))
    ok("JSON 字段齐全", sorted(status()), sorted(["workspace", "in_workspace", "total_records", "old_records", "tier_start",
                                                   "last_full_ts", "counted_from", "records_since", "pages_since",
                                                   "page_count_since", "days_since", "suggest_full", "reasons",
                                                   "thresholds"]))
    # ---- 不设分档上线时间：全部记录都算，天数从第一条记录算起
    plain = dict(os.environ, AAW_WS_BASE=BASE)
    plain.pop("AAW_TIER_START", None)
    ws9 = ws_with("ws9", item("a", T0 - 9 * 86400, None, "1-3"), item("b", T0 - 8 * 86400, "small", "4"))
    probe = ("import accept_record as r,json;s=r.status(%r,now=%r);"
             "print(json.dumps([r.TIER_START is None,s['old_records'],s['records_since'],s['page_count_since'],"
             "s['suggest_full'],s['tier_start'],r.status_text(s)],ensure_ascii=False))") % (ws9, T0 - 8.5 * 86400)
    p = subprocess.run([sys.executable, "-c", probe], cwd=HERE, capture_output=True, text=True, env=plain)
    try:
        got = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        got = [p.stdout, p.stderr]
    ok("不设分档上线时间：没有旧记录、全部计数、0.5 天不催", got[:6], [True, 0, 2, 4, False, None])
    ok("不设分档上线时间：文字版不提分档上线", isinstance(got[-1], str) and "分档上线" not in got[-1]
       and "还没有全稿验收" in got[-1], True)
    p = subprocess.run([sys.executable, "-c", probe.replace(repr(T0 - 8.5 * 86400), repr(T0 - 5 * 86400))],
                       cwd=HERE, capture_output=True, text=True, env=plain)
    try:
        got = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        got = [p.stdout, p.stderr, "", "", None]
    ok("不设分档上线时间：第一条记录 4 天后建议全稿", (got[4], "第一条验收记录已是 4.0 天前" in got[-1]), (True, True))

    before = (os.path.getsize(RECS), sorted(os.listdir(os.path.dirname(RECS))))
    run(["status"])
    run(["status", "--json"])
    ok("status 不写任何文件", (os.path.getsize(RECS), sorted(os.listdir(os.path.dirname(RECS)))), before)

    bad = 0
    for name, got, want in res:
        if got != want:
            bad += 1
            print("FAIL", name, "| got", got, "| want", want)
    print(f"{len(res) - bad}/{len(res)} 通过")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
