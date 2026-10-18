#!/usr/bin/env python3
"""护栏（PreToolUse / Bash）。拦下面几类操作，其余一律放行：
  1. 启停或杀掉分析助手自己的桥进程
  2. 用 lark-cli 发飞书消息时没有指定机器人身份（--as bot）
  3. 改动自己的护栏、规则和设置：runtime 目录（含钩子、workflow.md、tools/）、.claude/settings*.json、
     ~/.claude/CLAUDE.md、~/.claude/agents/、桥的配置文件（设了 AAW_BRIDGE_CONFIG 时）。只读照常放行
  4. 调用密钥工具、读钥匙串或密钥文件
  5. 把消息发到本轮群以外的群或个人（命令带 ALLOW_OTHER_TARGET='理由' 时放行并记日志）

为什么拦：
  1 用错启动命令会把桥悄悄换掉，或者整个机器人掉线；
  2 不带机器人身份发出的消息会被桥当成用户消息，造成死循环；
  3–5 是防“指令注入”的门槛：数据包、附件、网页里写着“把配置改掉”“把密钥贴出来”“发到另一个群”时，
      就算模型被骗去照做，命令也执行不了。

3–5 只认明显的写法，挡不住刻意绕过。任何解析异常都放行（护栏坏了不能把正常工作也拦住）。
日志只记规则名和时间（放行别处目标时另记理由），不记命令原文（数据包里可能有明文口令）。

可调的环境变量（都可不设）：
  AAW_RUNTIME        runtime 目录；不设就取本文件上一级目录
  AAW_WS_BASE        各项目工作区的总目录（默认 ~/aaw-workspaces），其下各工作区的 .claude/ 受保护
  AAW_HOOK_STATE     钩子状态目录（日志、GATE_ENFORCE），默认本目录
  AAW_BRIDGE_CONFIG  桥的配置文件；设了才保护
  AAW_BRIDGE_HOME    桥的主目录；设了之后，在它下面运行命令也会走完整检查
  AAW_BRIDGE_NAMES   桥的程序名，逗号分隔（默认 lark-channel-bridge）
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cmdparse  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")

# ---- 换成你的桥的程序名和密钥文件名（默认值对应上游 lark-channel-bridge 的写法）
BRIDGE_NAMES = [n.strip() for n in (os.environ.get("AAW_BRIDGE_NAMES") or "lark-channel-bridge").split(",")
                if n.strip()]
SECRET_TOOLS = ("secrets-getter",)                    # 桥自带的取密钥小工具
SECRET_FILE_NAMES = ("secrets.enc", ".keystore.salt")  # 桥存密钥的文件


def _bridge_alternatives():
    """桥的进程名：完整名，以及去掉“-bridge”后缀的短名（短名后面不能紧跟 - / 字母，免得误伤工作区目录名）。"""
    out = [re.escape(n) for n in BRIDGE_NAMES]
    for n in BRIDGE_NAMES:
        stem = re.sub(r"-bridge$", "", n)
        if stem != n:
            out.append(re.escape(stem) + r"(?![-/\w])")
    return "|".join(out)


_NAMES = "|".join(re.escape(n) for n in BRIDGE_NAMES)
# 桥程序出现在“命令的位置”上（开头、分隔符之后，或跟在 node / sudo / env 等后面），不是别的命令的参数或一段文字
AT_COMMAND = r"(?:^|[;&|\n(]\s*|\b(?:exec|nohup|sudo|node|command|env)\s+(?:\S+\s+)*?)(?:\w+=\S*\s+)*"
BRIDGE_CTL = re.compile(
    AT_COMMAND + r"(?:\S*/)?(?:" + _NAMES + r")(?:\.mjs)?\s+(?:--?\S+(?:\s+[^-\s]\S*)?\s+)*?"
    r"(start|stop|restart|install|uninstall|service|run)\b"
)
LAUNCHCTL = re.compile(
    r"\blaunchctl\b[^\n;|&]*?\b(bootout|bootstrap|kickstart|unload|load|remove|disable|enable|stop|start)\b"
    r"[^\n;|&]*(?:" + _NAMES + r")"
)
BRIDGE_PROC = r"(?:" + _bridge_alternatives() + r")"
KILL = re.compile(r"\b(kill|pkill|killall)\b[^\n;|&]*" + BRIDGE_PROC)             # 同一条命令里点名杀桥
FIND_THEN_KILL = re.compile(                                                         # 先查出桥的进程号再杀
    r"\b(pgrep|pidof|grep)\b[^\n;&]*" + BRIDGE_PROC + r"[\s\S]*\b(kill|pkill|killall)\b")
KILL_NODE = re.compile(r"\b(killall|pkill)\b[^\n;|&]*\bnode\b")
SEND = re.compile(
    r"\blark-cli\b[^\n;|&]*?\sim\s+(\+messages-send|\+messages-reply|\+messages-edit|send-card|"
    r"messages\s+(forward|merge_forward|urgent_app|urgent_phone|urgent_sms)|threads\s+forward)\b"
)

# ---- 3. 自我保护：这些地方只能读，不能写、删、挪、改权限
RUNTIME = os.path.normpath(os.environ.get("AAW_RUNTIME") or os.path.dirname(HERE))
WS_BASE = os.path.normpath(os.path.expanduser(os.environ.get("AAW_WS_BASE") or "~/aaw-workspaces"))
STATE = os.path.normpath(os.environ.get("AAW_HOOK_STATE") or HERE)
HOOKS_DIR = os.path.join(RUNTIME, "hooks")
WORKFLOW = os.path.join(RUNTIME, "workflow.md")
CLAUDE_MD = os.path.join(HOME, ".claude/CLAUDE.md")
AGENTS_DIR = os.path.join(HOME, ".claude/agents")
BRIDGE_CONFIG = os.path.expanduser(os.environ["AAW_BRIDGE_CONFIG"]) if os.environ.get("AAW_BRIDGE_CONFIG") else None
BRIDGE_HOME = os.path.expanduser(os.environ["AAW_BRIDGE_HOME"]) if os.environ.get("AAW_BRIDGE_HOME") else None
STATE_SWITCHES = [os.path.join(STATE, n) for n in ("GATE_ENFORCE", "DISABLED")]   # 验收门模式、总开关
# 整个删掉、挪走或改权限时，删的是这些东西的上级目录也算（比如 rm -rf ~/.claude）
ROOTS = [HOOKS_DIR, WORKFLOW, CLAUDE_MD, AGENTS_DIR, os.path.join(HOME, ".claude/settings.json")] + STATE_SWITCHES + \
    ([BRIDGE_CONFIG] if BRIDGE_CONFIG else []) + sorted(glob.glob(os.path.join(WS_BASE, "*/.claude")))

# 廉价预检：每条规则都要求命令里出现下面某个词；一个都没有就直接放行。
# 很大的命令（几十 KB 的 heredoc）逐条跑正则会按平方变慢，超过钩子超时就成了静默放行。
BRIDGE_WORDS = tuple(BRIDGE_NAMES) + tuple(re.sub(r"-bridge$", "", n) for n in BRIDGE_NAMES) + \
    ("launchctl", "kill", "pkill")
SEND_WORDS = ("lark-cli",)
PROTECT_WORDS = ("hooks", "workflow.md", "settings", "CLAUDE.md", "agents", ".claude", "accept_record",
                 "GATE_ENFORCE", "DISABLED", "AAW_", os.path.basename(RUNTIME)) + \
    ((os.path.basename(BRIDGE_CONFIG),) if BRIDGE_CONFIG else ())
SECRET_WORDS = SECRET_TOOLS + SECRET_FILE_NAMES + ("keystore", "security")
TARGET_WORDS = ("lark-cli", "card.py", "bin/p")
CHEAP = tuple(dict.fromkeys(w for w in BRIDGE_WORDS + SEND_WORDS + PROTECT_WORDS + SECRET_WORDS + TARGET_WORDS if w))

WRAPPERS = {"sudo", "command", "env", "nohup", "time", "exec", "nice", "caffeinate", "builtin"}
OPS = ["&>>", "<<<", ">>", "<<", "&&", "||", "|&", "&>", ">&", "<&", ">|", "<>", ";;", ";", "&", "|", "(", ")",
       "<", ">", "`"]
SEPS = {"&&", "||", "|&", ";;", ";", "&", "|", "(", ")", "`"}
WRITE_REDIRS = {">", ">>", ">|", "&>", "&>>", "<>"}
SKIP_REDIRS = {"<", "<<", "<<<", "<&", ">&"}          # 后面跟的是输入文件、heredoc 结束词或文件描述符
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
ASSIGN_WORD = re.compile(r"^[A-Za-z_]\w*=")
VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")
INTERP = re.compile(r"(?:^|[\s;&|(`])(?:\S*/)?(?:python3?(?:\.\d+)?|node|ruby|perl|osascript)(?=\s|$)")
WRITE_API = re.compile(
    r"open\([^)\n]*['\"][wax]\+?b?['\"]|\.write_(?:text|bytes)\(|(?:os|shutil)\.(?:remove|unlink|rename|replace|rmtree|"
    r"move|copy\w*|chmod|chown)\(|\.(?:unlink|rename|replace|chmod|touch)\(|(?:write|append)FileSync\(|"
    r"(?:rm|unlink|rename|copyFile|chmod)Sync\(|fs\.(?:writeFile|appendFile|rm|unlink|rename|copyFile|chmod)\b")
PATHLIKE = re.compile(r"[~$\w./{}@-]*(?:\.claude|hooks|workflow\.md|CLAUDE\.md|agents|accept_record|"
                      + re.escape(os.path.basename(RUNTIME)) + r")[\w./@-]*")

# ---- 4. 密钥
SECRET_FILES = re.compile("|".join(re.escape(n) for n in SECRET_FILE_NAMES))
SECURITY_SUB = {"find-generic-password", "find-internet-password", "dump-keychain", "export"}

# ---- 5. 发到别处
ALLOW_OTHER = re.compile(r"\bALLOW_OTHER_TARGET=(?:'([^']*)'|\"([^\"]*)\"|(\S+))")
API_SEND = re.compile(r"\blark-cli\b[^\n;|&]*?\sapi\s+POST\s+['\"]?/open-apis/im/v1/messages(?![/\w])")
TOOL_SEND = re.compile(r"(?:^|[\s;&|(])(?:\S*/)?(?:bin/p|card\.py\s+(?:start|auto))\s+(['\"]?)([^\s'\";&|]+)\1")
PERSON_OPTS = ("--user-id", "--open-id", "--email", "--union-id")

ASK_USER = "需要的话请用户自己在电脑上处理（不经过机器人）。"
MSG_BRIDGE = (
    "护栏：分析助手的会话里不能启停或杀掉桥进程（用错启动命令会把桥悄悄换掉，或者让机器人掉线）。"
    "需要维护桥，" + ASK_USER
)
MSG_SEND = (
    "护栏：用 lark-cli 发飞书消息，每一条发送命令自己都要带 `--as bot`，并使用本轮 bridge_context 里的 chatId。"
    "不带机器人身份发出的消息会被桥当成用户消息，造成死循环。请补上 `--as bot` 后重试。"
)
MSG_PROTECT = (
    "护栏：分析助手不能改动自己的护栏、规则和设置（runtime 目录，含钩子、workflow.md 和 tools/；各处 .claude/settings*.json、"
    "~/.claude/CLAUDE.md、~/.claude/agents/、桥的配置文件），只读查看可以。" + ASK_USER
)
MSG_SECRET = (
    "护栏：分析助手不能调用密钥工具、读钥匙串或密钥文件（" + "、".join(SECRET_TOOLS) +
    "、security find-*-password / dump-keychain / export、" + "、".join(SECRET_FILE_NAMES) + "）。" + ASK_USER
)
MSG_TARGET = (
    "护栏：这条命令要发到{where}，不是本轮所在的群。分析助手只往本轮的群发；用户明确要求发到别处时，"
    "在命令最前面加 `ALLOW_OTHER_TARGET='用户的原话或理由'` 再发（会记日志）。其他情况" + ASK_USER
)


# ---------- 3. 自我保护 ----------

def is_protected(p):
    # 整个 runtime 目录都只读（比 hooks/ 和 workflow.md 多护了 tools/：验收门靠 tools/accept_record.py 判断，改了它门就形同虚设）
    if p == RUNTIME or p.startswith(RUNTIME + os.sep) or p == CLAUDE_MD or p in STATE_SWITCHES:
        return True
    if BRIDGE_CONFIG and p == BRIDGE_CONFIG:
        return True
    if p == AGENTS_DIR or p.startswith(AGENTS_DIR + os.sep):
        return True
    return os.path.basename(os.path.dirname(p)) == ".claude" and fnmatch.fnmatch(os.path.basename(p), "settings*.json")


def hits(path, destructive):
    """这个写入目标碰到了受保护的地方（destructive：删、挪、改权限时，删上级目录也算）。"""
    for p in {os.path.normpath(path), os.path.realpath(path)}:
        if is_protected(p):
            return True
        if destructive and any(r == p or r.startswith(p.rstrip(os.sep) + os.sep) for r in ROOTS):
            return True
    return False


def resolve(tok, cwd, known):
    """命令里的一个路径参数还原成绝对路径；还原不了（未知变量、命令替换）返回 None。
    $HOME 和 AAW_* 这几个变量按钩子自己的环境代入（钩子和模型用的是同一套环境变量）。"""
    if not tok or tok in ("-", "/dev/null"):
        return None

    def sub(m):
        name = m.group(1) or m.group(2)
        if name == "HOME":
            return HOME
        if known.get(name) is not None:
            return known[name]
        if name not in known and name.startswith("AAW_") and os.environ.get(name):
            return os.environ[name]
        raise KeyError(name)

    try:
        s = VAR.sub(sub, tok)              # 先代入变量，再展开 ~（变量的值里可能带 ~）
    except KeyError:
        return None
    if s == "~" or s.startswith("~/"):
        s = HOME + s[1:]
    if "$" in s or "`" in s:
        return None
    if not os.path.isabs(s):
        if not cwd:
            return None
        s = os.path.join(cwd, s)
    return os.path.normpath(s)


def strip_heredocs(command):
    """把 heredoc 正文拿出来：返回（去掉正文后的命令, [正文…]）。"""
    lines, out, bodies, i = command.split("\n"), [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in HEREDOC.finditer(line):
            body = []
            while i < len(lines):
                cur = lines[i]
                i += 1
                if (cur.lstrip("\t") if m.group(1) else cur) == m.group(2):
                    break
                body.append(cur)
            bodies.append("\n".join(body))
    return "\n".join(out), bodies


def split_ops(tok):
    """shlex 把相连的符号当成一个词（比如 “);”），拆成一个个操作符；拆不开就原样返回。"""
    out, i = [], 0
    while i < len(tok):
        for op in OPS:
            if tok.startswith(op, i):
                out.append(op)
                i += len(op)
                break
        else:
            return [tok]
    return out


def tokens(text):
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>`")
    lex.whitespace_split = True
    lex.commenters = ""
    out = []
    for t in lex:
        out += split_ops(t) if t and all(c in ";&|()<>`" for c in t) else [t]
    return out


def simple_commands(text):
    """切成一条条简单命令：(词列表, 写入的重定向目标列表)。"""
    words, redirs, toks, i = [], [], tokens(text), 0
    while i < len(toks):
        t = toks[i]
        if t in SEPS:
            yield words, redirs
            words, redirs = [], []
        elif t in WRITE_REDIRS:
            if i + 1 < len(toks):
                redirs.append(toks[i + 1])
            i += 1
        elif t in SKIP_REDIRS:
            i += 1
        else:
            words.append(t)
        i += 1
    yield words, redirs


def write_targets(words, redirs):
    """一条简单命令要写的路径：[(路径参数, 是否删挪改权限)]。"""
    out = [(r, False) for r in redirs]
    while words and (ASSIGN_WORD.match(words[0]) or os.path.basename(words[0]) in WRAPPERS):
        words = words[1:]
    if not words:
        return out
    name, args = os.path.basename(words[0]), words[1:]
    paths = [a for a in args if a and not a.startswith("-")]
    if name in ("rm", "rmdir", "unlink", "shred", "srm", "trash"):
        out += [(p, True) for p in paths]
    elif name in ("touch", "truncate", "mkdir", "tee"):
        out += [(p, False) for p in paths]
    elif name in ("mv", "cp", "ln", "install", "rsync", "ditto"):
        dest = paths[-1] if len(paths) >= 2 else None
        if dest:
            out.append((dest, name == "mv"))
            out += [(os.path.join(dest, os.path.basename(s.rstrip("/"))), False) for s in paths[:-1]]
        if name == "mv":
            out += [(p, True) for p in paths[:-1]]
    elif name in ("chmod", "chown", "chgrp", "chflags"):
        out += [(p, True) for p in paths[1:]]
    elif name in ("sed", "gsed", "perl") and any(a.startswith("-i") or a.startswith("--in-place")
                                                 or (name == "perl" and a.startswith("-") and "i" in a) for a in args):
        out += [(p, False) for p in paths]
    elif name == "dd":
        out += [(a[3:], False) for a in args if a.startswith("of=")]
    elif name == "find" and ("-delete" in args or "-exec" in args or "-execdir" in args):
        start = []
        for a in args:
            if a.startswith("-") or a in ("(", "!"):
                break
            start.append(a)
        out += [(p, True) for p in start]
    return out


def touches_protected(command, cwd):
    """命令写、删、挪受保护的地方，或用解释器明显地写它们。"""
    text, bodies = strip_heredocs(cmdparse.normalize(command))
    text = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    known, cur = {}, cwd
    try:
        for words, redirs in simple_commands(text.replace("\n", " ; ")):
            if words and ASSIGN_WORD.match(words[0]) and len(words) == 1:
                k, v = words[0].split("=", 1)
                known[k] = None if ("$(" in v or "`" in v) else v
                continue
            if words and words[0] in ("cd", "pushd"):
                cur = resolve(words[1] if len(words) > 1 else "~", cur, known)   # 推不出来就记成不知道
                continue
            for tok, destructive in write_targets(words, redirs):
                p = resolve(tok, cur, known)
                if p and hits(p, destructive):
                    return True
    except ValueError:
        pass                              # 引号不配对等解析不了的：这一部分照旧放行
    if INTERP.search(command):            # python / node 这类解释器里明显的写法：同一句既写文件又点名受保护的路径
        for chunk in [text] + bodies:
            for part in re.split(r"[;\n]", chunk):
                if WRITE_API.search(part):
                    for m in PATHLIKE.finditer(part):
                        p = resolve(m.group(0).strip("'\"").rstrip(".,"), cwd, {})
                        if p and hits(p, True):
                            return True
    return False


def in_protected_area(cwd):
    p = os.path.normpath(str(cwd or ""))
    return bool(cwd) and (hits(p, False) or p.startswith(os.path.join(HOME, ".claude")) or "/.claude" in p
                          or p == RUNTIME or p.startswith(RUNTIME + os.sep)
                          or bool(BRIDGE_HOME and (p == BRIDGE_HOME or p.startswith(BRIDGE_HOME + os.sep))))


# ---------- 4. 密钥 ----------

def touches_secrets(command):
    if SECRET_FILES.search(command):
        return True
    try:
        for words, _ in simple_commands(strip_heredocs(cmdparse.normalize(command))[0].replace("\n", " ; ")):
            while words and (ASSIGN_WORD.match(words[0]) or os.path.basename(words[0]) in WRAPPERS):
                words = words[1:]
            if not words:
                continue
            name = os.path.basename(words[0])
            if name in SECRET_TOOLS:
                return True
            if name in ("sh", "bash", "zsh", "node", "python", "python3") and any(
                    os.path.basename(w) in SECRET_TOOLS for w in words[1:]):
                return True
            if name == "security" and any(w in SECURITY_SUB for w in words[1:]):
                return True
    except ValueError:
        pass
    return False


# ---------- 5. 发到别处 ----------

def json_option(seg, name):
    for v in cmdparse.option_values(seg, name):
        try:
            d = json.loads(v)
        except Exception:
            continue
        if isinstance(d, dict):
            return d
    return {}


def concrete(v):
    """能看出具体值（不是变量、命令替换）。"""
    return bool(v) and "$" not in v and "`" not in v


def other_target(command, chat):
    """发到本轮群以外的地方时返回去处（“个人”“别的群”）；看不出来或不是发送返回 None。
    heredoc 正文和引号里的字是数据（比如状态文件里抄的命令），不当成发送命令看。"""
    command = strip_heredocs(command)[0]
    masked = cmdparse.QUOTED.sub(lambda q: q.group(0)[0] + "x" * (len(q.group(0)) - 2) + q.group(0)[-1], command)
    for m in list(SEND.finditer(masked)) + list(API_SEND.finditer(masked)):
        seg = cmdparse.segment(command, m.start())
        if cmdparse.is_help(seg):
            continue
        if any(concrete(v) for opt in PERSON_OPTS for v in cmdparse.option_values(seg, opt)):
            return "个人"
        params, data = json_option(seg, "--params"), json_option(seg, "--data")
        rtype, rid = params.get("receive_id_type"), data.get("receive_id")
        if (rtype and rtype != "chat_id") or data.get("user_id_list") or data.get("open_id_list"):
            return "个人"
        ids = [v for v in cmdparse.option_values(seg, "--chat-id") if concrete(v)]
        if rtype == "chat_id" and isinstance(rid, str) and concrete(rid):
            ids.append(rid)
        if chat and any(v != chat for v in ids):
            return "别的群"
    if chat:
        for m in TOOL_SEND.finditer(masked):
            value = command[m.start(2):m.end(2)]
            if concrete(value) and value.startswith("oc_") and value != chat:
                return "别的群"
    return None


def turn_chat(session):
    """本轮所在的群（remind.py 每轮登记在 /tmp/.aaw_turn_<会话>.json）；读不到返回 None。"""
    try:
        if session:
            with open(f"/tmp/.aaw_turn_{session}.json", encoding="utf-8") as f:
                chat = json.load(f).get("chat")
            return chat if isinstance(chat, str) and chat.startswith("oc_") else None
    except Exception:
        pass
    return None


def decide(command, cwd=None, chat=None):
    """返回 (规则名, 提示语)；不拦返回 (None, None)。
    提示语为 None 而规则名不为空：放行但要记日志（带 ALLOW_OTHER_TARGET 发到别处）。"""
    if not isinstance(command, str) or not command:
        return None, None
    if not any(w in command for w in CHEAP) and not in_protected_area(cwd):
        return None, None                 # 续行符接起来只会插入空格，不会凭空拼出这些词，所以对原文查就够了
    command = cmdparse.normalize(command)
    if any(w in command for w in BRIDGE_WORDS) and (
            BRIDGE_CTL.search(command) or LAUNCHCTL.search(command) or KILL.search(command)
            or FIND_THEN_KILL.search(command) or KILL_NODE.search(command)):
        return "bridge-control", MSG_BRIDGE
    if "lark-cli" in command:
        for m in SEND.finditer(command):
            seg = cmdparse.segment(command, m.start())
            if cmdparse.is_help(seg):
                continue
            who = cmdparse.option_values(seg, "--as")
            if "user" in who or "bot" not in who:
                return "send-without-bot", MSG_SEND
    if any(w in command for w in SECRET_WORDS) and touches_secrets(command):
        return "secrets", MSG_SECRET
    if (any(w in command for w in PROTECT_WORDS) or in_protected_area(cwd)) and touches_protected(command, cwd):
        return "self-protect", MSG_PROTECT
    if any(w in command for w in TARGET_WORDS):
        where = other_target(command, chat)
        if where:
            if ALLOW_OTHER.search(command):
                return "other-target-allowed", None
            return "other-target", MSG_TARGET.format(where=where)
    return None, None


def log(rule, data, reason=None):
    try:
        path = os.path.join(STATE, "hook.log")
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hook": "guard",
            "rule": rule,
            "cwd": os.path.basename(str(data.get("cwd") or "")),
            "session": str(data.get("session_id") or "")[-6:],
        }
        if reason is not None:
            rec["reason"] = reason[:120]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command")
    rule, msg = decide(command, data.get("cwd"), turn_chat(str(data.get("session_id") or "")))
    if not rule:
        return
    if msg is None:                       # 带了 ALLOW_OTHER_TARGET：放行，日志里记下理由
        m = ALLOW_OTHER.search(cmdparse.normalize(command))
        log(rule, data, reason=next((g for g in m.groups() if g is not None), "") if m else "")
        return
    log(rule, data)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
