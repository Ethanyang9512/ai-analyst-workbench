# -*- coding: utf-8 -*-
"""check_deck.py 的冒烟测试（需要 python-pptx；没装就整组跳过）。

运行（在技能目录下）：${AAW_PY:-python3} tests/test_check_deck.py -v
片子在临时目录里现造，不依赖任何母版；文字和数字都是虚构的。
柱图数值轴起点那组：该报不该报的依据是用 PowerPoint 实测的起点规则（见 check_deck.py 的 chart_axis_issues）。
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 技能目录（本文件在 tests/ 下）
SCRIPT = os.path.join(HERE, "scripts", "check_deck.py")

try:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Cm, Pt
    from lxml import etree                                           # python-pptx 自带的依赖
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False


@unittest.skipUnless(HAS_PPTX, "没装 python-pptx，check_deck 测试跳过")
class TestCheckDeck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="check_deck_test_")

    def tearDown(self):
        self.tmp.cleanup()

    def deck(self, name, bar_color="1A1A1A", box_top_cm=3.0, box_text="续费率 W6 起比前 5 周低约 4pt"):
        prs = Presentation()
        prs.slide_width, prs.slide_height = Cm(33.87), Cm(19.05)
        slide = prs.slides.add_slide(prs.slide_layouts[6])            # 空白版式
        tb = slide.shapes.add_textbox(Cm(2), Cm(box_top_cm), Cm(20), Cm(1.2))
        tb.text_frame.text = box_text
        tb.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
        data = CategoryChartData()
        data.categories = ["W5", "W6", "W7"]
        data.add_series("续费率", (80.3, 76.4, 76.1))
        gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Cm(2), Cm(6), Cm(16), Cm(8), data)
        fill = gf.chart.plots[0].series[0].format.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(bar_color)
        gf.chart.value_axis.minimum_scale = 0                          # 三根柱只差几个点：不写 0，第 ⑧ 项会报
        path = os.path.join(self.tmp.name, name)
        prs.save(path)
        return path

    def run_cd(self, *args):
        r = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout + r.stderr

    def test_clean_deck_passes(self):
        code, out = self.run_cd(self.deck("ok.pptx"))
        self.assertEqual(code, 0, out)
        self.assertIn("全部通过", out)
        self.assertIn("页脚条 未给，不查", out)

    def test_footer_only_checked_when_given(self):
        path = self.deck("low.pptx", box_top_cm=17.6)                  # 框底沿 18.8cm，在页面内
        self.assertEqual(self.run_cd(path)[0], 0)
        code, out = self.run_cd(path, "--footer-top", "18.16")
        self.assertEqual(code, 1, out)
        self.assertIn("压页脚条", out)

    def test_off_palette_chart_color_is_hint_only(self):
        path = self.deck("brand.pptx", bar_color="0055AA")
        code, out = self.run_cd(path)
        self.assertEqual(code, 0, out)                                 # 只提示，不计入失败
        self.assertIn("#0055AA", out)
        code, out = self.run_cd(path, "--palette", "0055AA,FFFFFF")
        self.assertNotIn("#0055AA", out)
        code, out = self.run_cd(path, "--palette", "none")
        self.assertNotIn("配色表以外", out)

    def test_terms_blacklist(self):
        path = self.deck("terms.pptx", box_text="这里有一个自造词：抓手")
        code, out = self.run_cd(path, "--terms", "抓手,赋能")
        self.assertEqual(code, 1, out)
        self.assertIn("抓手", out)


C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"


@unittest.skipUnless(HAS_PPTX, "没装 python-pptx，check_deck 测试跳过")
class TestBarAxisZero(unittest.TestCase):
    """⑧ 原生柱形图、条形图的数值轴要从 0 起。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="check_deck_axis_")

    def tearDown(self):
        self.tmp.cleanup()

    def chart_deck(self, name, kind, series, low=None, clear_first=False, line_last=False, log=False, charts=1, grouped=False):
        """一页原生图。series = [(系列名, [各类的值]), ...]；low 不是 None 时把数值轴最小值写成它；
        clear_first 把第一个系列设成透明；line_last 把最后一个系列改成同一根轴上的折线；log 把数值轴改成对数轴；
        charts 是这一页放几张同样的图；grouped 把图放进一个组合里。"""
        prs = Presentation()
        prs.slide_width, prs.slide_height = Cm(33.87), Cm(19.05)
        s = prs.slides.add_slide(prs.slide_layouts[6])
        shapes = s.shapes.add_group_shape().shapes if grouped else s.shapes
        for k in range(charts):
            data = CategoryChartData()
            data.categories = ["类%d" % (i + 1) for i in range(len(series[0][1]))]
            for nm, vals in series:
                data.add_series(nm, vals)
            ch = shapes.add_chart(kind, Cm(1 + k * 10), Cm(3), Cm(9.5), Cm(9), data).chart
            if low is not None:
                ch.value_axis.minimum_scale = low
            if clear_first:
                ch.plots[0].series[0].format.fill.background()
            plot = ch._chartSpace.find(".//" + C + "plotArea")
            if line_last:
                bar = plot.find(C + "barChart")
                ser = bar.findall(C + "ser")[-1]
                bar.remove(ser)
                for el in ser.findall(C + "invertIfNegative"):
                    ser.remove(el)
                line = etree.Element(C + "lineChart")
                etree.SubElement(line, C + "grouping").set("val", "standard")
                etree.SubElement(line, C + "varyColors").set("val", "0")
                line.append(ser)
                etree.SubElement(line, C + "marker").set("val", "1")
                for a in bar.findall(C + "axId"):
                    etree.SubElement(line, C + "axId").set("val", a.get("val"))
                bar.addnext(line)
            if log:
                scaling = plot.find(C + "valAx").find(C + "scaling")
                lb = etree.Element(C + "logBase")
                lb.set("val", "10")
                scaling.insert(0, lb)
        path = os.path.join(self.tmp.name, name)
        prs.save(path)
        return path

    def axis(self, name, kind, series, **kw):
        """跑一遍，返回 (退出码, 第 ⑧ 项报了几处, 第 ⑧ 项那几行)。"""
        r = subprocess.run([sys.executable, SCRIPT, self.chart_deck(name, kind, series, **kw)],
                           capture_output=True, text=True, encoding="utf-8")
        lines = []
        for ln in (r.stdout + r.stderr).split("柱图数值轴起点")[1].split("\n")[1:]:
            if not ln.startswith("   "):
                break
            lines.append(ln)
        return r.returncode, len([ln for ln in lines if "→" in ln]), lines

    def test_cases(self):
        COL, STK, PCT, LINE, BAR, BARSTK = (XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.COLUMN_STACKED,
                                            XL_CHART_TYPE.COLUMN_STACKED_100, XL_CHART_TYPE.LINE,
                                            XL_CHART_TYPE.BAR_CLUSTERED, XL_CHART_TYPE.BAR_STACKED)
        near = [("甲", [100, 101, 103, 102, 100.5, 98])]
        bridge = [("下", [0, 80, 83, 0]), ("上", [80, 3, 2, 85])]
        gap = [("下", [None, 80, 83, None]), ("上", [80, 3, 2, 85])]
        band = [("下", [102, 112, 113]), ("宽", [8, 6, 9])]
        cases = [   # (说明, 文件名, 图类型, 系列, 其他参数, 该报几处)
            ("同一张窄幅柱图把最小值写成 0：过", "near0", COL, near, dict(low=0), 0),
            ("两柱差 17%、没写最小值：不报（PowerPoint 从 0 起）", "d17", COL, [("甲", [100, 83])], {}, 0),
            ("两柱差 16%、没写最小值：报", "d16", COL, [("甲", [100, 84])], {}, 1),
            ("有负数的图：不查", "neg", COL, [("甲", [-30, -8, -1])], dict(low=-40), 0),
            ("各柱一样高：不报", "same", COL, [("甲", [12.5, 12.5, 12.5])], {}, 0),
            ("只有一根柱：不报", "one", COL, [("甲", [89])], {}, 0),
            ("折线图：不查", "line", LINE, near, {}, 0),
            ("横向条形图差 10%：报", "barh", BAR, [("甲", [100, 90])], {}, 1),
            ("簇状两个系列、一大一小：不报（小的那组把范围拉开了）", "two", COL, [("甲", [100, 98]), ("乙", [5, 6])], {}, 0),
            ("堆积柱 下段 50/100、上段 60/12（按每段叠到的高度算）：不报", "stk_a", STK, [("下", [50, 100]), ("上", [60, 12])], {}, 0),
            ("堆积柱 下段 100/100、上段 5/8：报", "stk_c", STK, [("下", [100, 100]), ("上", [5, 8])], {}, 1),
            ("透明下段拼的瀑布图（首尾下段是 0）、没写最小值：不报", "bridge", STK, bridge, dict(clear_first=True), 0),
            ("瀑布图透明下段首尾留空、没写最小值：不报（PowerPoint 照样从 0 起）", "gap", STK, gap, dict(clear_first=True), 0),
            ("同上、最小值写成 70：报（不当成区间条放过）", "gap70", STK, gap, dict(clear_first=True, low=70), 1),
            ("透明下段托起的区间条（下段都大于 0）：不查", "band", BARSTK, band, dict(clear_first=True), 0),
            ("同上、写了最小值 90：也不报", "band90", BARSTK, band, dict(clear_first=True, low=90), 0),
            ("同样的数、下段不透明：照查", "band_solid", BARSTK, band, {}, 1),
            ("百分比堆积：不查", "pct", PCT, [("下", [70, 69, 68]), ("上", [30, 31, 32])], {}, 0),
            ("柱加同轴折线、折线的值很小：不报（折线把范围拉开了）", "combo", COL, [("柱", [100, 101, 103]), ("线", [2, 5, 7])],
             dict(line_last=True), 0),
            ("柱加同轴折线、折线也挨着柱顶：报", "combo2", COL, [("柱", [100, 101, 103]), ("线", [99, 100, 102])],
             dict(line_last=True), 1),
            ("对数轴：不查", "log", COL, [("甲", [100, 300])], dict(low=1, log=True), 0),
            ("组合里的窄幅柱图：照查", "group", COL, near, dict(grouped=True), 1),
        ]
        for what, name, kind, series, kw, want in cases:
            with self.subTest(what):
                code, hits, lines = self.axis(name + ".pptx", kind, series, **kw)
                self.assertEqual((code, hits), (1 if want else 0, want), "\n".join(lines))

    def test_message_says_how_to_fix(self):
        code, hits, lines = self.axis("near.pptx", XL_CHART_TYPE.COLUMN_CLUSTERED, [("甲", [100, 101, 103, 102, 100.5, 98])])
        txt = " ".join(lines)
        self.assertEqual((code, hits), (1, 1), txt)
        self.assertIn("没写最小值", txt)
        self.assertIn("minimum_scale = 0", txt)

    def test_explicit_low_is_named(self):
        code, hits, lines = self.axis("cut.pptx", XL_CHART_TYPE.COLUMN_CLUSTERED, [("甲", [50, 58])], low=40)
        self.assertEqual((code, hits), (1, 1))
        self.assertIn("从 40 起", " ".join(lines))
        bridge = [("下", [0, 80, 83, 0]), ("上", [80, 3, 2, 85])]
        code, hits, lines = self.axis("bridge70.pptx", XL_CHART_TYPE.COLUMN_STACKED, bridge, clear_first=True, low=70)
        self.assertEqual((code, hits), (1, 1))
        self.assertIn("从 70 起", " ".join(lines))

    def test_each_chart_on_a_slide_reported_by_name(self):
        code, hits, lines = self.axis("three.pptx", XL_CHART_TYPE.COLUMN_CLUSTERED, [("甲", [100, 101, 103])], charts=3)
        self.assertEqual((code, hits), (1, 3))
        self.assertEqual(len(set(ln.split(":")[0] for ln in lines if "→" in ln)), 3)


if __name__ == "__main__":
    unittest.main()
