#!/usr/bin/env python3
"""run_case.sh 的收尾：写 done.txt（退出码、起止时间、会话号、花费）。
用法: finish.py <case> <退出码> <开始> <结束> <秒数>；可单独重跑。
花费：先记会话结果事件里的 total_cost_usd；装了 ccusage（PATH 里找得到）时，再离线算一遍 token 数和美元数。"""
import json
import os
import shutil
import subprocess
import sys

case, rc, start, end, secs = sys.argv[1:6]
sid = res = None
with open(case + "/out.jsonl", encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            sid = e.get("session_id")
        if e.get("type") == "result":
            res = e
usage = None
ccusage = shutil.which("ccusage")
if sid and ccusage:
    try:
        out = subprocess.run([ccusage, "session", "-i", sid, "--json", "--offline"],
                             capture_output=True, text=True, timeout=180).stdout
        usage = json.loads(out)
    except Exception as ex:
        usage = {"error": str(ex)[:200]}


def usage_sum(usage):
    """ccusage --offline 的结果：美元数 + 四类 token 合计。离线价格表里没有的型号，美元数会是 0，照实标出来。"""
    if not isinstance(usage, dict) or "entries" not in usage:
        return "n/a", "n/a"
    t = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    for e in usage.get("entries") or []:
        t["input"] += e.get("inputTokens") or 0
        t["output"] += e.get("outputTokens") or 0
        t["cache_create"] += e.get("cacheCreationTokens") or 0
        t["cache_read"] += e.get("cacheReadTokens") or 0
    usd = usage.get("totalCost")
    if not usd and sum(t.values()) > 0:
        usd = "0（未定价：ccusage 离线价格表里没有这个型号，不联网就算不出美元数）"
    return usd, " ".join("%s=%d" % kv for kv in t.items())


usage_usd, usage_tok = usage_sum(usage)
lines = [
    "exit=%s" % rc, "start=%s" % start, "end=%s" % end, "seconds=%s" % secs,
    "timeout=%s" % ("yes" if os.path.exists(case + "/run/timeout") else "no"),
    "session_id=%s" % sid,
    "result_subtype=%s" % (res or {}).get("subtype"),
    "is_error=%s" % (res or {}).get("is_error"),
    "num_turns=%s" % (res or {}).get("num_turns"),
    "cost_usd_result_event=%s" % (res or {}).get("total_cost_usd"),
    "cost_usd_ccusage_offline=%s" % (usage_usd if ccusage else "n/a（没装 ccusage）"),
    "tokens_ccusage=%s" % usage_tok,
]
open(case + "/done.txt", "w").write("\n".join(lines) + "\n")
if usage is not None:
    json.dump(usage, open(case + "/run/ccusage.json", "w"), ensure_ascii=False, indent=1)
print("\n".join(lines))
