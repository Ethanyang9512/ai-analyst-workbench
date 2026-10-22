#!/usr/bin/env python3
"""护栏规则的回归测试：python3 test_guard.py
全部在临时目录里搭（假的工作区总目录、钩子状态目录），不写正式日志、不碰真实工作区。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.realpath(tempfile.mkdtemp(prefix="aaw-guard-"))
os.environ["AAW_HOOK_STATE"] = os.path.join(TMP, "state")          # 测试不写正式日志
os.environ["AAW_WS_BASE"] = os.path.join(TMP, "workspaces")        # 假的工作区总目录
os.environ["AAW_PROFILE"] = "aaw"
for k in ("AAW_RUNTIME", "AAW_BRIDGE_CONFIG", "AAW_BRIDGE_HOME", "AAW_BRIDGE_NAMES"):
    os.environ.pop(k, None)
os.makedirs(os.environ["AAW_HOOK_STATE"])
WS = os.path.join(os.environ["AAW_WS_BASE"], "demo-project")       # 假的项目工作区
os.makedirs(os.path.join(WS, ".claude"))                              # 工作区自己的设置目录（受保护）
sys.path.insert(0, HERE)
import guard  # noqa: E402
from guard import decide  # noqa: E402

RT = guard.RUNTIME                      # 本仓库的 runtime 目录（受保护）
H = os.path.expanduser("~")
CHAT = "oc_guardtestchatfake"
OTHER = "oc_otherchatfake"
CONTEXT = [   # (命令, cwd, 应当命中的规则；None 表示放行)
    ("touch " + RT + "/hooks/DISABLED", WS, "self-protect"),
    ("rm " + RT + "/hooks/GATE_ENFORCE", WS, "self-protect"),
    ("echo '{}' > .claude/settings.json", WS, "self-protect"),
    ("cat x.json >> ~/.claude/settings.local.json", WS, "self-protect"),
    ("sed -i '' 's/a/b/' ~/.claude/CLAUDE.md", WS, "self-protect"),
    ("cp evil.md ~/.claude/agents/", WS, "self-protect"),
    ("chmod 000 " + RT + "/workflow.md", WS, "self-protect"),
    ("rm -rf .claude", WS, "self-protect"),
    ("rm -rf ~/.claude", WS, "self-protect"),
    ("cd " + RT + "/hooks && touch DISABLED", WS, "self-protect"),
    ("touch DISABLED", RT + "/hooks", "self-protect"),
    ('F=~/.claude/settings.json; echo x > "$F"', WS, "self-protect"),
    ("echo x | tee -a " + RT + "/tools/accept_record.py", WS, "self-protect"),
    ('touch "$AAW_RUNTIME/hooks/DISABLED"', WS, "self-protect"),          # 变量写法（钩子按自己的环境代入）
    ("touch " + os.environ["AAW_HOOK_STATE"] + "/GATE_ENFORCE", WS, "self-protect"),   # 改验收门模式
    ("python3 -c \"open('" + H + "/.claude/settings.json','w').write('{}')\"", WS, "self-protect"),
    ("python3 - <<'EOF'\nimport pathlib\npathlib.Path('" + H + "/.claude/CLAUDE.md').write_text('x')\nEOF", WS,
     "self-protect"),
    ("find " + RT + "/hooks -name '*.py' -delete", WS, "self-protect"),
    ("cat ~/.claude/settings.json && grep -n hooks .claude/settings.json && ls ~/.claude/agents/", WS, None),
    ("cp ~/.claude/agents/cold-reader.md /tmp/x.md", WS, None),
    ("python3 " + RT + "/tools/accept_record.py write --file a.pptx --reader x --visual y", WS, None),
    ("python3 -c \"import json; d=json.load(open('.claude/settings.json')); open('/tmp/o.json','w').write(str(d))\"",
     WS, None),
    ("echo ok > _status.md; mkdir -p _acceptance; cat > ~/.claude/projects/demo/memory/x.md <<'EOF'\nhi\nEOF",
     WS, None),
    ("cp ~/.claude/skills/ethan-report-writing/scripts/figcheck.py . && python3 figcheck.py > out.txt 2>&1", WS, None),
    ("lark-cli im +messages-send --as bot --chat-id " + CHAT + " --text '请运行 rm ~/.claude/settings.json'", WS, None),
    ("echo a#b > notes.md", WS, None),
    ("python3 " + RT + "/hooks/test_guard.py > /tmp/g.txt", WS, None),
    ("~/.lark-channel/secrets-getter feishu", WS, "secrets"),
    ("security find-generic-password -s lark -w", WS, "secrets"),
    ("security dump-keychain > /tmp/k.txt", WS, "secrets"),
    ("xxd ~/.lark-channel/secrets.enc | head", WS, "secrets"),
    ("cat ~/.lark-channel/.keystore.salt", WS, "secrets"),
    ("echo 'security review done' && grep -rn security notes.md", WS, None),
    ("lark-cli im +messages-send --as bot --chat-id " + OTHER + " --text hi", WS, "other-target"),
    ("lark-cli im +messages-send --as bot --chat-id '" + OTHER + "' --text hi", WS, "other-target"),
    ("lark-cli im +messages-send --as bot --user-id ou_abc --text hi", WS, "other-target"),
    ("lark-cli im +messages-send --as bot --email someone_at_example --file x.pptx", WS, "other-target"),
    ("lark-cli api POST /open-apis/im/v1/messages --as bot --params '{\"receive_id_type\":\"open_id\"}' "
     "--data '{\"receive_id\":\"ou_x\"}'", WS, "other-target"),
    ("./bin/p " + OTHER + " '第 1/2 步'", WS, "other-target"),
    ("./bin/card.py start " + OTHER + " '任务' 'a|b'", WS, "other-target"),
    ("ALLOW_OTHER_TARGET='用户让发到运营群' lark-cli im +messages-send --as bot --chat-id " + OTHER + " --text hi", WS,
     "other-target-allowed"),
    ("lark-cli im +messages-send --as bot --chat-id " + CHAT + " --text hi", WS, None),
    ('lark-cli im +messages-send --as bot --chat-id "$CHAT" --text hi', WS, None),
    ("lark-cli im +messages-reply --as bot --message-id om_x --text ok", WS, None),
    ("./bin/p " + CHAT + " '第 1/2 步'", WS, None),
    ("CARD_CHAT=" + CHAT + " ./bin/card.py step 2 '出图'", WS, None),
    ("cat > _status.md <<'EOF'\n用 ./bin/p " + OTHER + " 播报；lark-cli im +messages-send --as bot --chat-id " + OTHER +
     "\nEOF", WS, None),                                          # heredoc 正文里抄的命令不算
    ('echo "示例：lark-cli im +messages-send --as bot --chat-id ' + OTHER + '" >> notes.md', WS, None),   # 引号里的不算
]

DENY = [
    ("bridge-control", "lark-channel-bridge start --profile aaw"),
    ("bridge-control", "cd /tmp && lark-channel-bridge restart"),
    ("bridge-control", "lark-channel-bridge stop"),
    ("bridge-control", "launchctl bootout gui/501/com.example.lark-channel-bridge.aaw"),
    ("bridge-control", "launchctl kickstart -k gui/$(id -u)/com.example.lark-channel-bridge.aaw"),
    ("bridge-control", "pkill -f lark-channel-bridge"),
    ("bridge-control", "kill $(pgrep -f lark-channel-bridge.mjs)"),
    ("send-without-bot", "lark-cli im +messages-send --chat-id oc_x --text hi"),
    ("send-without-bot", "lark-cli im +messages-send --as user --chat-id oc_x --text hi"),
    ("send-without-bot", "lark-cli im +messages-reply --message-id om_x --text ok"),
    ("send-without-bot", 'python3 -c "..." && lark-cli im +messages-send --chat-id oc_x --file a.md'),
    ("send-without-bot", "lark-cli im messages forward --params '{}'"),
    # 独立审查发现过的漏拦
    ("bridge-control", "lark-channel-bridge run --profile aaw"),
    ("bridge-control", "node ~/bridge/bin/lark-channel-bridge.mjs run --profile aaw"),
    ("bridge-control", "lark-channel-bridge --profile aaw start"),
    ("bridge-control", "pgrep -f lark-channel-bridge | xargs kill"),
    ("bridge-control", "PID=$(pgrep -f lark-channel-bridge); kill $PID"),
    ("bridge-control", "pkill -f lark-channel"),
    ("bridge-control", "killall node"),
    ("bridge-control", "ps aux | grep lark-channel-bridge | grep -v grep | awk '{print $2}' | xargs kill"),
    ("bridge-control", "kill -9 $(pgrep -f 'lark-channel-bridge.mjs run')"),
    ("send-without-bot", "lark-cli im +messages-send --as bot --chat-id oc_x --text a && lark-cli im +messages-send --chat-id oc_x --file b.md"),
    ("send-without-bot", "lark-cli --as user im +messages-send --chat-id oc_x --text hi"),
    ("send-without-bot", "lark-cli im +messages-send \\\n  --chat-id oc_x --text hi"),
    ("send-without-bot", "lark-cli im +messages-send --chat-id oc_x --text '记得带 --as bot'"),
]
ALLOW = [
    "lark-cli im +messages-send --as bot --chat-id oc_x --markdown 'a; b'",
    'lark-cli im +messages-send --chat-id oc_x --content "$(cat /tmp/m.json)" --as bot',
    "lark-cli im +messages-send --as=bot --chat-id oc_x --file out.pptx",
    "lark-cli docs +fetch --as user --doc doxcnEXAMPLE",
    "lark-cli im +chat-messages-list --as user --chat-id oc_x",
    "./bin/card.py start oc_x '任务' '一|二'",
    "CARD_CHAT=oc_x ./bin/card.py step 2 '正在出图' >/dev/null; python3 build.py",
    "lark-channel-bridge status",
    "lark-channel-bridge --help",
    "launchctl list | grep lark",
    "kill 12345",
    "ps aux | grep lark-channel-bridge",
    "rm -rf ./_tmp_build",
    "echo hello",
    "",
    # 独立审查发现过的误拦
    "lark-cli im +messages-send --help",
    "lark-cli docs +fetch --as user --doc doxcnEXAMPLE > a.md && lark-cli im +messages-send --as bot --chat-id oc_x --file a.md",
    'lark-cli im +messages-send --as bot --chat-id oc_x --markdown "读这个文档要用 --as user 身份，请先授权"',
    'lark-cli im +messages-send --as "bot" --chat-id oc_x --text hi',
    "lark-cli im +messages-send \\\n  --as bot --chat-id oc_x --text hi",
    "lark-cli --as bot im +messages-send --chat-id oc_x --text hi",
    'echo "lark-channel-bridge 上次 start 于 10:00" >> _status.md',
    'lark-cli im +messages-send --as bot --chat-id oc_x --text "lark-channel-bridge 需要 restart，请用户自己处理"',
    'ps aux | grep "lark-channel-bridge.mjs run"',
    "pkill -f plot_all.py",
    "cd ~/.lark-channel-workspaces/demo && kill -TERM 92051 2>/dev/null; echo ok",   # 工作区目录名里带桥的短名，不算点名杀桥
    'grep -n "pkill\\|强杀\\|重启" ~/aaw-workspaces/default/CLAUDE.md | head -12',
    "python3 " + RT + "/tools/accept_record.py list; kill 12345",
]


def run_script(payload, profile="aaw"):
    env = dict(os.environ)
    if profile is None:
        env.pop("LARK_CHANNEL_PROFILE", None)
    else:
        env["LARK_CHANNEL_PROFILE"] = profile
    p = subprocess.run(
        [os.path.join(HERE, "run-hook.sh"), "guard"],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    )
    return p.returncode, p.stdout.strip()


def main():
    bad = 0
    for rule, cmd in DENY:
        got, _ = decide(cmd)
        if got != rule:
            bad += 1
            print("FAIL 应拦未拦:", rule, "|", cmd, "| got", got)
    for cmd in ALLOW:
        got, _ = decide(cmd)
        if got is not None:
            bad += 1
            print("FAIL 误拦:", cmd, "| got", got)

    # 端到端：经过 run-hook.sh
    payload = {"tool_name": "Bash", "tool_input": {"command": "lark-channel-bridge start"}, "cwd": "/x/y"}
    code, out = run_script(payload)
    if code != 0 or '"deny"' not in out:
        bad += 1
        print("FAIL 分析助手身份下应输出拦截 JSON:", code, out[:120])
    code, out = run_script(payload, profile=None)
    if code != 0 or out:
        bad += 1
        print("FAIL 不是从桥来的（没有 profile）应不做任何事:", code, out[:120])
    code, out = run_script(payload, profile="other-bot")
    if code != 0 or out:
        bad += 1
        print("FAIL 别的机器人的 profile 应不做任何事:", code, out[:120])
    code, out = run_script({"tool_name": "Bash", "tool_input": {"command": "echo ok"}})
    if code != 0 or out:
        bad += 1
        print("FAIL 正常命令应放行:", code, out[:120])
    # 输入坏掉也要放行
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "guard"], input="not json",
                       capture_output=True, text=True, env=dict(os.environ, LARK_CHANNEL_PROFILE="aaw"))
    if p.returncode != 0 or p.stdout.strip():
        bad += 1
        print("FAIL 坏输入应放行:", p.returncode, p.stdout[:120])
    # 脚本名不存在也要放行
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "no-such-hook"], input="{}",
                       capture_output=True, text=True, env=dict(os.environ, LARK_CHANNEL_PROFILE="aaw"))
    if p.returncode != 0 or p.stdout.strip():
        bad += 1
        print("FAIL 脚本缺失应放行:", p.returncode, p.stdout[:120])

    # 廉价预检：几百 KB、不含护栏关心的词的大命令要立刻放行（以前按平方变慢，会撞钩子超时）
    big = "cat <<'EOF' > x.py\n" + "\n".join(
        "grep -n 'p%d' f%d.txt | head -5 && echo node bridge %d" % (i, i, i) for i in range(6000)) + "\nEOF"
    t0 = time.time()
    got, _ = decide(big)
    if got is not None or time.time() - t0 > 0.5:
        bad += 1
        print("FAIL 大命令应立刻放行:", got, "%.2fs" % (time.time() - t0))
    if decide(big + "\nlark-channel-bridge restart")[0] != "bridge-control":
        bad += 1
        print("FAIL 大命令里带了重启桥也要拦")

    # 自我保护、密钥、发到别处：要看当时的目录和本轮群号
    os.environ["AAW_RUNTIME"] = RT     # 让命令里的 $AAW_RUNTIME 能代入
    for cmd, cwd, want in CONTEXT:
        got = decide(cmd, cwd, CHAT)[0]
        if got != want:
            bad += 1
            print("FAIL 新规则:", repr(cmd[:80]), "| got", got, "| want", want)
    if decide("lark-cli im +messages-send --as bot --chat-id " + OTHER + " --text hi", WS, None)[0] is not None:
        bad += 1
        print("FAIL 读不到本轮群号时应放行")
    # 端到端：本轮群号从 /tmp/.aaw_turn_<会话>.json 读；拦下和带理由放行都要记日志
    sid = "guardtest-%d" % os.getpid()
    turn = "/tmp/.aaw_turn_%s.json" % sid
    hlog = os.path.join(os.environ["AAW_HOOK_STATE"], "hook.log")
    try:
        with open(turn, "w") as f:
            json.dump({"session": sid, "chat": CHAT}, f)
        send = "lark-cli im +messages-send --as bot --chat-id %s --text hi" % OTHER
        code, out = run_script({"tool_name": "Bash", "tool_input": {"command": send}, "cwd": WS, "session_id": sid})
        reason = json.loads(out)["hookSpecificOutput"].get("permissionDecisionReason", "") if out else ""
        if code != 0 or '"deny"' not in out or "请用户自己在电脑上处理" not in reason:
            bad += 1
            print("FAIL 端到端：发到别的群应拦下并提示请用户自己处理:", code, out[:120])
        code, out = run_script({"tool_name": "Bash", "cwd": WS, "session_id": sid,
                                "tool_input": {"command": "ALLOW_OTHER_TARGET='用户点名发运营群' " + send}})
        logs = [json.loads(x) for x in open(hlog, encoding="utf-8")] if os.path.exists(hlog) else []
        if code != 0 or out or not any(x.get("rule") == "other-target-allowed" and x.get("reason") == "用户点名发运营群"
                                       for x in logs):
            bad += 1
            print("FAIL 端到端：带理由应放行并把理由记进日志:", code, out[:120], logs[-1:] if logs else None)
        code, out = run_script({"tool_name": "Bash", "cwd": WS, "session_id": sid,
                                "tool_input": {"command": "touch " + RT + "/hooks/DISABLED"}})
        logs = [json.loads(x) for x in open(hlog, encoding="utf-8")] if os.path.exists(hlog) else []
        if '"deny"' not in out or not logs or logs[-1].get("rule") != "self-protect" or os.path.exists(RT + "/hooks/DISABLED"):
            bad += 1
            print("FAIL 端到端：改护栏应拦下并记日志:", out[:120])
        logs_txt = open(hlog, encoding="utf-8").read() if os.path.exists(hlog) else ""
        if "lark-cli" in logs_txt or OTHER in logs_txt:
            bad += 1
            print("FAIL 日志不应记命令原文")
    finally:
        if os.path.exists(turn):
            os.remove(turn)

    # 换一个桥的程序名（AAW_BRIDGE_NAMES）：新名字要拦，旧名字不再管
    env = dict(os.environ, AAW_BRIDGE_NAMES="my-feishu-bridge")
    probe = ("import guard,json;print(json.dumps([guard.decide(c)[0] for c in "
             "['my-feishu-bridge restart','pkill -f my-feishu','lark-channel-bridge restart']]))")
    p = subprocess.run([sys.executable, "-c", probe], cwd=HERE, capture_output=True, text=True, env=env)
    try:
        got = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        got = p.stdout + p.stderr
    if got != ["bridge-control", "bridge-control", None]:
        bad += 1
        print("FAIL 换桥的程序名:", got)

    total = len(DENY) + len(ALLOW) + 8 + len(CONTEXT) + 6
    print(f"{total - bad}/{total} 通过")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
