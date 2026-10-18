#!/usr/bin/env python3
"""这一轮结束时，把还开着的进度卡收尾（Stop）。

不拦截、不输出任何东西；只做一件事：如果当前群的进度卡还在“进行中”，把它标成已完成。
本轮的卡被标成“可能已中断”的也一并收尾。系统正在后台起卡时，先等它几秒再收。
这样不会留下一张永远转圈的卡。任何异常都安静退出。
Stop 钩子只做这种安静的收尾：它在每一轮结束时都会跑，输出内容或拦截都可能打乱桥的“最终回复”判断。
"""
import json
import os
import subprocess
import sys
import time

RUNTIME = os.environ.get("AAW_RUNTIME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_PY = os.environ.get("AAW_CARD_PY") or os.path.join(RUNTIME, "bin", "card.py")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    session = str(data.get("session_id") or "")
    turn = read_json(f"/tmp/.aaw_turn_{session}.json") if session else None
    if not turn or not turn.get("chat"):
        return
    chat = turn["chat"]
    lock = f"/tmp/.claude_card_{chat[-12:]}.autolock"
    deadline = time.time() + 4
    while os.path.exists(lock) and time.time() < deadline:      # 系统正在后台起卡
        time.sleep(0.2)
    card = read_json(f"/tmp/.claude_card_{chat[-12:]}.json")
    if not card or not card.get("mid") or not os.path.isfile(CARD_PY):
        return
    mine = float(card.get("t0", 0)) >= float(turn.get("t0", 0))
    if card.get("terminal") == "done" or (card.get("terminal") == "stale" and not mine):
        return
    subprocess.run([sys.executable, CARD_PY, "done", "这一轮已结束，结论见下方回复"],
                   env={**os.environ, "CARD_CHAT": chat}, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
