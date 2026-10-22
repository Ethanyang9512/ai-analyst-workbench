#!/usr/bin/env python3
"""每轮自动提醒的回归测试：python3 test_remind.py
额度和现状摘要两段用临时目录里的假文件（AAW_CLAUDE_JSON 指向假的 ~/.claude.json），不读正式文件。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.pop("AAW_TZ_HOURS", None)        # 下面的时间断言按默认的 UTC+8 写
os.environ["AAW_PROFILE"] = "aaw"
sys.path.insert(0, HERE)
import gate  # noqa: E402  只用它的提示文字，核对两处都指向 workflow.md
import remind  # noqa: E402
from remind import ASK, BASE, DOC, FULL, LOCAL_TZ, build  # noqa: E402

CHAT = "oc_remindtest" + uuid.uuid4().hex[:20]
TMP = os.path.realpath(tempfile.mkdtemp(prefix="aaw-remind-"))
FAKE_JSON = os.path.join(TMP, "claude.json")
remind.CLAUDE_JSON = FAKE_JSON      # 进程内的调用也只读假文件
USAGE = "【额度读数】"
STALE = "读数可能已过期（Claude Code 有一阵没打开时不会刷新），回答时说明。"


def usage_file(now, path=FAKE_JSON, fetched_ago=3, five_in=110, week_in=60 * 24 * 7 + 180, five=23, week=41.5):
    """造一份假的 ~/.claude.json：额度键之外还放了几项不该被读出来的内容。时间都相对 now（分钟）。"""
    utc = lambda minutes: (now + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()
    data = {
        "oauthAccount": {"emailAddress": "SECRET-mail-address"},
        "userID": "SECRET-user-id",
        "projects": {"/x": {"history": [{"display": "SECRET 额度 history"}]}},
        "cachedUsageUtilization": {
            "fetchedAtMs": int((now - timedelta(minutes=fetched_ago)).timestamp() * 1000),
            "accountUuid": "SECRET-account-uuid",
            "utilization": {
                "five_hour": {"utilization": five, "resets_at": utc(five_in), "limit_dollars": None},
                "seven_day": {"utilization": week, "resets_at": utc(week_in)},
                "seven_day_opus": None,
            },
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def status_file(folder, size, colon=":", pad="\n", before=""):
    """在 folder 下写一份 _status.md，现状摘要正文正好 size 个字。"""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "_status.md"), "w", encoding="utf-8") as f:
        f.write(before + f"<!-- 现状摘要{colon}开始 -->{pad}" + "当" * size + f"{pad}<!-- 现状摘要{colon}结束 -->\n"
                + "\n## 历史记录\n" + "旧记录一行\n" * 200)
    return folder


def wrap(text, chat=CHAT):
    head = '<bridge_context>\n{"chatId":"%s","chatType":"group"}\n</bridge_context>\n\n' % chat if chat else ""
    return head + "<user_input>\n" + json.dumps({"text": text}, ensure_ascii=False) + "\n</user_input>"


def hook(payload, profile="aaw"):
    env = dict(os.environ, AAW_CLAUDE_JSON=FAKE_JSON, AAW_HOOK_STATE=TMP)   # “最近一次触发”记号写到临时目录
    env.pop("LARK_CHANNEL_PROFILE", None)
    if profile:
        env["LARK_CHANNEL_PROFILE"] = profile
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "remind"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.strip()


def main():
    res = []
    # (消息, 应不应该带第 4 条文档提醒, 应不应该有提醒)
    cases = [
        ("在吗", False, True),
        ("帮我改一下这篇文档，按评论来", True, True),
        ("做一版 PPT 给我", True, True),
        ("这个数是怎么算的", False, True),
        ("/new", None, False),
        ("/tmp/数据包.zip 解压后帮我核对行数，做成 PPT", True, True),      # 以路径开头的消息不是斜杠命令
        ("/data 目录下那个数再核一遍", False, True),
        ('[card-click] {"choice":"a"}', None, False),
    ]
    for text, doc, has in cases:
        out = build(wrap(text))
        good = (bool(out) == has) and (doc is None or (DOC in out) == doc)
        res.append(("提醒内容：" + text, good))

    sid = "sess-remindtest-" + uuid.uuid4().hex[:8]
    turn = f"/tmp/.aaw_turn_{sid}.json"
    base = {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt_id": "p1", "cwd": "/x"}
    try:
        code, out = hook(dict(base, prompt=wrap("帮我看下这个 PPT")))
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""
        res.append(("分析助手身份：输出提醒", code == 0 and ctx.startswith("【系统每轮自动提醒") and DOC in ctx))
        t = json.load(open(turn)) if os.path.exists(turn) else {}
        res.append(("分析助手身份：登记了群号和本轮编号", t.get("chat") == CHAT and t.get("prompt_id") == "p1" and t.get("tools") == 0))
        os.remove(turn)
        code, out = hook(dict(base, prompt=wrap("帮我看下这个 PPT")), profile="other-bot")
        res.append(("别的机器人：不提醒也不登记", code == 0 and not out and not os.path.exists(turn)))
        code, out = hook(dict(base, prompt=wrap("帮我看下这个 PPT")), profile=None)
        res.append(("不是从桥来的（终端里直接用）：不提醒也不登记", code == 0 and not out and not os.path.exists(turn)))
        code, out = hook(dict(base, prompt=wrap("你好", chat=None)))
        res.append(("没有群号的消息：提醒但不登记", code == 0 and bool(out) and not os.path.exists(turn)))
        code, out = hook(dict(base, prompt=wrap("/new")))
        res.append(("命令消息：不提醒", code == 0 and not out))
        p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "remind"], input="not json", capture_output=True,
                           text=True, env=dict(os.environ, LARK_CHANNEL_PROFILE="aaw", AAW_HOOK_STATE=TMP))
        res.append(("坏输入：安静放行", p.returncode == 0 and not p.stdout.strip()))

        # 真实入口：额度、全稿、追问清单、摘要一起出现
        ws = status_file(os.path.join(TMP, "ws-hook"), 7000)
        usage_file(datetime.now(LOCAL_TZ))
        code, out = hook(dict(base, prompt=wrap("现在额度怎么样，顺便把最终版发给领导"), cwd=ws))
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""
        res.append(("分析助手身份：额度、全稿、追问清单、摘要都在", code == 0 and ctx.startswith("【系统每轮自动提醒")
                    and USAGE in ctx and FULL in ctx and ASK in ctx and "现状摘要现在 7,000 字" in ctx
                    and "SECRET" not in ctx))
    finally:
        if os.path.exists(turn):
            os.remove(turn)

    # ---- 1a 三问自答、挂在第 1 条“动手前写理解”上；三档全文只留在 workflow.md，钩子里只指过去
    three = ("新增一组页或口径要变时，写理解时用一句话自答三问：口径是不是同一个、和谁比、听众拿它做什么"
             "（项目约定页已写明的照写；小改不写）。")
    res.append(("三问自答、挂在第 1 条上，每轮都带", three in BASE.split("\n2.")[0] and three in build(wrap("在吗"))))
    res.append(("不再用没定义的“我的理解和打算”", "我的理解和打算" not in BASE + DOC))
    res.append(("文档提醒只留一句分档验收，不重复三档全文", DOC.endswith(
        "改稿按 workflow.md 的分档验收：先跑 deckcheck.py scope 和 accept_record.py status 定档。")
        and "不超过 3 页" not in DOC and "--tier" not in DOC))
    why = gate.message(["x.pptx"], True)
    res.append(("文档提醒和验收门都指向 workflow.md、deckcheck.py scope、accept_record.py status",
                all(w in DOC and w in why for w in ("workflow.md", "deckcheck.py scope", "accept_record.py status"))))

    # ---- 1c 两个触发：全稿验收（定稿、要汇报、发给领导这类话）；《会前追问清单》只在要汇报、汇报前、拿去汇报、
    #      向领导汇报、给领导看、发（送）给或转给领导、老板时出现。按分句看，否定的、讲旧版本的都不算。
    res.append(("两段文字", (FULL, ASK) == (
        "本轮按全稿验收：两位验收员通读全稿，记录写 --tier full（本轮不交付稿子就不适用）。",
        "回复末尾附《会前追问清单》（见 ethan-pyramid-storyline 的「会前追问清单」一节），不另发文件。")))
    cases = [   # (消息, 全稿验收, 会前追问清单)
        # 审查员造的口语句子里，旧判法错的 17 句
        ("还没有定稿，先出个草稿", False, False), ("现在还没到定稿的时候", False, False),
        ("领导还没看过，等定稿再说", False, False), ("定稿还早，先别急", False, False), ("我不会拿去汇报", False, False),
        ("别把它当终稿", False, False), ("不要把这份当成最终版", False, False), ("这份不能算定稿", False, False),
        ("还不到定稿的程度", False, False), ("离定稿还差两页", False, False), ("不着急发给领导", False, False),
        ("我没打算汇报前再改", False, False), ("上次定稿的版本第 5 页有误", False, False),
        ("发送给领导之前再看一遍", True, True), ("周五向领导汇报", True, True), ("这是 final 版", True, False),
        ("汇报材料最终确认一下", True, False),
        # 原有的 25 句（“定稿后再说”按新判法属于否定）
        ("明天要汇报，帮我再看看", True, True), ("汇报前再检查一下第5页", True, True), ("这版拿去汇报", True, True),
        ("改完给领导看", True, True), ("改完发给领导", True, True), ("这个要发给老板", True, True),
        ("这版可以定稿了", True, False), ("你通读一遍", True, False), ("全面检查一下这份文档", True, False),
        ("把最终版发我", True, False), ("发给业务之前看一遍", True, False), ("整理好发给大家", True, False),
        ("上一版不是最终版，这版是最终版了", True, False),
        ("帮我把第5页的标题改一下", False, False), ("还没定稿，先改第3页", False, False),
        ("不用通读，只看第5页", False, False), ("这不是最终版", False, False), ("先别发给领导", False, False),
        ("不需要全面检查", False, False), ("这个数是怎么算的", False, False),
        ("这次不拿去汇报，先自己看", False, False), ("不要汇报了，改完发我", False, False), ("先别给领导看", False, False),
        ("还没定稿，但明天要汇报", True, True), ("先别发给领导，定稿后再说", False, False),
        # 补充：新判法不能误伤的说法（条件句、带“不”字的好话、没逗号的转折、旧版本、英文）
        ("先别发给领导，这版可以定稿了", True, False), ("没问题就定稿吧", True, False), ("不改了就拿去汇报", True, True),
        ("这版不错可以定稿了", True, False), ("还没定稿但明天要汇报", True, True), ("汇报之前再看一遍", True, True),
        ("之前发给领导的那版有个错", False, False), ("finally 改好了", False, False), ("转给领导审一下", True, True),
    ]
    for text, full, ask in cases:
        out = build(wrap(text))
        res.append(("全稿 / 追问清单：" + text, (FULL in out, ASK in out) == (full, ask)))

    # ---- 1b 额度读数（指定“现在”，看格式、本地时间（默认 UTC+8）和过期提示）
    now = datetime(2026, 10, 14, 15, 0, tzinfo=LOCAL_TZ)
    usage_file(now)
    note = remind.usage_note(FAKE_JSON, now)
    res.append(("额度读数：写明已用、本地时间", note == "【额度读数】5 小时窗口已用 23%（今天 16:50 刷新）、"
                "周额度已用 41.5%（10-21 18:00 刷新）；读数取于 14:57（3 分钟前）。直接据此回答，不必再查。"))
    late = datetime(2026, 10, 14, 22, 0, tzinfo=LOCAL_TZ)
    usage_file(late, five_in=170)
    res.append(("额度读数：跨天的刷新时间带“明天”", "5 小时窗口已用 23%（明天 00:50 刷新）" in remind.usage_note(FAKE_JSON, late)))
    usage_file(now, five_in=-60 * 24 * 2)
    res.append(("额度读数：更早的刷新时间写日期", "5 小时窗口已用 23%（10-12 15:00 刷新）" in remind.usage_note(FAKE_JSON, now)))
    res.append(("额度读数：不带出文件里的其他内容", "SECRET" not in note))
    usage_file(now, fetched_ago=30)
    res.append(("额度读数：30 分钟内不提示过期", STALE not in remind.usage_note(FAKE_JSON, now)))
    usage_file(now, fetched_ago=31)
    note = remind.usage_note(FAKE_JSON, now)
    res.append(("额度读数：超过 30 分钟提示过期", note.endswith(STALE) and "（31 分钟前）" in note))
    usage_file(now, five_in=-5)
    res.append(("额度读数：刷新时间已过提示过期", remind.usage_note(FAKE_JSON, now).endswith(STALE)))
    usage_file(now, fetched_ago=60 * 20)
    res.append(("额度读数：不是当天的读数带日期", "读数取于 10-13 19:00（1,200 分钟前）" in remind.usage_note(FAKE_JSON, now)))
    res.append(("UTC 换本地时间：带小数、Z 的写法都认", (
        remind.local_time("2026-01-14T16:50:00.440497+00:00").strftime("%m-%d %H:%M"),
        remind.local_time("2026-01-21T10:00:00Z").strftime("%m-%d %H:%M"),
        remind.local_time("2026-01-21T10:00:00.12+00:00").strftime("%m-%d %H:%M")) == ("01-15 00:50", "01-21 18:00", "01-21 18:00")))
    p = subprocess.run([sys.executable, "-c", "import remind;print(remind.local_time('2026-01-21T10:00:00Z').strftime('%H:%M'))"],
                       cwd=HERE, capture_output=True, text=True, env=dict(os.environ, AAW_TZ_HOURS="1"))
    res.append(("时区可以用 AAW_TZ_HOURS 改", p.stdout.strip() == "11:00"))
    usage_file(datetime.now(LOCAL_TZ))
    for text in ("现在额度怎么样", "这周用量多少了", "会不会碰到限额", "check usage", "USAGE?"):
        res.append(("问额度：附读数 · " + text, USAGE in build(wrap(text))))
    res.append(("没问额度：不附读数", USAGE not in build(wrap("这个数是怎么算的"))))
    with open(FAKE_JSON, "w", encoding="utf-8") as f:
        f.write('{"cachedUsageUtilization": {"fetchedAtMs": ')         # 写到一半的坏文件
    out = build(wrap("额度还有多少"))
    res.append(("额度文件坏了：省掉这段，其余照常", out.startswith("【系统每轮自动提醒") and USAGE not in out))
    with open(FAKE_JSON, "w", encoding="utf-8") as f:
        json.dump({"other": 1}, f)
    res.append(("没有额度键：不附读数", USAGE not in build(wrap("额度还有多少"))))

    # ---- 1d 现状摘要超过 5,000 字
    ws = os.path.join(TMP, "ws")
    status_file(ws, 5000)
    res.append(("现状摘要正好 5,000 字：不提醒", remind.summary_note(ws) == ""))
    status_file(ws, 5001)
    note = remind.summary_note(ws)
    res.append(("现状摘要 5,001 字：提醒", note == "现状摘要现在 5,001 字，超过新会话预览的 5,000 字。本轮结束前顺手压到 5,000 字以内："
                "下一步和仍然有效的限制放最前，页码对照表这类细节移到单独文件并写明路径。"))
    res.append(("提醒里不叫它“先压缩”", "先压缩" not in note))
    status_file(ws, 5000, pad="\n\n   \n")
    res.append(("摘要首尾的空白不算字数", remind.summary_note(ws) == ""))
    status_file(ws, 6000, colon="：")
    res.append(("全角冒号的标记也认", "6,000 字" in remind.summary_note(ws)))
    status_file(ws, 6000, before="x" * (200 * 1024))
    res.append(("只读文件开头 200KB", remind.summary_note(ws) == ""))
    status_file(ws, 210 * 1024)
    note = remind.summary_note(ws)
    res.append(("摘要长到 200KB 里找不到结束标记：也提醒", "文件开头 200KB 内没有结束标记" in note
                and "本轮结束前顺手修好：压到 5,000 字以内并留好结束标记" in note))
    with open(os.path.join(ws, "_status.md"), "w", encoding="utf-8") as f:
        f.write("<!-- 现状摘要:开始 -->\n## 现状摘要\n结束标记丢了\n\n## 历史\n")
    res.append(("只有开始标记、结束标记丢了：也提醒", "没有结束标记" in remind.summary_note(ws)))
    with open(os.path.join(ws, "_status.md"), "w", encoding="utf-8") as f:
        f.write("# 没有现状摘要的状态文件\n" + "长" * 9000)
    res.append(("没有摘要标记：不提醒", remind.summary_note(ws) == ""))
    status_file(ws, 7000)
    out = build(wrap("在吗"), ws)
    res.append(("摘要超长：附在提醒后面", out.startswith("【系统每轮自动提醒") and "现状摘要现在 7,000 字" in out))
    res.append(("没有状态文件：不提醒", "现状摘要现在" not in build(wrap("在吗"), os.path.join(TMP, "empty"))))
    weird = os.path.join(TMP, "weird")
    os.makedirs(os.path.join(weird, "_status.md"))          # 同名的是个目录，读的时候出错
    out = build(wrap("在吗"), weird)
    res.append(("状态文件读失败：省掉这段，其余照常", out.startswith("【系统每轮自动提醒") and "现状摘要现在" not in out))
    res.append(("命令消息：额度和摘要也不附", build(wrap("/usage"), ws) == "" and build(wrap("[card-click] 额度"), ws) == ""))

    shutil.rmtree(TMP, ignore_errors=True)
    bad = 0
    for name, good in res:
        if not good:
            bad += 1
            print("FAIL", name)
    print(f"{len(res) - bad}/{len(res)} 通过")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
