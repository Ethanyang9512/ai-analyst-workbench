#!/usr/bin/env python3
"""验收门的回归测试：python3 test_gate.py
全部在临时目录里跑，不碰正式的 GATE_ENFORCE、日志和工作区。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), "tools", "accept_record.py")
TMP = os.path.realpath(tempfile.mkdtemp(prefix="aaw-gate-"))
BASE = os.path.join(TMP, "workspaces")          # 假的工作区总目录
WS = os.path.join(BASE, "ws1")                  # 假的工作区
WS2 = os.path.join(BASE, "ws2")                 # 另一个假工作区
SUB = os.path.join(WS, "out", "ppt")
OUTSIDE = os.path.join(TMP, "outside")          # 工作区以外的目录
STATE = os.path.join(TMP, "state")              # 假的钩子状态目录（GATE_ENFORCE、hook.log）
FLAG = os.path.join(STATE, "GATE_ENFORCE")
ENV = dict(os.environ, LARK_CHANNEL_PROFILE="aaw", AAW_PROFILE="aaw", AAW_WS_BASE=BASE, AAW_HOOK_STATE=STATE)
ENV.pop("AAW_RUNTIME", None)
SEND = "lark-cli im +messages-send --as bot --chat-id oc_x --file "
RA = ["--reader", "冷读通过", "--visual", "12 页看过，8 个数核过"]


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def gate(cmd, cwd=WS, profile="aaw"):
    env = dict(ENV, LARK_CHANNEL_PROFILE=profile)
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd, "session_id": "s-test"}
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "gate"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    out = p.stdout.strip()
    if p.returncode != 0:
        return "exit%d" % p.returncode
    if not out:
        return "pass"
    d = json.loads(out)["hookSpecificOutput"]
    if d.get("permissionDecision") == "deny":
        return "deny"
    return "remind" if d.get("additionalContext") else "?"


def reason(cmd, cwd=WS):
    """强制模式拦下时给模型看的那段话。"""
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd, "session_id": "s-test"}
    p = subprocess.run([os.path.join(HERE, "run-hook.sh"), "gate"], input=json.dumps(payload),
                       capture_output=True, text=True, env=ENV)
    out = p.stdout.strip()
    return json.loads(out)["hookSpecificOutput"].get("permissionDecisionReason", "") if out else ""


def record(args, cwd=WS):
    p = subprocess.run([sys.executable, TOOL] + args, cwd=cwd, capture_output=True, text=True, env=ENV)
    return p.returncode, p.stdout + p.stderr


def real_state():
    """正式目录里的开关和日志的现状（测试前后应当一样）。"""
    log = os.path.join(HERE, "hook.log")
    return (os.path.exists(os.path.join(HERE, "GATE_ENFORCE")),
            os.path.getsize(log) if os.path.exists(log) else -1)


def main():
    before = real_state()
    os.makedirs(STATE)
    put(os.path.join(WS, "deck.pptx"), "deck v1")
    put(os.path.join(WS, "note.md"), "x")
    put(os.path.join(WS, "data.xlsx"), "data")
    put(os.path.join(WS, "memo.docx"), "memo")
    put(os.path.join(WS, "my deck v2.pptx"), "spaces")
    put(os.path.join(WS, "成本$分析.xlsx"), "dollar")
    put(os.path.join(SUB, "final.pptx"), "final v1")
    put(os.path.join(SUB, "other.pptx"), "other")
    put(os.path.join(WS, "v1", "report.pptx"), "report old")
    put(os.path.join(WS2, "out", "d.pptx"), "in ws2")
    put(os.path.join(OUTSIDE, "ext.pptx"), "outside")
    os.symlink(os.path.join("..", "ws2"), os.path.join(WS, "projB"))
    res = []
    ok = lambda name, got, want: res.append((name, got, want))

    # ---- 提醒模式（没有 GATE_ENFORCE）
    ok("提醒模式·无记录", gate(SEND + "deck.pptx"), "remind")
    ok("md 文件不设门", gate(SEND + "note.md"), "pass")
    ok("zip 文件不设门", gate(SEND + "pkg.zip"), "pass")
    ok("带跳过理由", gate("ACCEPT_SKIP='小改动' " + SEND + "deck.pptx"), "pass")
    ok("提醒模式·新建飞书文档无记录", gate("lark-cli docs +create --as bot --title 测试"), "remind")
    ok("别的机器人的身份不设门", gate(SEND + "deck.pptx", profile="other-bot"), "pass")
    ok("不是发送命令", gate("ls deck.pptx && echo --file deck.pptx"), "pass")

    # ---- 强制模式
    open(FLAG, "w").close()
    ok("强制·无记录", gate(SEND + "deck.pptx"), "deny")
    why = reason(SEND + "deck.pptx")
    ok("拦下时指向 workflow.md 的分档、写清记录要带什么，不重复三档全文，小改不再叫人跳过", all(w in why for w in (
        "按 workflow.md 的分档验收（先跑 deckcheck.py scope 和 accept_record.py status 定档）",
        "写记录时带 --tier 和 --pages", "没请某位验收员时写 --reader 或 --visual \"不适用：原因\"",
        "ACCEPT_SKIP")) and "不超过 3 页" not in why and "小改动、中间文件" not in why, True)
    ok("写记录成功", record(["write", "--file", "deck.pptx"] + RA)[0], 0)
    ok("强制·有记录", gate(SEND + "deck.pptx"), "pass")
    ok("--file=值 的写法", gate(SEND.rstrip() + "=deck.pptx"), "pass")
    ok("命令后面接管道", gate(SEND + '"deck.pptx" 2>&1 | tail -1'), "pass")
    ok("全局参数放在 im 前面", gate("lark-cli --as bot im +messages-send --chat-id oc_x --file data.xlsx"), "deny")
    put(os.path.join(WS, "deck.pptx"), "deck v2 changed")
    ok("文件改过·记录失效", gate(SEND + "deck.pptx"), "deny")
    ok("check 返回没有记录", record(["check", "--file", "deck.pptx"])[0], 1)
    ok("新建文档·无记录", gate("lark-cli docs +create --as user --title 测试"), "deny")
    ok("看帮助不设门", gate("lark-cli docs +create --help") + "/" + gate("lark-cli im +messages-send --help --file data.xlsx"),
       "pass/pass")
    ok("写文档记录", record(["write", "--doc", "测试文档"] + RA)[0], 0)
    ok("新建文档·有记录", gate("lark-cli docs +create --as user --title 测试"), "pass")
    ok("把 Word 导成飞书文档·无记录", gate("lark-cli drive +import --as bot --file memo.docx --type docx"), "deny")
    record(["write", "--file", "memo.docx"] + RA)
    ok("把 Word 导成飞书文档·有记录", gate("lark-cli drive +import --as bot --file memo.docx --type docx"), "pass")

    # ---- 先进子目录再发
    cd_send = "cd out/ppt && " + SEND + "final.pptx"
    ok("cd 子目录·无记录", gate(cd_send), "deny")
    ok("cd 绝对路径·无记录", gate('cd "%s" && %sfinal.pptx' % (SUB, SEND)), "deny")
    ok("停在子目录里发·无记录", gate(SEND + "final.pptx", cwd=SUB), "deny")
    ok("括号里 cd·无记录", gate("(cd out/ppt && %sfinal.pptx)" % SEND), "deny")
    ok("pushd·无记录", gate("pushd out/ppt && %sfinal.pptx" % SEND), "deny")
    ok("在子目录里写记录", record(["write", "--file", "final.pptx"] + RA, cwd=SUB)[0], 0)
    ok("记录落在工作区最上层", os.path.isfile(os.path.join(WS, "_acceptance", "records.jsonl"))
       and not os.path.exists(os.path.join(SUB, "_acceptance")), True)
    ok("cd 子目录·有记录", gate(cd_send), "pass")
    ok("停在子目录里发·有记录", gate(SEND + "final.pptx", cwd=SUB), "pass")
    ok("从上层带路径发·有记录", gate(SEND + "out/ppt/final.pptx"), "pass")
    ok("括号里 cd·有记录", gate("(cd out/ppt && %sfinal.pptx)" % SEND), "pass")
    ok("pushd·有记录", gate("pushd out/ppt && %sfinal.pptx" % SEND), "pass")
    ok("多行命令·有记录", gate("cd out/ppt\n" + SEND + "final.pptx\necho done"), "pass")
    ok("续行符·有记录", gate("cd out/ppt && lark-cli im +messages-send --as bot \\\n  --chat-id oc_x \\\n  --file final.pptx"), "pass")
    ok("变量指目录", gate('P=out/ppt\ncd "$P" || exit 1\n' + SEND + "final.pptx"), "pass")
    ok("变量指文件", gate('F="out/ppt/final.pptx"; ' + SEND + '"$F"'), "pass")
    ok("变量指文件·无记录", gate('F="out/ppt/other.pptx"; ' + SEND + '"$F"'), "deny")
    ok("两个文件一个没记录", gate("cd out/ppt && %sfinal.pptx && %sother.pptx" % (SEND, SEND)), "deny")

    # ---- 推算不出来的写法：一律按没有记录处理
    ok("未知变量（看得出是 PPT）", gate(SEND + '"$OUT/final.pptx"'), "deny")
    ok("未知变量（看不出类型）", gate("cd out/ppt && " + SEND + '"$f"'), "deny")
    ok("循环里发（通配符）", gate("cd out/ppt && for f in *.pptx; do %s\"$f\"; done" % SEND), "deny")
    loop = 'for f in %s; do lark-cli im +messages-send --as bot --chat-id oc_x --file "$f"; sleep 1; done'
    ok("循环里发·清单写明·都有记录", gate("cd out/ppt && " + loop % "final.pptx"), "pass")
    ok("循环里发·清单写明·有一个没记录", gate("cd out/ppt && " + loop % '"final.pptx" "other.pptx"'), "deny")
    ok("循环里发·清单里都是不设门的类型", gate(loop % '"审核报告.md" "任务书.md" "payloads.zip"'), "pass")
    ok("循环里发·./$f 的写法", gate("cd out/ppt && " + (loop % "final.pptx").replace('"$f"', "./$f")), "pass")
    ok("命令替换", gate("cd out/ppt && F=$(ls -t *.pptx | head -1); %s\"$F\"" % SEND), "deny")
    ok("通配符", gate("cd out/ppt && " + SEND + "*.pptx"), "deny")
    ok("目录是命令替换", gate('cd "$(dirname out/ppt/final.pptx)" && ' + SEND + "final.pptx"), "deny")
    ok("未知变量但看得出是压缩包", gate(SEND + '"$OUT/pkg.zip"'), "pass")
    ok("文件标识和链接不设门", gate(SEND + "file_v2_abc") + "/" + gate(SEND + "https://example.invalid/file/a.pdf"), "pass/pass")
    ok("同一条命令里才生成的文件", gate("cp deck.pptx new_v9.pptx && " + SEND + "new_v9.pptx"), "deny")
    ok("别处有同名旧文件的记录也不算", (record(["write", "--file", "v1/report.pptx"] + RA)[0],
                              gate("python3 make.py --out v2/report.pptx && cd v2 && " + SEND + "report.pptx")), (0, "deny"))
    ok("别的命令的 --file 不算", gate("python3 x.py --file data.xlsx; " + SEND + "note.md"), "pass")
    ok("消息里有分号不影响", gate("lark-cli im +messages-send --as bot --chat-id oc_x --markdown 'a; b' --file data.xlsx"), "deny")
    ok("回复消息同样设门", gate("lark-cli im +messages-reply --as bot --message-id om_x --file data.xlsx"), "deny")
    ok("强制·带跳过理由", gate("ACCEPT_SKIP='数据清单' " + SEND + "data.xlsx"), "pass")

    # ---- 文件名里的特殊字符
    ok("文件名带空格·无记录", gate(SEND + '"my deck v2.pptx"'), "deny")
    record(["write", "--file", "my deck v2.pptx"] + RA)
    ok("文件名带空格·有记录", gate(SEND + '"my deck v2.pptx"'), "pass")
    ok("反斜杠转义空格·有记录", gate(SEND + "my\\ deck\\ v2.pptx"), "pass")
    record(["write", "--file", "成本$分析.xlsx"] + RA)
    ok("文件名里有 $ 接中文", gate(SEND + '"成本$分析.xlsx"') + "/" + gate(SEND + "'成本$分析.xlsx'"), "pass/pass")

    # ---- 文件不在本会话的工作区里：记录跟着文件走
    out_send = 'cd "%s" && %sext.pptx' % (OUTSIDE, SEND)
    ok("工作区外的文件·无记录", gate(out_send), "deny")
    ok("工作区外写记录", record(["write", "--file", "ext.pptx"] + RA, cwd=OUTSIDE)[0], 0)
    ok("工作区外的文件·有记录", gate(out_send), "pass")
    link_send = "cd projB/out && " + SEND + "d.pptx"
    ok("软链进另一个工作区·无记录", gate(link_send), "deny")
    ok("在软链目录里写记录", record(["write", "--file", "d.pptx"] + RA, cwd=os.path.join(WS, "projB", "out"))[0], 0)
    ok("记录落在文件所在的工作区", os.path.isfile(os.path.join(WS2, "_acceptance", "records.jsonl")), True)
    ok("软链进另一个工作区·有记录", gate(link_send), "pass")
    ok("从别处用路径写记录也认", (record(["write", "--file", os.path.join(SUB, "other.pptx")] + RA, cwd=OUTSIDE)[0],
                           gate("cd out/ppt && " + SEND + "other.pptx")), (0, "pass"))
    ok("list 能在子目录里看到记录", "final.pptx" in record(["list"], cwd=SUB)[1], True)

    # ---- 坏记录不让门失效；日志不记命令原文
    with open(os.path.join(WS, "_acceptance", "records.jsonl"), "ab") as f:
        f.write('not json\n{"files": ["x.pptx"], "reader": "ok"}\n[]\n"abc"\n123\nnull\n{"files": null}\n'
                '{"doc": "x", "epoch": "abc"}\n'.encode() + b"\xff\xfe bad bytes\n")
    put(os.path.join(WS, "fresh.pptx"), "never accepted")
    ok("记录文件里有各种坏行·有记录的照过", gate(cd_send), "pass")
    ok("记录文件里有各种坏行·没记录的照拦", gate(SEND + "fresh.pptx"), "deny")
    os.chmod(os.path.join(WS, "_acceptance", "records.jsonl"), 0)
    ok("记录文件读不了：放行并记 error", gate(SEND + "fresh.pptx"), "pass")
    os.chmod(os.path.join(WS, "_acceptance", "records.jsonl"), 0o644)
    logs = open(os.path.join(STATE, "hook.log"), encoding="utf-8").read()
    ok("日志不记命令原文", "lark-cli" not in logs and "oc_x" not in logs and "final" not in logs, True)
    ok("日志记了跳过和出错", '"decision": "skip"' in logs and '"decision": "error"' in logs, True)
    ok("正式的开关和日志没被动过", real_state(), before)

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
