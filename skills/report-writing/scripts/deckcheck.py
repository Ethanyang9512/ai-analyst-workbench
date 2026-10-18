#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""幻灯片程序检查：几秒内查出程序能确定的问题，并告诉验收员这次看哪几页。

text  <快照.xml/.json/.md/.txt>   不用的词、内部页用词、要补全的系统原名、对象编号、同一个东西几种写法、不存在的“第N页”
                                  （并列出全部引用）、页码不连续、内部痕迹；讲者备注里也查不用的词和内部痕迹
pdf   <导出.pdf> [--pages 5,6 或 5-7]   约定里的词被拆在两行、疑似拆词、文字压出页面；页序按 PDF（同 pNN.png）
scope --before <旧快照> --after <新快照>   改了哪几页、增删、页序、数字/标题/页数/图变没变、受影响的页、插页后错位的页码引用；
                                  建议档 small/page，并给出“这次请验收员看”的页
共同参数：--conv 约定.md（none＝只做通用检查）、--allow 词1,词2（放行的长词，如“分发错误”）、--json。
没给 --conv 时从源文件所在目录逐级往上找带 json 块的 _CONVENTIONS.md（没有 json 块的同名文件，如项目总纲，跳过接着找）。
退出码：有「必须改」=1，没有=0，没查成=2（读不了、不是幻灯片快照、0 张幻灯片、PDF 没有文字、页号超范围、约定页找不到或坏了）。
Python 用 $AAW_PY（装了 PyMuPDF 的解释器；pdf 子命令要 fitz，text/scope 只用标准库）。图里的字、颜色和表达仍要人看。
约定页 json 里的 codes 键是「对象名→编号」映射（门店、站点、渠道等，项目自己定），设了才查：正文写对象名时要求前面带编号。"""
import argparse
import collections
import difflib
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import trace_scan          # 内部痕迹沿用 trace_scan.py 的规则表（HARD=必须改，SOFT=建议核对）和它的放行办法
    TRACE_WARN = ''
except Exception as e:         # noqa: BLE001
    trace_scan, TRACE_WARN = None, f'内部痕迹没查：trace_scan.py 导入失败（{type(e).__name__}: {e}）'

MUST, CHECK = '必须改', '建议核对'
ZWSP = chr(0x200b)                                 # 零宽空格：飞书导出 PDF 时加在段尾
SP1 = '[ %s%s]' % (chr(0xa0), chr(0x3000))        # 一个空格（含不换行空格、全角空格）
HAN = re.compile('[%s-%s]' % (chr(0x4e00), chr(0x9fff)))
INTERNAL = ('会前追问清单', '只给用户看')           # 内部预演页的标记，正式稿里不能出现
FUNC = set('的了和与及或在是为按对从到把被等') | set('给由于都也就又再还才个')   # 换行两侧是这类字时不报疑似拆词
SOFT_BREAK = set('、，,；;/ ')                     # 在这些符号处换行不算把词拆开
COHESION = 0.3                                     # 疑似拆词：两字连着出现的次数 ÷ 两字里较少那个的出现次数，低于它不报
CONV_KEYS = {'banned', 'display_names', 'codes', 'terms', 'variants', 'allow'}
SHORT_SUFFIXES = ('店', '站', '仓', '中心')           # 对象名以这些字结尾时，去掉后缀的短写法（“1008 丙区”）也核编号
FENCE = re.compile(r'^(`{3,}|~{3,})[ \t]*json\b[^\n]*\n(.*?)^\1[ \t]*\r?$', re.M | re.S | re.I)
REF = re.compile(r'第\s*\d+\s*(?:(?:[、,，和及与或]|[—–\-~～至到])\s*第?\s*\d+\s*)*页')
RANGE = re.compile(r'[—–\-~～至到]')
NUM = re.compile(r'W\d{1,2}(?!\d)|(?<![A-Za-z0-9_.,])[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|pt)?'
                 r'|[一二两三四五六七八九十]+[成倍]|[一二三四五六七八九十]+分之[一二三四五六七八九十]+|一半')


def issue(level, kind, where, context, fix):
    return {'level': level, 'kind': kind, 'where': where, 'context': context, 'fix': fix}

def around(s, a, b, n=12):
    return ('…' if a > n else '') + s[max(0, a - n):b + n] + ('…' if b + n < len(s) else '')

def norm(s):
    return re.sub(r'\s+', ' ', s.replace(ZWSP, '')).strip()

def short(t, n=24):
    return t if len(t) <= n else t[:n] + '…'

def spans(s, words):
    return [m.span() for w in words if w for m in re.finditer(re.escape(w), s)]

def covered(sp, a, z):
    return any(x <= a and z <= y for x, y in sp)


# ---------- 约定 ----------
def read_conv(path):
    """取约定页里的 json：有“程序检查用”标题就取它下面第一段，没有就取第一段像约定的。
    返回 (约定, 提示)；文件里没有这样的 json 块返回 (None, '')（往上接着找）；json 坏了抛错（退出 2）。"""
    text = pathlib.Path(path).read_text(encoding='utf-8-sig')
    blocks = [(m.start(), m.group(2)) for m in FENCE.finditer(text)]
    head = re.search(r'^#.*程序检查用', text, re.M)
    picks = [b for b in blocks if b[0] > head.start()][:1] if head else blocks
    for _, body in picks:
        try:
            c = json.loads(body)
        except ValueError as e:
            raise ValueError(f'约定页 {path} 的 json 读不了：{e}')
        if isinstance(c, dict) and CONV_KEYS & set(c):
            c['banned'] = [b for b in (x if isinstance(x, dict) else {'word': str(x)} for x in c.get('banned', [])) if b.get('word')]
            c['codes'] = {k: [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in c.get('codes', {}).items()}
            c['allow'] = [str(w) for w in c.get('allow', []) if w]
            more = f'约定页里共有 {len(blocks)} 段 json，用的是' + ('“程序检查用”下面那段' if head else '第一段像约定的') if len(blocks) > 1 else ''
            return c, more
        if head:
            raise ValueError(f'约定页 {path} “程序检查用”下面的 json 里没有 {"、".join(sorted(CONV_KEYS))} 这些键')
    return None, ''

def find_conv(src):
    """从源文件所在目录逐级往上找带 json 块的约定页；没有 json 块的同名文件跳过。"""
    skipped = []
    for d in pathlib.Path(src).resolve().parents:
        f = next((d / n for n in ('_CONVENTIONS.md', '_conventions.md') if (d / n).is_file()), None)
        if f:
            c, more = read_conv(f)
            if c is not None:
                return str(f), c, more, skipped
            skipped.append(str(f))
    return None, None, '', skipped

def protected(conv):
    names = conv.get('display_names', {})
    ws = set(conv.get('terms', [])) | set(conv.get('codes', {})) | set(names) | set(names.values())
    ws |= {w for k, v in conv.get('variants', {}).items() for w in [k, *v]}
    return sorted((w for w in ws if len(w) > 1), key=len, reverse=True)


# ---------- 读源文件：每页 {idx, id, label, num, title, paras, notes, imgs, sig} ----------
def find_xml(obj):
    """lark-cli 存的 JSON 外壳（{"data":{"xml_presentation":{"content":…}}}、列表等）里找 <presentation …>。"""
    if isinstance(obj, str):
        return obj if re.match(r'\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*<presentation\b', obj, re.S) else None
    vals = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []
    return next(filter(None, map(find_xml, vals)), None)

def load_deck(path):
    raw = pathlib.Path(path).read_bytes()
    s = raw.decode('utf-16' if raw[:2] in (bytes([255, 254]), bytes([254, 255])) else 'utf-8-sig').strip()
    if not s:
        raise ValueError(f'{path} 是空文件')
    if '<presentation' not in s:
        if str(path).lower().endswith(('.xml', '.json')) or s[0] in '<{[':
            raise ValueError(f'{path} 不是幻灯片快照（里面没有 <presentation>），可能存成了报错页')
        return text_pages(s)
    if s.startswith('<'):
        return slides(s)
    for k in sorted(i for i in (s.find('{'), s.find('[')) if i >= 0):      # JSON 外壳；前面可能有一行提示（如“[notice] …”）
        try:
            xml = find_xml(json.JSONDecoder().raw_decode(s[k:])[0])
        except ValueError:
            continue
        if xml:
            return slides(xml)
    raise ValueError(f'{path} 里没找到幻灯片 XML')

def slides(xml):
    root = ET.fromstring(xml)
    for e in root.iter():                            # 去掉命名空间，后面直接按 slide/p/img 找
        e.tag = e.tag.rsplit('}', 1)[-1]
    height, pages = float(root.get('height') or 540), []
    for idx, sl in enumerate(root.iterfind('slide'), 1):
        boxes, imgs, sig = [], [], []
        for el in sl.iterfind('data/*'):
            sig += [(x.tag, sorted((k, v) for k, v in x.attrib.items() if k not in ('id', 'src'))) for x in el.iter()]
            imgs += [x.get('src') or x.get('id') or '' for x in el.iter('img')]   # 图片引用：换了图，引用就变
            paras = [p for p in (norm(''.join(x.itertext())) for x in el.iter('p')) if p]
            auto = any(f.get('type') == 'slidenum' for f in el.iter('field'))   # 自动页码：显示的是第几张，XML 里缓存的数常是旧的
            if paras or auto:
                boxes.append((float(el.get('topLeftY') or 0), float(el.get('topLeftX') or 0), paras, auto))
        nums = sorted((b for b in boxes if b[0] >= 0.75 * height and (b[3] or len(b[2]) == 1 and re.fullmatch(r'\d{1,3}', b[2][0]))),
                      key=lambda b: b[0])[-1:]        # 页码：页面下方四分之一里只有 1—3 位数字的框，取最靠下的
        body = sorted(b[:3] for b in boxes if not nums or b is not nums[0])
        note = sl.find('note')
        pages.append({'idx': idx, 'id': sl.get('id'), 'label': (idx if nums[0][3] else int(nums[0][2][0])) if nums else None,
                      'title': ' '.join(body[0][2]) if body else '', 'paras': [p for b in body for p in b[2]], 'imgs': imgs,
                      'notes': [p for p in (norm(''.join(x.itertext())) for x in (note.iter('p') if note is not None else [])) if p],
                      'sig': repr(sig)})
    if not pages:
        raise ValueError('快照里没有幻灯片（0 张）')
    labelled = any(p['label'] for p in pages)       # 有页码就按页码（自用页不编号）；全片都没有就按顺序
    return [dict(p, num=p['label'] if labelled else p['idx']) for p in pages]

def text_pages(s):
    """Markdown/纯文本：按“## 第 N 页｜标题”分页；没有这种标题就整篇算一段，不查页码范围。"""
    pages = []
    for line in s.splitlines():
        m = re.match(r'\s*#{1,6}\s*第\s*(\d+)\s*页\s*[｜|:：]?\s*(.*)', line)
        if m or not pages:
            num = int(m.group(1)) if m else None
            pages.append({'idx': len(pages) + 1, 'id': None, 'label': num, 'num': num, 'title': norm(m.group(2)) if m else '',
                          'paras': [], 'notes': [], 'imgs': [], 'sig': ''})
        text = norm(m.group(2)) if m else norm(line)
        if text:
            pages[-1]['paras'].append(text)
    return pages

