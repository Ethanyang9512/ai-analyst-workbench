#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取数助手回包体检 pkgcheck.py 的回归测试：python3 test_pkgcheck.py（在技能目录下运行）

夹具都在临时目录里现造（假包、假 Excel、假口令），不读业务数据。
想拿自己的历史包做回放：把"连续几轮 Excel 没重跑却写已修复"的包放进临时目录，照 TestCompare 的写法加一组即可。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')  # 本文件在 tests/ 下，程序在 scripts/ 下
sys.path.insert(0, HERE)
import pkgcheck  # noqa: E402

# 假的个人信息、口令和本机路径：拼起来写，运行时照样喂给检查程序；
# 这样仓库自查（grep、敏感信息扫描）不会把测试夹具当成真泄露。
FAKE_PHONE = '138' + '1234' + '5678'
FAKE_PHONE2 = '139' + '1234' + '5678'
FAKE_IOT = '140' + '1234' + '0142'          # 物联网号段，不该算手机号
FAKE_EMAIL = 'someone' + '@' + 'example.com'
FAKE_HOME = '/' + 'Users/x'


def make_xlsx(path, sheets, shared=()):
    """sheets: {表名: [[单元格, ...], ...]}；单元格写法：
    数字 → 数值格；('s', i) → 共享字符串；('f', 公式, 缓存值或 None) → 公式格；None → 空。"""
    main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        sheet_tags, rels = [], []
        for n, (name, rows) in enumerate(sheets.items(), 1):
            sheet_tags.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Type="{rel}/worksheet" Target="worksheets/sheet{n}.xml"/>')
            xml_rows = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, cell in enumerate(row):
                    ref = f'{chr(65 + c)}{r}'
                    if cell is None:
                        continue
                    if isinstance(cell, tuple) and cell[0] == 's':
                        cells.append(f'<c r="{ref}" t="s"><v>{cell[1]}</v></c>')
                    elif isinstance(cell, tuple) and cell[0] == 'f':
                        v = '' if cell[2] is None else f'<v>{cell[2]}</v>'
                        cells.append(f'<c r="{ref}"><f>{cell[1]}</f>{v}</c>')
                    else:
                        cells.append(f'<c r="{ref}"><v>{cell}</v></c>')
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(f'xl/worksheets/sheet{n}.xml',
                       f'<worksheet xmlns="{main}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>{"".join(sheet_tags)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
        if shared:
            sis = ''.join(f'<si><t>{s}</t></si>' for s in shared)
            z.writestr('xl/sharedStrings.xml', f'<sst xmlns="{main}">{sis}</sst>')


def id_number(body17):
    """给 17 位本体补上校验位，造一个格式合法的假身份证号。"""
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    return body17 + '10X98765432'[sum(int(c) * w for c, w in zip(body17, weights)) % 11]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pkgcheck_test_')

    def tearDown(self):
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for n in dirnames + filenames:
                p = os.path.join(dirpath, n)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pkg(self, name, files):
        root = os.path.join(self.tmp, name)
        os.makedirs(root, exist_ok=True)
        for rel, content in files.items():
            path = os.path.join(root, *rel.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if isinstance(content, str):
                content = content.encode('utf-8')
            with open(path, 'wb') as fh:
                fh.write(content)
        return root

    def xlsx_bytes(self, sheets, shared=()):
        path = os.path.join(self.tmp, f'_tmp_{len(os.listdir(self.tmp))}.xlsx')
        make_xlsx(path, sheets, shared)
        with open(path, 'rb') as fh:
            data = fh.read()
        os.remove(path)
        return data

    def checks(self, res, level=None):
        return [(f['level'], f['check'], f['file']) for f in res['findings'] if level in (None, f['level'])]

    def has(self, res, level, check, file=None):
        return any(lv == level and ck == check and (file is None or fl == file) for lv, ck, fl in self.checks(res))

    def exit_code(self, *argv):
        with redirect_stdout(io.StringIO()) as buf, redirect_stderr(io.StringIO()):
            code = pkgcheck.main(list(argv))
        return code, buf.getvalue()


class TestCompare(Base):
    def setUp(self):
        super().setUp()
        self.x1 = self.xlsx_bytes({'汇总': [['渠道', '笔数'], ['A', 10], ['B', 20]]})
        self.x2 = self.xlsx_bytes({'汇总': [['渠道', '笔数'], ['A', 11], ['B', 20], ['C', 5]]})

    def test_claim_text_but_excel_same_is_severe(self):
        prev = self.pkg('v1', {'out/结果.xlsx': self.x1, '分析.md': '# 分析\n结论一\n'})
        cur = self.pkg('v2', {'out/结果.xlsx': self.x1, '分析.md': '# 分析\n结论一\nP1-3 已修复：口径改为扣款日\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', 'out/结果.xlsx'))
        self.assertEqual(len(res['claims']), 1)
        self.assertEqual(self.exit_code(cur, '--prev', prev)[0], pkgcheck.EXIT_NO_RERUN)

    def test_excel_regenerated_is_not_flagged(self):
        prev = self.pkg('v1', {'out/结果.xlsx': self.x1, '分析.md': '旧\n'})
        cur = self.pkg('v2', {'out/结果.xlsx': self.x2, '分析.md': '新\nP1 已修复\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertFalse(any(ck == '说改了没重跑' for _, ck, _ in self.checks(res)))
        self.assertEqual(self.exit_code(cur, '--prev', prev)[0], 0)

    def test_new_fix_files_count_as_claim(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': 'b\n', 'scripts/fix_p1_p2.py': 'print(1)\n'})
        res = pkgcheck.run_check(cur, prev)
        sev = [f for f in res['findings'] if f['check'] == '说改了没重跑']
        self.assertEqual(len(sev), 1)
        self.assertIn('fix_p1_p2.py', sev[0]['message'])

    def test_no_claim_md_changed_excel_same_is_reminder(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': 'b\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '提醒', 'MD 改了 Excel 没变'))
        self.assertEqual(self.checks(res, '严重'), [])

    def test_report_names_an_unchanged_csv(self):
        csv = '日期,单量\n2026-03-02,1\n'
        prev = self.pkg('v1', {'Q3_ontime.csv': csv, '结果.xlsx': self.x1})
        cur = self.pkg('v2', {'Q3_ontime.csv': csv, '结果.xlsx': self.x2})
        report = os.path.join(self.tmp, 'partner_reply.txt')
        with open(report, 'w', encoding='utf-8') as fh:
            fh.write('本轮改动：\n1. Q3_ontime.csv 已修正分母口径\n2. 结果.xlsx 已重新生成\n')
        res = pkgcheck.run_check(cur, prev, report)
        files = [fl for lv, ck, fl in self.checks(res, '严重') if ck == '说改了没重跑']
        self.assertEqual(files, ['Q3_ontime.csv'])  # Excel 确实变了，不报

    def test_quoted_claim_lines_are_redacted(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': 'b\n口径已修复，联系人电话 ' + FAKE_PHONE + '，口令：Zz9!abcd\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', '结果.xlsx'))
        dump = pkgcheck.format_text(res) + json.dumps(res, ensure_ascii=False)
        self.assertNotIn(FAKE_PHONE, dump)
        self.assertNotIn('Zz9!abcd', dump)

    def test_auto_found_name_of_unchanged_file_is_only_reminder(self):
        prev = self.pkg('v1', {'scripts/config.py': 'x = 1\n', '日志.md': 'v1\n', '结果.xlsx': self.x1})
        cur = self.pkg('v2', {'scripts/config.py': 'x = 1\n', '日志.md': 'v2\n- P1-6：config.py 已改环境变量\n',
                              '结果.xlsx': self.x2})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '提醒', '说改了没重跑', 'scripts/config.py'))
        self.assertEqual(self.checks(res, '严重'), [])

    def test_new_regular_outputs_downgrade_unchanged_excel(self):
        prev = self.pkg('v1', {'out/0812/基线.xlsx': self.x1, '日志.md': 'v1\n'})
        cur = self.pkg('v2', {'out/0812/基线.xlsx': self.x1, '日志.md': 'v2\nP1 已修复\n',
                              'out/0817/metrics_swap.csv': 'a\n1\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '提醒', '部分 Excel 没变'))
        self.assertEqual(self.checks(res, '严重'), [])

    def test_fix_side_outputs_do_not_count_as_rerun(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, 'Q1.csv': 'a\n1\n', '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, 'Q1.csv': 'a\n1\n', '分析.md': 'b\n',
                              'fix_attribution.csv': 'a\n2\n', 'scripts/fix_p1.py': 'pass\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', '结果.xlsx'))

    def test_renamed_but_same_bytes(self):
        prev = self.pkg('v1', {'结果_v1.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果_v2_20260203.xlsx': self.x1, '分析.md': 'b\n已改为新口径\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', '结果_v2_20260203.xlsx'))
        row = [r for r in res['files'] if r['file'] == '结果_v2_20260203.xlsx'][0]
        self.assertEqual(row['status'], pkgcheck.RENAMED_SAME)

    def test_versioned_names_are_paired(self):
        prev = self.pkg('v1', {'output/2026-02-04/分析_20260204.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'output/2026-02-05/分析_v2_20260205.xlsx': self.x2, '分析_v2.md': 'b\n'})
        res = pkgcheck.run_check(cur, prev)
        statuses = {r['file']: r['status'] for r in res['files']}
        self.assertEqual(statuses, {'output/2026-02-05/分析_v2_20260205.xlsx': '已变', '分析_v2.md': '已变'})

    def test_old_claim_lines_are_not_recounted(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': 'P1 已修复\n旧段落\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': 'P1 已修复\n新段落\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertEqual(res['claims'], [])
        self.assertEqual(self.checks(res, '严重'), [])

    def test_reviewer_files_are_ignored(self):
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '审核报告_v1_20260105.md': 'x\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '审核报告_v2_20260112.md': 'P1 已修复（审核方自己写的）\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertEqual(res['claims'], [])
        self.assertEqual(self.checks(res), [])
        self.assertIn('审核报告_v2_20260112.md', [s['file'] for s in res['skipped']])

    def test_line_counts_and_sheet_rows(self):
        prev = self.pkg('v1', {'a.csv': 'x\n1\n2\n', 'q.sql': 'select 1;\n', '结果.xlsx': self.x1})
        cur = self.pkg('v2', {'a.csv': 'x\n1\n2\n3\n4\n', 'q.sql': 'select 1;\n', '结果.xlsx': self.x2})
        res = pkgcheck.run_check(cur, prev)
        rows = {r['file']: r for r in res['files']}
        self.assertEqual(rows['a.csv']['lines'], [3, 5])
        self.assertEqual(rows['q.sql']['status'], '相同')
        self.assertEqual(rows['结果.xlsx']['sheets'], [{'汇总': 3}, {'汇总': 4}])
        self.assertIn('各表行数 汇总 3→4', pkgcheck.format_text(res))

    def test_removed_file_and_sheet(self):
        two = self.xlsx_bytes({'汇总': [['a']], 'Q3': [['b']]})
        prev = self.pkg('v1', {'结果.xlsx': two, 'old.csv': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x2})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '提醒', '文件删除'))
        self.assertTrue(self.has(res, '提醒', '工作表删除', '结果.xlsx'))

    def test_csv_only_package_with_claim_and_nothing_changed(self):
        prev = self.pkg('v1', {'a.csv': 'x\n1\n', 'b.csv': 'y\n2\n', '说明.md': 'v1\n'})
        cur = self.pkg('v2', {'a.csv': 'x\n1\n', 'b.csv': 'y\n2\n', '说明.md': 'v2\n两处问题都已修正，单量已重算\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', ''))

    def test_wording_only_claim_without_report_is_reminder(self):
        # 只改措辞：md 新增一句"已调整"，没提数据，也没有修复类文件、没给 --report → 只报提醒，退出码 0
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': '# 分析\n第3段\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': '# 分析\n第3段\n第3段措辞已调整\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertTrue(self.has(res, '提醒', '说改了没重跑', '结果.xlsx'))
        self.assertEqual(self.checks(res, '严重'), [])
        self.assertEqual(res['exit_code'], pkgcheck.EXIT_OK)
        # 同样的句子写在取数助手回话里、用 --report 传入，就算严重
        report = os.path.join(self.tmp, 'partner_reply.txt')
        with open(report, 'w', encoding='utf-8') as fh:
            fh.write('第3段措辞已调整\n')
        res = pkgcheck.run_check(cur, prev, report)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', '结果.xlsx'))

    def test_fixed_cost_file_is_not_a_fix_file(self):
        for name in ('fix_p1.py', 'fix.py', 'output/fix2_output.txt', 'fixv2.sql', 'P3-fix.md', '修复_Q3.csv'):
            self.assertTrue(pkgcheck.FIX_FILENAME_RE.search(name.rsplit('/', 1)[-1]), name)
        for name in ('fixed_cost_breakdown.csv', 'fixture_orders.csv', 'prefix_a.csv', 'suffix.csv'):
            self.assertFalse(pkgcheck.FIX_FILENAME_RE.search(name), name)
        prev = self.pkg('v1', {'结果.xlsx': self.x1, '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': self.x1, '分析.md': 'b\n', 'fixed_cost_breakdown.csv': '渠道,固定成本\nA,1\n'})
        res = pkgcheck.run_check(cur, prev)
        self.assertEqual(res['fix_files'], [])
        self.assertEqual(self.checks(res, '严重'), [])

    def test_generic_stem_is_not_a_reference(self):
        prev = self.pkg('v1', {'data.csv': 'a\n1\n', 'test.sql': 'select 1;\n', '结果.xlsx': self.x1})
        cur = self.pkg('v2', {'data.csv': 'a\n1\n', 'test.sql': 'select 1;\n', '结果.xlsx': self.x2})
        report = os.path.join(self.tmp, 'partner_reply.txt')
        with open(report, 'w', encoding='utf-8') as fh:
            fh.write('已更新 data dictionary 的字段说明\n已补 test case 说明\n')
        res = pkgcheck.run_check(cur, prev, report)
        self.assertEqual(self.checks(res, '严重'), [])
        with open(report, 'w', encoding='utf-8') as fh:
            fh.write('data.csv 已更新\n')
        res = pkgcheck.run_check(cur, prev, report)
        self.assertTrue(self.has(res, '严重', '说改了没重跑', 'data.csv'))

    def test_findings_in_unchanged_files_are_carried(self):
        cfg = "DB = {'password': 'S3cretValue!x'}\n"
        prev = self.pkg('v1', {'scripts/config.py': cfg, '结果.xlsx': self.x1})
        cur = self.pkg('v2', {'scripts/config.py': cfg, '结果.xlsx': self.x2})
        res = pkgcheck.run_check(cur, prev)
        f = [x for x in res['findings'] if x['check'] == '明文口令/密钥'][0]
        self.assertEqual((f['level'], f.get('carried')), ('严重', True))
        self.assertEqual(res['exit_code'], pkgcheck.EXIT_OK)
        self.assertIn('上一轮已有、文件未变', pkgcheck.format_text(res))
        cur2 = self.pkg('v3', {'scripts/config.py': cfg + 'x = 1\n', '结果.xlsx': self.x2})
        res = pkgcheck.run_check(cur2, prev)
        self.assertEqual(res['exit_code'], pkgcheck.EXIT_SEVERE)  # 文件改过，口令就算本轮新的

    def test_ignore_reviewer_files(self):
        common = {'结果.xlsx': self.x1, 'local/snapshot_1.json': '{"owner": "' + FAKE_EMAIL + '"}\n',
                  '01_审核记录/复核.md': 'P1 口径已修正\n'}
        prev = self.pkg('v1', dict(common, **{'_文档结构方案_1.md': 'a\n'}))
        cur = self.pkg('v2', dict(common, **{'_参考_上次.md': 'b\n', '01_审核记录/复核.md': 'P2 口径已修正\n'}))
        res = pkgcheck.run_check(cur, prev, ignore=['local', '_*.md', '01_审核记录/'])
        self.assertEqual([r['file'] for r in res['files']], ['结果.xlsx'])
        self.assertEqual(self.checks(res), [])
        skipped = [s['file'] for s in res['skipped']]
        self.assertEqual(sorted(skipped), ['01_审核记录/', '_参考_上次.md', 'local/'])
        code, _ = self.exit_code(cur, '--prev', prev, '--ignore', 'local/*', '--ignore', '_*.md', '--ignore', '01_审核记录')
        self.assertEqual(code, pkgcheck.EXIT_OK)


class TestExcel(Base):
    def test_empty_formula_cache_reminder(self):
        rows = [[1, 2, ('f', 'A1+B1', None)], [3, 4, ('f', 'A2+B2', None)], [5, 6, ('f', 'A3+B3', 11)]]
        cur = self.pkg('v1', {'表.xlsx': self.xlsx_bytes({'计算': rows})})
        res = pkgcheck.run_check(cur)
        f = [x for x in res['findings'] if x['check'] == '公式缓存为空'][0]
        self.assertEqual(f['level'], '提醒')
        self.assertIn('3 个公式格里有 2 格', f['message'])
        self.assertIn('C1', f['message'])

    def test_empty_formula_cache_severe_only_when_threshold_given(self):
        rows = [[('f', f'1+{i}', None)] for i in range(300)]
        cur = self.pkg('v1', {'表.xlsx': self.xlsx_bytes({'计算': rows})})
        res = pkgcheck.run_check(cur)  # 阈值待用户拍板，默认再多也只是提醒
        self.assertTrue(self.has(res, '提醒', '公式缓存为空', '表.xlsx'))
        self.assertEqual(self.exit_code(cur)[0], pkgcheck.EXIT_OK)
        res = pkgcheck.run_check(cur, empty_severe=200)
        self.assertTrue(self.has(res, '严重', '公式缓存为空', '表.xlsx'))
        self.assertEqual(self.exit_code(cur, '--empty-cache-severe', '200')[0], pkgcheck.EXIT_SEVERE)
        self.assertEqual(self.exit_code(cur, '--empty-cache-severe', '301')[0], pkgcheck.EXIT_OK)
        self.assertEqual(self.exit_code(cur, '--empty-cache-severe', '0')[0], pkgcheck.EXIT_ARGS)

    def test_cells_are_scanned_for_personal_info(self):
        data = self.xlsx_bytes({'明细': [[int(FAKE_PHONE2), ('s', 0)]]}, shared=['李女士反映重复扣款'])
        cur = self.pkg('v1', {'明细.xlsx': data})
        res = pkgcheck.run_check(cur)
        msgs = {f['check']: f['message'] for f in res['findings']}
        self.assertIn('明细!A1', msgs['明文手机号'])
        self.assertIn('明细!B1', msgs['疑似个人信息'])
        self.assertNotIn(FAKE_PHONE2, json.dumps(res, ensure_ascii=False))


class TestSensitive(Base):
    def test_secrets_are_found_and_masked(self):
        cur = self.pkg('v1', {
            'scripts/config.py': "DB = {'host': 'h', 'password': 'S3cretValue!x'}\n",
            '说明.md': '数据库口令：Abcd!2345\n',
            '.env': 'API_KEY' + '=abcd1234efgh\n',
            'run.sh': 'psql postgres://bi:pw12345' + '@db.local/x\n',
            '交接.txt': '密码是Demo@2026xx\n',
            '备忘.md': '口令为 Abc12345678\n',
        })
        res = pkgcheck.run_check(cur)
        files = sorted(fl for lv, ck, fl in self.checks(res, '严重') if ck == '明文口令/密钥')
        self.assertEqual(files, ['.env', 'run.sh', 'scripts/config.py', '交接.txt', '备忘.md', '说明.md'])
        dump = pkgcheck.format_text(res) + json.dumps(res, ensure_ascii=False)
        for raw in ('S3cretValue!x', 'Abcd!2345', 'abcd1234efgh', 'pw12345', 'Demo@2026xx', 'Abc12345678'):
            self.assertNotIn(raw, dump)

    def test_notebook_secrets(self):
        nb = {'cells': [{'cell_type': 'code', 'source': ['import pymysql\n', 'password = "Demo@2026xx"\n'], 'outputs': []},
                        {'cell_type': 'markdown', 'source': ['王先生反馈慢\n']}], 'nbformat': 4}
        cur = self.pkg('v1', {'分析.ipynb': json.dumps(nb, ensure_ascii=False),
                              '坏.ipynb': '{"cells": [ {"source": "password = \\"Zz9!abcd\\"\n"'})
        res = pkgcheck.run_check(cur)
        sev = {fl: f['message'] for f in res['findings'] for lv, ck, fl in [(f['level'], f['check'], f['file'])]
               if lv == '严重' and ck == '明文口令/密钥'}
        self.assertEqual(sorted(sev), ['分析.ipynb', '坏.ipynb'])
        self.assertIn('第 1 格第 2 行', sev['分析.ipynb'])
        self.assertTrue(self.has(res, '提醒', '疑似个人信息', '分析.ipynb'))
        self.assertNotIn('Demo@2026xx', json.dumps(res, ensure_ascii=False))

    def test_bare_token_is_only_reminder(self):
        cur = self.pkg('v1', {'info.json': '{"token": "AbCdEf' + 'GhIjKlMnOpQrStUvWxYz1", "access_token": "t-abcdef' + '123456"}\n'})
        res = pkgcheck.run_check(cur)
        self.assertTrue(self.has(res, '提醒', '疑似口令（token）', 'info.json'))
        self.assertTrue(self.has(res, '严重', '明文口令/密钥', 'info.json'))  # access_token 照样算严重

    def test_placeholders_are_not_secrets(self):
        cur = self.pkg('v1', {
            'config.py': ("DB = {'password': os.environ['DB_PWD']}\nPASSWORD = '******'\npwd = os.getcwd()\n"
                          "pwd = '" + FAKE_HOME + "/project/output'\nPWD='~/work'\n"),
            '说明.md': '密码：见 .env 文件\n口令只放在 .env 里\n',
        })
        res = pkgcheck.run_check(cur)
        self.assertEqual(self.checks(res), [])

    def test_phone_id_email(self):
        good_id = id_number('11010519491231002')
        bad_id = good_id[:-1] + ('0' if good_id[-1] != '0' else '1')
        csv = ('客户,备注\n'
               f'甲,{FAKE_PHONE}\n'
               f'乙,{good_id}\n'
               f'丙,{bad_id}\n'
               f'ding,{FAKE_EMAIL}\n'
               '戊,138****5678\n'
               f'sku,{FAKE_IOT}\n')
        cur = self.pkg('v1', {'明细.csv': csv})
        res = pkgcheck.run_check(cur)
        got = {ck: f['message'] for f in res['findings'] for ck in [f['check']] if f['level'] == '严重'}
        self.assertEqual(sorted(got), ['明文手机号', '明文身份证号', '明文邮箱'])
        self.assertIn('1 处', got['明文身份证号'])       # 校验位不对的那个不算
        self.assertIn('1 处', got['明文手机号'])         # 打过码的、物联网号段的都不算
        self.assertIn('138****5678', got['明文手机号'])
        dump = json.dumps(res, ensure_ascii=False)
        for raw in (FAKE_PHONE, good_id, 'someone@'):
            self.assertNotIn(raw, dump)

    def test_free_text_reminders(self):
        csv = '客户原话\n王先生说送货慢，电话 021-12345678\n某牌女士T恤尺码偏小\n'
        cur = self.pkg('v1', {'原话.csv': csv})
        res = pkgcheck.run_check(cur)
        f = [x for x in res['findings'] if x['check'] == '疑似个人信息'][0]
        self.assertEqual(f['level'], '提醒')
        self.assertIn('2 处', f['message'])
        self.assertNotIn('12345678', f['message'])


class TestDates(Base):
    def daily(self, start_day, n, skip=()):
        import datetime as dt
        d0 = dt.date(2026, 3, start_day)
        rows = [str(d0 + dt.timedelta(days=k)) for k in range(n) if k not in skip]
        return '扣款日期,笔数\n' + ''.join(f'{d},1\n' for d in rows)

    def test_complete_week_window_is_info_only(self):
        cur = self.pkg('v1', {'a.csv': self.daily(2, 21)})
        res = pkgcheck.run_check(cur)
        self.assertFalse(self.has(res, '提醒', '时间窗'))
        w = res['time_windows'][0]
        self.assertEqual((w['first'], w['last'], w['span_days'], w['multiple_of_7']), ('2026-03-02', '2026-03-22', 21, True))
        self.assertIn('2026-03-02（周一）～2026-03-22（周日）', w['text'])

    def test_gap_and_partial_week_are_reported(self):
        cur = self.pkg('v1', {'a.csv': self.daily(2, 20, skip=(5,))})
        res = pkgcheck.run_check(cur)
        f = [x for x in res['findings'] if x['check'] == '时间窗'][0]
        self.assertIn('跨 20 天，不是 7 的整数倍，缺 1 天：2026-03-07', f['message'])

    def test_weekly_labels(self):
        csv = '自然周_周一,笔数\n2026-01-05 00:00:00,1\n2026-01-12 00:00:00,2\n2026-01-26 00:00:00,3\n'
        cur = self.pkg('v1', {'w.csv': csv})
        res = pkgcheck.run_check(cur)
        w = res['time_windows'][0]
        self.assertEqual((w['granularity'], w['missing']), ('周', ['2026-01-19']))
        self.assertTrue(self.has(res, '提醒', '时间窗'))

    def test_single_date_is_not_a_window(self):
        cur = self.pkg('v1', {'diag.csv': '最早单,最晚单\n2026-03-02 00:01:00,2026-03-22 23:59:00\n'})
        res = pkgcheck.run_check(cur)
        self.assertFalse(self.has(res, '提醒', '时间窗'))
        self.assertIn('只有 1 个日期', res['time_windows'][0]['text'])

    def test_monthly_points_in_non_leap_february(self):
        cur = self.pkg('v1', {'m.csv': '月份,笔数\n2026-02-01,1\n2026-03-01,2\n'})
        res = pkgcheck.run_check(cur)
        w = res['time_windows'][0]
        self.assertEqual((w['granularity'], w['missing']), ('月', []))
        self.assertFalse(self.has(res, '提醒', '时间窗'))

    def test_biweekly_is_not_weekly(self):
        w = pkgcheck.describe_dates({pkgcheck.dt.date(2026, 3, 2), pkgcheck.dt.date(2026, 3, 16)})
        self.assertEqual(w['granularity'], '日')

    def test_one_time_window_finding_per_file(self):
        csv = ('订阅日期,扣款日期,到期日期\n2026-01-08,2026-01-09,2026-01-11\n'
               '2026-01-12,2026-01-15,2026-01-19\n2026-01-17,2026-01-21,2026-01-25\n')
        cur = self.pkg('v1', {'明细.csv': csv})
        res = pkgcheck.run_check(cur)
        tw = [f for f in res['findings'] if f['check'] == '时间窗']
        self.assertEqual(len(tw), 1)
        self.assertIn('另有 2 列', tw[0]['message'])
        self.assertEqual(sum(len(g['columns']) for g in res['time_windows']), 3)

    def test_same_window_in_several_files_is_one_finding(self):
        csv = 'dt,笔数\n2026-01-08,1\n2026-01-10,2\n'
        prev = self.pkg('v1', {'a.csv': csv, 'b.csv': csv})
        cur = self.pkg('v2', {'a.csv': csv, 'b.csv': csv + '2026-01-10,3\n'})
        res = pkgcheck.run_check(cur, prev)
        tw = [f for f in res['findings'] if f['check'] == '时间窗']
        self.assertEqual(len(tw), 1)
        self.assertIn('涉及 2 个文件 2 列', tw[0]['message'])
        self.assertFalse(tw[0].get('carried'))  # b.csv 改过，整条不算"上一轮已有"

    def test_hour_and_id_columns_are_not_dates(self):
        cur = self.pkg('v1', {'h.csv': '扣款小时,渠道编号\n9,1001\n10,1002\n'})
        self.assertEqual(pkgcheck.run_check(cur)['time_windows'], [])


class TestRobustness(Base):
    def test_gbk_mojibake_name_and_gbk_content(self):
        garbled = '明细.csv'.encode('gb18030').decode('cp437')
        content = '日期,地区\n2026-01-08,甲区\n2026-01-09,乙区\n'.encode('gb18030')
        cur = self.pkg('v1', {garbled: content})
        res = pkgcheck.run_check(cur)
        f = [x for x in res['findings'] if x['check'] == '文件名乱码'][0]
        self.assertIn('明细.csv', f['message'])
        self.assertEqual(res['time_windows'][0]['span_days'], 2)

    def test_unreadable_files_are_skipped_not_crashing(self):
        cur = self.pkg('v1', {'坏.xlsx': b'not a zip', 'inner.zip': b'PK\x03\x04', 'ok.csv': 'a\n1\n'})
        os.symlink('/etc/hosts', os.path.join(cur, 'link.txt'))
        os.symlink('/etc', os.path.join(cur, 'linkdir'))
        locked = os.path.join(cur, 'locked.csv')
        with open(locked, 'w') as fh:
            fh.write('a\n')
        os.chmod(locked, 0)
        res = pkgcheck.run_check(cur)
        reasons = {s['file']: s['reason'] for s in res['skipped']}
        self.assertIn('Excel 打不开', reasons['坏.xlsx'])
        self.assertIn('压缩包', reasons['inner.zip'])
        self.assertIn('软链接', reasons['link.txt'])
        self.assertIn('软链接目录', reasons['linkdir/'])
        if os.geteuid() != 0:
            self.assertIn('读取出错', reasons['locked.csv'])
        self.assertIn('本脚本不查', pkgcheck.format_text(res))

    def test_cli_args_and_json(self):
        prev = self.pkg('v1', {'结果.xlsx': b'x', '分析.md': 'a\n'})
        cur = self.pkg('v2', {'结果.xlsx': b'x', '分析.md': 'b\n已修复，Q3 单量已重算\n'})
        zip_path = os.path.join(self.tmp, '包.zip')
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.writestr('a.txt', 'a')
        self.assertEqual(self.exit_code(zip_path)[0], 2)
        self.assertEqual(self.exit_code(cur, '--prev', cur)[0], 2)
        self.assertEqual(self.exit_code(cur, '--report', os.path.join(self.tmp, 'nope.txt'))[0], 2)
        proc = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'pkgcheck.py'), cur, '--prev', prev, '--json'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, pkgcheck.EXIT_NO_RERUN, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data['not_checked'], pkgcheck.NOT_CHECKED)
        self.assertTrue(any(f['check'] == '说改了没重跑' for f in data['findings']))

    def test_text_output_states_what_is_not_checked(self):
        cur = self.pkg('v1', {'a.md': '无\n'})
        code, out = self.exit_code(cur)
        self.assertEqual(code, 0)
        self.assertIn('本脚本不查', out)
        for item in pkgcheck.NOT_CHECKED:
            self.assertIn(item, out)
        self.assertIn('未提供（不做和上一轮的对比）', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
