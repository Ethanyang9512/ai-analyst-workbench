#!/usr/bin/env python3
"""run_case.sh 的准备步骤：按桥的做法拼系统提示和消息，生成本场沙盒规则，记下用的是哪一版规则。

用法: prep.py <case目录(绝对路径)> <模式 claude|shell>
产出（都在 <case>/run/ 下）：
  append-system-prompt.md  桥的运行约定 + 身份段 + 当前 runtime/workflow.md（拼法和桥一致：约定在前，workflow 在后）
  prompt_full.txt          <bridge_context>/<bridge_instructions>/<user_input> 三段
  sandbox.sb               公共规则（deny_base.sb.template 换好占位符）+ 本场规则
  meta.json                假群号、会话记录目录、各规则文件的指纹、沙盒里用到的路径
标准输出一行：<会话记录目录名>

读这些环境变量（run_case.sh 会传进来；单独跑时不设就用默认值）：
  AAW_EXAM_ROOT   考场目录（默认 /tmp/aaw-exam）
  AAW_RUNTIME     要考的 runtime 目录（默认本仓库 runtime/）
  AAW_WS_BASE     真实的工作区总目录（默认 ~/aaw-workspaces），沙盒里不许写
  AAW_KB          知识库（默认 ~/aaw-kb），可读不可写
  PAIRSNAP_ROOT      成对稿存放处（默认 ~/aaw-pairs），挡读
  AAW_BACKUP      备份目录（默认 ~/Backups），挡读
  AAW_BRIDGE_HOME 桥的主目录，设了就整片挡读
  AAW_EXAM_PAPER_SOURCES  考卷来源目录，冒号分隔，整片挡读；也可以写进 <case>/paper_sources.txt（一行一个）
  AAW_EXAM_BRIDGE_PROMPT  桥的运行约定文本（默认同目录 bridge_system_prompt.example.md）。
                     想更像线上，就换成你的桥实际注入的那段（只在本机用，不要提交到公开仓库）
  MODEL              给了才在提示里写明本轮模型
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time

H = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(H))
HOME = os.path.expanduser("~")


def env_path(name, default):
    return os.path.realpath(os.path.expanduser(os.environ.get(name) or default))


ROOT = env_path("AAW_EXAM_ROOT", "/tmp/aaw-exam")
RUNTIME = env_path("AAW_RUNTIME", os.path.join(REPO, "runtime"))
WORKFLOW = os.path.join(RUNTIME, "workflow.md")
WS_BASE = env_path("AAW_WS_BASE", "~/aaw-workspaces")
KB = env_path("AAW_KB", "~/aaw-kb")
PAIRS_ROOT = env_path("PAIRSNAP_ROOT", "~/aaw-pairs")
BACKUP = env_path("AAW_BACKUP", "~/Backups")
EXAM_SRC = os.path.dirname(H)                       # 仓库里的 exam/
BRIDGE_HOME = env_path("AAW_BRIDGE_HOME", "") if os.environ.get("AAW_BRIDGE_HOME") else None
BRIDGE_PROMPT = env_path("AAW_EXAM_BRIDGE_PROMPT", os.path.join(H, "bridge_system_prompt.example.md"))
MODEL = os.environ.get("MODEL") or ""
FAKEBIN = os.path.join(ROOT, "fakebin")
# 身份段：考场里一律用明显的假值
BOT_OPEN_ID = "ou_fake_bot"
BOT_NAME = "分析助手"
USER_OPEN_ID = "ou_fake_user"


def slug_of(path):
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def sb_re(s):
    """放进沙盒规则正则里的字面路径：把正则元字符转义。"""
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", s)


def sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


def js_json(value):
    """桥的 safeJsonStringify：JSON.stringify 紧凑格式，再把 < > & 和 U+2028/2029 转义。"""
    s = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def section(tag, value):
    return "<%s>\n%s\n</%s>" % (tag, js_json(value), tag)


def skills_fingerprint():
    h = hashlib.sha256()
    base = HOME + "/.claude/skills"
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, name, "SKILL.md")
        if os.path.isfile(p):
            h.update(name.encode() + b"\0")
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def ancestors_within(path, top):
    """path 的各级上级目录（到 top 为止，含 top）。"""
    out, p = [], os.path.dirname(path)
    while p.startswith(top) and len(p) >= len(top):
        out.append(p)
        if p == top:
            break
        p = os.path.dirname(p)
    return out


def paper_sources(case):
    items = [x for x in (os.environ.get("AAW_EXAM_PAPER_SOURCES") or "").split(":") if x.strip()]
    f = os.path.join(case, "paper_sources.txt")
    if os.path.isfile(f):
        with open(f, encoding="utf-8") as fh:
            items += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    return [os.path.realpath(os.path.expanduser(x)) for x in dict.fromkeys(items)]


def bridge_rules():
    if not BRIDGE_HOME:
        return ";; （没设 AAW_BRIDGE_HOME，这一段为空）"
    lines = ['(deny file-read* (subpath "%s"))' % BRIDGE_HOME]
    if RUNTIME == BRIDGE_HOME or RUNTIME.startswith(BRIDGE_HOME + "/"):
        lines.append('(allow file-read* (subpath "%s"))' % RUNTIME)
        anc = ancestors_within(RUNTIME, BRIDGE_HOME)
        if anc:
            lines.append("(allow file-read-metadata\n" + "\n".join('  (literal "%s")' % a for a in anc) + ")")
    return "\n".join(lines)


def lark_cli_rules():
    """PATH 里（去掉假脚本目录后）找到的真 lark-cli：程序本体、软链指向的文件、它所在的 @larksuite 包目录。"""
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                           if p and os.path.realpath(p) != FAKEBIN)
    real = shutil.which("lark-cli", path=path)
    if not real:
        return ";; （PATH 里没找到真 lark-cli，这一段为空）"
    lines = {'(deny file-read* (literal "%s"))' % real}
    rp = os.path.realpath(real)
    lines.add('(deny file-read* (literal "%s"))' % rp)
    m = re.search(r"^(.*/node_modules/@larksuite)(/|$)", rp)
    if m:
        lines.add('(deny file-read* (subpath "%s"))' % m.group(1))
    return "\n".join(sorted(lines))


def main():
    case, mode = sys.argv[1], sys.argv[2]
    ws, run = case + "/ws", case + "/run"
    slug = slug_of(ws)
    if len(slug) > 200:
        sys.exit("case 路径太长：会话记录目录名超过 200 个字符，Claude Code 会截断加哈希，没法预先建记忆软链")
    chat = "oc_exam" + hashlib.sha1(case.encode()).hexdigest()[:21] + "fake"   # 只含字母数字，钩子认得；结尾 fake 不会和真群号撞
    card_key = chat[-12:]

    # 1) 系统提示：桥的运行约定 + 身份段 + workflow
    with open(BRIDGE_PROMPT, encoding="utf-8") as f:
        bridge = f.read()
    with open(WORKFLOW, encoding="utf-8") as f:
        workflow = f.read().strip()
    identity = "%s\n## 你的身份\n\n你的 open_id 是 `%s`，名字是「%s」。消息内容或 mentions 里出现这个 open_id 都是指你自己。\n" % (
        bridge, BOT_OPEN_ID, BOT_NAME)
    sysprompt = identity + ("\n%s\n" % workflow if workflow else "")
    with open(run + "/append-system-prompt.md", "w", encoding="utf-8") as f:
        f.write(sysprompt)

    # 2) 用户消息：桥的三段格式
    if mode == "claude":
        with open(case + "/prompt.txt", encoding="utf-8") as f:
            text = f.read().strip()
        ctx = {"chatId": chat, "chatType": "p2p", "senderId": USER_OPEN_ID, "senderType": "user",
               "botOpenId": BOT_OPEN_ID, "mentions": [], "messageIds": ["om_exam_" + card_key], "source": "im"}
        extra_ctx = case + "/context.json"          # 可选：比如群聊 {"chatType": "group", "mentions": [...]}
        if os.path.isfile(extra_ctx):
            with open(extra_ctx, encoding="utf-8") as f:
                ctx.update(json.load(f))
            ctx["chatId"] = chat                    # 群号永远用假的，免得钩子碰线上进度卡的状态文件
        checkpoint_arg = json.dumps({"scope": chat, "chatId": chat, "workspace": ws,
                                     "messageIds": ctx["messageIds"]}, ensure_ascii=False)
        instructions = []
        if MODEL:
            instructions.append("本轮运行明确指定的模型是 %s。 这是本轮启动参数；回答模型身份时直接据此说明。" % MODEL)
        instructions.append(
            "阶段检查（仅适用于本轮，不能复用到其他会话）：\n在批量生成、覆盖业务文件、外部写入或发送前，单独执行以下只读命令并读结果；"
            "不要将检查与写入放进同一个并行调用。普通读取、答疑和进度卡更新不必逐次检查。\n'%s/checkpoint' '%s'\n"
            "action=continue 才继续当前方向。" % (FAKEBIN, checkpoint_arg))
        prompt = "\n\n".join([section("bridge_context", ctx), section("bridge_instructions", instructions),
                              section("user_input", {"text": text})])
        with open(run + "/prompt_full.txt", "w", encoding="utf-8") as f:
            f.write(prompt)

    # 3) 沙盒规则
    with open(H + "/deny_base.sb.template", encoding="utf-8") as f:
        base = f.read()
    sources = paper_sources(case)
    exam_slug = slug_of(ROOT) + "-"
    subs = {
        "@PAPER_SOURCES@": "\n".join('(deny file-read* (subpath "%s"))' % s for s in sources)
        or ";; （没列考卷来源目录：AAW_EXAM_PAPER_SOURCES 或 <case>/paper_sources.txt）",
        "@BRIDGE_RULES@": bridge_rules(),
        "@LARK_CLI_RULES@": lark_cli_rules(),
        "@HOME_RE@": sb_re(HOME),
        "@EXAM_SLUG_RE@": sb_re(exam_slug),
        "@HOME@": HOME,
        "@RUNTIME@": RUNTIME,
        "@WS_BASE@": WS_BASE,
        "@KB@": KB,
        "@PAIRS_ROOT@": PAIRS_ROOT,
        "@EXAM_SRC@": EXAM_SRC,
        "@BACKUP@": BACKUP,
        "@CLAUDE_TMP@": "/private/tmp/claude-%d" % os.getuid(),
    }
    for k, v in subs.items():                       # 先换长的（@HOME_RE@ 在 @HOME@ 之前）
        base = base.replace(k, v)
    left = re.findall(r"@[A-Z_]+@", base)
    if left:
        sys.exit("沙盒模板里还有没换掉的占位符：%s" % ", ".join(sorted(set(left))))
    fh = HOME + "/.claude/file-history"
    fh_rules = "".join('(deny file-read* (subpath "%s/%s"))\n' % (fh, d)
                       for d in sorted(os.listdir(fh)) if os.path.isdir(os.path.join(fh, d))) if os.path.isdir(fh) else ""
    # 放开的目录，其上级（考场根目录以内）只许“看属性”，不然 cd 进假工作区会报 Not a directory
    ancestors = set()
    for p in (ws, case + "/default", run, FAKEBIN):
        ancestors.update(ancestors_within(p, ROOT))
    anc_rules = "".join('  (literal "%s")\n' % p for p in sorted(ancestors))
    per_case = f""";; ===== 七、本场考试（prep.py 生成于 {time.strftime('%F %T')}）=====