def where(p):
    return f"第{p['num']}页" if p['num'] else f"第{p['idx']}张（无页码）" if p['id'] else '未分页部分'


# ---------- text：用词、系统原名、对象编号、几种写法、页码引用、内部痕迹 ----------
def explained(s, a, z, show):
    """原名是在说明里出现的：写成“原名→规范写法”，或放在“”「」里且同一句话里有规范写法。"""
    if re.match(r'\s*(?:→|->|=>|⇒)\s*' + re.escape(show), s[z:]):
        return True
    if a == 0 or z >= len(s) or (s[a - 1], s[z]) not in (('“', '”'), ('「', '」')):
        return False
    masked = s[:a] + '\0' * (z - a) + s[z:]          # 盖掉这处原名，免得规范写法是原名的一部分时自己算数
    start = max(masked.rfind(c, 0, a) for c in '。！？!?') + 1
    ends = [i for i in (masked.find(c, z) for c in '。！？!?') if i >= 0]
    return show in masked[start:min(ends) if ends else len(s)]

def quoted(s, a, z):
    return any(s.rfind(o, 0, a) > s.rfind(c, 0, a) and s.find(c, z) >= 0 for o, c in (('“', '”'), ('「', '」')))

def word_checks(deck, conv, allow):
    out, names = [], conv.get('display_names', {})
    for p in deck:
        for s, w, body in [(s, where(p), True) for s in p['paras']] + [(s, where(p) + '备注', False) for s in p['notes']]:
            ok = spans(s, allow)                         # 放行的长词（如“分发错误”“背包损坏”）里的不报
            for b in conv.get('banned', []):
                fix = f"把『{b['word']}』改成『{b['use']}』" if b.get('use') else f"删掉『{b['word']}』或换个说法"
                fix += f"（{b['why']}）" if b.get('why') else ''
                out += [issue(MUST, '不用的词', w, around(s, *m.span()), fix) for m in re.finditer(re.escape(b['word']), s)
                        if not covered(ok, *m.span())]
            out += [issue(MUST, '内部页用词', w, around(s, *m.span()), '这是内部页的标记：正式稿删掉这一页或这段')
                    for x in INTERNAL for m in re.finditer(x, s) if not covered(ok, *m.span())]
            for level, table in ((MUST, getattr(trace_scan, 'HARD', [])), (CHECK, getattr(trace_scan, 'SOFT', []))):
                out += [issue(level, '内部痕迹：' + kind, w, around(s, *m.span()), f"删掉『{m.group(0)}』或换成读者看得懂的说法")
                        for kind, pat in table for m in pat.finditer(s) if m.group(0) not in allow and not covered(ok, *m.span())]
            if not body:
                continue
            shown = spans(s, names.values())
            for orig, show in names.items():
                for m in re.finditer(re.escape(orig), s):
                    a, z = m.span()
                    if covered(shown, a, z) or covered(ok, a, z) or explained(s, a, z, show):
                        continue                     # “扣款未成功”里的“扣款未成”，或脚注里说明原名
                    if quoted(s, a, z):              # 在引号里：多半是客户原话或说明，降为建议核对
                        out.append(issue(CHECK, '系统原名', w, around(s, a, z), f"引号里是原话或说明就保留；否则改成『{show}』"))
                    else:
                        out.append(issue(MUST, '系统原名', w, around(s, a, z),
                                         f"把『{orig}』改成『{show}』（脚注要说明原名时写成：“{show}”对应系统标签“{orig}”）"))
            for name, codes in conv.get('codes', {}).items():
                for m in re.finditer(re.escape(name), s):
                    pre = re.search(r'(\d{4})' + SP1 + '?$', s[:m.start()])
                    if covered(ok, *m.span()) or pre and pre.group(1) in codes:
                        continue
                    if pre:
                        out.append(issue(CHECK, '编号和约定不一致', w, around(s, pre.start(), m.end()),
                                         f"约定里{name}是 {'、'.join(codes)}：核对编号；确是别的对象就补进约定"))
                    else:
                        out.append(issue(MUST, '对象名缺编号', w, around(s, *m.span()), '对象名前加编号：' + ' 或 '.join(f'{c} {name}' for c in codes)))
                suf = next((x for x in SHORT_SUFFIXES if name.endswith(x) and len(name) > len(x) + 1), '')
                short = name[:-len(suf)] if suf else ''
                for m in re.finditer(r'(\d{4})' + SP1 + '?' + re.escape(short) + '(?!' + re.escape(suf) + ')', s) if short else []:
                    if m.group(1) not in codes:              # 短写法“1008 丙区”：编号要对得上这个对象
                        out.append(issue(CHECK, '编号和约定不一致', w, around(s, *m.span()),
                                         f"约定里{name}是 {'、'.join(codes)}：核对编号；确是别的对象就补进约定"))
    for key, vals in conv.get('variants', {}).items():
        forms, seen = sorted({key, *vals}, key=len, reverse=True), collections.defaultdict(list)
        for p in deck:
            for s in p['paras']:
                for f in forms:                      # 长的先数，数过的地方盖掉，免得短的重复计
                    seen[f] += [where(p)] * s.count(f)
                    s = s.replace(f, '\0' * len(f))
        used = [(f, seen[f]) for f in forms if seen[f]]
        out += [issue(CHECK, '同一个东西几种写法', '全片', '；'.join(f"『{f}』{len(v)} 处（{'、'.join(dict.fromkeys(v))}）"
                                                                for f, v in used), '选一种写法，全片统一')] if len(used) > 1 else []
    return out

