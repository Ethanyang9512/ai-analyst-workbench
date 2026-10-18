#!/usr/bin/env python3
"""长任务状态卡片：一张卡原地刷新，上方耗时、下方当前步骤。

  card.py start <chatId> "任务名" "步骤1|步骤2|步骤3"   # 发卡 + 自动起心跳
  card.py step <n> "正在做什么"                          # n 从 1 开始
  card.py note "补充一句"                                # 只改下方文字，不换步
  card.py done "一句话结论"                              # 收尾（先停心跳）
  card.py heartbeat                                      # 内部：定时刷耗时
  card.py auto <chatId> "任务名"                          # 内部：系统自动起卡（分析助手的进度钩子 hooks/progress.py 用）

状态文件里有 act（当前动作，由钩子自动写入）时，卡片多显示一行“当前动作”；
系统已经自动起了卡时，再 start 会接着用那张卡，不会另起一张。
卡片通过 lark-cli 以机器人身份（--as bot）发送和原地更新；状态文件在 /tmp/.claude_card_<群号后 12 位>.json。

step/note/done 找卡的规则：
  1. 环境变量 CARD_CHAT=<chatId> 明确指定 —— 推荐写法：CARD_CHAT=<chat_id> ./bin/card.py step 2 "…"
  2. 没指定时，若本机只有一张进行中的卡，自动用它
  3. 有多张进行中的卡 -> 拒绝执行并列出候选（AMBIGUOUS），绝不猜"最近那张"
"""
import glob, json, os, signal, subprocess, sys, time

_CH = os.environ.get("CARD_CHAT", "")


def _paths(chat=None):
    key = (chat or _CH or "default")[-12:]
    return f"/tmp/.claude_card_{key}.json", f"/tmp/.claude_card_{key}.pid"


S, PID = _paths()
TICK = 10          # 心跳间隔（秒）
MAX_MIN = 30       # 超过这么久没收尾 -> 自动标记异常，绝不冻死
HB_FAIL_ALERT = 3  # 心跳连续 PATCH 失败这么多次 -> 发一条文字提醒（只发一次）
API_TIMEOUT = 20   # 调 lark-cli 最多等这么久（秒），卡住就当这次失败


def load():
    return json.load(open(S, encoding="utf-8"))


def save(d):
    tmp = f"{S}.{os.getpid()}.tmp"       # 带进程号：两个进程同时写也不会互相踩
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, S)          # 原子替换，避免心跳读到写了一半的文件


def elapsed(d):
    sec = int(time.time() - d["t0"])
    return f"{sec//60}:{sec%60:02d}"


def build(d):
    el, term, name = elapsed(d), d.get("terminal"), d.get("name", "")
    tag = f"{name} · " if name else ""
    if term == "done":
        head, tmpl = f"✅ {tag}已完成 · 用时 {el}", "green"
    elif term == "stale":
        head, tmpl = f"⚠️ {tag}超过 {MAX_MIN} 分钟未收到收尾信号 · {el}", "orange"
    else:
        head, tmpl = f"⏳ {tag}进行中 · 已耗时 {el}", "blue"
    cur, n = d["cur"], len(d["steps"])
    lines = [f"{'✅' if (i < cur or term == 'done') else ('⏳' if i == cur else '⬜')} {i}. {s}"
             for i, s in enumerate(d["steps"], 1)]
    first = [{"tag": "div", "text": {"tag": "lark_md", "content": f"**{d.get('msg', '')}**"}}]
    act = d.get("act")
    if act and not term:
        age = int(time.time() - d.get("act_ts", time.time()))
        ago = "刚刚" if age < 20 else (f"{age} 秒前" if age < 90 else f"{age // 60} 分钟前")
        first.append({"tag": "div", "text": {"tag": "lark_md", "content": f"当前动作：{act}（{ago}）"}})
    return {"config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"template": tmpl, "title": {"tag": "plain_text", "content": head}},
            "elements": first + [
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
                {"tag": "note", "elements": [{"tag": "plain_text",
                 "content": f"共 {n} 步 · 每 {TICK} 秒刷新"}]}]}


