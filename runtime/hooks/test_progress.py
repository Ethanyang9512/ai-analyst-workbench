#!/usr/bin/env python3
"""进度卡钩子的回归测试：python3 test_progress.py
用一张假的进度卡程序代替真的，不发飞书。"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="aaw-prog-")
FAKE = os.path.join(TMP, "fake_card.py")
CALLS = os.path.join(TMP, "calls.log")
FAKE_SRC = r'''#!/usr/bin/env python3
# 测试用的假进度卡：不发飞书，只改状态文件、记调用。FAKE_FAIL=1 模拟起卡失败，FAKE_DELAY 模拟接口慢。
import json, os, sys, time
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.log")
open(log, "a").write(json.dumps(sys.argv[1:] + [os.environ.get("CARD_CHAT", "")], ensure_ascii=False) + "\n")
cmd = sys.argv[1]
if cmd == "auto":
    chat = sys.argv[2]; p = f"/tmp/.claude_card_{chat[-12:]}.json"
    time.sleep(float(os.environ.get("FAKE_DELAY", "0")))
    if not os.environ.get("FAKE_FAIL"):
        json.dump({"chat": chat, "name": sys.argv[3], "steps": ["处理中"], "cur": 1, "t0": time.time(),
                   "msg": "正在处理你的消息", "terminal": None, "mid": "om_fake", "auto": True}, open(p, "w"))
    lock = p[:-5] + ".autolock"
    if os.path.exists(lock): os.remove(lock)
elif cmd in ("done", "note"):
    chat = os.environ["CARD_CHAT"]; p = f"/tmp/.claude_card_{chat[-12:]}.json"
    d = json.load(open(p)); d["terminal"] = "done" if cmd == "done" else None; json.dump(d, open(p, "w"))
'''
ENV = dict(os.environ, LARK_CHANNEL_PROFILE="aaw", AAW_PROFILE="aaw", AAW_CARD_PY=FAKE,
           AAW_HOOK_STATE=TMP)   # run-hook.sh 的“最近一次触发”记号写到临时目录，不动正式的


def hook(name, payload, env=ENV):
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), name], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout


def calls():
    return [json.loads(x) for x in open(CALLS, encoding="utf-8")] if os.path.exists(CALLS) else []


def wait_for(cond, sec=3.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class Turn:
    """一轮对话：登记群号，然后可以模拟工具调用。"""

    def __init__(self):
        uid = uuid.uuid4().hex
        self.chat = "oc_progtest" + uid[:24]
        self.sid = "sess-progtest-" + uid[:8]
        self.card = f"/tmp/.claude_card_{self.chat[-12:]}.json"
        self.turn = f"/tmp/.aaw_turn_{self.sid}.json"
        self.base = {"session_id": self.sid, "prompt_id": "prompt-1", "cwd": "/x"}
        prompt = ('<bridge_context>\n{"chatId":"%s","chatType":"group"}\n</bridge_context>\n'
                  '<user_input>\n{"text":"帮我审一下这个包"}\n</user_input>' % self.chat)
        hook("remind", dict(self.base, hook_event_name="UserPromptSubmit", prompt=prompt))

    def payload(self, name, inp, **extra):
        return dict(self.base, hook_event_name="PreToolUse", tool_name=name, tool_input=inp, **extra)

    def tool(self, name, inp, env=ENV, **extra):
        return hook("progress", self.payload(name, inp, **extra), env=env)

    def stop(self, env=ENV):
        return hook("progress_stop", dict(self.base, hook_event_name="Stop", stop_hook_active=False), env=env)

    def patch(self, path, **kv):
        d = json.load(open(path)); d.update(kv); json.dump(d, open(path, "w"))

    def age(self, sec):
        self.patch(self.turn, t0=time.time() - sec)

    def read(self, path=None):
        try:
            return json.load(open(path or self.card))
        except Exception:
            return {}

    def mine(self):
        return [c for c in calls() if self.chat in c]

    def clean(self):
        for f in [self.turn] + glob.glob(self.card[:-5] + ".*"):
            if os.path.exists(f):
                os.remove(f)


def main():
    with open(FAKE, "w", encoding="utf-8") as f:
        f.write(FAKE_SRC)
    res = []
    ok = lambda name, good: res.append((name, bool(good)))

    # ---- 一轮正常的任务
    a = Turn()
    try:
        ok("登记了群号", a.read(a.turn).get("chat") == a.chat and a.read(a.turn).get("tools") == 0)
        a.tool("Read", {"file_path": "/a/b/数据包说明.md"})
        ok("第 1 步、未满 30 秒：不起卡", not os.path.exists(a.card))
        a.age(40)
        a.tool("Bash", {"command": "python3 x.py", "description": "解压数据包并核对文件数"})
        ok("超过 30 秒且第 2 步：自动起卡", wait_for(lambda: a.read().get("auto") is True))
        ok("起卡时带上当前动作", a.mine()[-1][:4] == ["auto", a.chat, "本轮任务", "解压数据包并核对文件数"])
        a.tool("Bash", {"command": "python3 y.py", "description": "核对行数与哈希"})
        ok("卡片写入当前动作", a.read().get("act") == "核对行数与哈希")
        a.tool("Bash", {"command": "ls", "description": "子代理里的动作"}, agent_id="a1", agent_type="general-purpose")
        ok("子代理的动作不算", a.read().get("act") == "核对行数与哈希")
        a.tool("Bash", {"command": 'CARD_CHAT=x ./bin/card.py step 2 "出图"', "description": "更新进度卡"})
        ok("分析助手自己操作进度卡时不覆盖", a.read().get("act") == "核对行数与哈希")
        a.tool("Agent", {"description": "读者验收", "prompt": "…"})
        ok("叫子代理时显示人话", a.read().get("act") == "交给子代理：读者验收")
        hook("progress", dict(a.payload("Read", {"file_path": "/z.md"}), prompt_id="prompt-OLD"))
        ok("不是本轮的调用不处理", a.read().get("act") == "交给子代理：读者验收")

        # 卡片超过 30 分钟被标成“可能已中断”，任务其实还在跑
        a.patch(a.card, terminal="stale")
        n = len(a.mine())
        a.tool("Bash", {"command": "python3 z.py", "description": "继续出图"})
        ok("本轮的卡被标成中断：恢复成进行中",
           wait_for(lambda: len(a.mine()) == n + 1 and a.mine()[-1][:2] == ["note", "任务仍在进行"]
                    and a.read().get("terminal") is None))
        a.patch(a.card, terminal="stale")
        a.tool("Bash", {"command": "python3 z2.py", "description": "再出一张"})
        time.sleep(0.4)
        ok("30 秒内不重复恢复", len(a.mine()) == n + 1)

        # 分析助手自己收了卡，之后又做了别的事：不再另起一张
        a.patch(a.card, terminal="done")
        a.tool("Bash", {"command": "python3 w.py", "description": "更新项目进度文件"})
        a.tool("Agent", {"description": "再审一次", "prompt": "…"})
        time.sleep(0.4)
        ok("本轮已经收过卡：不再另起", [c[0] for c in a.mine()] == ["auto", "note"])
        a.stop()
        ok("已收尾的卡：结束时不重复收尾", [c[0] for c in a.mine()] == ["auto", "note"])
    finally:
        a.clean()

    # ---- 一上来就叫子代理：不等 30 秒；一轮结束自动收尾
    b = Turn()
    try:
        b.tool("Agent", {"description": "图表与数字验收", "prompt": "…"})
        ok("第 1 步就叫子代理：马上起卡", wait_for(lambda: b.read().get("auto") is True))
        b.stop()
        ok("一轮结束自动收尾", b.read().get("terminal") == "done" and [c[0] for c in b.mine()] == ["auto", "done"])
    finally:
        b.clean()

    # ---- 同时发出三个子代理调用：只起一张卡
    p3 = Turn()
    try:
        procs = [subprocess.Popen([os.path.join(HERE, "run-hook.sh"), "progress"], stdin=subprocess.PIPE, env=ENV,
                                  stdout=subprocess.DEVNULL, text=True) for _ in range(3)]
        for i, pr in enumerate(procs):
            pr.stdin.write(json.dumps(p3.payload("Agent", {"description": f"验收 {i}", "prompt": "…"})))
            pr.stdin.close()
        for pr in procs:
            pr.wait()
        time.sleep(0.5)
        ok("并行的三个调用：只起一张卡", [c[0] for c in p3.mine()] == ["auto"])
    finally:
        p3.clean()

    # ---- 以前留下的旧卡（不是本轮起的）不去恢复，另起一张
    d = Turn()
    try:
        json.dump({"chat": d.chat, "name": "旧任务", "steps": ["处理中"], "cur": 1, "t0": time.time() - 7200,
                   "msg": "任务可能已中断", "terminal": "stale", "mid": "om_old"}, open(d.card, "w"))
        d.age(40)
        d.tool("Read", {"file_path": "/a.md"})
        d.tool("Read", {"file_path": "/b.md"})
        ok("两小时前的旧卡不恢复，另起新卡", wait_for(lambda: [c[0] for c in d.mine()] == ["auto"]))
    finally:
        d.clean()

    # ---- 起卡失败：60 秒后最多再试一次
    f = Turn()
    try:
        fail = dict(ENV, FAKE_FAIL="1")
        f.tool("Agent", {"description": "验收", "prompt": "…"}, env=fail)
        wait_for(lambda: len(f.mine()) == 1 and not glob.glob(f.card[:-5] + ".autolock"))
        for i in range(3):
            f.tool("Bash", {"command": "x", "description": f"第 {i} 步"}, env=fail)
        time.sleep(0.3)
        ok("起卡失败后 60 秒内不重试", [c[0] for c in f.mine()] == ["auto"])
        f.patch(f.turn, auto_ts=time.time() - 61, t0=time.time() - 120)
        f.tool("Bash", {"command": "x", "description": "又一步"}, env=fail)
        wait_for(lambda: len(f.mine()) == 2 and not glob.glob(f.card[:-5] + ".autolock"))
        f.patch(f.turn, auto_ts=time.time() - 61)
        f.tool("Bash", {"command": "x", "description": "再一步"}, env=fail)
        time.sleep(0.3)
        ok("60 秒后再试一次，之后不再试", [c[0] for c in f.mine()] == ["auto", "auto"])
    finally:
        f.clean()

    # ---- 本轮的卡被标成中断后再没有新动作：结束时照样收尾
    g = Turn()
    try:
        g.tool("Agent", {"description": "很长的验收", "prompt": "…"})
        wait_for(lambda: g.read().get("auto") is True)
        g.patch(g.card, terminal="stale")
        g.stop()
        ok("被标成中断的本轮卡：结束时收尾", g.read().get("terminal") == "done")
    finally:
        g.clean()

    # ---- 系统正在后台起卡时这一轮就结束了：等它起完再收尾
    h = Turn()
    try:
        slow = dict(ENV, FAKE_DELAY="1.2")
        h.tool("Agent", {"description": "验收", "prompt": "…"}, env=slow)
        h.stop()
        ok("起卡还在途时结束：等卡出来再收尾", h.read().get("terminal") == "done"
           and [c[0] for c in h.mine()] == ["auto", "done"])
    finally:
        h.clean()

    # ---- 没有卡时，一轮结束什么都不做；别的身份不登记
    e = Turn()
    try:
        code, out = e.stop()
        ok("没有卡：收尾钩子不做事也不输出", code == 0 and not out.strip() and not e.mine())
        os.remove(e.turn)
        prompt = '<bridge_context>\n{"chatId":"%s"}\n</bridge_context>\n<user_input>\n{"text":"hi"}\n</user_input>' % e.chat
        hook("remind", dict(e.base, hook_event_name="UserPromptSubmit", prompt=prompt),
             env=dict(os.environ, LARK_CHANNEL_PROFILE="other-bot", AAW_PROFILE="aaw"))
        ok("别的机器人的身份不登记", not os.path.exists(e.turn))
        code, out = e.tool("Read", {})
        ok("没登记的会话：进度钩子不做事", code == 0 and not out.strip() and not os.path.exists(e.card))
    finally:
        e.clean()

    bad = 0
    for name, good in res:
        if not good:
            bad += 1
            print("FAIL", name)
    print(f"{len(res) - bad}/{len(res)} 通过")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