def ref_numbers(t):
    """“第4—11页”→([4, 11], {4..11})：前者是写出来的页号，后者是覆盖到的页。"""
    parts = re.split(r'(\d+)', t)
    nums = [int(x) for x in parts[1::2]]
    spans_ = [range(nums[i - 1], nums[i] + 1) for i in range(1, len(nums))
              if RANGE.search(parts[2 * i]) and 0 < nums[i] - nums[i - 1] < 200]
    return nums, set(nums).union(*spans_)

def ref_checks(deck):
    at, refs, out = {p['num']: p for p in deck if p['num']}, [], []
    for p in deck:
        for s in p['paras']:
            for m in REF.finditer(s):
                for n in ref_numbers(m.group(0))[0]:
                    t = at.get(n)
                    refs.append({'where': where(p), 'ref': m.group(0), 'page': n, 'title': t['title'] if t else None})
                    if at and not t:
                        out.append(issue(MUST, '页码引用不存在', where(p), around(s, *m.span()),
                                         f"全片是第{min(at)}—{max(at)}页，没有第{n}页：核对这处引用"))
    labels = [p for p in deck if p['label'] is not None and p['id']]
    out += [issue(MUST, '页码不连续', f"第{p['idx']}张", f"页码标的是 {p['label']}", f"按顺序应为 {labels[0]['label'] + i}：重新编页码")
            for i, p in enumerate(labels) if p['label'] != labels[0]['label'] + i]
    return refs, out


