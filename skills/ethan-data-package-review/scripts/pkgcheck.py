#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取数助手回包体检：解包后、人工审核前先跑一遍，把能用程序查的几样先查掉。

用法：
    python3 pkgcheck.py <本轮包目录> [--prev <上一轮包目录>] [--report <回包说明.md/.txt>]
                        [--ignore <通配符> ...] [--empty-cache-severe <格数>] [--json]

查四样：
  1. 和上一轮比（要给 --prev）：每个文件的 MD5、行数（CSV/SQL/MD）、Excel 各工作表行数。
     说改了，其实没重跑，分两种：
       a. 说了"已修复/已修正/已改"之类，Excel 却和上一轮逐字节相同，而且除了 fix 旁路输出没有别的数据文件变化
          → 严重；但没给 --report、也没有新增修复类文件、包里 md/txt 的句子又没提到数据/口径/重跑/Excel/CSV 时，
          可能只是改了措辞，只报提醒；
       b. --report 里点名了某个文件"已改"，这个文件 MD5 没变 → 严重（从包里自动找到的点名只报提醒）。
     修改说明从哪来：给了 --report 就读它；没给就读本轮包里新增或改动过的 md/txt 里新出现的句子。
     本轮新增的、文件名带 fix/修复/修正 的文件，也算"说改了"。
  2. Excel 公式单元格的缓存值为空的格数 → 提醒。是否升为严重、阈值多少等用户拍板，
     拍板前默认只报提醒；要升严重用 --empty-cache-severe <格数>。
  3. 明文手机号、身份证号、邮箱、口令/密钥 → 严重；疑似人名称呼、座机、微信/QQ 号、门牌地址，
     以及单写 token=… 的（飞书文档编号也叫 token）→ 提醒。
     输出里一律打码，不回显原值。
  4. CSV 里认得出的日期列：首尾日期、缺了哪几天、是不是 7 的整数倍天。只报事实，不判对错
     （切周口径各项目不一样）。同一个文件最多出一条提醒，其余列放在时间窗清单里。

带 --prev 时，2-4 查出的问题如果所在文件和上一轮 MD5 相同，标"上一轮已有、文件未变"，不计入退出码。

本脚本不查：MD 和 Excel 里同名指标的数是否一致；表连接前后行数放大了几倍（扇出）。
这两项仍靠人工审核。本脚本也不替代人工审核。

审核方自己写进轮次目录的文件（审核报告_v*、复核记录_*）不算回包内容，不参与对比和扫描；
别的审核方文件用 --ignore 排除（可写多次，按相对路径或文件名匹配，目录名也行）。
读不了的文件（坏的 xlsx、软链接、包内压缩包、超大文件等）列在"跳过"里，不中断。