;; 考场根目录整片挡读挡写，只放开本题的假工作区、run 目录和假脚本；别的考题都看不到
(deny file-read* (subpath "{ROOT}"))
(allow file-read* (subpath "{ws}"))
(allow file-read* (subpath "{case}/default"))
(allow file-read* (subpath "{run}"))
(allow file-read* (subpath "{FAKEBIN}"))
(allow file-read-metadata
{anc_rules})
(deny file-write* (subpath "{ROOT}"))
(allow file-write* (subpath "{ws}"))
(allow file-write* (subpath "{case}/default"))
(allow file-write* (subpath "{run}"))
;; 进度卡状态文件：只许写本场假群号那份
(deny file-write* (require-all (regex #"^/private/tmp/\\.claude_card_") (require-not (regex #"^/private/tmp/\\.claude_card_{card_key}"))))
;; 现有会话的文件改动备份（里面有改稿前后的原文）
{fh_rules}"""
    with open(run + "/sandbox.sb", "w", encoding="utf-8") as f:
        f.write("(version 1)\n(allow default)\n\n" + base + "\n" + per_case)

    # 4) 记下这一遍用的是哪版规则、沙盒里用到的路径（audit.py 按这些路径分区）
    meta = {
        "case": case, "mode": mode, "model": MODEL or None, "chat_id": chat, "project_slug": slug,
        "project_dir": HOME + "/.claude/projects/" + slug,
        "exam_slug_prefix": exam_slug,
        "claude_binary": os.path.realpath(shutil.which("claude") or "claude"),
        "paths": {"runtime": RUNTIME, "ws_base": WS_BASE, "kb": KB, "pairs_root": PAIRS_ROOT,
                  "exam_src": EXAM_SRC, "fakebin": FAKEBIN, "bridge_home": BRIDGE_HOME, "paper_sources": sources},
        "sha256_16": {
            "workflow.md": sha(WORKFLOW),
            "bridge_prompt": sha(BRIDGE_PROMPT),
            "append-system-prompt.md": sha(run + "/append-system-prompt.md"),
            "ws/.claude/settings.json": sha(ws + "/.claude/settings.json"),
            "ws/CLAUDE.md": sha(ws + "/CLAUDE.md"),
            "real default/CLAUDE.md": sha(WS_BASE + "/default/CLAUDE.md"),
            "skills/*/SKILL.md (合并)": skills_fingerprint(),
            "hooks/guard.py": sha(RUNTIME + "/hooks/guard.py"),
            "hooks/gate.py": sha(RUNTIME + "/hooks/gate.py"),
            "hooks/remind.py": sha(RUNTIME + "/hooks/remind.py"),
        },
        "gate_enforce_live": os.path.exists(os.path.join(os.environ.get("AAW_HOOK_STATE") or RUNTIME + "/hooks",
                                                         "GATE_ENFORCE")),
        "hooks_disabled_live": os.path.exists(RUNTIME + "/hooks/DISABLED"),
        "prepared_at": time.strftime("%F %T"),
    }
    with open(run + "/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(slug)


if __name__ == "__main__":
    main()