# ---------- pdf：拆词、出界 ----------
def pdf_check(path, only, conv, allow):
    import fitz
    doc = fitz.open(path)
    if not doc.page_count:
        raise ValueError(f'{path} 没有页')
    bad = sorted(k for k in only if not 1 <= k <= doc.page_count)
    if bad:
        raise ValueError(f"--pages 里的 {'、'.join(map(str, bad))} 超出 1—{doc.page_count}")
    flags = fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_MEDIABOX_CLIP      # 不裁掉页面外的字，才查得到出界
    # 飞书导出把各页放在同一张长画布上：只放开左右；上下按页面取（压着下边线的行照样取得到）
    pages = [(pg.rect, [[(''.join(sp['text'] for sp in ln['spans']), ln['bbox'], max(sp['size'] for sp in ln['spans']))
                         for ln in b.get('lines', []) if ln['spans']]
                        for b in pg.get_text('dict', flags=flags, clip=(-1e5, 0, 1e5, pg.rect.height))['blocks']])
             for pg in doc]
    corpus = '\n'.join(norm(t) for _, bl in pages for b in bl for t, _, _ in b)   # 按行拼，不跨行计数
    if not corpus.strip():
        raise ValueError(f'{path} 里一个文字行都没有（图片导出、文件坏了或截断）：拆词和出界都没查')
    chars, words, out = collections.Counter(corpus), protected(conv), []
    for i, (rect, blocks) in enumerate(pages, 1):
        if only and i not in only:
            continue
        lab = next((norm(t) for b in blocks for t, bb, _ in b if re.fullmatch(r'\d{1,3}', norm(t)) and bb[1] > 0.9 * rect.height), '')
        top = max([sz for b in blocks for _, _, sz in b] or [0])
        for b in blocks:
            for t, (x0, y0, x1, y1), _ in b:             # 压着本页下边线的行算本页的；压着上边线的是上一页的，不重复报
                if norm(t) and (x1 > rect.width + 1 or x0 < -1 or y0 < rect.height < y1 - 1 or (y0 < -1 and i == 1)):
                    out.append(issue(MUST, '文字超出页面', f'PDF第{i}页', short(norm(t), 40), '缩短文字或调整文本框，让文字留在页面里'))
            for (ta, ba, sz), (tb, bb, _) in zip(b, b[1:]):
                h, left, right = ba[3] - ba[1], norm(ta), norm(tb)
                if not (left and right) or ta.rstrip(' ').endswith(ZWSP) or bb[1] < ba[1] + 0.5 * h \
                        or bb[1] - ba[3] > h or bb[0] >= ba[2] or ba[0] >= bb[2]:
                    continue        # 段尾（飞书导出在段尾加零宽空格），或不是上下相邻的两行（表格里并排的格子）
                hit = next((x for x in words for k in range(1, len(x)) if left.endswith(x[:k]) and right.startswith(x[k:])
                            and x[k - 1] not in SOFT_BREAK and x[k] not in SOFT_BREAK), None)
                if any(x < len(left) < y for x, y in spans(left + right, allow)) \
                        or any((right.startswith(x) or left.endswith(x)) and x not in (hit or '') for x in words):
                    continue        # 换行在放行的长词里，或正好落在另一个约定词的开头或结尾（“续费／扣款未成功”；“扣款未成／功”仍算拆开）
                w = f'PDF第{i}页' + (f'（页码{lab}）' if lab else '') + ('标题' if sz >= 0.9 * top else '')
                ctx = f'…{left[-8:]}／{right[:8]}…'
                a, c = left[-1], right[0]
                if hit:                                  # 两个字的约定词（如“包损”）容易和别的词碰上，只报建议核对
                    out.append(issue(MUST if len(hit) >= 3 else CHECK, '约定里的词被拆在两行', w, ctx,
                                     f'让『{hit}』落在同一行（调文本框宽度、字号或断句）'))
                elif HAN.match(a) and HAN.match(c) and not FUNC & {a, c} and corpus.count(a + c) >= max(2, COHESION * min(chars[a], chars[c])):
                    best = max((x for x in (left[-k:] + right[:j] for k in (1, 2, 3) for j in (1, 2, 3) if k + j <= 4)
                                if all(HAN.match(ch) for ch in x) and corpus.count(x) >= 2), key=len)
                    out.append(issue(CHECK, '疑似拆词', w, ctx,
                                     f'『{best}』在别处连着出现 {corpus.count(best)} 次，像一个词被拆开：是的话让它落在同一行'))
    return out, doc.page_count


