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


class TestNeighbourWords(LintCase):
    """“其实”撞上“其”加另一个词时不算；“几成”不加除外。"""

    lexicon = u"""# 测试台账

## 一、硬禁（lint 命中即不过）

| 禁用 | 改成 | 来源 |
|---|---|---|
| 其实 | 删 | 测试 |
| 三成 | 写百分比 | 测试 |
| 九成 | 写百分比 | 测试 |
"""

    def test_other_words_not_hit(self):
        for text in (u"及其实现方式见下表", u"订阅模式助其实现扭亏为盈", u"最接近其实际损失", u"其实施细则如下"):
            self.assertNoHit(text)

    def test_real_uses_still_hit(self):
        for text in (u"其实不然", u"这其实", u"其实现在看是对的", u"其实现实世界里更复杂", u"其实现场的客服很少",
                     u"其实现有数据已经够了", u"其实现阶段不必改", u"其实际上不难", u"其实现金流是正的", u"其实现货库存够",
                     u"其实现成的模板可以用", u"其实施工方没到"):
            self.assertHit(text, u"删")
        for text in (u"约三成的订单", u"流失九成员工", u"约三成本月到期", u"前三成本项"):      # “几成”照旧，一处除外都不加
            self.assertHit(text, u"写百分比")


class TestLongLine(LintCase):
    """一行超过 300 字（单行的飞书回读稿、很长的段落）：每一处都报，位置写第几个字。"""

    def test_every_hit_reported_with_position(self):
        text = u"<p>" + u"甲" * 320 + u"</p><p>这件事说白了</p><p>你看，那件事也说白了，你说呢</p>\n"
        hard, warn = style_lint.lint_file(self.write_doc(text, "one.xml"), self.banned)
        self.assertEqual([h[1] for h in hard], [u"说白了", u"说白了"])
        self.assertEqual(hard[0][0], u"1 第 %d 字" % (text.index(u"说白了") + 1))
        self.assertIn(u"那件事也说白了", hard[1][3])
        self.assertEqual([w[1] for w in warn], [u"你", u"你"])

    def test_short_line_still_first_hit_only(self):
        hard, _ = style_lint.lint_file(self.write_doc(u"这件事说白了，那件事也说白了\n"), self.banned)
        self.assertEqual([(h[0], h[1]) for h in hard], [(1, u"说白了")])


class TestPlaceholderOnlyCell(LintCase):
    lexicon = (u"## 一、硬禁\n\n| 禁用 | 改成 | 来源 |\n|---|---|---|\n"
               u"| …… | 只有占位 | 测试 |\n| X | 只有占位 | 测试 |\n| / | 只有分隔 | 测试 |\n")

    def test_no_rule_matches_everything(self):
        self.assertNoHit(u"普通文字 123，第三章。\n")


