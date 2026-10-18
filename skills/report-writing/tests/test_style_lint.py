# -*- coding: utf-8 -*-
"""style_lint 的回归测试（只用标准库）。

用法（在技能目录下）: python3 tests/test_style_lint.py   或   python3 -m unittest discover -s tests -p "test_style_lint.py" -v
夹具是测试自己写的小台账，不依赖线上 style-lexicon.md 的具体条目；
只有最后一条集成测试读同目录的真台账，且只断言"能解析、不报错"。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能目录（本文件在 tests/ 下）
sys.path.insert(0, os.path.join(HERE, "scripts"))
import style_lint  # noqa: E402

FIXTURE = u"""# 测试台账

## 一、硬禁（lint 命中即不过）

| 禁用 | 改成 | 来源 |
|---|---|---|
| 说白了 | 简言之 | 测试 |
| 断崖式 / 断崖 | 明显 | 测试 |
| 甲方／乙方/丙方 | 合作方 | 测试 |
| 需要…说明的是 | 另外 | 测试 |
| 原因……很简单 | 原因为 | 测试 |
| 一方面...另一方面 | 删 | 测试 |
| 第X章 | 去掉章号 | 测试 |
| UX走查 | 体验检查 | 测试 |
| 需要 … 区分的是 | 删澄清句 | 测试 |
| 第 X 节 | 去掉章号 | 测试 |

## 二、启发式（lint 报警告，人工判断）

| 禁用 | 改成 | 来源 |
|---|---|---|
| 启发式表里的词 | 不该被当硬禁 | 测试 |

## 2026-01-30 · 某项目（新增硬性词表）

