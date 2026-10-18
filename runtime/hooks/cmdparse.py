#!/usr/bin/env python3
"""护栏和验收门共用的命令解析小工具。只做粗略解析：够判断“这一条发送命令自己带了什么参数”就行。"""
import re
import shlex

QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')
HELP = re.compile(r"(?:^|\s)(--help|-h)(?=\s|$)")


def normalize(command):
    """把行尾的续行符接起来。"""
    return command.replace("\\\n", " ")


def segment(command, start):
    """从 start 起取到这一条命令结束（引号外的 ; | & 或换行）。"""
    quote, i, n = None, start, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in ";|&\n":
            break
        i += 1
    return command[start:i]


def unquoted(seg):
    """把引号里的内容抹掉：消息正文里的字不当成参数看。"""
    return QUOTED.sub('""', seg)


def is_help(seg):
    """这条命令只是在看帮助。"""
    return HELP.search(unquoted(seg)) is not None


def words(seg):
    """按 shell 的规则切成词；切不开（引号不配对等）返回 None。"""
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return None


def option_values(seg, name):
    """取这条命令里某个参数的全部取值，比如 option_values(seg, "--as") -> ["bot"]。"""
    parts = words(seg)
    if parts is None:
        return re.findall(re.escape(name) + r"(?:=|\s+)([^\s\"']+)", unquoted(seg))
    out = []
    for i, part in enumerate(parts):
        if part == name and i + 1 < len(parts):
            out.append(parts[i + 1])
        elif part.startswith(name + "="):
            out.append(part[len(name) + 1:])
    return out