退出码：3 = 有"说改了没重跑"的严重；1 = 有别的新的严重；0 = 没有新的严重；2 = 参数错误。
只用 Python 标准库，不联网，不改包里的任何文件。
"""
import argparse
import csv
import datetime as dt
import fnmatch
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

# ---------------- 可调常量 ----------------
EMPTY_CACHE_SEVERE = None         # 公式缓存为空的格数达到多少算严重：待用户拍板，None = 一律只报提醒
MAX_SAMPLES = 3                   # 每类发现最多列几处位置
MAX_LISTED = 15                   # 缺的日期、文件清单最多列几个
MAX_TEXT_BYTES = 100 * 1024 * 1024  # 单个文本文件超过这个大小只算 MD5 和行数，不扫内容
DATE_COLUMN_MIN_SHARE = 0.9       # 一列非空值里能解析成日期的占比达到这个数，才当日期列
DATE_SAMPLE_ROWS = 200            # 先看前多少行来筛掉明显不是日期的列

SEVERE, REMIND = '严重', '提醒'
NO_RERUN = '说改了没重跑'
EXIT_OK, EXIT_SEVERE, EXIT_ARGS, EXIT_NO_RERUN = 0, 1, 2, 3
NOT_CHECKED = ['MD 和 Excel 里同名指标的数是否一致', '表连接前后行数放大了几倍（扇出）']

TEXT_EXTS = {'.md', '.txt', '.csv', '.tsv', '.sql', '.py', '.json', '.xml', '.yaml', '.yml', '.ini',
             '.cfg', '.conf', '.toml', '.env', '.log', '.sh', '.ipynb', '.html', '.htm', '.r',
             '.properties'}
LINE_COUNT_EXTS = {'.md', '.csv', '.tsv', '.sql'}
EXCEL_EXTS = {'.xlsx', '.xlsm'}
CSV_EXTS = {'.csv', '.tsv'}
CLAIM_SOURCE_EXTS = {'.md', '.txt'}
ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz'}
CODE_EXTS = {'.py', '.sql', '.sh', '.r'}
CONFIG_EXTS = {'.env', '.ini', '.cfg', '.conf', '.toml', '.yaml', '.yml', '.properties'}
PROSE_EXTS = {'.md', '.txt', '.log', '.html', '.htm'}
JUNK_DIRS = {'__pycache__', '.git', '__MACOSX', '.ipynb_checkpoints', '.idea', '.vscode'}
JUNK_FILES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
REVIEWER_FILE_RE = re.compile(r'^(审核报告_v\d+|复核记录_)')

# "说改了"的说法。宁可多认，不要漏。
CLAIM_RE = re.compile(
    r'已(?:经)?(?:修复|修正|修好|更正|订正|改正|修改|改|调整|更新|重跑|重算|重新|同步|处理|解决|补|替换|删除|优化|完成)'
    r'|修复了|修正了|修好了|改好了|改完了|本版修正|修正后|修复后|\bfixed\b|\bresolved\b', re.I)
# 没给 --report 时，包里 md/txt 的句子要提到这些，才算"数据层说改了"（否则可能只是改措辞）
DATA_CLAIM_RE = re.compile(r'重跑|重算|重新(?:跑|算|计算|生成|导出|取数|出数)|口径|数据|数值|数字|取数|单量|指标'
                           r'|excel|xlsx|csv|sql|工作表|sheet|明细|底表|公式|rerun|recomput|regenerat', re.I)
# fix 后面要跟分隔符、数字或 v+数字，免得把 fixed_cost、fixture 当成修复类文件
FIX_FILENAME_RE = re.compile(r'(?:^|[_\-\s.])fix(?=$|[_\-\s.\d]|v\d)|修复|修正|更正', re.I)

# ---- 严重：明文个人信息、口令 ----
# 号段只收个人手机号段；140-144 是物联网卡号段，常和 11 位商品编码撞上，不收
PHONE_RE = re.compile(r'(?<![0-9A-Za-z])(?<!\d\.)(?:\+?86[- ]?)?1(?:3\d|4[5-9]|5[0-35-9]|6[2567]|7[0-8]|8\d|9\d)'
                      r'[- ]?\d{4}[- ]?\d{4}(?![0-9A-Za-z])')
IDCARD_RE = re.compile(r'(?<![0-9A-Za-z])[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])'
                       r'(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9A-Za-z])')
EMAIL_RE = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
EMAIL_NOT_RE = re.compile(r'\.(?:png|jpe?g|gif|svg|webp|bmp|pdf|xlsx?|csv|md|py)$', re.I)
SECRET_KEYS = (r'(?:password|passwd|pwd|passphrase|secret(?:[_-]?key)?|client[_-]?secret|app[_-]?secret'
               r'|api[_-]?key|access[_-]?key(?:[_-]?id)?|access[_-]?token|auth[_-]?token'
               r'|refresh[_-]?token|token|private[_-]?key)')
SECRET_QUOTED_RE = re.compile(r'(?<![A-Za-z0-9])(?P<key>' + SECRET_KEYS + r''')["']?\s*[:=]\s*[rbuf]?'''
                              r'''(?P<q>["'])(?P<val>[^"'\n]{4,})(?P=q)''', re.I)
SECRET_BARE_RE = re.compile(r'(?<![A-Za-z0-9])(?P<key>' + SECRET_KEYS + r''')\s*[:=]\s*'''
                            r'''(?P<val>[^\s"'`,;，。；()\[\]{}<>]{4,})''', re.I)
CN_SECRET_RE = re.compile(r'(?P<key>口令|密码|密钥|秘钥|令牌)\s*(?:(?:是|为)\s*[:：=]?|[:：=])\s*(?P<val>[^\s，。；,;、]{4,})')
PATH_VALUE_RE = re.compile(r'^(?:/|~|\.{1,2}/)')  # pwd 的值像路径时是"当前目录"，不是口令
CONN_STR_RE = re.compile(r'\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@"\']+:(?P<val>[^\s@/"\']{3,})@[^\s/"\']+')
TOKEN_FORMAT_RE = re.compile(r'\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}'
                             r'|\bgithub_pat_[A-Za-z0-9_]{30,}|\bxox[abpr]-[A-Za-z0-9-]{10,}'
                             r'|-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')
PLACEHOLDER_RE = re.compile(r'^(?:[\u4e00-\u9fff]|\*|x{3,}|\.{3}|…|<|\$\{|\{\{|%\(|os\.|getenv|environ'
                            r'|config\[|settings\.|none$|null$|true$|false$|your|example|placeholder'
                            r'|changeme|dummy)', re.I)

# ---- 提醒：客户原话等自由文本里的疑似个人信息 ----
# 称呼只认常见姓氏开头的，免得把商品名里的"女士/先生"（如某某女士T恤）当人名
SURNAMES = ('王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁'
            '任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴'
            '莫孔向汤常温康施文牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪'
            '梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻祁蒲房滕屈饶解牟艾尤阳时穆农司卓古吉缪简'
            '车项连芦麦褚娄窦戚岑景党宫费卜冷晏席卫米柏宗瞿桂全佟应臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄'
            '丛仲虞敖巩明佘池查麻苑迟邝')
NAME_RE = re.compile('[' + SURNAMES + r'](?:先生|女士|小姐)|(?:我叫|我姓|本人姓)\s*[\u4e00-\u9fff]{1,3}'
                     r'|(?:联系人|收件人)[:：]\s*(?!姓名|电话|手机|地址|信息|名称|字段|脱敏)[\u4e00-\u9fff]{1,3}')
LANDLINE_RE = re.compile(r'(?<![0-9A-Za-z-])0\d{2,3}-\d{7,8}(?![0-9A-Za-z-])')
IM_RE = re.compile(r'(?:微信号?|vx|wx|qq号?)\s*[:：]\s*[A-Za-z0-9_-]{5,}|微信号\s*[A-Za-z0-9_-]{5,}', re.I)
ADDRESS_RE = re.compile(r'[\u4e00-\u9fff]{1,10}(?:路|街|大道|巷|弄|胡同)\d+号(?:\d+[栋幢座楼])?(?:\d+单元)?(?:\d+室)?')

# ---- 日期列 ----
DATE_RE = re.compile(r'^\s*(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:[ T]\d{1,2}:\d{2}.*)?\s*$')
COMPACT_DATE_RE = re.compile(r'^\s*(20\d{2})(\d{2})(\d{2})\s*$')
DATE_HEADER_RE = re.compile(r'date|\bdt\b|^ds$|day|日期|自然周|周一|week', re.I)

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
NS_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

SAME, RENAMED_SAME, CHANGED, NEW, REMOVED = '相同', '改名但内容相同', '已变', '新增', '删除'


# ---------------- 小工具 ----------------
def show(s):
    """把文件名里解不开的字节（GBK 乱码等）转成可打印的样子，避免打印时崩。"""
    return str(s).encode('utf-8', 'backslashreplace').decode('utf-8')


def ext_of(name):
    low = name.lower()
    if low == '.env' or low.startswith('.env.'):
        return '.env'
    return os.path.splitext(low)[1]


def weekday(d):
    return '周' + '一二三四五六日'[d.weekday()]


def short(s, n=60):
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n] + '…'


def listing(items, n=MAX_LISTED):
    items = list(items)
    head = '、'.join(items[:n])
    return head + (f' 等 {len(items)} 个' if len(items) > n else '')


def decode_bytes(data):
    """返回 (文本, 问题说明)。文本为 None 表示看起来是二进制。"""
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return data.decode('utf-16'), None
        except UnicodeDecodeError:
            pass
    if b'\x00' in data[:8192]:
        return None, '看起来是二进制文件，没扫内容'
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(enc), None
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', 'replace'), '编码认不出，按 UTF-8 替换读取，内容检查可能不全'


def mojibake_guess(name):
    """文件名是不是 GBK 被当成 cp437 解开的乱码；是就返回猜出来的原名。"""
    if name.isascii() or re.search(r'[\u4e00-\u9fff]', name):
        return None
    try:
        guess = name.encode('cp437').decode('gb18030')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return guess if re.search(r'[\u4e00-\u9fff]', guess) else None


def norm_component(s):
    """去掉路径里的版本号、日期，用来把 _v2/_v3、不同日期目录下的同一份文件配上对。"""
    s = s.lower()
    s = re.sub(r'\d{4}-\d{2}-\d{2}', '', s)
    s = re.sub(r'(?<!\d)20\d{6}(?!\d)', '', s)
    s = re.sub(r'(?:^|(?<=[_\-\s]))(?:v|r|round|第)\d+轮?(?=$|[_\-\s.])', '', s)
    s = re.sub(r'[_\-\s]+', '_', s)
    return re.sub(r'_(?=\.)', '', s).strip('_')


def id_checksum_ok(s):
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    total = sum(int(c) * w for c, w in zip(s[:17], weights))
    return '10X98765432'[total % 11] == s[17].upper()


# ---------------- 敏感信息扫描 ----------------
class Hits:
    """按（级别, 类别）计数，每类只留前几处位置。"""

    def __init__(self):
        self.data = {}

    def add(self, level, check, loc, shown):
        item = self.data.setdefault((level, check), [0, []])
        item[0] += 1
        if len(item[1]) < MAX_SAMPLES:
            item[1].append(f'{loc}：{shown}')


def _secret_shown(key, val):
    return f'{key}=****（{len(val)} 位，已隐去）'


def scan_string(s, loc, hits, kind):
    """kind: code / config / prose / data。PII 提醒只在 prose、data 里查；不带引号的 key=value 只在 config、prose 里查。"""
    if not s or len(s) < 4:
        return
    for m in PHONE_RE.finditer(s):
        d = re.sub(r'\D', '', m.group(0))[-11:]
        hits.add(SEVERE, '明文手机号', loc, d[:3] + '****' + d[-4:])
    for m in IDCARD_RE.finditer(s):
        if id_checksum_ok(m.group(0)):
            v = m.group(0)
            hits.add(SEVERE, '明文身份证号', loc, v[:3] + '*' * 13 + v[-2:])
    for m in EMAIL_RE.finditer(s):
        v = m.group(0)
        if not EMAIL_NOT_RE.search(v):
            local, domain = v.split('@', 1)
            hits.add(SEVERE, '明文邮箱', loc, local[:1] + '***@' + domain)
    secret_spans = []
    patterns = [SECRET_QUOTED_RE, CN_SECRET_RE] + ([SECRET_BARE_RE] if kind in ('config', 'prose') else [])
    for pat in patterns:
        for m in pat.finditer(s):
            val = m.group('val')
            if PLACEHOLDER_RE.match(val) or any(a <= m.start() < b for a, b in secret_spans):
                continue
            if m.group('key').lower() == 'pwd' and PATH_VALUE_RE.match(val):
                continue
            secret_spans.append(m.span())
            if m.group('key').lower() == 'token':  # 飞书接口里的 token 多半是文档编号，不一定是密钥
                hits.add(REMIND, '疑似口令（token）', loc, _secret_shown('token', val) + '，可能只是飞书文档 token')
            else:
                hits.add(SEVERE, '明文口令/密钥', loc, _secret_shown(m.group('key'), val))
    for m in CONN_STR_RE.finditer(s):
        if not PLACEHOLDER_RE.match(m.group('val')):
            hits.add(SEVERE, '明文口令/密钥', loc, '连接串里带口令（****，已隐去）')
    for m in TOKEN_FORMAT_RE.finditer(s):
        hits.add(SEVERE, '明文口令/密钥', loc, m.group(0)[:4] + '****（已隐去）')
    if kind not in ('prose', 'data'):
        return
    for m in NAME_RE.finditer(s):
        v = m.group(0)
        tail = re.search(r'先生|女士|小姐$', v)
        hits.add(REMIND, '疑似个人信息', loc, '称呼 *' + tail.group(0) if tail else '称呼 ' + v[:2] + '*')
    for m in LANDLINE_RE.finditer(s):
        v = m.group(0)
        hits.add(REMIND, '疑似个人信息', loc, '座机 ' + v[:4] + '****' + v[-2:])
    for m in IM_RE.finditer(s):
        hits.add(REMIND, '疑似个人信息', loc, '微信/QQ 号 ****')
    for m in ADDRESS_RE.finditer(s):
        hits.add(REMIND, '疑似个人信息', loc, '门牌地址 ' + m.group(0)[:4] + '…（已隐去）')


def redact(text):
    """引用 取数助手原句时先把手机号、身份证号、邮箱、口令抹掉，免得报告里回显。"""
    for pat in (PHONE_RE, IDCARD_RE, EMAIL_RE, CONN_STR_RE, TOKEN_FORMAT_RE):
        text = pat.sub('****', text)
    for pat in (SECRET_QUOTED_RE, SECRET_BARE_RE, CN_SECRET_RE):
        text = pat.sub(lambda m: m.group('key') + '=****', text)
    return text


def scan_notebook(text, hits):
    """.ipynb 先按 JSON 拆开再扫：代码格按代码、文字格按正文、文本输出按数据。不是合法 JSON 返回 False。"""
    try:
        nb = json.loads(text)
        cells = nb.get('cells') or [c for ws in nb.get('worksheets') or [] for c in ws.get('cells') or []]
    except (ValueError, AttributeError, TypeError):
        return False
    for n, cell in enumerate(cells, 1):
        if not isinstance(cell, dict):
            continue
        kind = {'code': 'code', 'markdown': 'prose'}.get(cell.get('cell_type'), 'data')
        parts = [(kind, cell.get('source', cell.get('input', '')))]
        for out in cell.get('outputs') or []:
            if isinstance(out, dict):
                parts.append(('data', out.get('text', '')))
                parts.extend(('data', v) for k, v in (out.get('data') or {}).items() if str(k).startswith('text/'))
        for k, src in parts:
            if isinstance(src, list):
                src = ''.join(str(x) for x in src)
            if isinstance(src, str):
                for i, line in enumerate(src.splitlines(), 1):
                    scan_string(line, f'第 {n} 格第 {i} 行', hits, k)
    return True


def scan_kind(ext):
    if ext in CODE_EXTS:
        return 'code'
    if ext in CONFIG_EXTS:
        return 'config'
    if ext in PROSE_EXTS:
        return 'prose'
    return 'data'


# ---------------- Excel ----------------
def _si_text(si):
    parts = []
    for child in si:
        if child.tag == NS + 't':
            parts.append(child.text or '')
        elif child.tag == NS + 'r':
            parts.extend(t.text or '' for t in child.iter(NS + 't'))
    return ''.join(parts)


def read_xlsx(path, hits=None):
    """返回 {工作表名: {'rows', 'formulas', 'empty_cache', 'empty_samples'}}。给了 hits 就顺带扫字符串和数字格。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = {}
        if 'xl/_rels/workbook.xml.rels' in names:
            for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels')):
                rels[r.get('Id')] = r.get('Target', '')
        sheets = []
        for s in wb.iter(NS + 'sheet'):
            target = rels.get(s.get(NS_R + 'id'), '')
            part = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
            sheets.append((s.get('name') or '?', part))
        string_hits = {}
        if hits is not None and 'xl/sharedStrings.xml' in names:
            with z.open('xl/sharedStrings.xml') as fh:
                idx = 0
                for _, el in ET.iterparse(fh):
                    if el.tag == NS + 'si':
                        local = Hits()
                        scan_string(_si_text(el), '', local, 'data')
                        if local.data:
                            string_hits[idx] = local
                        idx += 1
                        el.clear()
        referenced = set()
        result = {}
        for name, part in sheets:
            info = {'rows': 0, 'formulas': 0, 'empty_cache': 0, 'empty_samples': []}
            result[name] = info
            if part not in names:
                continue
            row_has_value = False
            with z.open(part) as fh:
                for _, el in ET.iterparse(fh):
                    if el.tag == NS + 'c':
                        f, v, t = el.find(NS + 'f'), el.find(NS + 'v'), el.get('t')
                        ref = el.get('r', '?')
                        vtext = (v.text or '') if v is not None else ''
                        if f is not None or vtext or el.find(NS + 'is') is not None:
                            row_has_value = True
                        if f is not None:
                            info['formulas'] += 1
                            if not vtext.strip():
                                info['empty_cache'] += 1
                                if len(info['empty_samples']) < MAX_SAMPLES:
                                    info['empty_samples'].append(ref)
                        if hits is not None:
                            loc = f'{name}!{ref}'
                            if t == 's' and vtext.strip().isdigit():
                                local = string_hits.get(int(vtext))
                                if local:
                                    referenced.add(int(vtext))
                                    for (level, check), (_, samples) in local.data.items():
                                        hits.add(level, check, loc, samples[0].split('：', 1)[1])
                            elif t == 'inlineStr':
                                scan_string(''.join(x.text or '' for x in el.iter(NS + 't')), loc, hits, 'data')
                            elif t in (None, 'n') and vtext:
                                scan_string(vtext, loc, hits, 'data')
                        el.clear()
                    elif el.tag == NS + 'row':
                        if row_has_value:
                            info['rows'] += 1
                        row_has_value = False
                        el.clear()
        for idx, local in string_hits.items():
            if idx not in referenced:
                for (level, check), (_, samples) in local.data.items():
                    hits.add(level, check, '共享字符串（没有单元格引用）', samples[0].split('：', 1)[1])
    return result


