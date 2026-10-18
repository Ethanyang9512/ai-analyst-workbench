# -*- coding: utf-8 -*-
"""deckcheck.py 的测试。

运行（在技能目录下）：${AAW_PY:-python3} tests/test_deckcheck.py -v
全部是合成用例，覆盖每项检查；约定里的词、对象名、编号、数字都是虚构的。
PDF 那组要 PyMuPDF（import fitz），没装就跳过。临时文件放在 $TMPDIR 下新建的目录里。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能目录（本文件在 tests/ 下）
sys.path.insert(0, os.path.join(HERE, "scripts"))
import deckcheck as dc  # noqa: E402

PY = sys.executable                    # 子进程用跑测试的同一个解释器
try:
    import fitz  # noqa: F401
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False
# 测试用约定：按 _CONVENTIONS.md 的 json 格式写；词、对象名、编号都是虚构的，只在测试里用
CONV = {
    'banned': [{'word': '腰斩', 'use': '下降一半', 'why': '用户纠正'}, {'word': '个百分点', 'use': 'pt', 'why': '用户纠正'},
               {'word': '查不到明细', 'use': '', 'why': '用户纠正'}, {'word': '口径差异', 'use': '', 'why': '用户纠正'},
               {'word': '尾差', 'use': '', 'why': '用户纠正'}],
    'display_names': {'扣款未成': '扣款未成功', '错扣': '错扣费用', '漏开': '漏开发票',
                      '卡挂': '银行卡挂失', '扣款超时单': '扣款超时'},
    'codes': {'A店': '1001', 'B店': ['1002', '1004'], 'C店': '1003', 'D店': '1005',
              'E店': '1006', 'F店': '1007', '丙区店': '1008', '丁区店': ['1009', '1010']},
    'terms': ['每千单退款数', '续费率', '续费扣款', '主动取消', '每千单', '支付渠道'],
    'variants': {'改价退订': ['改价、退订'], '漏扣重扣': ['漏扣、重扣'], '换卡失败': ['换卡、失败']},
}


def conv_md(conv=None, fence='```json', head='## 程序检查用（deckcheck.py 读这一段）\n\n', before='', after=''):
    body = json.dumps(CONV if conv is None else conv, ensure_ascii=False, indent=1)
    close = fence[:3] if fence else ''
    return '# 约定\n\n说明文字。\n\n' + before + head + (f'{fence}\n{body}\n{close}\n' if fence else body + '\n') + after


def slide(sid, *texts, label=None, imgs=(), x=70, label_y=520, note=''):
    """一张幻灯片：texts 每段一个文本框，第一个最靠上（当标题）；label 是页码；imgs 是 (src, 横坐标) 列表；note 是讲者备注。"""
    out = [f'<slide id="{sid}"><data>']
    out += [f'<img id="i{k}" src="{src}" width="279" height="200" topLeftX="{ix}" topLeftY="100"/>' for k, (src, ix) in enumerate(imgs)]
    out += [f'<shape type="text" topLeftX="{x}" topLeftY="{26 + 30 * k}" width="800" height="30"><content><p><span>{t}</span></p>'
            '</content></shape>' for k, t in enumerate(texts)]
    if label is not None:
        out.append(f'<shape type="text" topLeftX="866" topLeftY="{label_y}" width="40" height="14"><content><p>{label}</p></content></shape>')
    return ''.join(out) + f'</data><note><content>{"<p>" + note + "</p>" if note else ""}</content></note></slide>'


def deck(*slides):
    return ('<presentation xmlns="https://www.larkoffice.com/sml/2.0" width="960" height="540"><title>测试</title>'
            + ''.join(slides) + '</presentation>')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='deckcheck_test_')
        self.dir = self.tmp.name
        self.conv = self.write('conv/约定.md', conv_md())

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text, encoding='utf-8'):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding=encoding, newline='') as f:
            f.write(text)
        return path

    def run_dc(self, *args, conv=True, as_json=True):
        """conv=True 用测试约定；'none' 只做通用检查；False 让工具自己往上找。"""
        argv = list(args) + (['--conv', self.conv] if conv is True else ['--conv', 'none'] if conv == 'none' else [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = dc.main(argv + (['--json'] if as_json else []))
        out = buf.getvalue()
        return code, (json.loads(out) if as_json and code in (0, 1) else out)

    def text(self, *texts, conv=True, extra=()):
        code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', *texts, label=1))), *extra, conv=conv)
        return code, res['issues']

    def kinds(self, issues, level=None):
        return [i['kind'] for i in issues if level is None or i['level'] == level]


class TestConventions(Base):
    def test_auto_find_upper_name_in_parent_dir(self):
        self.write('proj/_CONVENTIONS.md', conv_md())
        src = self.write('proj/slides/readback/d.xml', deck(slide('s1', '较上周腰斩', label=1)))
        code, res = self.run_dc('text', src, conv=False)
        self.assertTrue(res['conventions'].endswith('_CONVENTIONS.md'))
        self.assertEqual(code, 1)
        self.assertIn('不用的词', self.kinds(res['issues']))

    def test_lower_name_found(self):
        self.write('proj/_conventions.md', conv_md())
        src = self.write('proj/d.xml', deck(slide('s1', '较上周腰斩', label=1)))
        code, res = self.run_dc('text', src, conv=False)
        self.assertIsNotNone(res['conventions'])
        self.assertEqual(code, 1)

    def test_charter_without_json_is_skipped_and_parent_used(self):
        self.write('proj/_CONVENTIONS.md', conv_md())                                     # 上级：带 json 的约定页
        self.write('proj/sub/_CONVENTIONS.md', '# 项目总纲\n\n```\nsql/S01_x_v1.sql\n```\n')  # 子目录：用户锁定的总纲，没有 json
        src = self.write('proj/sub/d.xml', deck(slide('s1', '较上周腰斩', label=1)))
        code, res = self.run_dc('text', src, conv=False)
        self.assertEqual(os.path.dirname(res['conventions']), os.path.join(os.path.realpath(self.dir), 'proj'))
        self.assertEqual(code, 1)

    def test_no_conventions_exits_2_unless_conv_none(self):
        self.write('proj/_CONVENTIONS.md', '# 项目总纲\n\n没有 json。\n')
        src = self.write('proj/d.xml', deck(slide('s1', '较上周腰斩，见第9页', label=1)))
        code, out = self.run_dc('text', src, conv=False, as_json=False)
        self.assertEqual(code, 2)
        self.assertIn('项目还没有约定页', out)
        self.assertIn('--conv none', out)
        code, res = self.run_dc('text', src, conv='none')
        self.assertEqual((code, self.kinds(res['issues'])), (1, ['页码引用不存在']))   # 只做通用检查

    def test_explicit_conv_wins(self):
        self.write('proj/_CONVENTIONS.md', conv_md())
        other = self.write('other.md', conv_md({'banned': [{'word': '翻番', 'use': '增长一倍', 'why': ''}]}))
        src = self.write('proj/d.xml', deck(slide('s1', '腰斩和翻番', label=1)))
        code, res = self.run_dc('text', src, '--conv', other, conv=False)
        self.assertEqual([i['fix'] for i in res['issues']], ['把『翻番』改成『增长一倍』'])

    def test_fence_variants(self):
        for fence in ('```JSON', '``` json', '```json title="deckcheck"', '~~~json'):
            with self.subTest(fence=fence):
                conv = self.write('v.md', conv_md(fence=fence, head=''))
                code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', '腰斩', label=1))), '--conv', conv, conv=False)
                self.assertEqual((code, self.kinds(res['issues'])), (1, ['不用的词']))
        conv = self.write('crlf.md', conv_md().replace('\n', '\r\n'))
        self.assertEqual(self.run_dc('text', self.write('d.xml', deck(slide('s1', '腰斩', label=1))), '--conv', conv, conv=False)[0], 1)

    def test_program_heading_picks_its_block_and_hints(self):
        sample = '## 附：输出样例\n\n```json\n{"mode": "text", "must_fix": 0}\n```\n\n'
        conv = self.write('h.md', conv_md(before=sample, after='\n```json\n{"banned": []}\n```\n'))
        code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', '腰斩', label=1))), '--conv', conv, conv=False)
        self.assertEqual(code, 1)
        self.assertTrue(any('3 段 json' in w for w in res['warnings']))
        conv = self.write('n.md', conv_md(head='', after=sample))           # 没有标题：取第一段像约定的
        code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', '腰斩', label=1))), '--conv', conv, conv=False)
        self.assertEqual(code, 1)

    def test_broken_or_wrong_json_exits_2(self):
        bad = self.write('bad.md', '## 程序检查用\n\n```json\n{"banned": [\n```\n')
        code, out = self.run_dc('text', self.write('d.xml', deck(slide('s1', '文字', label=1))), '--conv', bad, conv=False)
        self.assertEqual(code, 2)
        self.assertIn('约定页', out)
        nokeys = self.write('nokeys.md', '## 程序检查用\n\n```json\n{"mode": "x"}\n```\n')
        self.assertEqual(self.run_dc('text', self.write('d.xml', deck(slide('s1', '文字', label=1))), '--conv', nokeys, conv=False)[0], 2)
        self.write('proj/_CONVENTIONS.md', '## 程序检查用\n\n```json\n{"banned": [\n```\n')     # 自动找到的约定页坏了
        self.assertEqual(self.run_dc('text', self.write('proj/d.xml', deck(slide('s1', '文字', label=1))), conv=False)[0], 2)

    def test_loose_formats_and_unexpected_shapes(self):
        loose = self.write('loose.md', conv_md({'banned': ['腰斩'], 'codes': {'A店': 1001}}))   # 词写成字符串、编号写成数字
        code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', '腰斩；A店；1001 A店', label=1))), '--conv', loose, conv=False)
        self.assertEqual((code, sorted(self.kinds(res['issues']))), (1, ['不用的词', '对象名缺编号']))
        odd = self.write('odd.md', conv_md({'codes': ['A店']}))                                  # 结构不对：退出 2，不是 1
        self.assertEqual(self.run_dc('text', self.write('d.xml', deck(slide('s1', '文字', label=1))), '--conv', odd, conv=False)[0], 2)


class TestText(Base):
    def test_banned_words_with_fix(self):
        code, issues = self.text('较上周腰斩，降了0.5个百分点，尾差并入前一项')
        self.assertEqual(code, 1)
        fixes = [i['fix'] for i in issues if i['kind'] == '不用的词']
        self.assertEqual(len(fixes), 3)
        self.assertTrue(fixes[0].startswith('把『腰斩』改成『下降一半』'))
        self.assertTrue(any(f.startswith('删掉『尾差』或换个说法') for f in fixes))

    def test_display_names(self):
        cases = [('银行卡挂失、扣款未成各+0.4单', [dc.MUST]), ('银行卡挂失、扣款未成功各+0.4单', []),
                 ('图里的“扣款未成功”对应系统标签“扣款未成”。', []), ('其余标签用系统原名（如“扣款未成”）。', [dc.CHECK]),
                 ('系统原名已补全：扣款未成→扣款未成功，卡挂→银行卡挂失', []), ('“扣款未成功”是补全写法。系统标签“扣款未成”。', [dc.CHECK]),
                 ('系统标签「漏开」即漏开发票', []), ('系统标签“扣款超时单”的订单', [dc.CHECK]),
                 ('“扣款超时”对应系统标签“扣款超时单”', []), ('漏开+1.0单，卡挂+0.9单', [dc.MUST, dc.MUST]),
                 ('客户原话“说卡挂了扣不了”', [dc.CHECK])]                         # 引号里多半是原话或说明：建议核对
        for text, levels in cases:
            with self.subTest(text=text):
                self.assertEqual([i['level'] for i in self.text(text)[1] if i['kind'] == '系统原名'], levels)
        fix = [i['fix'] for i in self.text('扣款未成各+0.4单')[1]][0]
        self.assertTrue(fix.startswith('把『扣款未成』改成『扣款未成功』'))

    def test_allow_list_from_conv_and_cli(self):
        texts = ('系统出错扣回两次', '个别门店遗漏开票', '1001 A店读卡挂起较多', 'W2与W8首尾差距不大')
        code, issues = self.text(*texts)
        self.assertEqual(len(self.kinds(issues, dc.MUST)), 4)
        conv = self.write('allow.md', conv_md(dict(CONV, allow=['出错扣回', '遗漏开票', '读卡挂起', '首尾差距'])))
        code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', *texts, label=1))), '--conv', conv, conv=False)
        self.assertEqual((code, res['issues']), (0, []))
        self.assertEqual(self.text(*texts, extra=('--allow', '出错扣回,遗漏开票,读卡挂起,首尾差距')), (0, []))

    @unittest.skipIf(dc.trace_scan is None, 'trace_scan.py 不在')
    def test_trace_scan_reused_with_allow(self):
        self.assertEqual([i['level'] for i in self.text('R20 回包里的数')[1] if i['kind'].startswith('内部痕迹')], [dc.MUST, dc.MUST])
        for text, allow in (('这类工单由AI客服直接关闭', '由AI客服'), ('进场要场馆验收员签字', '场馆验收员'), ('客户退回包裹后才能退款', '退回包裹')):
            with self.subTest(text=text):
                self.assertTrue(any(i['kind'].startswith('内部痕迹') for i in self.text(text)[1]))
                self.assertEqual(self.text(text, extra=('--allow', allow)), (0, []))
        self.assertEqual(self.text('客户退回包裹后才能退款', extra=('--allow', '回包')), (0, []))    # 和 trace_scan 一样：原样放行

    def test_trace_missing_warns(self):
        saved = dc.trace_scan, dc.TRACE_WARN
        dc.trace_scan, dc.TRACE_WARN = None, '内部痕迹没查：测试'
        try:
            code, res = self.run_dc('text', self.write('d.xml', deck(slide('s1', 'R20', label=1))))
        finally:
            dc.trace_scan, dc.TRACE_WARN = saved
        self.assertEqual((code, res['warnings']), (0, ['内部痕迹没查：测试']))

    def test_internal_page_words(self):
        issues = self.text('会前追问清单：先问清口径', '本页只给用户看')[1]
        self.assertEqual(self.kinds(issues, dc.MUST), ['内部页用词', '内部页用词'])

    def test_notes_checked_for_banned_and_traces(self):
        path = self.write('d.xml', deck(slide('s1', '正文', label=1, note='讲的时候说腰斩，R20 的数，扣款未成')))
        code, res = self.run_dc('text', path)
        self.assertEqual(code, 1)
        self.assertEqual({(i['where'], i['kind']) for i in res['issues']} - {('第1页备注', '内部痕迹：内部轮次号')},
                         {('第1页备注', '不用的词')})               # 备注只查不用的词和内部痕迹，不查系统原名

    def test_object_codes(self):
        cases = [('A店最高', dc.MUST), ('1001 A店最高', None), ('1001A店最高', None), ('1001  A店', None),   # 连续空白读入时并成一个
                 ('1002 B店和1004 B店', None), ('B店偏高', dc.MUST), ('1012 A店', dc.CHECK),
                 ('1011 丙区偏高', dc.CHECK), ('1008 丙区偏高', None), ('1009 丁区、1010 丁区', None)]                # 短写法也核编号
        for text, level in cases:
            with self.subTest(text=text):
                issues = [i for i in self.text(text)[1] if '编号' in i['kind']]
                self.assertEqual([i['level'] for i in issues], [level] if level else [])
        self.assertEqual(self.text('A店最高')[1][0]['fix'], '对象名前加编号：1001 A店')
        self.assertEqual(self.text('B店偏高')[1][0]['fix'], '对象名前加编号：1002 B店 或 1004 B店')

    def test_variants_are_suggestions(self):
        path = self.write('d.xml', deck(slide('s1', '改价退订升得最多', label=1), slide('s2', '改价、退订+1.3单', label=2)))
        code, res = self.run_dc('text', path)
        self.assertEqual(code, 0)
        self.assertEqual([(i['level'], i['kind']) for i in res['issues']], [(dc.CHECK, '同一个东西几种写法')])
        self.assertIn('第1页', res['issues'][0]['context'])
        self.assertEqual(self.text('改价、退订+1.3单；改价、退订')[1], [])

    def test_page_refs_listed_and_out_of_range(self):
        path = self.write('d.xml', deck(slide('s0', '故事线（自用）', '第1—3页；附录见第5页'),
                                        slide('s1', '总览', '详见第2页', label=1), slide('s2', '明细', label=2),
                                        slide('s3', '附录', label=3)))
        code, res = self.run_dc('text', path)
        self.assertEqual(code, 1)
        self.assertEqual([(i['where'], i['kind']) for i in res['issues']], [('第1张（无页码）', '页码引用不存在')])
        self.assertEqual({(r['where'], r['page'], r['title']) for r in res['page_refs']},
                         {('第1张（无页码）', 1, '总览'), ('第1张（无页码）', 3, '附录'), ('第1张（无页码）', 5, None), ('第1页', 2, '明细')})

    def test_page_labels(self):
        path = self.write('d.xml', deck(slide('a', '一', label=1), slide('b', '二', label=2), slide('c', '三', label=2)))
        self.assertEqual([(i['where'], i['kind']) for i in self.run_dc('text', path)[1]['issues']], [('第3张', '页码不连续')])
        path = self.write('d.xml', deck(slide('a', '一', '见第3页', label=1), slide('b', '二', label=2, label_y=455), slide('c', '三', label=3)))
        self.assertEqual(self.run_dc('text', path)[0], 0)                       # 页码框放得高一些（Y=455）也认得出

    def test_auto_page_number_field_uses_position(self):
        field = '<field type="slidenum">{}</field>'      # 飞书自动页码：XML 里缓存的数常是旧的（显示 1、2、3，缓存可能是 1、2、2）
        xml = deck(slide('a', '一', '见第3页', label=field.format(1)), slide('b', '二', label=field.format(1)),
                   slide('c', '三', label=field.format(2)))
        code, res = self.run_dc('text', self.write('d.xml', xml))
        self.assertEqual((code, res['issues'], res['page_refs'][0]['title']), (0, [], '三'))

    def test_input_formats(self):
        xml = deck(slide('a', '一', label=1), slide('b', '二', label=2))
        wrapped = json.dumps({'ok': True, 'data': {'xml_presentation': {'content': xml}}})
        for name, text, enc in [('raw.xml', xml, 'utf-8'), ('c.json', json.dumps({'content': xml}), 'utf-8'), ('w.xml', wrapped, 'utf-8'),
                                ('decl.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<!-- ' + '注释' * 200 + ' -->\n' + xml, 'utf-8'),
                                ('decl.json', json.dumps({'content': '<?xml version="1.0"?>\n' + xml}), 'utf-8'),
                                ('list.json', json.dumps([{'content': xml}]), 'utf-8'), ('notice.json', '[notice] new version\n' + wrapped, 'utf-8'),
                                ('u16.xml', xml, 'utf-16')]:
            with self.subTest(name=name):
                code, res = self.run_dc('text', self.write(name, text, enc))
                self.assertEqual((code, res['slides']), (0, 2))

    def test_bad_inputs_exit_2(self):
        for name, text in [('empty.xml', ''), ('nojson.json', '{"ok": false}'), ('bad.xml', '<presentation><slide>'),
                           ('zero.xml', deck()), ('err.xml', '<html><body>502 Bad Gateway</body></html>'),
                           ('err.json', 'Error: permission denied'), ('slide_only.xml', slide('s', '1001 A店', label=1))]:
            with self.subTest(name=name):
                self.assertEqual(self.run_dc('text', self.write(name, text))[0], 2)
        self.assertEqual(self.run_dc('text', os.path.join(self.dir, 'missing.xml'))[0], 2)

    def test_markdown_pages(self):
        md = '# 文字稿\n\n## 第 1 页｜总览 | 每千单退款数\n见第3页\n\n## 第 2 页｜明细\nA店最高\n'
        code, res = self.run_dc('text', self.write('d.md', md))
        self.assertEqual(code, 1)
        self.assertEqual(sorted((i['where'], i['kind']) for i in res['issues']), [('第1页', '页码引用不存在'), ('第2页', '对象名缺编号')])

    def test_plain_text_without_pages(self):
        code, res = self.run_dc('text', self.write('d.txt', '这是正文，见第99页。\n'))
        self.assertEqual((code, len(res['page_refs'])), (0, 1))

    def test_plain_output_and_exit_codes(self):
        path = self.write('d.xml', deck(slide('s1', '较上周腰斩', label=1)))
        code, out = self.run_dc('text', path, as_json=False)
        self.assertEqual(code, 1)
        self.assertIn('[必须改] 第1页｜不用的词', out)
        self.assertIn('把『腰斩』改成『下降一半』', out)
        code, out = self.run_dc('text', self.write('ok.xml', deck(slide('s1', '较上周下降一半', label=1))), as_json=False)
        self.assertEqual(code, 0)
        self.assertIn('没查出问题', out)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            dc.main(['scope', '--after', path])

    def test_non_utf8_stdout_does_not_flip_exit_code(self):
        path = self.write('ok.xml', deck(slide('s1', '较上周下降一半', label=1)))
        env = dict(os.environ, PYTHONIOENCODING='ascii')
        r = subprocess.run([PY, os.path.join(HERE, "scripts", "deckcheck.py"), 'text', path, '--conv', self.conv], env=env, capture_output=True)
        self.assertEqual(r.returncode, 0)


@unittest.skipUnless(HAS_FITZ, '没装 PyMuPDF（fitz），PDF 检查跳过')
class TestPdf(Base):
    def pdf(self, *pages, name='d.pdf'):
        """pages: 每页一个 [(x, 基线 y, 文字, 字号), …] 列表；页面 720×405，和飞书导出一样。"""
        import fitz
        doc = fitz.open()
        for lines in pages:
            page = doc.new_page(width=720, height=405)
            page.draw_rect((10, 10, 20, 20))
            for x, y, t, size in lines:
                page.insert_text((x, y), t, fontname='china-s', fontsize=size)
        path = os.path.join(self.dir, name)
        doc.save(path)
        return path

    def test_convention_word_split_is_must(self):
        code, res = self.run_dc('pdf', self.pdf([(60, 60, '本周W6每千单退', 10), (60, 74, '款数上升明显', 10)]))
        self.assertEqual(code, 1)
        self.assertEqual([(i['kind'], i['fix'][:9]) for i in res['issues']], [('约定里的词被拆在两行', '让『每千单退款数』')])

    def test_two_char_word_and_allow(self):
        lines = [(60, 60, '1001 A店读卡', 10), (60, 74, '挂起较多', 10)]
        code, res = self.run_dc('pdf', self.pdf(lines))
        self.assertEqual((code, [i['level'] for i in res['issues']]), (0, [dc.CHECK]))       # 两个字的“卡挂”拆行只报建议核对
        self.assertEqual(self.run_dc('pdf', self.pdf(lines), '--allow', '读卡挂起')[1]['issues'], [])

    def test_break_at_another_word_boundary(self):
        self.assertEqual(self.run_dc('pdf', self.pdf([(60, 60, '退款最多的是续费', 10), (60, 74, '扣款未成功，其次', 10)]))[1]['issues'], [])
        code, res = self.run_dc('pdf', self.pdf([(60, 60, '图里的扣款未成', 10), (60, 74, '功对应系统标签', 10)]))
        self.assertEqual((code, res['issues'][0]['fix'][:8]), (1, '让『扣款未成功』'))   # 换行在“扣款未成功”中间，仍算拆开

    def test_heuristic_split_function_words_and_cohesion(self):
        lines = [(60, 60, '退款数高于目', 10), (60, 74, '标，下周再看', 10), (60, 150, '目标一', 10), (60, 170, '目标二', 10),
                 (60, 230, '约六成归到', 10), (60, 244, '续费（支付渠道）', 10), (60, 300, '归到续费', 10), (60, 320, '归到续费', 10)]
        code, res = self.run_dc('pdf', self.pdf(lines))
        self.assertEqual((code, [(i['level'], i['kind']) for i in res['issues']]), (0, [(dc.CHECK, '疑似拆词')]))
        self.assertIn('目／标', res['issues'][0]['context'])
        common = [(60, 100 + 30 * k, '甲丙乙丁' * 3, 10) for k in range(8)]   # “甲”“乙”到处都有，“甲乙”只连着出现 2 次：不像一个词
        lines = [(400, 40, '戊甲', 10), (400, 54, '乙己', 10), (400, 300, '甲乙', 10), (400, 340, '甲乙', 10)] + common
        self.assertEqual(self.run_dc('pdf', self.pdf(lines))[1]['issues'], [])

    def test_lines_far_apart_are_not_a_break(self):
        self.assertEqual(self.run_dc('pdf', self.pdf([(60, 60, '本周W6每千单退', 10), (60, 120, '款数上升', 10)]))[1]['issues'], [])

    def test_text_outside_page_reported_once(self):
        code, res = self.run_dc('pdf', self.pdf([(60, 395, '脚注第一行', 9), (60, 409, '脚注出框的一行', 9), (650, 60, '右边超出页面的一行字', 10)]))
        self.assertEqual((code, self.kinds(res['issues'])), (1, ['文字超出页面', '文字超出页面']))
        path = self.pdf([(60, 409, '脚注出框的一行', 9)], [(60, 4, '脚注出框的一行', 9), (60, 100, '第二页正文', 10)])  # 长画布：同一行压着两页
        self.assertEqual([i['where'] for i in self.run_dc('pdf', path)[1]['issues']], ['PDF第1页'])

    def test_pages_filter_ranges_label_title_and_header(self):
        path = self.pdf([(60, 60, '第一页正文', 10)],
                        [(60, 30, '标题里的退款数上升，续', 21), (60, 56, '费率持平', 21), (60, 120, '正文', 8), (675, 397, '5', 7)])
        self.assertEqual(self.run_dc('pdf', path, '--pages', '1')[1]['issues'], [])
        code, res = self.run_dc('pdf', path, '--pages', '1-2')
        self.assertEqual(([i['where'] for i in res['issues']], res['checked'], res['pages']), (['PDF第2页（页码5）标题'], [1, 2], 2))
        self.assertIn('共 2 页', self.run_dc('pdf', path, as_json=False)[1])
        self.assertEqual(self.run_dc('pdf', path, '--pages', '3')[0], 2)            # 超出 1..N
        self.assertEqual(self.run_dc('pdf', path, '--pages', '0,1')[0], 2)

    def test_textless_or_broken_pdf_exits_2(self):
        self.assertEqual(self.run_dc('pdf', self.pdf([], [], name='blank.pdf'))[0], 2)   # 一个文字行都没有
        good = self.pdf([(60, 60, '正文' * 20, 10)], name='good.pdf')
        with open(good, 'rb') as f:
            data = f.read()
        cut = os.path.join(self.dir, 'cut.pdf')
        with open(cut, 'wb') as f:
            f.write(data[:len(data) // 3])
        self.assertEqual(self.run_dc('pdf', cut)[0], 2)


class TestScope(Base):
    def scope(self, before, after):
        return self.run_dc('scope', '--before', self.write('before.xml', before), '--after', self.write('after.xml', after))

    def base(self, **over):
        pages = {'s1': ('总览', '续费率91.2%，见第2页'), 's2': ('明细', '每千单+6.6单，续费率91.2%'), 's3': ('附录', '口径说明')}
        pages.update(over)
        return deck(*[slide(sid, *texts, label=k) for k, (sid, texts) in enumerate(pages.items(), 1)])

    def test_text_change_without_numbers_is_small(self):
        code, res = self.scope(self.base(), self.base(s3=('附录', '口径说明，补一句话')))
        self.assertEqual((code, res['level'], res['flags']), (0, 'small', []))
        self.assertEqual(([c['page'] for c in res['changed']], res['review'], res['review_slides']), (['第3页'], ['第3页'], [3]))

    def test_number_change_is_page_and_finds_affected(self):
        _, res = self.scope(self.base(), self.base(s2=('明细', '每千单+6.9单，续费率91.2%')))
        self.assertEqual((res['level'], res['flags']), ('page', ['数字']))
        self.assertEqual({a['page']: a['why'] for a in res['affected']}, {'第1页': ['引用了改动的第2页']})
        _, res = self.scope(self.base(), self.base(s2=('明细', '每千单+6.6单，续费率91.5%')))
        self.assertEqual({a['page']: a['why'] for a in res['affected']}, {'第1页': ['引用了改动的第2页', '有改动处的数字 91.2%']})

    def test_swapped_numbers_and_cell_set_to_existing_number(self):
        _, res = self.scope(self.base(s3=('附录', '自营 1.48%、平台 1.26%')), self.base(s3=('附录', '自营 1.26%、平台 1.48%')))
        self.assertEqual((res['level'], res['flags']), ('page', ['数字']))
        cells = lambda v: self.base(s3=('附录', '1001 A店 2.15%', f'1002 B店 {v}', '1003 C店 1.64%'), s4=('另页', '乙区 1.92%'))
        _, res = self.scope(cells('1.92%'), cells('2.15%'))
        self.assertEqual(res['flags'], ['数字'])
        self.assertEqual({a['page'] for a in res['affected']}, {'第4页'})          # 1.92% 少了一处：写着 1.92% 的页要看

    def test_number_tokens(self):
        for old, new in (('W3起低于目标', 'W5起低于目标'), ('约六成归到续费', '约五成归到续费'), ('共1500多单', '共2100多单'),
                         ('共1200箱', '共1300箱'), ('多44张', '多45张')):
            with self.subTest(old=old):
                _, res = self.scope(self.base(s3=('附录', old)), self.base(s3=('附录', new)))
                self.assertEqual(res['flags'], ['数字'])
        for old, new in (('1001 A店偏高', '1001 A店偏高；1013 甲区也高'), ('2026年9月', '2025年9月')):
            with self.subTest(old=old):                                         # 编号（约定里的，或后面是空格加汉字）、年份不算数字
                self.assertEqual(self.scope(self.base(s3=('附录', old)), self.base(s3=('附录', new)))[1]['flags'], [])

    def test_affected_pages_use_every_changed_number(self):
        pages = [('总览', '续费率91.2%')] + [(f'标题{k}', '续费率91.2%' if k < 6 else '其他') for k in range(2, 11)]
        before = deck(*[slide(f's{k}', *t, label=k) for k, t in enumerate(pages, 1)])
        _, res = self.scope(before, before.replace('<span>续费率91.2%</span>', '<span>续费率91.5%</span>', 1))
        self.assertEqual([a['page'] for a in res['affected']], ['第2页', '第3页', '第4页', '第5页'])   # 出现在多少页都算
        _, res = self.scope(self.base(s3=('附录', '八周里5周最高')), self.base(s3=('附录', '八周里4周最高')))
        self.assertEqual((res['flags'], res['affected']), (['数字'], []))       # 单个数字算改了数字，但不拿来找受影响的页
        _, res = self.scope(self.base(s3=('附录', 'W3起低于目标'), s4=('另页', 'W3回落')),
                            self.base(s3=('附录', 'W5起低于目标'), s4=('另页', 'W3回落')))
        self.assertEqual((res['level'], res['flags'], res['affected']), ('page', ['数字'], []))   # 周号同理：算改了数字、判 page，不拿来找受影响的页

    def test_title_change_is_page(self):
        _, res = self.scope(self.base(), self.base(s3=('附录二', '口径说明')))
        self.assertEqual((res['level'], res['flags']), ('page', ['页标题']))

    def test_inserted_page_flags_stale_reference(self):
        before = deck(slide('s1', '总览', '细节见第2页', label=1), slide('s2', '明细', label=2), slide('s3', '附录', label=3))
        after = deck(slide('s1', '总览', '细节见第2页', label=1), slide('sx', '新插的页', label=2),
                     slide('s2', '明细', label=3), slide('s3', '附录', label=4))
        code, res = self.scope(before, after)
        self.assertEqual(code, 1)
        self.assertIn('页数', res['flags'])
        self.assertEqual([c['why'] for c in res['changed']], ['新增'])
        self.assertEqual([(i['where'], i['kind']) for i in res['issues']], [('第1页', '插页后页码引用错位')])
        self.assertTrue(res['issues'][0]['fix'].endswith('改成第3页'))
        code, res = self.scope(before, after.replace('细节见第2页', '细节见第3页'))
        self.assertEqual((code, res['issues']), (0, []))

    def test_recreated_page_with_new_id_and_same_content(self):
        before = deck(slide('s1', '总览', '细节见第2页', label=1), slide('s2', '明细', '每千单+6.6单', label=2), slide('s3', '附录', label=3))
        code, res = self.scope(before, before.replace('id="s2"', 'id="s2b"'))
        self.assertEqual((code, res['issues'], res['changed'], res['level']), (0, [], [], 'small'))

    def test_replaced_in_place_is_page(self):
        after = self.base().replace('id="s2"', 'id="sNEW"').replace('明细', '完全不同的新页').replace('每千单+6.6单，续费率91.2%', '每千单+9.9单，退款率95.0%')
        _, res = self.scope(self.base(), after)
        self.assertEqual((res['level'], res['flags'], res['removed']), ('page', ['数字', '页标题'], []))
        self.assertTrue(res['changed'][0]['why'].startswith('删旧建新'))

    def test_removed_page(self):
        after = deck(slide('s1', '总览', '续费率91.2%，见第2页', label=1), slide('s3', '附录', '口径说明', label=2))
        code, res = self.scope(self.base(), after)
        self.assertEqual(code, 1)                      # 第1页那句“见第2页”原来指“明细”，现在指“附录”
        self.assertEqual([r['title'] for r in res['removed']], ['明细'])
        self.assertIn('页数', res['flags'])

    def test_images(self):
        def mk(c2='C2', note2='图说明'):
            return deck(slide('s1', '总览', label=1, imgs=[('L1', 900)]),
                        slide('s2', '图页', note2, label=2, imgs=[('L2', 900), (c2, 73)]),
                        slide('s3', '附录', label=3, imgs=[('L3', 900), ('C3', 73)]))
        _, res = self.scope(mk(), mk(c2='C2new'))                                    # 只换图
        self.assertEqual(([c['page'] for c in res['changed']], res['flags'], res['level']), (['第2页'], ['图'], 'page'))
        _, res = self.scope(mk(), mk(c2='C2new', note2='图的说明'))                  # 改字＋换图
        self.assertEqual((res['flags'], res['level']), (['图'], 'page'))
        same_slot = lambda c: deck(*[slide(f's{k}', f'第{k}张标题', label=k, imgs=[(c if k == 2 else f'CH{k}', 73)]) for k in (1, 2, 3)])
        self.assertEqual(self.scope(same_slot('CH2'), same_slot('CH2b'))[1]['flags'], ['图'])   # 各页同一位置的图换了也看得见
        before = mk()
        after = before.replace('src="L3"', 'src="M3"').replace('src="C3"', 'src="C3b"').replace('<p>3</p>', '<p>4</p>')
        _, res = self.scope(before, after)
        self.assertEqual((res['changed'], res['renumbered_only']), ([], ['第4页']))   # 重编页码、整页重建：图片全换、文字版式没变
        _, res = self.scope(before, before.replace('src="C3"', 'src="C3b"').replace('<p>3</p>', '<p>4</p>'))
        self.assertEqual(([c['page'] for c in res['changed']], res['renumbered_only']), (['第4页'], []))   # 只换了图表：要看

    def test_reorder_is_reported(self):
        before = deck(*[slide(f's{k}', f'第{k}张的标题', label=k) for k in (1, 2, 3, 4)])
        after = deck(*[slide(f's{k}', f'第{k}张的标题', label=n) for n, k in enumerate((1, 3, 2, 4), 1)])
        _, res = self.scope(before, after)
        self.assertEqual((res['level'], res['flags']), ('page', ['页序']))
        self.assertEqual([c['page'] for c in res['changed']], ['第2页', '第3页', '第4页'])   # 挪动的两页和接在后面的那页

    def test_layout_only_is_small(self):
        _, res = self.scope(deck(slide('s1', '总览', '正文', label=1)), deck(slide('s1', '总览', '正文', label=1, x=90)))
        self.assertEqual(([c['why'] for c in res['changed']], res['level']), (['改了版式'], 'small'))

    def test_zero_slides_or_markdown_exit_2(self):
        self.assertEqual(self.scope(deck(), self.base())[0], 2)
        md = self.write('a.md', '## 第 1 页｜总览\n正文\n')
        self.assertEqual(self.run_dc('scope', '--before', md, '--after', md)[0], 2)


if __name__ == '__main__':
    unittest.main()