| 禁用 | 改成 |
|---|---|
| 日期小节里的词 | 不该被当硬禁 |
"""


class LintCase(unittest.TestCase):
    """每条用例一个临时目录：写夹具台账，再按需写稿件。"""

    lexicon = FIXTURE

    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # style_lint 原有的文件句柄没显式关，与本次修改无关
        self.tmp = tempfile.mkdtemp(prefix="style_lint_test_")
        self.lex_path = os.path.join(self.tmp, "style-lexicon.md")
        with io.open(self.lex_path, "w", encoding="utf-8") as f:
            f.write(self.lexicon)
        self.banned = style_lint.load_banned(self.lex_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_doc(self, text, name="doc.md"):
        path = os.path.join(self.tmp, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def hits(self, text):
        """返回 [(行号, 命中的原文片段, 改法)]。"""
        hard, _ = style_lint.lint_file(self.write_doc(text), self.banned)
        return [(ln, term, fix) for ln, term, fix, _ctx in hard]

    def assertHit(self, text, fix):
        got = [h for h in self.hits(text) if h[2] == fix]
        self.assertTrue(got, u"应命中「%s」规则却没拦住：%s" % (fix, text))
        return got

    def assertNoHit(self, text):
        self.assertEqual(self.hits(text), [], u"不该命中：%s" % text)


class TestSplit(LintCase):
    def test_slash_with_spaces(self):
        self.assertEqual(self.assertHit(u"本周断崖式下降 2pt", u"明显")[0][1], u"断崖式")
        self.assertEqual(self.assertHit(u"笔数断崖下降", u"明显")[0][1], u"断崖")

    def test_fullwidth_and_halfwidth_slash(self):
        for word in (u"甲方", u"乙方", u"丙方"):
            got = self.assertHit(u"与%s沟通后确认" % word, u"合作方")
            self.assertEqual(got[0][1], word)

    def test_one_hit_per_row_per_line(self):
        # 同一行里同一条规则的几个写法都出现，仍只记一次（和原来"一条一行一次"一致）
        got = self.assertHit(u"断崖式与断崖都要看", u"明显")
        self.assertEqual(len(got), 1)

    def test_original_joined_text_not_needed(self):
        # 原来要整串"断崖式 / 断崖"出现才命中；现在拆开后单写也能拦住
        self.assertHit(u"断崖", u"明显")


class TestEllipsisGap(LintCase):
    def test_variants_hit(self):
        for text in (u"需要说明的是，本期口径不变",
                     u"需要单独说明的是，本期口径不变",
                     u"需要特别说明的是，本期口径不变"):
            got = self.assertHit(text, u"另外")
            self.assertTrue(got[0][1].startswith(u"需要") and got[0][1].endswith(u"说明的是"))

    def test_double_ellipsis(self):
        self.assertHit(u"原因其实很简单：", u"原因为")
        self.assertHit(u"原因很简单：", u"原因为")
        # "……"是一个省略号，夹字上限照样是 MAX_GAP，不是两倍
        self.assertNoHit(u"原因" + u"甲" * (style_lint.MAX_GAP + 1) + u"很简单")

    def test_ascii_dots(self):
        self.assertHit(u"一方面看成本另一方面看时效", u"删")
        self.assertNoHit(u"一方面看成本，另一方面看时效")

    def test_gap_upper_bound(self):
        n = style_lint.MAX_GAP
        self.assertHit(u"需要" + u"甲" * n + u"说明的是", u"另外")
        self.assertNoHit(u"需要" + u"甲" * (n + 1) + u"说明的是")

    def test_spaces_around_placeholder_in_rule(self):
        # 台账里写成"需要 … 区分的是""第 X 节"，占位两边的空格不当实字
        self.assertHit(u"需要区分的是", u"删澄清句")
        self.assertHit(u"需要特别区分的是", u"删澄清句")
        self.assertHit(u"见第3节", u"去掉章号")

    def test_gap_counts_spaces(self):
        self.assertHit(u"需要对 B 区说明的是", u"另外")

    def test_gap_does_not_cross_punctuation_or_table_cell(self):
        self.assertNoHit(u"这一步需要复核。说明的是另一件事")
        self.assertNoHit(u"需要，说明的是")
        self.assertNoHit(u"| 需要 | 说明的是 |")


class TestNumberPlaceholder(LintCase):
    def test_numbers_hit(self):
        for text, frag in ((u"见第3章", u"第3章"), (u"见第12章", u"第12章"),
                           (u"见第三章", u"第三章"), (u"见第十二章", u"第十二章"),
                           (u"见第 3 章", u"第 3 章"), (u"见第３章", u"第３章")):
            got = self.assertHit(text, u"去掉章号")
            self.assertEqual(got[0][1], frag)

    def test_non_numbers_not_hit(self):
        self.assertNoHit(u"见第一部分")
        self.assertNoHit(u"见第几章")
        self.assertNoHit(u"第章")

    def test_x_inside_latin_word_stays_literal(self):
        self.assertHit(u"上线前做一次UX走查", u"体验检查")
        self.assertNoHit(u"上线前做一次U3走查")


class TestPlainAndScope(LintCase):
    def test_plain_term_still_hits(self):
        got = self.assertHit(u"这件事说白了", u"简言之")
        self.assertEqual(got, [(1, u"说白了", u"简言之")])

    def test_line_numbers(self):
        got = self.hits(u"第一行正常\n第二行说白了\n")
        self.assertEqual([h[0] for h in got], [2])

    def test_only_hard_section_is_read(self):
        terms = u" ".join(t for t, _f, _p in self.banned)
        self.assertNotIn(u"启发式表里的词", terms)
        self.assertNotIn(u"日期小节里的词", terms)
        self.assertNoHit(u"启发式表里的词；日期小节里的词")

    def test_normal_text_no_false_positive(self):
        self.assertNoHit(
            u"一、结论与建议\n"
            u"本周续费率较上周提升 0.4pt，改善主要来自月付方案。\n"
            u"另外，第一部分列出口径，下一部分给出分渠道明细。\n"
            u"| 渠道 | 到期订阅 | 变化(pt) |\n|---|---|---|\n| 官网 | 1.2万 | +0.3 |\n")


class TestPlaceholderOnlyCell(LintCase):
    lexicon = (u"## 一、硬禁\n\n| 禁用 | 改成 | 来源 |\n|---|---|---|\n"
               u"| …… | 只有占位 | 测试 |\n| X | 只有占位 | 测试 |\n| / | 只有分隔 | 测试 |\n")

    def test_no_rule_matches_everything(self):
        self.assertNoHit(u"普通文字 123，第三章。\n")


class TestCli(LintCase):
    """把脚本拷进临时目录，让它读夹具台账，验证退出码和输出格式。"""

    def setUp(self):
        super(TestCli, self).setUp()
        self.script = os.path.join(self.tmp, "style_lint.py")
        shutil.copy(os.path.join(HERE, "scripts", "style_lint.py"), self.script)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, self.script] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, encoding="utf-8")

    def test_exit_1_on_hard_hit(self):
        r = self.run_cli(self.write_doc(u"需要特别说明的是，口径不变\n"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"硬禁 1 / 警告 0 ==")
        self.assertRegex(r.stdout, u"  \\[硬禁\\] L1 「需要特别说明的是」→ 另外   \\| ")

    def test_exit_0_on_clean(self):
        r = self.run_cli(self.write_doc(u"本周续费率提升 0.4pt\n"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(u"硬禁 0 / 警告 0", r.stdout)

    def test_warning_does_not_block(self):
        r = self.run_cli(self.write_doc(u"你可以看第一部分\n"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(u"[警告] L1", r.stdout)

    def test_multiple_files_any_hit_exits_1(self):
        clean = self.write_doc(u"正常\n", "a.md")
        dirty = self.write_doc(u"第3章\n", "b.md")
        r = self.run_cli(clean, dirty)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_no_args_exit_2(self):
        self.assertEqual(self.run_cli().returncode, 2)


class TestRealLexicon(unittest.TestCase):
    """读同目录真台账：规则作者可能同时在改它，只断言能解析、能跑、不报错。"""

    def test_parses_and_runs(self):
        warnings.simplefilter("ignore", ResourceWarning)
        banned = style_lint.load_banned()
        self.assertIsInstance(banned, list)
        for term, fix, pat in banned:
            self.assertTrue(hasattr(pat, "search"))
        tmp = tempfile.mkdtemp(prefix="style_lint_real_")
        try:
            doc = os.path.join(tmp, "doc.md")
            with io.open(doc, "w", encoding="utf-8") as f:
                f.write(u"一、结论与建议\n本周续费率提升 0.4pt。\n")
            style_lint.lint_file(doc, banned)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