# ---------- scope：改了哪几页、影响哪几页 ----------
def numbers(paras, codes):
    """页里的数，按出现顺序。对象编号（约定里的，或后面是空格加汉字的 4 位数）、年份（后面紧跟年月日）不算。"""
    out = []
    for s in paras:
        s = REF.sub(' ', s)
        for m in NUM.finditer(s):
            t = m.group(0).lstrip('+-−')
            if not (re.fullmatch(r'\d{4}', t) and (t in codes or re.match(SP1 + HAN.pattern, s[m.end():]) or s[m.end():m.end() + 1] in ('年', '月', '日'))):
                out.append(t)
    return out

def scope(before, after, conv):
    if not all(p['id'] for p in before + after):
        raise ValueError('scope 要两个幻灯片 XML 快照')
    codes = {c for v in conv.get('codes', {}).values() for c in v}
    olds = {q['id']: q for q in before}
    match = {p['idx']: olds[p['id']] for p in after if p['id'] in olds}
    how, text = dict.fromkeys(match, 'id'), (lambda p: '\n'.join(p['paras']))
    for step in ('content', 'slot'):                  # id 变了：先按内容找（整页重建），再按同一位置找（删旧建新）
        for p in after:
            free = [q for q in before if all(q is not v for v in match.values())]
            if p['idx'] in match or not free:
                continue
            if step == 'content':
                q = max(free, key=lambda q: difflib.SequenceMatcher(None, text(p), text(q)).ratio())
                q = q if difflib.SequenceMatcher(None, text(p), text(q)).ratio() >= 0.6 else None
            else:
                q = next((q for q in free if q['idx'] == p['idx']), None)
            if q:
                match[p['idx']], how[p['idx']] = q, step
    taken = {id(v) for v in match.values()}
    removed = [q for q in before if id(q) not in taken]
    order = [match[p['idx']]['idx'] for p in after if p['idx'] in match]     # 配上的页在新稿里的先后（用旧序号表示）
    old_pairs = set(zip([None] + sorted(order), sorted(order)))
    moved = {b for a, b in zip([None] + order, order) if (a, b) not in old_pairs}   # 前一页换了：页被挪动，或挪动页的新邻居
    changed, renum, gone, flags = [], [], set(), set()
    for p in after:
        q = match.get(p['idx'])
        if q is None:
            changed.append((p, '新增'))
            gone |= set(numbers(p['paras'], codes))
            continue
        nb, na = numbers(q['paras'], codes), numbers(p['paras'], codes)
        if p['paras'] == q['paras'] and p['sig'] == q['sig'] and p['label'] != q['label'] and p['imgs'] and not set(p['imgs']) & set(q['imgs']):
            renum.append(where(p))                       # 插页后重编页码：整页重建、图片全部重新上传，文字和版式没变
            continue
        why = ['删旧建新'] if how[p['idx']] == 'slot' else []
        if p['paras'] != q['paras']:
            why.append('改了文字')
            if p['title'] != q['title']:
                why.append('页标题')
                flags.add('页标题')
            if nb != na:                                 # 数的个数、顺序变了都算改了数字
                cb, ca = collections.Counter(nb), collections.Counter(na)   # 找受影响的页：确切的数（带小数点、%、千分位或三位以上）按处数比，
                d = {t for t in (cb - ca) + (ca - cb) if re.search(r'[.,%]|pt$', t) or len(t) > 2 and t.isdigit()} | (set(nb) ^ set(na))
                gone |= d or ({x for pair in zip(nb, na) if pair[0] != pair[1] for x in pair} if cb == ca else set())   # 周号、两位数按有没有比；只是换位置就记换位的数
                why.append('数字')
                flags.add('数字')
        elif p['sig'] != q['sig']:
            why.append('改了版式')
        if p['imgs'] != q['imgs']:
            why.append('换了图（图里的数程序看不见）')
            flags.add('图')
        if q['idx'] in moved:
            why.append('页序变了')
            flags.add('页序')
        if why:
            changed.append((p, '、'.join(why)))
    gone |= {t for q in removed for t in numbers(q['paras'], codes)}
    size = lambda d: (max([p['num'] for p in d if p['num']] or [0]), len(d))
    flags |= {'页数'} if size(before) != size(after) else set()
    chg, chg_nums = {p['idx'] for p, _ in changed}, {p['num'] for p, _ in changed if p['num']}
    keys = {t for t in gone if not re.fullmatch(r'\d|W\d+', t)}            # 这次新出现或消失的数（单个数字 0—9、周号不拿来找）
    old_at, new_at = {q['num']: q for q in before if q['num']}, {p['num']: p for p in after if p['num']}
    new_of = {id(q): p for p in after for q in [match.get(p['idx'])] if q}
    affected, issues = collections.defaultdict(list), []
    for p in after:
        old_paras = set(match[p['idx']]['paras']) if p['idx'] in match else set()
        for s in (s for s in p['paras'] if s in old_paras):     # 这段话没改，但它引用的那页挪了位置
            for m in REF.finditer(s):
                for n in ref_numbers(m.group(0))[0]:
                    was = old_at.get(n)
                    if not was or (n in new_at and match.get(new_at[n]['idx']) is was):
                        continue
                    now = new_of.get(id(was))
                    fix = f"改成第{now['num']}页" if now and now['num'] else '那页已删掉或没有页码，改掉这处引用'
                    issues.append(issue(MUST, '插页后页码引用错位', where(p), around(s, *m.span()),
                                        f"原来的第{n}页『{short(was['title'])}』现在不在第{n}页：{fix}"))
                    if p['idx'] not in chg:
                        affected[p['idx']].append(f'第{n}页的引用错位')
        if p['idx'] in chg:
            continue
        hit = {n for s in p['paras'] for m in REF.finditer(s) for n in ref_numbers(m.group(0))[1]} & chg_nums
        if hit:
            affected[p['idx']].append('引用了改动的第' + '、'.join(map(str, sorted(hit))) + '页')
        same = sorted(keys & set(numbers(p['paras'], codes)))
        if same:
            affected[p['idx']].append('有改动处的数字 ' + '、'.join(same[:6]) + ('等' if len(same) > 6 else ''))
    by_idx = {p['idx']: p for p in after}
    return {'level': 'small' if len(changed) + len(removed) <= 3 and not flags else 'page', 'flags': sorted(flags),
            'changed': [{'page': where(p), 'title': p['title'], 'why': why} for p, why in changed],
            'removed': [{'page': '原' + where(q), 'title': q['title']} for q in removed], 'renumbered_only': renum,
            'affected': [{'page': where(by_idx[i]), 'title': by_idx[i]['title'], 'why': v} for i, v in sorted(affected.items())],
            'review': [where(by_idx[i]) for i in sorted(chg | set(affected))], 'review_slides': sorted(chg | set(affected)),
            'slides': [len(before), len(after)]}, issues


