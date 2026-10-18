#!/usr/bin/env python3
"""进度卡自动刷新（PreToolUse，所有工具）。

分析助手每做一步（调用一次工具），把“当前动作”写进进度卡的状态文件；进度卡自带的心跳程序每 10 秒
把它推到飞书。任务跑了一阵还没有进度卡时，自动起一张。

为什么要它：用户在飞书里只看得到发回的消息，长任务中途一片安静，会以为机器人卡住了。

设计要点（按对抗式审查的意见定）：
  - 钩子只写本机的状态文件，不直接调用飞书；推送仍由心跳程序一处负责，避免两头同时改卡。
  - 要叫子代理时（往往一去几分钟）不等 30 秒，马上起卡。
  - 本轮的卡超过 30 分钟被心跳标成“可能已中断”、而任务其实还在跑时，把卡恢复成进行中。
  - 一轮最多自动起一张卡：并行的工具调用用一把锁抢（只有一个能起）；本轮已经有过卡（哪怕已收尾）就不再起；
    起卡失败，60 秒后最多再试一次。
  - 子代理里的工具调用不算（不刷屏）。
  - 任何异常都安静退出，不影响任务本身。
"""
import json
import os
import re
import subprocess
import sys
import time

RUNTIME = os.environ.get("AAW_RUNTIME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_PY = os.environ.get("AAW_CARD_PY") or os.path.join(RUNTIME, "bin", "card.py")
AUTO_AFTER_SEC = 30      # 这一轮跑了多久之后才自动起卡
AUTO_MIN_TOOLS = 2       # 至少调用过几次工具才自动起卡
LONG_TOOLS = ("Agent", "Task")   # 这类调用一去几分钟：不等上面两个条件，马上起卡


def turn_path(session_id):
    return f"/tmp/.aaw_turn_{session_id}.json"


def card_path(chat):
    return f"/tmp/.claude_card_{chat[-12:]}.json"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def lock_path(chat, kind):
    return f"/tmp/.claude_card_{chat[-12:]}.{kind}"


def acquire(path, stale):
    """抢一把锁，抢到返回 True。超过 stale 秒的旧锁先清掉。"""
    try:
        if time.time() - os.path.getmtime(path) > stale:
            os.remove(path)
    except OSError:
        pass
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def describe(tool, inp):
    """把一次工具调用说成一句人话。"""
    inp = inp if isinstance(inp, dict) else {}
    name = lambda p: os.path.basename(str(p or "")) or "文件"
    if tool == "Bash":
        return str(inp.get("description") or "运行命令").strip()
    if tool == "Read":
        return f"读取 {name(inp.get('file_path'))}"
    if tool in ("Write", "Edit", "NotebookEdit"):
        return f"写入 {name(inp.get('file_path') or inp.get('notebook_path'))}"
    if tool in ("Agent", "Task"):
        return "交给子代理：" + str(inp.get("description") or "处理中").strip()
    if tool == "Skill":
        return f"加载技能 {inp.get('skill') or ''}".strip()
    if tool in ("WebSearch", "WebFetch"):
        return "查资料"
    if tool in ("Grep", "Glob"):
        return "查找文件"
    return f"使用 {tool}"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("agent_id") or data.get("agent_type"):
        return                                  # 子代理里的调用不算
    session = str(data.get("session_id") or "")
    if not session:
        return
    turn = read_json(turn_path(session))
    if not turn or not turn.get("chat") or turn.get("prompt_id") != data.get("prompt_id"):
        return                                  # 这一轮没有登记群号（不是桥里的消息）
    tool = str(data.get("tool_name") or "")
    inp = data.get("tool_input") or {}
    if tool == "Bash" and "card.py" in str(inp.get("command") or ""):
        return                                  # 分析助手自己在操作进度卡
    now = time.time()
    turn["tools"] = int(turn.get("tools", 0)) + 1
    chat = turn["chat"]
    t0 = float(turn.get("t0", now))
    card = read_json(card_path(chat))
    has_card = bool(card) and bool(card.get("mid"))
    this_turn = has_card and float(card.get("t0", 0)) >= t0          # 本轮起的卡（不管是否已收尾）
    active = has_card and not card.get("terminal")
    stale = this_turn and card.get("terminal") == "stale"
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 start_new_session=True)
    tries = int(turn.get("auto_tries", 0))
    wanted = tool in LONG_TOOLS or (turn["tools"] >= AUTO_MIN_TOOLS and now - t0 >= AUTO_AFTER_SEC)
    if active or stale:
        card["act"] = describe(tool, inp)[:60]
        card["act_ts"] = now
        write_json(card_path(chat), card)
        if stale and os.path.isfile(CARD_PY) and acquire(lock_path(chat, "revive"), stale=30):
            subprocess.Popen([sys.executable, CARD_PY, "note", "任务仍在进行"],
                             env={**os.environ, "CARD_CHAT": chat}, **quiet)
    elif (not this_turn and wanted and os.path.isfile(CARD_PY)
          and (tries == 0 or (tries == 1 and now - float(turn.get("auto_ts", 0)) >= 60))
          and acquire(lock_path(chat, "autolock"), stale=60)):
        turn["auto_tries"] = tries + 1
        turn["auto_ts"] = now
        subprocess.Popen([sys.executable, CARD_PY, "auto", chat, "本轮任务", describe(tool, inp)[:60]], **quiet)
    write_json(turn_path(session), turn)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
