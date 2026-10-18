#!/usr/bin/env python3
"""分析助手各工作区 .claude/settings.json 的统一维护脚本。

只增改本脚本管理的键，其余键（模型、代理等）原样保留；可重复执行。

  workspace_settings.py apply --all            # 写入全部分析助手工作区（default + 自动发现的项目工作区）
  workspace_settings.py apply --path <目录> --kind base|project   # 写入指定目录（测试/新项目用）
  workspace_settings.py check                  # 只检查，不写
  workspace_settings.py show --kind base|project   # 打印将要写入的受管键

受管的键：
  env.CLAUDE_CODE_DISABLE_BACKGROUND_TASKS  关掉后台运行（防止“还在处理”被桥当成最终答复）
  effortLevel                               推理强度
  hooks                                     护栏等钩子（只登记 hooks/ 目录下实际存在的脚本）
  enabledPlugins / skillOverrides           只对项目工作区：关掉用不上的插件、隐藏无关技能（少占上下文、少误触发）
  permissions.deny（下面 DENY_EDIT 几条）    不让用改文件的工具（Edit / Write）改护栏、规则和设置

工作区在哪：AAW_WS_BASE（默认 ~/aaw-workspaces）。其下 default/ 是基础工作区（私聊用），
其余有 CLAUDE.md 的子目录算项目工作区（一个群一个）。
可调的值（推理强度、要关的插件、要隐藏的技能）放在同目录的 workspace_settings.json，不改这份代码。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("AAW_WS_BASE") or "~/aaw-workspaces")
RUNTIME = os.environ.get("AAW_RUNTIME") or HERE
HOOKS_DIR = os.path.join(RUNTIME, "hooks")
RUN_HOOK = os.path.join(HOOKS_DIR, "run-hook.sh")
CONFIG = os.path.join(HERE, "workspace_settings.json")

BASE_DIRS = ["default"]
MARK = "/hooks/run-hook.sh"     # 用来识别本脚本登记的钩子

# 不让分析助手用 Edit / Write / NotebookEdit 改下面这些地方，读不受影响。
# 实测：完全权限模式（bypassPermissions）下 deny 照样生效；文件权限检查只认 Edit(...) 规则，
# 它管住全部改文件的工具（写 Write(...)、NotebookEdit(...) 不起作用，还会报警告），所以只写 Edit。
# “//” 开头是绝对路径。日常要写的地方（项目文件、_status.md、_acceptance/、记忆 ~/.claude/projects/、
# 技能 ~/.claude/skills/）都不在里面。Bash 里的写法由 hooks/guard.py 另外拦。
HOME = os.path.expanduser("~")
DENY_EDIT = [
    f"Edit(/{RUNTIME}/**)",                         # runtime 目录（钩子、workflow.md、工具）
    f"Edit(/{HOME}/.claude/settings*.json)",
    f"Edit(/{HOME}/.claude/CLAUDE.md)",
    f"Edit(/{HOME}/.claude/agents/**)",
    f"Edit(/{ROOT}/*/.claude/**)",                  # 各工作区的设置（含钩子登记）
]
if os.environ.get("AAW_BRIDGE_HOME"):           # 桥的配置和密钥所在目录
    DENY_EDIT.append(f"Edit(/{os.path.expanduser(os.environ['AAW_BRIDGE_HOME'])}/**)")

# 钩子登记表：(事件, matcher, 脚本名, 超时秒)。脚本文件不存在的不登记。
HOOK_TABLE = [
    ("PreToolUse", "Bash", "guard", 5),
    ("PreToolUse", "Bash", "gate", 10),
    ("UserPromptSubmit", None, "remind", 5),
    ("PreToolUse", None, "progress", 5),
    ("Stop", None, "progress_stop", 20),
]


def load_config():
    """读 workspace_settings.json；缺了或坏了用默认值（effort=high，不关插件、不藏技能）。"""
    cfg = {"effort": "high", "disabled_plugins": [], "hide_skills": [], "hide_skill_prefixes": []}
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
        for k in cfg:
            if k in data and not k.startswith("_"):
                cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    return cfg


CFG = load_config()


def hook_command(name):
    # 不用 exec：入口脚本自己坏掉（比如语法错）时会以退出码 2 结束，exec 会把它原样交回去，等于拦住所有工具。
    return f"/bin/sh -c '[ -x \"{RUN_HOOK}\" ] && \"{RUN_HOOK}\" {name}; exit 0'"


def managed_hooks():
    out = {}
    for event, matcher, name, timeout in HOOK_TABLE:
        if not os.path.isfile(os.path.join(HOOKS_DIR, name + ".py")):
            continue
        group = {"hooks": [{"type": "command", "command": hook_command(name), "timeout": timeout}]}
        if matcher:
            group["matcher"] = matcher
        out.setdefault(event, []).append(group)
    return out


def hidden_skills():
    skills_dir = os.path.expanduser("~/.claude/skills")
    names = sorted(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else []
    prefixes = tuple(CFG.get("hide_skill_prefixes") or ())
    hide = [n for n in names if (prefixes and n.startswith(prefixes)) or n in (CFG.get("hide_skills") or [])]
    return {n: "off" for n in hide}


def desired(current, kind, with_cleanup):
    """在 current 的基础上返回新的 settings（不修改入参）。"""
    s = json.loads(json.dumps(current))
    env = s.setdefault("env", {})
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    s["effortLevel"] = CFG["effort"]
    # 钩子：保留不是本脚本登记的，替换本脚本登记的
    hooks = s.get("hooks") or {}
    kept = {}
    for event, groups in hooks.items():
        rest = [g for g in groups if MARK not in json.dumps(g, ensure_ascii=False)]
        if rest:
            kept[event] = rest
    for event, groups in managed_hooks().items():
        kept.setdefault(event, []).extend(groups)
    if kept:
        s["hooks"] = kept
    elif "hooks" in s:
        del s["hooks"]
    # 写入门槛：保留别人加的 deny，补上本脚本管的几条
    perms = s.setdefault("permissions", {})
    perms["deny"] = [r for r in perms.get("deny", []) if r not in DENY_EDIT] + DENY_EDIT
    if kind == "project" and with_cleanup:
        if CFG.get("disabled_plugins"):
            plugins = s.setdefault("enabledPlugins", {})
            for p in CFG["disabled_plugins"]:
                plugins[p] = False
        hidden = hidden_skills()
        if hidden:
            s.setdefault("skillOverrides", {}).update(hidden)
    return s


def settings_path(ws_dir):
    return os.path.join(ws_dir, ".claude", "settings.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def project_dirs():
    """自动发现项目工作区：总目录下有 CLAUDE.md 的子目录（default 除外）。"""
    if not os.path.isdir(ROOT):
        return []
    return sorted(d for d in os.listdir(ROOT)
                  if d not in BASE_DIRS and not d.startswith(".") and os.path.isfile(os.path.join(ROOT, d, "CLAUDE.md")))


def targets(args):
    if args.path:
        return [(os.path.abspath(args.path), args.kind)]
    return [(os.path.join(ROOT, d), "base") for d in BASE_DIRS if os.path.isdir(os.path.join(ROOT, d))] + \
           [(os.path.join(ROOT, d), "project") for d in project_dirs()]


def summarize(s):
    hooks = s.get("hooks") or {}
    names = []
    for event, groups in hooks.items():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                if MARK in cmd:
                    names.append(event + ":" + cmd.split(" ")[-3].rstrip(";"))
    return {
        "bg_off": (s.get("env") or {}).get("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"),
        "effort": s.get("effortLevel"),
        "hooks": names,
        "plugins_off": [k for k, v in (s.get("enabledPlugins") or {}).items() if v is False],
        "skills_hidden": len(s.get("skillOverrides") or {}),
        "deny_edit": sum(r in ((s.get("permissions") or {}).get("deny") or []) for r in DENY_EDIT),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["apply", "check", "show"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--path")
    ap.add_argument("--kind", choices=["base", "project"], default="base")
    ap.add_argument("--no-cleanup", action="store_true", help="暂不写插件/技能设置")
    args = ap.parse_args()
    with_cleanup = not args.no_cleanup
    if not os.path.isfile(RUN_HOOK):    # AAW_RUNTIME 指错时，别静默写出一份没有钩子的设置
        print(f"找不到钩子入口 {RUN_HOOK}。AAW_RUNTIME 现在是 {RUNTIME}；"
              "请把它改成仓库里 runtime/ 的绝对路径，或者不设（默认用本脚本所在的 runtime/）。", file=sys.stderr)
        return 2

    if args.action == "show":
        print(json.dumps(desired({}, args.kind, with_cleanup), ensure_ascii=False, indent=2))
        return 0
    if args.action == "apply" and not (args.all or args.path):
        print("apply 需要 --all 或 --path", file=sys.stderr)
        return 2

    rc = 0
    found = targets(args)
    if not found:
        print(f"{ROOT} 下没有找到工作区（default/ 或带 CLAUDE.md 的子目录）")
        return 1
    for ws, kind in found:
        path = settings_path(ws)
        name = os.path.basename(ws)
        if not os.path.isfile(path):
            if args.action == "apply":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                cur = {}
            else:
                print(f"{name}: 缺 settings.json")
                rc = 1
                continue
        else:
            cur = load(path)
        want = desired(cur, kind, with_cleanup)
        same = json.dumps(cur, sort_keys=True) == json.dumps(want, sort_keys=True)
        if args.action == "check":
            print(f"{name} [{kind}] {'一致' if same else '不一致'} {json.dumps(summarize(cur), ensure_ascii=False)}")
            rc = rc or (0 if same else 1)
        else:
            if not same:
                write_atomic(path, want)
            print(f"{name} [{kind}] {'未变' if same else '已写入'} {json.dumps(summarize(want), ensure_ascii=False)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