# ---------------- CSV 日期列 ----------------
def _parse_date(s, allow_compact):
    m = DATE_RE.match(s) or (COMPACT_DATE_RE.match(s) if allow_compact else None)
    if not m:
        return None
    try:
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d if 2000 <= d.year <= 2099 else None


def csv_date_columns(text, ext):
    """返回 [(列名, set(日期))]，只收能认成日期列的。"""
    first_line = text.split('\n', 1)[0]
    delim = '\t' if ext == '.tsv' or first_line.count('\t') > first_line.count(',') else ','
    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = next(reader, None)
    if not header:
        return []
    header = [h.strip().lstrip('\ufeff') for h in header]
    cols = {i: {'nonempty': 0, 'parsed': 0, 'dates': set(), 'compact': bool(DATE_HEADER_RE.search(h))}
            for i, h in enumerate(header)}
    for n, row in enumerate(reader, 1):
        for i in list(cols):
            if i >= len(row):
                continue
            v = row[i].strip()
            if not v:
                continue
            c = cols[i]
            c['nonempty'] += 1
            d = _parse_date(v, c['compact'])
            if d:
                c['parsed'] += 1
                c['dates'].add(d)
        if n == DATE_SAMPLE_ROWS:
            cols = {i: c for i, c in cols.items() if c['nonempty'] and c['parsed'] / c['nonempty'] >= DATE_COLUMN_MIN_SHARE}
            if not cols:
                return []
    return [(header[i], c['dates']) for i, c in cols.items()
            if c['dates'] and c['parsed'] / c['nonempty'] >= DATE_COLUMN_MIN_SHARE]