def api(method, path, data, params=None):
    cmd = ["lark-cli", "api", method, path, "--as", "bot",
           "--data", json.dumps(data, ensure_ascii=False)]
    if params:
        cmd += ["--params", json.dumps(params, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=API_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "raw": f"lark-cli {API_TIMEOUT} 秒没有返回"}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout or r.stderr)[:200]}


def send_text(chat, text):
    return api("POST", "/open-apis/im/v1/messages",
               {"receive_id": chat, "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False)},
               {"receive_id_type": "chat_id"})


def push(d, retry=True):
    r = api("PATCH", f"/open-apis/im/v1/messages/{d['mid']}",
            {"content": json.dumps(build(d), ensure_ascii=False)})
    if not r.get("ok") and retry:
        time.sleep(2)
        return push(d, retry=False)
    return r


def push_or_fallback(d):
    """用户触发的更新：卡片 PATCH 失败就改发一条文字，别让用户对着旧卡等。"""
    r = push(d)
    if r.get("ok"):
        return "ok"
    send_text(d["chat"], f"⚠️ 状态卡更新失败，改用文字播报：{d.get('msg', '')}")
    return "patch_failed(text_sent)"


def _is_heartbeat(pid):
    """这个进程号确实是 card.py 的心跳（看命令行）；进程号被系统复用给别的进程时不是。"""
    try:
        line = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=5).stdout
    except Exception:
        return False
    return "card.py" in line and "heartbeat" in line


def stop_heartbeat():
    try:
        pid = int(open(PID).read().strip())
        if _is_heartbeat(pid):          # 不是心跳就只删 pid 文件，不杀
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    try:
        os.remove(PID)
    except Exception:
        pass


def spawn_heartbeat():
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "heartbeat"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env={**os.environ, "CARD_CHAT": _CH})


def _pid_alive(pidfile):
    try:
        os.kill(int(open(pidfile).read().strip()), 0)
        return True
    except Exception:
        return False


def _active_cards():
    """本机所有"进行中"的卡：状态文件 terminal 为空，且心跳还活着或刚 stale。"""
    out = []
    for f in glob.glob("/tmp/.claude_card_*.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("terminal") == "done":
            continue
        if d.get("terminal") == "stale" and time.time() - d.get("t0", 0) > 3 * 3600:
            continue                    # 几小时前橙掉的旧卡不算候选
        out.append(d)
    return out


cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
if cmd in ("step", "note", "done") and not _CH:
    act = _active_cards()
    if len(act) == 1:
        _CH = act[0]["chat"]
        S, PID = _paths(_CH)
    elif len(act) > 1:
        print("AMBIGUOUS: 本机有多张进行中的卡，请用 CARD_CHAT=<chatId> 指定：")
        for d in act:
            print(f"  CARD_CHAT={d['chat']}   # {d.get('name','')} · {d.get('msg','')}")
        sys.exit(2)
    else:
        print("NO_ACTIVE_CARD: 没有进行中的卡，先 card.py start"); sys.exit(2)

if cmd in ("start", "auto"):
    chat, name = sys.argv[2], sys.argv[3]
    steps = sys.argv[4].split("|") if cmd == "start" and len(sys.argv) > 4 else ["处理中"]
    _CH = chat
    S, PID = _paths(chat)
    LOCK = S[:-5] + ".autolock"          # 进度钩子自动起卡时放的锁（hooks/progress.py）
    if cmd == "auto":
        import atexit
        atexit.register(lambda: os.path.exists(LOCK) and os.remove(LOCK))
    else:                                # 系统正在自动起卡：等它起完，接着用那张卡，不另起一张
        for _ in range(25):
            try:
                if time.time() - os.path.getmtime(LOCK) > 8:
                    break
            except OSError:
                break
            time.sleep(0.2)
    old = None
    try:
        old = load()
    except Exception:
        pass
    alive = bool(old) and not old.get("terminal") and old.get("mid") and _pid_alive(PID)
    if cmd == "auto" and alive:
        print("card: 已有进行中的卡，不重复起"); sys.exit(0)
    if cmd == "start" and alive and old.get("auto"):
        # 系统已经自动起了卡：接着用那张卡，换成模型给的任务名和步骤，耗时接着走
        old.update({"name": name, "steps": steps, "cur": 1, "auto": False,
                    "msg": f"第 1/{len(steps)} 步 · {steps[0]}"})
        save(old)
        print("card:", old["mid"], "| 接着用系统自动起的卡 |", push_or_fallback(old),
              "| 后续请用 CARD_CHAT=%s ./bin/card.py step/note/done" % chat)
        sys.exit(0)
    stop_heartbeat()
    d = {"chat": chat, "name": name, "steps": steps, "cur": 1, "t0": time.time(),
         "msg": f"第 1/{len(steps)} 步 · {steps[0]}", "terminal": None, "hb_fail": 0}
    if cmd == "auto":
        d["auto"] = True
        d["msg"] = "正在处理你的消息"
        if len(sys.argv) > 4:
            d["act"], d["act_ts"] = sys.argv[4], time.time()
    r = api("POST", "/open-apis/im/v1/messages",
            {"receive_id": chat, "msg_type": "interactive",
             "content": json.dumps(build(d), ensure_ascii=False)},
            {"receive_id_type": "chat_id"})
    mid = (r.get("data") or {}).get("message_id")
    if not mid:
        print("START_FAILED", json.dumps(r, ensure_ascii=False)[:200]); sys.exit(1)
    d["mid"] = mid; save(d)
    spawn_heartbeat()
    if cmd == "start":                   # 自动起的卡不重置计时器（计时器全机共用）
        subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "t"), "start"],
                       capture_output=True)
    print("card:", mid, "| 后续请用 CARD_CHAT=%s ./bin/card.py step/note/done" % chat)

