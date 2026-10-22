#!/usr/bin/env python3
"""每轮自动提醒（UserPromptSubmit）。

把用户反复重申的要求，在每条消息后面自动补上，省得用户每次再说：
  “先理解/理解我的意思”“不要过度展开”“用大白话”“按既有文档和 PPT 要求来”。
这几条来自翻历史会话：数一数用户手打最多的要求，把排在前面的固化成每轮提醒。换成你自己的高频要求即可。
消息涉及文档、图表、PPT 时，再提醒先加载对应规范。另有三段，各自按需出现：
  - 用户说定稿、要汇报、发给领导这类话：提醒本轮按全稿验收；说要汇报、发给领导或老板时，再提醒回复末尾附《会前追问清单》；
  - 用户问额度：附上 Claude Code 缓存的额度读数（只读 ~/.claude.json 里 cachedUsageUtilization 这一个键）；
  - 当前目录 _status.md 的现状摘要超过新会话预览的 5,000 字：提醒本轮结束前顺手压缩。
同时登记“这一轮属于哪个群”（/tmp/.aaw_turn_<会话>.json），给进度卡钩子和护栏用。
只输出附加上下文，从不拦截。任何异常都安静退出；某一段出错，只省掉那一段。

可调的环境变量：AAW_CLAUDE_JSON（额度缓存文件，默认 ~/.claude.json）、AAW_TZ_HOURS（显示时间用的时区，默认 8 即 UTC+8）。
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BASE = (
    "【系统每轮自动提醒 · 这些是用户的长期要求】\n"
    "1. 动手前，先用一句话写出你对需求和范围的理解（做什么、不做什么）；简单问答不用。"
    "新增一组页或口径要变时，写理解时用一句话自答三问：口径是不是同一个、和谁比、听众拿它做什么"
    "（项目约定页已写明的照写；小改不写）。"
    "用户说“先讨论 / 先理解 / 先别动手”时，停在理解和讨论，不动手。\n"
    "2. 只做被要求的，不额外展开。\n"
    "3. 用大白话；术语首次出现要解释；不自造概念。"
)
DOC = (
    "\n4. 本轮如果要新写或修改文档、图表、PPT：先加载 ethan-report-writing 和 ethan-pyramid-storyline（做 PPT 再加 ethan-slide-deck），"
    "对照用户认可过的稿子；新写的先给故事线骨架；新做的图默认要可编辑。"
    "只是发送、查看或讨论现成的稿子时，不用加载，也不顺手重做。"
    "改稿按 workflow.md 的分档验收：先跑 deckcheck.py scope 和 accept_record.py status 定档。"
)
DOC_WORDS = re.compile(r"文档|PPT|ppt|汇报|报告|改稿|评论|出图|图表|幻灯|片子|方法论|故事线|docx|wiki", re.I)
SKIP = re.compile(r"^\s*(\[card-click\]|/[a-z][a-z-]*\s*$)")    # 卡片点击，或单独一个斜杠命令

# 全稿验收：用户说定稿、要汇报、发给领导这类话时提醒。否定的、讲旧版本的不算（判法见 said()）。
FULL = "本轮按全稿验收：两位验收员通读全稿，记录写 --tier full（本轮不交付稿子就不适用）。"
FULL_WORDS = re.compile(
    r"定稿|终稿|最终(?:版|稿|确认)|终版|(?<![A-Za-z])(?i:final)(?![A-Za-z])|通读|从头到尾"
    r"|全面(?:检查|核查|审查|复核|审核)|(?:要|去|拿去|准备)汇报|汇报之?前|(?:向|跟)(?:领导|老板)汇报"
    r"|(?:发送|转发|发|交|转)(?:给|到)?(?:领导|老板|业务|大家|别人|同事)|给(?:领导|老板)(?:看|过目)")
# 《会前追问清单》：只在说要汇报、汇报前、拿去汇报、向领导汇报、给领导看、发（送）给或转给领导、老板时提醒
# （通读、全面检查、定稿只触发全稿验收）。这几种说法都在 FULL_WORDS 里，所以只在全稿验收也触发时才看它。
ASK = "回复末尾附《会前追问清单》（见 ethan-pyramid-storyline 的「会前追问清单」一节），不另发文件。"
ASK_WORDS = re.compile(r"要汇报|汇报之?前|拿去汇报|(?:向|跟)(?:领导|老板)汇报|给领导看|(?:发送|转发|发|转)给(?:领导|老板)")
# 否定的判法（按审查员造的口语句子改过一轮）：按分句看——
CLAUSE = re.compile(r"[，。！？；,.!?;：:\n]|但是|但|可是|不过")        # 分句的边界
NEG_BEFORE = re.compile(r"[不没未别非尚]|无需|无须|无法")              # 同一分句里、词前面出现这些就算否定
NOT_NEG = re.compile(r"不错|不少|不管|不论|不如|不仅|要不|差不多|没问题|没有问题|没错|非常|非得|别人|别的|特别")  # 带这些字但不是否定
COND = re.compile(r"就|的话")       # “没问题就定稿”：否定词在“就 / 的话”前面，说的是条件，不算否定这个词
NEG_AFTER = re.compile(r"还早|再说|还差|的时候|的程度")             # 词后面 8 个字内出现这些也算否定（“定稿还早”）
OLD = re.compile(r"(?:上次|之前|以前|原来)的?$")                   # “上次定稿的版本”讲的是旧版本，不算

# 额度读数：只读 ~/.claude.json 里 Claude Code 缓存的 cachedUsageUtilization 这一个键，不碰钥匙串。
USAGE_WORDS = re.compile(r"额度|用量|限额|usage", re.I)
CLAUDE_JSON = os.environ.get("AAW_CLAUDE_JSON") or os.path.expanduser("~/.claude.json")


def _tz():
    try:
        return timezone(timedelta(hours=float(os.environ.get("AAW_TZ_HOURS") or 8)))
    except Exception:
        return timezone(timedelta(hours=8))


LOCAL_TZ = _tz()                # 显示时间用的时区
USAGE_STALE_MINUTES = 30        # 读数比这更旧，提示可能已过期

# 现状摘要长度：标记写法和计数方式与 status_preview.py 相同（去掉首尾空白后的字数）。
SUMMARY = re.compile(r"<!--\s*现状摘要[:：]\s*开始\s*-->(.*?)<!--\s*现状摘要[:：]\s*结束\s*-->", re.S)
SUMMARY_START = re.compile(r"<!--\s*现状摘要[:：]\s*开始\s*-->")
SUMMARY_LIMIT = 5000            # 新会话状态预览只显示摘要的前 5,000 字
STATUS_HEAD = 200 * 1024        # 只读 _status.md 开头这么多字节


def user_text(prompt):
    """从桥包装的提示词里取出用户原话；取不到就用整段。"""
    texts = []
    for block in re.findall(r"<user_input>\s*(.*?)\s*</user_input>", prompt, re.S):
        try:
            data = json.loads(block)
            if isinstance(data, dict) and isinstance(data.get("text"), str):
                texts.append(data["text"])
                continue
        except Exception:
            pass
        texts.append(block)
    return "\n".join(texts) if texts else prompt


def said(words, text):
    """用户原话里说了 words 里的话：按分句看，被否定的、讲旧版本的不算。"""
    for clause in CLAUSE.split(text):
        for m in words.finditer(clause):
            before = clause[:m.start()]
            if OLD.search(before) or NEG_AFTER.search(clause[m.end():m.end() + 8]):
                continue
            cond = [c.end() for c in COND.finditer(before)]
            if not NEG_BEFORE.search(NOT_NEG.sub("", before[cond[-1] if cond else 0:])):
                return True
    return False


def local_time(utc_text):
    """额度接口给的 UTC 时间（ISO 写法）换成本地时间（LOCAL_TZ）。"""
    s = re.sub(r"\.\d+", "", str(utc_text).strip())     # 去掉秒的小数：系统自带的 Python 3.9 只认 3 位或 6 位
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    t = datetime.fromisoformat(s)
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(LOCAL_TZ)


def day_time(t, now):
    """今天 / 明天 HH:MM；别的日子写 M-D HH:MM。"""
    return {0: "今天 ", 1: "明天 "}.get((t.date() - now.date()).days, f"{t.month}-{t.day} ") + f"{t:%H:%M}"


def usage_note(path=None, now=None):
    """【额度读数】一段。读不到、格式不对就返回空串。"""
    with open(path or CLAUDE_JSON, encoding="utf-8") as f:
        cache = json.load(f).get("cachedUsageUtilization")
    now = now or datetime.now(LOCAL_TZ)
    fetched = datetime.fromtimestamp(cache["fetchedAtMs"] / 1000, LOCAL_TZ)
    minutes = max(0, int((now - fetched).total_seconds() // 60))
    stale = minutes > USAGE_STALE_MINUTES
    parts = []
    for key, label in (("five_hour", "5 小时窗口已用"), ("seven_day", "周额度已用")):
        window = cache["utilization"].get(key) or {}
        pct = window.get("utilization")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        pct = ("%d" % pct) if float(pct).is_integer() else ("%.1f" % pct)
        if window.get("resets_at"):
            reset = local_time(window["resets_at"])
            stale = stale or reset <= now
            when = day_time(reset, now) if key == "five_hour" else f"{reset.month}-{reset.day} {reset:%H:%M}"
            parts.append(f"{label} {pct}%（{when} 刷新）")
        else:
            parts.append(f"{label} {pct}%（刷新时间不详）")
    if not parts:
        return ""
    at = f"{fetched:%H:%M}" if fetched.date() == now.date() else f"{fetched.month}-{fetched.day} {fetched:%H:%M}"
    text = "【额度读数】" + "、".join(parts) + f"；读数取于 {at}（{minutes:,} 分钟前）。直接据此回答，不必再查。"
    if stale:
        text += "读数可能已过期（Claude Code 有一阵没打开时不会刷新），回答时说明。"
    return text


def summary_note(cwd):
    """当前目录 _status.md 的现状摘要超过新会话预览的长度（或开头一段里找不到结束标记）时，提醒本轮结束前顺手压缩。
    没超、没有摘要返回空串。"""
    with open(os.path.join(cwd, "_status.md"), "rb") as f:
        head = f.read(STATUS_HEAD).decode("utf-8", errors="replace")
    m = SUMMARY.search(head)
    if not m and SUMMARY_START.search(head):     # 有开始标记、开头这一段里没有结束标记：多半超得很长，最该提醒
        return (f"现状摘要的开始标记之后，文件开头 {STATUS_HEAD // 1024}KB 内没有结束标记（摘要太长，或结束标记丢了），"
                f"新会话预览显示不全。本轮结束前顺手修好：压到 {SUMMARY_LIMIT:,} 字以内并留好结束标记，"
                "下一步和仍然有效的限制放最前，页码对照表这类细节移到单独文件并写明路径。")
    size = len(m.group(1).strip()) if m else 0
    if size <= SUMMARY_LIMIT:
        return ""
    return (f"现状摘要现在 {size:,} 字，超过新会话预览的 {SUMMARY_LIMIT:,} 字。"
            f"本轮结束前顺手压到 {SUMMARY_LIMIT:,} 字以内：下一步和仍然有效的限制放最前，"
            "页码对照表这类细节移到单独文件并写明路径。")


def quietly(fn, *args):
    """新加的几段各自出错只省掉那一段，不影响整条提醒。"""
    try:
        return fn(*args)
    except Exception:
        return ""


def build(prompt, cwd=""):
    text = user_text(prompt or "")
    if SKIP.match(text):
        return ""
    out = BASE
    if DOC_WORDS.search(text):
        out += DOC
    extra = []
    if said(FULL_WORDS, text):
        extra.append(FULL)
        if said(ASK_WORDS, text):
            extra.append(ASK)
    if USAGE_WORDS.search(text):
        extra.append(quietly(usage_note))
    if cwd:
        extra.append(quietly(summary_note, cwd))
    return "\n".join([out] + [x for x in extra if x])


def record_turn(data):
    """登记这一轮属于哪个群，给进度卡的钩子用（progress.py）。失败不影响提醒。"""
    try:
        import os
        import time
        session = str(data.get("session_id") or "")
        m = re.search(r'"chatId"\s*:\s*"(oc_[A-Za-z0-9]+)"', str(data.get("prompt") or ""))
        if not session or not m:
            return
        path = f"/tmp/.aaw_turn_{session}.json"
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"session": session, "prompt_id": data.get("prompt_id"), "chat": m.group(1),
                       "t0": time.time(), "tools": 0, "auto_tries": 0}, f)
        os.replace(tmp, path)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    record_turn(data)
    context = build(str(data.get("prompt") or ""), str(data.get("cwd") or ""))
    if not context:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
