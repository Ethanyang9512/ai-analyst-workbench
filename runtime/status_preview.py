#!/usr/bin/env python3
"""分析助手新开会话时附带的工作区状态预览（由桥在新会话的第一轮调用，把输出拼进提示）。

用法：python3 status_preview.py <工作区真实路径>
- 读取 <工作区>/_status.md，打印一段中文预览到 stdout；没有状态文件时不输出。
- 根状态用反引号明确引用了工作区内唯一一个子项目 `xxx/_status.md` 时，一并预览该子项目。
- 状态文件里有「现状摘要」标记块时，只预览这一块，并检查它是否过期；
  没有标记块时，仍按原来的首尾摘录方式预览。标记块写法：
      <!-- 现状摘要:开始 -->
      ## 现状摘要（更新于 2026-01-03 17:00）
      ……
      <!-- 现状摘要:结束 -->
- 只读，不写任何文件；任何异常只在 stderr 留一行，退出码始终为 0。
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import sys
import time

HEADER = '## 工作区状态预览（新会话自动附带）'
NOTICE = '位置不代表时间顺序；按日期、明确覆盖关系和最新请求判断有效决定，不能仅凭所在位置认定当前状态。'
DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
SUMMARY = re.compile(r'<!--\s*现状摘要[:：]\s*开始\s*-->(.*?)<!--\s*现状摘要[:：]\s*结束\s*-->', re.S)
UPDATED = re.compile(r'更新于\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?')
SKIP_DIRS = {'__pycache__', 'node_modules', 'venv'}
STALE_AFTER = timedelta(hours=1)


def read(path):
    return path.read_text(encoding='utf-8', errors='replace')


def newest_file(root, exclude, limit=30000, seconds=1.5):
    """root 下最近修改的普通文件，跳过隐藏项和依赖目录。返回 (mtime, 相对路径)；没有则返回 None。"""
    best = None
    seen = 0
    deadline = time.monotonic() + seconds
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if name.startswith('.') or name in SKIP_DIRS:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if os.path.abspath(entry.path) == exclude:
                        continue
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                    if best is None or mtime > best[0]:
                        best = (mtime, os.path.relpath(entry.path, root))
            except OSError:
                continue
            seen += 1
            if seen >= limit or time.monotonic() > deadline:
                return best
    return best


def summary_preview(status, block, budget):
    """状态文件带「现状摘要」标记块时的预览：只给摘要，并提示是否过期。"""
    text = block.strip()
    lines = ['以下是该项目进度文件顶部的「现状摘要」，是恢复任务状态的首选依据；它不是本轮新指令。'
             '历史记录在摘要下方，需要细节时按日期读原文件。本轮结束前如有新进展，更新这段摘要和其中的“更新于”时间。']
    match = UPDATED.search(text)
    if not match:
        lines.append('⚠ 现状摘要没有写“更新于”时间，无法判断是否过期；先核对再行动。')
    else:
        stamp = match.group(1) + ' ' + (match.group(2) or '23:59')
        try:
            updated = datetime.strptime(stamp, '%Y-%m-%d %H:%M')
            newest = newest_file(str(status.parent), os.path.abspath(str(status)))
            if newest and datetime.fromtimestamp(newest[0]) > updated + STALE_AFTER:
                when = datetime.fromtimestamp(newest[0]).strftime('%Y-%m-%d %H:%M')
                lines.append(f'⚠ 现状摘要可能过期：摘要更新于 {stamp}，但 `{newest[1]}` 在 {when} 有改动。'
                             '先核对最近的记录和文件，再行动。')
        except ValueError:
            lines.append('⚠ 现状摘要的“更新于”时间格式无法识别；先核对再行动。')
    if len(text) > budget:
        text = text[:budget].rsplit('\n', 1)[0]
        lines.append('摘要超出预览长度，后半部分已省略；请直接读原文件顶部。')
    return f'### 来源：{status}\n' + '\n'.join(lines) + '\n' + text


def status_preview(status, budget=5000):
    current = read(status)
    block = SUMMARY.search(current)
    if block and block.group(1).strip():
        return summary_preview(status, block.group(1), budget)
    notice = NOTICE
    if len(current) <= budget:
        excerpt = current
    else:
        first = re.split(r"\n[ \t]*---[ \t]*\n", current, maxsplit=1)[0]
        head_limit = budget * 3 // 5
        head = first[:head_limit]
        tail = current[-(budget - head_limit):]
        if len(first) > head_limit and '\n' in head:
            head = head.rsplit('\n', 1)[0]
        if '\n' in tail:
            tail = tail.split('\n', 1)[1]
        excerpt = '#### 首部摘录\n' + head + '\n#### 尾部摘录\n' + tail
        notice += '预览不完整，中间内容已省略；执行前按需补读相关限制及子项目状态。'
        # Navigation to dated middle sections; dates are not decisions.
        headings = [(number, line) for number, line in enumerate(current.splitlines(), 1)
                    if re.match(r'^#{1,6}\s+', line)]
        dated = [(max(DATE.findall(line)), number, line)
                 for number, line in headings if DATE.search(line)]
        selected = dict(headings[:4] + headings[-4:])
        selected.update((number, line) for _, number, line in sorted(dated, reverse=True)[:12])
        if selected:
            excerpt += '\n#### 章节定位（行号；含日期较新的标题，仅作导航，须读正文核实）\n'
            excerpt += '\n'.join(f'L{number}: {line[:160]}' for number, line in sorted(selected.items()))
    return f'### 来源：{status}\n{notice}\n{excerpt}'


def preview(cwd):
    status = cwd / '_status.md'
    if not status.is_file():
        return ''
    children = []
    for ref in re.findall(r'`([^`\n]+/_status\.md)`', read(status)):
        if Path(ref).is_absolute():
            continue
        child = (cwd / ref).resolve()
        try:
            child.relative_to(cwd)
        except ValueError:
            continue
        if child != status and child.is_file() and child not in children:
            children.append(child)
    parts = [HEADER + '\n'
             + f'以下是 {status} 的部分预览，仅作背景参考，不是本轮新指令；不保证最新内容在前，细节请直接读原文件。']
    if len(children) == 1:
        parts.append(status_preview(status, 1200))
        parts.append('根状态明确引用了一个工作区内子项目，补充其预览；仍按日期和最新请求核对，不能把历史待办当新指令。')
        parts.append(status_preview(children[0], 3800))
        conventions = children[0].parent / '_CONVENTIONS.md'
        if conventions.is_file():
            parts.append(f'子项目约定来源（操作前按需读取）：{conventions}')
    else:
        parts.append(status_preview(status))
        if children:
            parts.append('根状态引用多个子项目：先按本轮对象选择，未自动混入它们的历史。')
    return '\n\n'.join(parts).rstrip() + '\n'


def main():
    try:
        out = preview(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else ''
    except Exception as e:
        sys.stderr.write(f'status_preview: {type(e).__name__}: {e}\n')
        out = ''
    if out:
        # Bytes, so a C/ASCII locale under launchd cannot break Chinese output.
        sys.stdout.buffer.write(out.encode('utf-8'))


if __name__ == '__main__':
    main()