elif cmd in ("step", "note"):
    d = load()
    if cmd == "step":
        d["cur"] = int(sys.argv[2])
        d["msg"] = f"第 {d['cur']}/{len(d['steps'])} 步 · {sys.argv[3]}"
    else:
        d["msg"] = sys.argv[2]
    revived = d.get("terminal") == "stale"
    if revived:                 # 橙色之后又有真实进展 -> 恢复蓝色，重新起心跳
        d["terminal"] = None
        d["hb_fail"] = 0
    save(d)
    if revived:
        stop_heartbeat(); spawn_heartbeat()
    print(push_or_fallback(d) + (" (revived from stale)" if revived else ""))

elif cmd == "done":
    stop_heartbeat(); time.sleep(1)
    d = load(); d["terminal"] = "done"; d["cur"] = len(d["steps"]) + 1
    d["msg"] = sys.argv[2] if len(sys.argv) > 2 else "全部完成"
    save(d)
    print(push_or_fallback(d))

elif cmd == "heartbeat":
    open(PID, "w").write(str(os.getpid()))
    for _ in range(int(MAX_MIN * 60 / TICK)):
        time.sleep(TICK)
        try:
            d = load()
        except Exception:
            break
        if d.get("terminal"):
            break
        ok = push(d, retry=False).get("ok")
        d = load()                          # step/note 可能刚改过，别用旧快照覆盖
        d["hb_fail"] = 0 if ok else d.get("hb_fail", 0) + 1
        if d["hb_fail"] == HB_FAIL_ALERT and not d.get("hb_alerted"):
            d["hb_alerted"] = True
            send_text(d["chat"], f"⚠️ 「{d.get('name','')}」状态卡连续 {HB_FAIL_ALERT} 次刷新失败，"
                                 f"卡片上的耗时可能不准；当前进度：{d.get('msg','')}")
        save(d)
    else:                       # 循环跑满 = 没人收尾，标记异常而不是永远转圈
        try:
            d = load()
            if not d.get("terminal"):
                d["terminal"] = "stale"
                d["msg"] = "任务可能已中断，请查看聊天里的最后一条消息"
                save(d); push(d)
        except Exception:
            pass
    try:
        os.remove(PID)
    except Exception:
        pass

else:                                   # 不认识的子命令（含不带参数）：打印用法
    print(__doc__.strip())
    sys.exit(2)
