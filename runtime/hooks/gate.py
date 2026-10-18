#!/usr/bin/env python3
"""验收门（PreToolUse / Bash）。

分析助手要把 PPT、Excel、Word、PDF 发到飞书（或把文件导成飞书文档、新建飞书文档）时，检查有没有对应的验收记录
（tools/accept_record.py 写在工作区最上层的 _acceptance/records.jsonl）。

为什么设这道门：正式交付物发出前要过程序检查和两位验收员（见 workflow.md「验收」），这一步最容易在赶时间时被跳过。
门只认“这个文件的内容指纹有没有被记录过”，不判断验收做得好不好；文件改过一个字节，记录就失效。

两种模式：
  提醒模式（默认）：没有记录时不拦，只在工具结果旁边加一段提醒。
  强制模式（钩子状态目录 AAW_HOOK_STATE，默认本目录，存在 GATE_ENFORCE 文件）：没有记录时拦下，并说明怎么做。
  建议先用提醒模式跑一两周，看日志里误报多不多，再切强制模式。
命令里带 ACCEPT_SKIP='理由' 时一律放行，并记一笔。钩子自己出错时放行，并在日志里记一行 error。
日志只记文件类型和处理结果，不记命令原文。

怎么找到要发的文件：钩子在命令执行之前运行，所以按命令里写明的 cd 和变量赋值推算发送那一刻所在的目录，
再按路径找文件。找不到（文件要在同一条命令里才生成）或推算不出来（路径里有变量、通配符、命令替换），
都按“没有记录”处理，并提示把目录和文件名直接写出来。
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("AAW_HOOK_STATE") or HERE     # GATE_ENFORCE 和日志所在目录（测试时换成临时目录）
TOOLS = os.path.join(os.environ.get("AAW_RUNTIME") or os.path.dirname(HERE), "tools")
TOOL = os.path.join(TOOLS, "accept_record.py")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
import accept_record as rec  # noqa: E402
import cmdparse  # noqa: E402

GATED_EXT = (".pptx", ".xlsx", ".docx", ".pdf")
SEND = re.compile(
    r"\blark-cli\b[^\n;|&]*?\s(?:im\s+(?:\+messages-send|\+messages-reply)|drive\s+\+import)\b")
DOC_CREATE = re.compile(r"\blark-cli\b[^\n;|&]*?\sdocs?\s+\+create\b")
FILE_ARG = re.compile(r"--file[=\s]+(\"(?:[^\"\\]|\\.)*\"|'[^']*'|(?:\\.|[^\s;|&)\"'])+)")
SKIP = re.compile(r"\bACCEPT_SKIP=")
ASSIGN = re.compile(r"(?:^|[;&|\n]|\bexport\s)\s*([A-Za-z_]\w*)=(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|]*)", re.ASCII)
CD = re.compile(r"(?:^|[;&|\n(])\s*(?:cd|pushd)\s+(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|)]+)")
FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\s+([^;\n]*?)\s*(?:;|\n)\s*do\b", re.ASCII)
VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)", re.ASCII)
UNRESOLVED = re.compile(r"\$[A-Za-z_{(]|`")
GLOB = re.compile(r"[*?\[\]{}]")
UNKNOWN = "路径里有变量或通配符的文件"


def expand(tok, known):
    """把命令里的一个路径参数还原成字符串；还原不了（未知变量、命令替换、通配符）返回 None。"""
    if len(tok) >= 2 and tok[0] == tok[-1] == "'":
        return tok[1:-1]
    quoted = len(tok) >= 2 and tok[0] == tok[-1] == '"'
    if quoted:
        tok = tok[1:-1]
    elif tok == "~" or tok.startswith("~/"):
        tok = os.path.expanduser("~") + tok[1:]

    def sub(m):
        name = m.group(1) or m.group(2)
        if name == "HOME":
            return os.path.expanduser("~")
        if known.get(name) is None:
            raise KeyError(name)
        return known[name]

    try:
        tok = VAR.sub(sub, tok)
    except KeyError:
        return None
    if UNRESOLVED.search(tok) or (not quoted and GLOB.search(tok)):
        return None
    return tok if quoted else re.sub(r"\\(.)", r"\1", tok)


def loop_lists(prefix):
    """发送命令之前出现的 for 循环：变量名 -> 写明的清单；清单里有变量或通配符就记成 None。"""
    out = {}
    for m in FOR.finditer(prefix):
        items = cmdparse.words(m.group(2))
        if not items or any(UNRESOLVED.search(x) or "$" in x or GLOB.search(x) for x in items):
            items = None
        out[m.group(1)] = items
    return out


def expansions(raw, known, loops):
    """一个 --file 参数可能对应的全部文件名（循环变量按清单逐个展开）。还原不了的那一项是 None。"""
    if not (len(raw) >= 2 and raw[0] == raw[-1] == "'"):
        for var, items in loops.items():
            if re.search(r"\$\{?" + var + r"(?![A-Za-z0-9_])", raw):
                if items is None:
                    return [None]
                return [expand(raw, dict(known, **{var: item})) for item in items]
    return [expand(raw, known)]


def effective_dir(prefix, cwd):
    """按发送命令之前出现的 cd 和变量赋值，推算发送那一刻所在的目录。推不出来返回 None。"""
    known, cur = {}, cwd
    events = [(m.start(), "set", m) for m in ASSIGN.finditer(prefix)]
    events += [(m.start(), "cd", m) for m in CD.finditer(prefix)]
    for _, kind, m in sorted(events, key=lambda e: e[0]):
        if kind == "set":
            known[m.group(1)] = expand(m.group(2), known)
            continue
        target = expand(m.group(1), known)
        if target is None or target == "-":
            cur = None
        elif os.path.isabs(target):
            cur = target
        elif cur is not None:
            cur = os.path.normpath(os.path.join(cur, target))
    return cur, known


def missing(command, cwd):
    """返回没有验收记录的交付物说明列表；空列表表示放行。"""
    out, cache = [], {}

    def recorded(digest, roots):
        for root in roots:
            if root not in cache:
                cache[root] = rec.digests(root)
            if digest in cache[root]:
                return True
        return False

    def roots_of(*dirs):
        return list(dict.fromkeys(rec.find_root(d) for d in dirs if d))

    for m in SEND.finditer(command):
        seg = cmdparse.segment(command, m.start())
        if cmdparse.is_help(seg):
            continue
        cur, known = effective_dir(command[:m.start()], cwd)
        loops = loop_lists(command[:m.start()])
        for raw, name in [(r, n) for r in FILE_ARG.findall(seg) for n in expansions(r, known, loops)]:
            shown = name if name is not None else raw.strip("\"'")
            ext = os.path.splitext(shown)[1].lower()
            if name is None:
                if re.fullmatch(r"\.\w{1,5}", ext, re.ASCII) and ext not in GATED_EXT:
                    continue                    # 看得出不是受控类型（比如 "$D/包.zip"）
                out.append(os.path.basename(shown) if ext in GATED_EXT else UNKNOWN)
                continue
            if ext not in GATED_EXT or re.match(r"https?://", name):
                continue
            path = name if os.path.isabs(name) else (os.path.join(cur, name) if cur else None)
            if (not path or not os.path.isfile(path)
                    or not recorded(rec.sha256(path), roots_of(cwd, cur, os.path.dirname(os.path.realpath(path))))):
                out.append(os.path.basename(name))
    for m in DOC_CREATE.finditer(command):
        if cmdparse.is_help(cmdparse.segment(command, m.start())):
            continue
        cur, _ = effective_dir(command[:m.start()], cwd)
        if not any(rec.recent_doc_record(root) for root in roots_of(cwd, cur)):
            out.append("新建飞书文档")
    return list(dict.fromkeys(out))


def message(items, enforce):
    names = "、".join(items)
    text = (
        f"验收门：{names} 没有查到验收记录。正式交付物发出前要这样做："
        "① 按 workflow.md 的分档验收（先跑 deckcheck.py scope 和 accept_record.py status 定档）；"
        "写记录时带 --tier 和 --pages；没请某位验收员时写 --reader 或 --visual \"不适用：原因\"。"
        "② 修掉必须改的问题；"
        f"③ 运行 `python3 {TOOL} write --file <文件> --tier <档位> --pages \"<涉及的页>\" "
        "--reader \"<结果>\" --visual \"<结果>\"`"
        "（新建飞书文档用 `--doc \"<标题>\"`）；"
        "④ 另起一条命令发送，并在回复里写一行验收结果（哪一档、看了哪几页、改了什么）。"
        "注意：检查发生在命令执行之前，所以要发的文件和验收记录都必须已经存在——"
        "生成文件、写验收记录、发送要分成几条命令；发送写成 `cd <目录> && lark-cli … --file <文件名>`，"
        "目录和文件名直接写出来，不用变量、通配符或命令替换。"
        "如果是中间文件，或用户明确说不用验收：在命令最前面加 `ACCEPT_SKIP='理由'` 再发。"
    )
    if not enforce:
        text += "（现在是提醒模式，这一次没有拦。）"
    return text


def log(decision, data, items):
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hook": "gate",
            "decision": decision,
            "items": items if decision == "error" else [
                os.path.splitext(x)[1] or ("doc" if x == "新建飞书文档" else "unknown") for x in items],
            "cwd": os.path.basename(str(data.get("cwd") or "")),
            "session": str(data.get("session_id") or "")[-6:],
        }
        with open(os.path.join(STATE, "hook.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return
    command = cmdparse.normalize(command)
    if not (SEND.search(command) or DOC_CREATE.search(command)):
        return
    cwd = str(data.get("cwd") or os.getcwd())
    try:
        items = missing(command, cwd)
    except Exception as e:
        log("error", data, [type(e).__name__])
        return
    if not items:
        return
    if SKIP.search(command):
        log("skip", data, items)
        return
    enforce = os.path.exists(os.path.join(STATE, "GATE_ENFORCE"))
    text = message(items, enforce)
    if enforce:
        log("deny", data, items)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": text,
        }}))
    else:
        log("remind", data, items)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
