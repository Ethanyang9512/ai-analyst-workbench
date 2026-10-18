#!/usr/bin/env python3
"""用分析助手过去的真实命令回放护栏和验收门，看新规则会不会误拦（改钩子后跑一遍）。

用法：AAW_HOOK_STATE=$(mktemp -d) python3 replay_history.py <runtime 目录或候选目录> [--sessions-glob <通配>]
      目录下要有 hooks/ 和 tools/。只读历史会话记录，不写任何正式文件；输出里的命令样例已脱敏。
      --sessions-glob 指向 Claude Code 存会话记录的目录，默认 ~/.claude/projects/*aaw-workspaces*
      （Claude Code 按工作区路径给会话目录起名，工作区换了位置就改这个通配）。
看什么：护栏应当 0 条误拦；验收门不应出错，被拦的应当只有 PPT、Excel、Word、PDF 和新建文档。
护栏按当时的 cwd 和本会话的群号判断（群号取自会话里 bridge_context 的 chatId），被拦的命令逐条列出。
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("runtime")
ap.add_argument("--sessions-glob", default=os.path.expanduser("~/.claude/projects/*aaw-workspaces*"))
args = ap.parse_args()
C = args.runtime
sys.path.insert(0, C + '/hooks'); sys.path.insert(0, C + '/tools')
import guard, gate, cmdparse  # noqa: E402,E401

dirs = [d for d in glob.glob(os.path.expanduser(args.sessions_glob)) if os.path.isdir(d)]
n = 0; g = collections.Counter(); gs = collections.defaultdict(list); gt = collections.Counter(); errs = 0; t_max = 0; sends = 0
allowed = collections.Counter(); CHAT_RE = re.compile(r'chatId\W{1,6}(oc_[A-Za-z0-9]+)')


def mask(s):
    s = re.sub(r'oc_[0-9a-f]{20,}', 'oc_…', s)
    s = re.sub(r"(--(?:text|markdown|content|data|params)[=\s]+)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|\S+)", r'\1<…>', s, flags=re.S)
    s = re.sub(r'[A-Za-z0-9+/=_-]{28,}', '<长串>', s)
    return re.sub(r'\s+', ' ', s)[:300]


for d in dirs:
    for f in glob.glob(d + '/*.jsonl'):
        chat = None
        for line in open(f, encoding='utf-8', errors='ignore'):
            if chat is None and 'chatId' in line:
                m = CHAT_RE.search(line); chat = m.group(1) if m else None
            if '"Bash"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('isSidechain'):
                continue
            c = (o.get('message') or {}).get('content')
            if not isinstance(c, list):
                continue
            cwd = o.get('cwd') or ''
            for b in c:
                if b.get('type') == 'tool_use' and b.get('name') == 'Bash':
                    cmd = (b.get('input') or {}).get('command')
                    if not isinstance(cmd, str):
                        continue
                    n += 1
                    rule, msg = guard.decide(cmd, cwd or None, chat)
                    if rule and msg:
                        g[rule] += 1; gs[rule].append(mask(cmd))
                    elif rule:
                        allowed[rule] += 1
                    norm = cmdparse.normalize(cmd)
                    if guard.SEND.search(norm):
                        sends += 1
                    if gate.SEND.search(norm) or gate.DOC_CREATE.search(norm):
                        t = time.time()
                        try:
                            items = gate.missing(norm, cwd or os.getcwd())
                        except Exception as e:
                            errs += 1; items = ['ERR:' + type(e).__name__]
                        t_max = max(t_max, time.time() - t)
                        if not items:
                            gt['放行'] += 1
                        for it in items:
                            kind = '新建文档' if it == '新建飞书文档' else ('推算不出' if it == gate.UNKNOWN else os.path.splitext(it)[1].lower() or it)
                            gt['会拦 ' + kind] += 1
print('会话目录:', len(dirs), '个（通配：%s）' % args.sessions_glob)
print('历史 Bash 命令:', n, '| 其中发消息的命令:', sends)
print('护栏会拦:', dict(g) or '0 条')
for r, ss in gs.items():
    for s in ss:
        print('   ', r, '|', s)
if allowed:
    print('护栏放行但记日志（带 ALLOW_OTHER_TARGET）:', dict(allowed))
print('验收门（强制模式；当时都没有验收记录，所以正式文件理应被拦）:', dict(gt))
print('验收门出错:', errs, '| 单次最长 %.3fs' % t_max)