class TestDefensiveWarnings(unittest.TestCase):
    """防御性写法只给警告，不算硬禁；一行写清的“原因待××确认”不报。"""

    def lint(self, text):
        fd, path = tempfile.mkstemp(suffix=".md")
        with io.open(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            return style_lint.lint_file(path, [])
        finally:
            os.remove(path)

    def test_defensive_phrases_warn(self):
        for text in (u"该结论尚未书面确认。\n", u"折算系数需业务确认。\n", u"这一项需要业务确认。\n", u"请业务确认我们的理解。\n",
                     u"口径待业务确认。\n", u"尽管样本有局限，结论仍成立。\n"):
            hard, warn = self.lint(text)
            self.assertEqual(hard, [], text)
            self.assertTrue(any(u"防御性写法" in w[2] for w in warn), text)

    def test_more_defensive_phrases_warn(self):
        # 把判断交回给读者、两头都留的说法也提醒（只警告，不拦）
        for text in (u"现在还不能说带不来新单。\n", u"样本太少，还不能下结论。\n", u"影响有待进一步观察。\n",
                     u"是否推广视试点结果而定。\n", u"达到 300 台后由董事会再定。\n", u"上线时间由产品团队再行决定。\n",
                     u"实际台数可能更多，也可能更少。\n"):
            hard, warn = self.lint(text)
            self.assertEqual(hard, [], text)
            self.assertTrue(any(u"防御性写法" in w[2] for w in warn), text)

    def test_defensive_wording_no_false_alarm(self):
        for text in (u"由华东仓发货。\n", u"视频会议定在周三。\n", u"预计缺口 1.6 万，按定版预测测算。\n",
                     u"门槛由产品团队在 11-06 会上定为 3 万。\n"):
            _hard, warn = self.lint(text)
            self.assertFalse(any(u"防御性写法" in w[2] for w in warn), text)

    def test_plain_pending_line_not_warned(self):
        hard, warn = self.lint(u"原因待产品团队确认。\n原因待业务确认。\n按业务说法，口径不变。\n本周续费率提升 0.4pt。\n")
        self.assertFalse(any(u"防御性写法" in w[2] for w in warn), warn)


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

    def test_long_line_prints_position(self):
        r = self.run_cli(self.write_doc(u"<p>" + u"乙" * 320 + u"</p><p>这件事说白了</p><p>那件事也说白了</p>\n", "one.xml"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"硬禁 2 / 警告 0 ==")
        self.assertRegex(r.stdout, u"  \\[硬禁\\] L1 第 \\d+ 字 「说白了」→ 简言之   \\| ")

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


class OpeningLength(unittest.TestCase):
    """分析文档开头字数：第一章是结论、摘要这类时，量到第一张图、表或下一章之前。"""

    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # 同 LintCase：style_lint 逐行读稿的文件句柄没显式关
        self.tmp = tempfile.mkdtemp(prefix="style_lint_opening_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doc(self, body, name="doc.md"):
        p = os.path.join(self.tmp, name)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return p

    def test_counts_until_first_figure(self):
        text = u"# 标题\n\n## 一、结论与建议\n\n**一句话结论。**\n\n1. 要点一\n\n![](fig/a.png)\n\n后面很长" + u"字" * 500
        ln, cnt = style_lint.opening_length(text)
        self.assertEqual((ln, cnt), (3, len(u"一句话结论。1.要点一")))

    def test_stops_at_table_and_next_heading(self):
        self.assertEqual(style_lint.opening_length(u"一、结论与建议\n甲乙丙\n| 事项 | 建议 |\n|---|---|\n")[1], 3)
        self.assertEqual(style_lint.opening_length(u"## 一、结论\n甲乙丙丁\n\n## 二、背景\n正文")[1], 4)
        self.assertEqual(style_lint.opening_length(u"一、结论与建议\n甲乙\n二、整体表现\n正文")[1], 2)

    def test_feishu_xml_on_one_line(self):
        xml = u'<title>稿</title><h1>一、结论与建议</h1><p><b>结论一句。</b></p><p><span text-color="gray">注一句</span></p><img src="x"/><p>后文</p>'
        self.assertEqual(style_lint.opening_length(xml)[1], len(u"结论一句。注一句"))

    def test_no_conclusion_chapter_is_not_checked(self):
        self.assertIsNone(style_lint.opening_length(u"# 方法说明\n\n## 一、计算规则\n" + u"字" * 900))
        self.assertIsNone(style_lint.opening_length(u"正文一段\n1. 结论是这样\n2. 另一条\n"))      # 编号列表不是章标题

    def test_numbered_list_inside_chapter_does_not_stop(self):
        text = u"# 标题\n\n## 一、结论与建议\n\n**结论。**\n\n1. 结论甲\n2. 要点乙\n3. 要点丙\n\n![](a.png)\n"
        self.assertEqual(style_lint.opening_length(text)[1], len(u"结论。1.结论甲2.要点乙3.要点丙"))

    def test_heading_variants(self):
        self.assertEqual(style_lint.opening_length(u"## 1. 结论与建议\n甲乙丙\n\n## 2. 背景\n正文")[1], 3)
        self.assertEqual(style_lint.opening_length(u"## 摘要\n甲乙\n\n## 正文第一章\n后文")[1], 2)
        self.assertEqual(style_lint.opening_length(u"# 稿\n\n## 一、核心结论\n甲\n### 小标题\n乙丙\n## 二、背景\n后文")[1], len(u"甲小标题乙丙"))

    def test_preface_before_chapter_counts(self):
        text = u"# 标题\n\n前言五个字\n\n## 一、结论与建议\n甲乙\n\n![](a.png)\n"
        self.assertEqual(style_lint.opening_length(text), (5, 7))

    def test_conclusion_must_be_first_heading(self):
        method = (u"# 方法说明\n\n## 一、计算规则\n" + u"字" * 600 + u"\n\n![](a.png)\n\n## 二、使用说明\n"
                  + u"字" * 600 + u"\n\n## 总结\n收尾\n")
        self.assertIsNone(style_lint.opening_length(method))                                      # 方法说明末尾的总结
        self.assertIsNone(style_lint.opening_length(u"# 稿\n\n## 一、背景\n" + u"字" * 600 + u"\n\n### 结论\n甲乙\n"))   # 章里的结论小节
        xml = u"<title>稿</title><h1>背景</h1><p>" + u"字" * 600 + u"</p><h1>结论</h1><p>甲</p>"
        self.assertIsNone(style_lint.opening_length(xml))
        self.assertIsNone(style_lint.opening_length(u"# 背景\n" + u"字" * 600 + u"\n\n# 结论\n甲乙\n"))   # 没有文档标题、结论排在第二章
        self.assertEqual(style_lint.opening_length(u"# 稿名\n\n# 一、结论与建议\n甲乙丙\n\n# 二、背景\n正文")[1], 3)
        hard, _ = style_lint.lint_file(self.doc(method, "method.md"), [])
        self.assertEqual(hard, [])

    def test_keyword_needs_boundary(self):
        for head in (u"## 摘要耗时拆回单仓", u"## 结论1：先看大仓", u"# 总结报告", u"## 一、总结会纪要"):
            self.assertIsNone(style_lint.opening_length(head + u"\n" + u"字" * 900), head)
        for head in (u"## 一、结论和下一步", u"## 核心结论与建议", u"## 结论（先看这里）", u"## 一、结论摘要", u"## 结论：三句话",
                     u"## 一、结论先行", u"## 结论先行", u"一、结论建议"):
            self.assertEqual(style_lint.opening_length(head + u"\n甲乙丙\n\n![](a.png)\n")[1], 3, head)

    def test_preface_with_figure_stops_there(self):
        text = u"# 标题\n\n前言\n\n![](a.png)\n\n" + u"字" * 500 + u"\n\n## 一、结论与建议\n甲乙\n"
        self.assertEqual(style_lint.opening_length(text)[1], 2)

    def test_xml_stops_at_same_level_heading(self):
        xml = u"<title>稿</title><h1>1. 结论与建议</h1><p>甲乙丙</p><h2>小节</h2><p>丁</p><h1>2. 背景</h1><p>后文很长</p>"
        self.assertEqual(style_lint.opening_length(xml)[1], len(u"甲乙丙小节丁"))

    def test_limit_comes_from_skill(self):
        skill = self.doc(u"一、结论与建议  一句话结论 + 3 条要点，到第一张图或表之前不超过 180 字 + 示意图\n", "SKILL.md")
        self.assertEqual(style_lint.opening_limit(skill), 180)
        self.assertEqual(style_lint.opening_limit(self.doc(u"没有写上限\n", "S2.md")), style_lint.OPENING_DEFAULT)
        self.assertEqual(style_lint.opening_limit(os.path.join(self.tmp, "不存在.md")), style_lint.OPENING_DEFAULT)

    def test_limit_read_from_skill_dir(self):
        """脚本在技能目录的 scripts/ 下：读上一级的 SKILL.md；scripts/ 里另有一份时用那份。"""
        os.makedirs(os.path.join(self.tmp, "scripts"))
        os.makedirs(os.path.join(self.tmp, "references"))
        script = os.path.join(self.tmp, "scripts", "style_lint.py")
        shutil.copy(os.path.join(HERE, "scripts", "style_lint.py"), script)
        self.doc(u"## 一、硬禁\n\n| 禁用 | 改成 | 来源 |\n|---|---|---|\n| 说白了 | 简言之 | 测试 |\n",
                 os.path.join("references", "style-lexicon.md"))
        self.doc(u"标题下到第一张图或表之前不超过 20 字\n", "SKILL.md")
        draft = self.doc(u"## 一、结论与建议\n\n" + u"字" * 21 + u"\n\n![](a.png)\n", "draft.md")
        run = lambda: subprocess.run([sys.executable, script, draft], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     universal_newlines=True, encoding="utf-8")
        r = run()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(u"开头 21 字", r.stdout)
        self.assertIn(u"不超过 20 字", r.stdout)
        self.doc(u"标题下到第一张图或表之前不超过 30 字\n", os.path.join("scripts", "SKILL.md"))
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_over_limit_is_hard_and_within_is_clean(self):
        limit = style_lint.opening_limit()
        long_doc = self.doc(u"## 一、结论与建议\n\n" + u"字" * (limit + 1) + u"\n\n![](a.png)\n")
        hard, _ = style_lint.lint_file(long_doc, [])
        self.assertEqual(len(hard), 1)
        self.assertIn(u"开头 %d 字" % (limit + 1), hard[0][1])
        ok_doc = self.doc(u"## 一、结论与建议\n\n" + u"字" * limit + u"\n\n![](a.png)\n", "ok.md")
        self.assertEqual(style_lint.lint_file(ok_doc, [])[0], [])

    def test_exit_code(self):
        p = self.doc(u"## 一、结论与建议\n\n" + u"字" * 2000 + u"\n")
        r = subprocess.run([sys.executable, os.path.join(HERE, "scripts", "style_lint.py"), p],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(r.returncode, 1)
        self.assertIn(u"开头 2000 字", r.stdout.decode("utf-8"))

if __name__ == "__main__":
    unittest.main()