def describe_dates(dates):
    """把一列日期归成 日/周/月 粒度，算首尾、缺口、是不是 7 的整数倍天。"""
    ds = sorted(dates)
    first, last = ds[0], ds[-1]
    present = set(ds)
    if len(ds) == 1:  # 只有一个日期，多半是汇总值（如"最早单"），不算时间窗
        return {'granularity': '日', 'first': str(first), 'last': str(last), 'missing': [], 'span_days': 1,
                'multiple_of_7': False, 'text': f'只有 1 个日期：{first}（{weekday(first)}）', 'problem': False}
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    if all(d.day == 1 for d in ds):  # 先判月：全是 1 号（平年 2 月 1 日到 3 月 1 日正好 28 天，不能当成周）
        months, y, m = [], first.year, first.month
        while (y, m) <= (last.year, last.month):
            months.append(dt.date(y, m, 1))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        missing = [d for d in months if d not in present]
        text = f'按月：{first:%Y-%m}～{last:%Y-%m}，缺 {len(missing)} 个月'
        return {'granularity': '月', 'first': str(first), 'last': str(last), 'missing': [f'{d:%Y-%m}' for d in missing],
                'span_days': (last - first).days + 1, 'multiple_of_7': None, 'text': text, 'problem': bool(missing)}
    if min(gaps) == 7 and all(g % 7 == 0 for g in gaps):  # 再判周：最小间隔正好 7 天
        expected = [first + dt.timedelta(days=7 * k) for k in range((last - first).days // 7 + 1)]
        missing = [d for d in expected if d not in present]
        text = (f'按周：{len(ds)} 个周起点，{first}（{weekday(first)}）～{last}（{weekday(last)}），'
                f'覆盖到 {last + dt.timedelta(days=6)}，缺 {len(missing)} 周')
        return {'granularity': '周', 'first': str(first), 'last': str(last), 'missing': [str(d) for d in missing],
                'span_days': (last - first).days + 7, 'multiple_of_7': True, 'text': text,
                'problem': bool(missing)}
    span = (last - first).days + 1
    missing = [first + dt.timedelta(days=k) for k in range(span) if first + dt.timedelta(days=k) not in present]
    text = (f'{first}（{weekday(first)}）～{last}（{weekday(last)}），跨 {span} 天，'
            f'{"是" if span % 7 == 0 else "不是"} 7 的整数倍，缺 {len(missing)} 天')
    if missing:
        text += '：' + listing([str(d) for d in missing])
    return {'granularity': '日', 'first': str(first), 'last': str(last), 'missing': [str(d) for d in missing],
            'span_days': span, 'multiple_of_7': span % 7 == 0, 'text': text,
            'problem': bool(missing) or span % 7 != 0}


# ---------------- 盘点一个包 ----------------
class Entry:
    def __init__(self, root, rel):
        self.rel = rel
        self.path = os.path.join(root, *rel.split('/'))
        self.name = rel.rsplit('/', 1)[-1]
        self.ext = ext_of(self.name)
        self.md5 = None
        self.lines = None
        self.sheets = None  # Excel: {表名: 信息}
        self.text = None    # md/txt 的全文，找"说改了"的新句子用（两轮都留）

    def as_dict(self):
        d = {'file': show(self.rel), 'md5': self.md5, 'lines': self.lines}
        if self.sheets is not None:
            d['sheets'] = {show(k): v['rows'] for k, v in self.sheets.items()}
        return d


def ignored(rel, patterns):
    """--ignore 的通配符按相对路径或最后一级名字匹配，目录也一样。"""
    name = rel.rsplit('/', 1)[-1]
    return any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(name, p) for p in patterns)


def walk_files(root, skipped, ignore=()):
    patterns = [p.strip().rstrip('/') for p in ignore if p.strip().rstrip('/')]
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in JUNK_DIRS)
        keep = []
        for d in dirnames:
            rel = os.path.relpath(os.path.join(dirpath, d), root).replace(os.sep, '/')
            if ignored(rel, patterns):
                skipped.append({'file': show(rel) + '/', 'reason': '按 --ignore 排除（不算回包内容）'})
            elif os.path.islink(os.path.join(dirpath, d)):  # os.walk 不进软链接目录，这里如实记一笔
                skipped.append({'file': show(rel) + '/', 'reason': '软链接目录，没跟进去读'})
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            if fn in JUNK_FILES or fn.startswith('._'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            if REVIEWER_FILE_RE.match(fn):
                skipped.append({'file': show(rel), 'reason': '审核方自己写的文件，不算回包内容'})
                continue
            if ignored(rel, patterns):
                skipped.append({'file': show(rel), 'reason': '按 --ignore 排除（不算回包内容）'})
                continue
            if os.path.islink(full):
                skipped.append({'file': show(rel), 'reason': '软链接，没跟进去读'})
                continue
            rels.append(rel)
    return rels


def inventory(root, deep, findings=None, skipped=None, windows=None, ignore=(), empty_severe=EMPTY_CACHE_SEVERE):
    """盘点包里每个文件：MD5、行数、Excel 各表行数。deep=True 时顺带做敏感信息、公式缓存、日期列、文件名检查。"""
    skipped = skipped if skipped is not None else []
    entries = []
    for rel in walk_files(root, skipped, ignore):
        e = Entry(root, rel)
        try:
            _inspect(e, deep, findings, skipped, windows, empty_severe)
        except Exception as exc:  # 现实里的包什么样都有：读不了就跳过，不中断整个体检
            skipped.append({'file': show(rel), 'reason': f'读取出错（{type(exc).__name__}: {short(exc, 80)}）'})
        if e.md5:
            entries.append(e)
    return entries


def _inspect(e, deep, findings, skipped, windows, empty_severe):
    size = os.path.getsize(e.path)
    if deep:
        guess = mojibake_guess(e.name)
        if guess or '\ufffd' in e.name or show(e.name) != e.name:
            findings.append({'level': REMIND, 'check': '文件名乱码', 'file': show(e.rel),
                             'message': '文件名疑似 GBK 乱码' + (f'，原名可能是「{guess}」' if guess else '')
                                        + '。建议用 scripts/extract_package.py 重新解包'})
    small_text = e.ext in TEXT_EXTS and size <= MAX_TEXT_BYTES
    if small_text:
        with open(e.path, 'rb') as fh:
            data = fh.read()
        e.md5 = hashlib.md5(data).hexdigest()
    else:
        h = hashlib.md5()
        newlines, last = 0, b''
        with open(e.path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
                newlines += chunk.count(b'\n')
                last = chunk[-1:]
        e.md5 = h.hexdigest()
        if e.ext in LINE_COUNT_EXTS:
            e.lines = newlines + (1 if last and last != b'\n' else 0)
        if deep and e.ext in TEXT_EXTS:
            skipped.append({'file': show(e.rel), 'reason': f'超过 {MAX_TEXT_BYTES // 1024 // 1024}MB，只算了 MD5 和行数，没扫内容'})
    if small_text:
        text, problem = decode_bytes(data)
        if text is None:
            if deep:
                skipped.append({'file': show(e.rel), 'reason': problem})
            return
        if e.ext in LINE_COUNT_EXTS:
            e.lines = len(text.splitlines())
        if e.ext in CLAIM_SOURCE_EXTS:
            e.text = text
        if deep:
            if problem:
                skipped.append({'file': show(e.rel), 'reason': problem})
            hits = Hits()
            if not (e.ext == '.ipynb' and scan_notebook(text, hits)):
                kind = 'code' if e.ext == '.ipynb' else scan_kind(e.ext)
                if e.ext == '.ipynb':  # 坏掉的 notebook：把 JSON 转义的 \" 还原，带引号的口令写法才认得出
                    text = text.replace('\\"', '"')
                for i, line in enumerate(text.splitlines(), 1):
                    scan_string(line, f'第 {i} 行', hits, kind)
            _hits_to_findings(hits, e.rel, findings)
            if e.ext in CSV_EXTS:
                for col, dates in csv_date_columns(text, e.ext):
                    windows.append({'file': show(e.rel), 'column': show(col), **describe_dates(dates)})
    elif e.ext in EXCEL_EXTS:
        hits = Hits() if deep else None
        try:
            e.sheets = read_xlsx(e.path, hits)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            if deep:
                skipped.append({'file': show(e.rel), 'reason': f'Excel 打不开（可能加密或损坏：{type(exc).__name__}），只算了 MD5'})
            return
        if deep:
            _hits_to_findings(hits, e.rel, findings)
            empty = sum(s['empty_cache'] for s in e.sheets.values())
            if empty:
                total = sum(s['formulas'] for s in e.sheets.values())
                where = '；'.join(f'{show(n)} {s["empty_cache"]} 格（如 {"、".join(s["empty_samples"])}）'
                                 for n, s in e.sheets.items() if s['empty_cache'])
                rule = (f'达到 {empty_severe} 格算严重' if empty_severe
                        else '要不要升严重待用户拍板，现在只报提醒')
                findings.append({
                    'level': SEVERE if empty_severe and empty >= empty_severe else REMIND, 'check': '公式缓存为空',
                    'file': show(e.rel),
                    'message': (f'{total} 个公式格里有 {empty} 格没有缓存值（{rule}）：{where}。'
                                '用 Python 读或在不重算的预览里看，这些格是空的，核数核不了；'
                                '要核数可以请 取数助手交付前用 Excel 或 LibreOffice 打开重算后再存（公式照留）')})
    elif deep and e.ext == '.xls':
        skipped.append({'file': show(e.rel), 'reason': '旧版 .xls 不解析，只算了 MD5'})
    elif deep and e.ext in ARCHIVE_EXTS:
        skipped.append({'file': show(e.rel), 'reason': '包里还有压缩包，没解开检查；要查请先解到新目录再跑'})


def _hits_to_findings(hits, rel, findings):
    for (level, check), (count, samples) in sorted(hits.data.items()):
        findings.append({'level': level, 'check': check, 'file': show(rel),
                         'message': f'{count} 处，例：' + '；'.join(samples)})


# ---------------- 和上一轮比 ----------------
def pair_files(prev_entries, cur_entries):
    pairs = []
    prev_by_rel = {e.rel: e for e in prev_entries}
    used, left_cur = set(), []
    for e in cur_entries:
        p = prev_by_rel.get(e.rel)
        if p:
            pairs.append([p, e])
            used.add(p.rel)
        else:
            left_cur.append(e)
    key = lambda e: '/'.join(norm_component(c) for c in e.rel.split('/'))  # noqa: E731
    left_prev = [p for p in prev_entries if p.rel not in used]
    pk, ck = {}, {}
    for p in left_prev:
        pk.setdefault(key(p), []).append(p)
    for e in left_cur:
        ck.setdefault(key(e), []).append(e)
    still_cur = []
    for e in left_cur:
        k = key(e)
        if len(ck[k]) == 1 and len(pk.get(k, [])) == 1 and pk[k][0].rel not in used:
            pairs.append([pk[k][0], e])
            used.add(pk[k][0].rel)
        else:
            still_cur.append(e)
    by_md5 = {}
    for p in prev_entries:
        if p.rel not in used:
            by_md5.setdefault(p.md5, []).append(p)
    for e in still_cur:
        cand = [p for p in by_md5.get(e.md5, []) if p.rel not in used]
        if cand:
            pairs.append([cand[0], e])
            used.add(cand[0].rel)
        else:
            pairs.append([None, e])
    pairs.extend([p, None] for p in prev_entries if p.rel not in used)
    out = []
    for p, c in pairs:
        if p is None:
            status = NEW
        elif c is None:
            status = REMOVED
        elif p.md5 == c.md5:
            status = SAME if p.rel == c.rel else RENAMED_SAME
        else:
            status = CHANGED
        out.append({'status': status, 'prev': p, 'cur': c})
    return out


def collect_claims(pairs, report_path):
    """返回 (说改了的句子 [(来源, 行号, 原句)], 本轮新增的修复类文件 [相对路径])。"""
    claims = []
    if report_path:
        with open(report_path, 'rb') as fh:
            text, _ = decode_bytes(fh.read())
        for i, line in enumerate((text or '').splitlines(), 1):
            if CLAIM_RE.search(line):
                claims.append((show(os.path.basename(report_path)), i, redact(line.strip())))
    else:
        for pr in pairs:
            c, p = pr['cur'], pr['prev']
            if c is None or c.text is None or pr['status'] in (SAME, RENAMED_SAME):
                continue
            old = set(x.strip() for x in p.text.splitlines()) if p is not None and p.text else set()
            for i, line in enumerate(c.text.splitlines(), 1):
                if CLAIM_RE.search(line) and line.strip() not in old:
                    claims.append((show(c.rel), i, redact(line.strip())))
    fix_files = [show(pr['cur'].rel) for pr in pairs
                 if pr['status'] == NEW and FIX_FILENAME_RE.search(pr['cur'].name)]
    return claims, fix_files


def _mentions(low, token):
    """按词边界找：前后不能紧挨着英文字母、数字、下划线（中文前后不限）。"""
    return re.search(r'(?<![a-z0-9_])' + re.escape(token) + r'(?![a-z0-9_])', low) is not None


def referenced(line, pairs):
    """修改说明这一句点名了哪些文件。整文件名（带后缀）出现就算；只出现词干的，
    词干要至少 6 个字符或含中文、数字，免得 data、test、main 这类通用词也算点名。"""
    low = line.lower()
    out = []
    for pr in pairs:
        c = pr['cur']
        if c is None:
            continue
        base = c.name.lower()
        stem = os.path.splitext(base)[0]
        stems = {t for t in (stem, norm_component(stem).strip('_- '))
                 if len(t) >= 4 and not t.isdigit() and (len(t) >= 6 or re.search(r'[一-鿿\d]', t))}
        if _mentions(low, base) or any(_mentions(low, t) for t in stems):
            out.append(pr)
    return out


def compare(pairs, report_path, findings):
    claims, fix_files = collect_claims(pairs, report_path)
    has_claims = bool(claims or fix_files)
    # 证据够不够硬：有 --report（取数助手本轮回话）、有新增修复类文件、或包里的句子提到了数据层，才判严重；
    # 只有包里 md/txt 一句"已调整"之类的话，可能只是改措辞，降为提醒，免得变成错误的指控
    data_claims = claims if report_path else [c for c in claims if DATA_CLAIM_RE.search(c[2])]
    strong = bool(fix_files or data_claims)
    flagged = set()

    # 1) 修改说明点名了某个文件，这个文件却没变。
    #    说明来自 --report（取数助手本轮回话）→ 严重；来自包里自动找的 md/txt → 提醒，
    #    因为累积写的日志常复述以前轮次的修改。自动找到的点名 Excel 交给下面第 2 条判。
    per_file = {}
    for src, ln, line in claims:
        for pr in referenced(line, pairs):
            if pr['status'] in (SAME, RENAMED_SAME) and (report_path or pr['cur'].ext not in EXCEL_EXTS):
                per_file.setdefault(pr['cur'].rel, (pr, []))[1].append(f'{src} 第 {ln} 行「{short(line)}」')
    for rel, (pr, where) in per_file.items():
        if report_path:
            flagged.add(rel)
        findings.append({'level': SEVERE if report_path else REMIND, 'check': NO_RERUN, 'file': show(rel),
                         'message': (f'修改说明点名了这个文件（{"；".join(where[:MAX_SAMPLES])}），'
                                     f'但它和上一轮 MD5 相同（{pr["cur"].md5[:8]}…'
                                     + (f'，上一轮叫 {show(pr["prev"].rel)}' if pr['status'] == RENAMED_SAME else '')
                                     + '）'
                                     + ('' if report_path else '。这句是从包里的 md/txt 自动找的，可能在复述以前轮次的修改；'
                                        '把 取数助手本轮回话存成 txt 用 --report 传入可确认'))})

    # 2) 说改了，数据层却没动：Excel 一个字节没变，而且除了 fix 旁路输出，没有任何数据文件变化或新增
    evidence = []
    if claims:
        shown_claims = data_claims or claims
        evidence.append(f'修改说明里有 {len(claims)} 处"已修复"类说法（例：'
                        + '；'.join(f'{s} 第 {n} 行「{short(t, 40)}」' for s, n, t in shown_claims[:2]) + '）')
    if fix_files:
        evidence.append(f'本轮新增了 {len(fix_files)} 个修复类文件（例：{listing(fix_files, 3)}）')
    weak_note = ('' if strong else '。这些说法只出现在包里的 md/txt，没提到数据、口径、重跑、Excel、CSV，'
                 '也没有新增修复类文件，可能只是改了措辞，先只报提醒；取数助手回话里如果说改过数，存成 txt 用 --report 再跑一遍')
    data = [pr for pr in pairs if pr['cur'] is not None and pr['cur'].ext in EXCEL_EXTS | CSV_EXTS]
    moved = [pr for pr in data if pr['status'] in (CHANGED, NEW) and not FIX_FILENAME_RE.search(pr['cur'].name)]
    x_same = [pr for pr in data if pr['cur'].ext in EXCEL_EXTS and pr['status'] in (SAME, RENAMED_SAME)]
    md_changed = any(pr['cur'] is not None and pr['cur'].ext == '.md' and pr['status'] in (CHANGED, NEW) for pr in pairs)
    if has_claims and data and not moved:
        for pr in x_same:
            if pr['cur'].rel in flagged:
                continue
            findings.append({'level': SEVERE if strong else REMIND, 'check': NO_RERUN, 'file': show(pr['cur'].rel),
                             'message': ('；'.join(evidence) + f'；但这份 Excel 和上一轮逐字节相同（MD5 {pr["cur"].md5[:8]}…），'
                                         '除了 fix 旁路输出也没有别的数据文件变化。修复可能只停在 MD 层、没有重跑数据，请核 Excel 的关键值'
                                         + weak_note)})
        if not x_same:
            findings.append({'level': SEVERE if strong else REMIND, 'check': NO_RERUN, 'file': '',
                             'message': '；'.join(evidence) + f'；但包里 {len(data)} 个数据文件和上一轮全部相同，'
                                                              '除了 fix 旁路输出也没有新增数据文件' + weak_note})
    elif has_claims and x_same:
        findings.append({'level': REMIND, 'check': '部分 Excel 没变', 'file': '',
                         'message': (f'本轮说改了，也有别的数据文件变了或新增（例：{listing([show(pr["cur"].rel) for pr in moved], 3)}），'
                                     '但这几份 Excel 和上一轮完全相同：' + listing(show(pr['cur'].rel) for pr in x_same)
                                     + '。确认它们本来就不该变（比如依赖的底表、以前日期的产物）')})
    elif not has_claims and x_same and not moved and md_changed:
        findings.append({'level': REMIND, 'check': 'MD 改了 Excel 没变', 'file': '',
                         'message': ('没找到"已修复"类说法，但本轮 MD 改了，Excel 和上一轮完全相同：'
                                     + listing(show(pr['cur'].rel) for pr in x_same)
                                     + '。如果 取数助手在回话里说改过数，把回话存成 txt 用 --report 再跑一遍')})

    # 4) 上一轮有、这一轮没了的文件和工作表
    removed = [show(pr['prev'].rel) for pr in pairs if pr['status'] == REMOVED]
    if removed:
        findings.append({'level': REMIND, 'check': '文件删除', 'file': '',
                         'message': f'上一轮有、这一轮没有 {len(removed)} 个文件：{listing(removed)}。确认是有意删掉，不是把有问题的部分删了没修'})
    for pr in data:
        p = pr['prev']
        if p is not None and p.sheets is not None and pr['cur'].sheets is not None:
            gone = [show(n) for n in p.sheets if n not in pr['cur'].sheets]
            if gone:
                findings.append({'level': REMIND, 'check': '工作表删除', 'file': show(pr['cur'].rel),
                                 'message': f'上一轮有、这一轮没有的工作表：{listing(gone)}'})
    return {'claims': [{'source': s, 'line': n, 'text': short(t, 120)} for s, n, t in claims],
            'fix_files': fix_files}


# ---------------- 主流程 ----------------
def run_check(cur, prev=None, report=None, ignore=(), empty_severe=EMPTY_CACHE_SEVERE):
    findings, skipped, windows = [], [], []
    cur_entries = inventory(cur, True, findings, skipped, windows, ignore, empty_severe)
    result = {'package': show(os.path.abspath(cur)), 'prev': show(os.path.abspath(prev)) if prev else None,
              'report': show(os.path.abspath(report)) if report else None,
              'ignore': list(ignore), 'empty_cache_severe': empty_severe,
              'findings': findings, 'skipped': skipped, 'files': [], 'time_windows': [],
              'claims': [], 'fix_files': [], 'not_checked': NOT_CHECKED}
    groups, members = {}, {}
    for w in windows:  # 时间窗完全一样的列归成一组
        k = (w['granularity'], w['first'], w['last'], tuple(w['missing']))
        groups.setdefault(k, {k2: w[k2] for k2 in ('granularity', 'first', 'last', 'missing', 'span_days',
                                                     'multiple_of_7', 'text', 'problem')} | {'columns': []})
        groups[k]['columns'].append(f'{w["file"]}[{w["column"]}]')
        members.setdefault(k, []).append((w['file'], f'{w["file"]}[{w["column"]}]'))
    result['time_windows'] = list(groups.values())
    problem_cols = {}
    for w in windows:
        if w['problem']:
            problem_cols[w['file']] = problem_cols.get(w['file'], 0) + 1
    reported = set()  # 一个文件只进一条时间窗提醒，其余列只列在时间窗清单里
    for k, g in groups.items():
        files = [f for f in dict.fromkeys(f for f, _ in members[k]) if f not in reported]
        if not g['problem'] or not files:
            continue
        reported.update(files)
        cols = [c for f, c in members[k] if f in files]
        extra = sum(problem_cols[f] for f in files) - len(cols)
        findings.append({'level': REMIND, 'check': '时间窗', 'file': files[0], 'files': files,
                         'message': g['text'] + f'。涉及 {len(files)} 个文件 {len(cols)} 列：{listing(cols, 5)}'
                                    + (f'；这些文件另有 {extra} 列也有缺口或不是整周，见时间窗清单' if extra else '')
                                    + '。只报事实，对不对按本项目的切周口径判断；一行一个事件的明细表日期本来就可能不连续'})
    if prev:
        pairs = pair_files(inventory(prev, False, ignore=ignore), cur_entries)
        unchanged = {show(pr['cur'].rel) for pr in pairs if pr['status'] in (SAME, RENAMED_SAME)}
        for f in findings:  # 到这里为止都是本轮文件自身的问题；所在文件和上一轮逐字节相同的，标出来
            if f['file'] and all(x in unchanged for x in f.get('files', [f['file']])):
                f['carried'] = True
        cmp = compare(pairs, report, findings)
        result.update(cmp)
        for pr in pairs:
            p, c = pr['prev'], pr['cur']
            row = {'status': pr['status'], 'file': show((c or p).rel)}
            if p is not None and c is not None and p.rel != c.rel:
                row['prev_file'] = show(p.rel)
            row['md5'] = [p.md5 if p else None, c.md5 if c else None]
            row['lines'] = [p.lines if p else None, c.lines if c else None]
            if (p and p.sheets is not None) or (c and c.sheets is not None):
                row['sheets'] = [{show(k): v['rows'] for k, v in p.sheets.items()} if p and p.sheets else None,
                                 {show(k): v['rows'] for k, v in c.sheets.items()} if c and c.sheets else None]
            result['files'].append(row)
    else:
        result['files'] = [dict(e.as_dict(), status='本轮') for e in cur_entries]
    order = {SEVERE: 0, REMIND: 1}
    findings.sort(key=lambda f: (order[f['level']], bool(f.get('carried'))))
    result['exit_code'] = exit_code_of(findings)
    return result


def exit_code_of(findings):
    new_severe = [f for f in findings if f['level'] == SEVERE and not f.get('carried')]
    if any(f['check'] == NO_RERUN for f in new_severe):
        return EXIT_NO_RERUN
    return EXIT_SEVERE if new_severe else EXIT_OK


def _fmt_pair_row(r):
    md5 = r['md5']
    parts = [f'  [{r["status"]}] {r["file"]}']
    if r.get('prev_file'):
        parts.append(f'（上一轮：{r["prev_file"]}）')
    parts.append(f'  MD5 {(md5[0] or "—")[:8]}→{(md5[1] or "—")[:8]}')
    if r['lines'][0] is not None or r['lines'][1] is not None:
        a, b = r['lines']
        parts.append(f'  行数 {a if a is not None else "—"}→{b if b is not None else "—"}')
    if r.get('sheets'):
        a, b = (x or {} for x in r['sheets'])
        names = list(dict.fromkeys(list(a) + list(b)))
        parts.append('  各表行数 ' + '；'.join(f'{n} {a.get(n, "—")}→{b.get(n, "—")}' for n in names))
    return ''.join(parts)


def format_text(res):
    sev = [f for f in res['findings'] if f['level'] == SEVERE and not f.get('carried')]
    old_sev = [f for f in res['findings'] if f['level'] == SEVERE and f.get('carried')]
    rem = [f for f in res['findings'] if f['level'] == REMIND]
    no_rerun = sum(1 for f in sev if f['check'] == NO_RERUN)
    out = [f'取数助手回包体检：{res["package"]}',
           f'上一轮：{res["prev"] or "未提供（不做和上一轮的对比）"}']
    if res['prev']:
        src = res['report'] or '没给 --report，读的是本轮包里新增或改动过的 md/txt 里新出现的句子'
        out.append(f'修改说明：{src}；找到"已修复"类说法 {len(res["claims"])} 处，新增修复类文件 {len(res["fix_files"])} 个')
    out.append(f'结论：严重 {len(sev)} 条（其中"说改了没重跑" {no_rerun} 条）'
               + (f'，上一轮已有、文件未变的严重 {len(old_sev)} 条' if old_sev else '')
               + f'，提醒 {len(rem)} 条，跳过 {len(res["skipped"])} 个文件；退出码 {res["exit_code"]}')
    for title, items in (('严重', sev), ('严重 · 上一轮已有、文件未变（不计入退出码）', old_sev), ('提醒', rem)):
        if not items and title.startswith('严重 · '):
            continue
        out.append(f'\n【{title}】' + ('' if items else '无'))
        for i, f in enumerate(items, 1):
            where = f'{f["file"]}：' if f['file'] else ''
            tag = '（上一轮已有、文件未变）' if f.get('carried') and f['level'] == REMIND else ''
            out.append(f'{i}. [{f["check"]}]{tag} {where}{f["message"]}')
    if res['skipped']:
        out.append('\n【跳过】')
        out.extend(f'- {s["file"]}：{s["reason"]}' for s in res['skipped'])
    if res['prev']:
        moved = [r for r in res['files'] if r['status'] != SAME]
        same = [r for r in res['files'] if r['status'] == SAME]
        out.append(f'\n【和上一轮对比】变化 {len(moved)} 个，相同 {len(same)} 个')
        out.extend(_fmt_pair_row(r) for r in moved)
        out.extend(_fmt_pair_row(r) for r in same if r.get('sheets'))
        if len(same) > sum(1 for r in same if r.get('sheets')):
            out.append('  其余相同的文件：' + listing([r['file'] for r in same if not r.get('sheets')], 10))
    if res['time_windows']:
        out.append('\n【CSV 时间窗】（只报事实，不判对错）')
        for g in res['time_windows']:
            out.append(f'- {g["text"]}：{listing(g["columns"], 5)}')
    out.append('\n【本脚本不查】' + '；'.join(NOT_CHECKED) + '。这两项仍靠人工审核；本脚本也不替代人工审核。')
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='取数助手回包体检（只读，不改包）')
    ap.add_argument('package', help='本轮包目录（先用 scripts/extract_package.py 解包）')
    ap.add_argument('--prev', help='上一轮包目录')
    ap.add_argument('--report', help='回包说明文件（md/txt），比如 取数助手的回话存成的 txt')
    ap.add_argument('--ignore', action='append', default=[], metavar='通配符',
                    help='不算回包内容的文件或目录（审核方自己放进轮次目录的），按相对路径或名字匹配，可写多次')
    ap.add_argument('--empty-cache-severe', type=int, default=EMPTY_CACHE_SEVERE, metavar='格数',
                    help='公式缓存为空的格数达到多少升为严重；不写就一律只报提醒（阈值待用户拍板）')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    args = ap.parse_args(argv)
    for label, path in (('本轮包', args.package), ('上一轮包', args.prev)):
        if path is None:
            continue
        if not os.path.isdir(path):
            hint = '；是压缩包的话，先用 scripts/extract_package.py 解到新目录' if ext_of(path) in ARCHIVE_EXTS else ''
            print(f'{label}不是目录：{show(path)}{hint}', file=sys.stderr)
            return EXIT_ARGS
    if args.prev and os.path.realpath(args.prev) == os.path.realpath(args.package):
        print('--prev 和本轮包是同一个目录', file=sys.stderr)
        return EXIT_ARGS
    if args.report and not os.path.isfile(args.report):
        print(f'回包说明文件不存在：{show(args.report)}', file=sys.stderr)
        return EXIT_ARGS
    if args.empty_cache_severe is not None and args.empty_cache_severe < 1:
        print('--empty-cache-severe 要写正整数', file=sys.stderr)
        return EXIT_ARGS
    res = run_check(args.package, args.prev, args.report, args.ignore, args.empty_cache_severe)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_text(res))
    return res['exit_code']


if __name__ == '__main__':
    sys.exit(main())