# ---------- 输出 ----------
def parse_pages(s):
    out = set()
    for part in filter(None, (x.strip() for x in (s or '').split(','))):
        lo, _, hi = re.sub(r'[—–~～]', '-', part).partition('-')
        out.update(range(int(lo), int(hi or lo) + 1))
    return out

def run(a):
    src = a.after if a.mode == 'scope' else a.src
    allow, warnings = [w.strip() for w in (a.allow or '').split(',') if w.strip()], []
    if (a.conv or '').lower() == 'none':
        conv_path, conv, note = None, {}, '约定：--conv none，只做通用检查'
    elif a.conv:
        conv, more = read_conv(a.conv)
        if conv is None:
            raise ValueError(f'{a.conv} 里没有程序检查用的 json 代码块')
        conv_path, note, warnings = a.conv, f'约定：{a.conv}', [more] if more else []
    else:
        conv_path, conv, more, skipped = find_conv(src)
        if conv is None:
            raise ValueError('项目还没有约定页：禁用词、系统原名、对象编号、同名写法四项没查；确认不需要就加 --conv none'
                             + (f'（往上找到的 {"、".join(skipped)} 里没有程序检查用的 json 块）' if skipped else ''))
        note, warnings = f'约定：{conv_path}', [more] if more else []
    allow += conv.get('allow', [])
    payload = {'mode': a.mode, 'source': src, 'conventions': conv_path, 'allow': allow}
    if a.mode == 'text':
        deck = load_deck(src)
        refs, issues = ref_checks(deck)
        warnings += [TRACE_WARN] if TRACE_WARN else []
        groups = collections.OrderedDict()
        for r in refs:
            groups.setdefault(r['where'], {}).setdefault(r['ref'], []).append(f"{r['page']}『{short(r['title'] or '（没有这一页）')}』")
        lines = [f'deckcheck text {os.path.basename(src)}（{len(deck)} 张）；{note}',
                 f'页码引用 {len(refs)} 处（请核对指的页对不对）：' if refs else '没有“第N页”引用']
        lines += [f'  {k}：' + '；'.join(f"{r}→" + '、'.join(v) for r, v in g.items()) for k, g in groups.items()]
        payload.update(slides=len(deck), page_refs=refs, warnings=warnings)
        return payload, word_checks(deck, conv, allow) + issues, lines
    if a.mode == 'pdf':
        only = parse_pages(a.pages)
        issues, n = pdf_check(src, only, conv, allow)
        payload.update(pages=n, checked=sorted(only) or list(range(1, n + 1)), warnings=warnings)
        return payload, issues, [
            f"deckcheck pdf {os.path.basename(src)}（共 {n} 页，查了{'第 ' + a.pages + ' 页' if only else '全部'}）；{note}",
            '说明：图里的字程序看不到；疑似拆词按“这两个字在别处常连着出现”推断，请看图确认；位置带“标题”的是页标题。']
    res, issues = scope(load_deck(a.before), load_deck(src), conv)
    payload.update(res, warnings=warnings)
    return payload, issues, [
        f"deckcheck scope {os.path.basename(a.before)} → {os.path.basename(src)}（{res['slides'][0]} 张 → {res['slides'][1]} 张）；{note}",
        f"建议档：{res['level']}（" + ('变了：' + '、'.join(res['flags']) if res['flags'] else '数字、页标题、页数、图都没变')
        + f"；改动 {len(res['changed'])} 页，删掉 {len(res['removed'])} 页）",
        '改了：' + ('；'.join(f"{c['page']}（{c['why']}）" for c in res['changed']) or '无'),
        '删掉：' + ('、'.join(f"{r['page']}『{short(r['title'])}』" for r in res['removed']) or '无'),
        '受影响的页：' + ('；'.join(f"{x['page']}（{'；'.join(x['why'])}）" for x in res['affected']) or '无'),
        '只是页码变了（整页重建、图片全部重新上传，文字和版式没变）：' + ('、'.join(res['renumbered_only']) or '无')
        + ('；这几页的图要是也重画了，请一并看' if res['renumbered_only'] else ''),
        '这次请验收员看：' + ('、'.join(res['review']) or '无')
        + (f"（PDF 页序 {','.join(map(str, res['review_slides']))}，可直接给 pdf --pages）" if res['review'] else '')]

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):              # 输出一律 UTF-8，免得终端编码不对时报错、把干净稿判成退出 1
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description='幻灯片程序检查（用法见文件开头）')
    ap.add_argument('mode', choices=('text', 'pdf', 'scope'))
    ap.add_argument('src', nargs='?')
    for opt in ('--before', '--after', '--conv', '--pages', '--allow'):
        ap.add_argument(opt)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if not (a.after and a.before if a.mode == 'scope' else a.src):
        ap.error('text/pdf 要给源文件；scope 要给 --before 和 --after')
    try:
        payload, issues, lines = run(a)
        must = sum(i['level'] == MUST for i in issues)
        payload.update(must_fix=must, to_check=len(issues) - must, issues=issues)
        if a.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
        else:
            print(lines[0])
            for x in payload.get('warnings', []):
                print(f'注意：{x}')
            print(f'必须改 {must} 处，建议核对 {len(issues) - must} 处' if issues else '没查出问题')
            for i in sorted(issues, key=lambda i: i['level'] != MUST):
                print(f"[{i['level']}] {i['where']}｜{i['kind']}：{i['context']} → {i['fix']}")
            print('\n'.join(lines[1:]))
    except Exception as e:                               # noqa: BLE001  任何意外都退出 2，不能让 1（=有必须改）或 0 被误读
        print(f'没查成：{type(e).__name__}: {e}')
        return 2
    return 1 if must else 0


if __name__ == '__main__':
    sys.exit(main())
