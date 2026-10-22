# -*- coding: utf-8 -*-
"""trace_scan.py 的回归测试（只用标准库）：python3 tests/test_trace_scan.py（在技能目录下运行）。"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能目录（本文件在 tests/ 下）
sys.path.insert(0, os.path.join(HERE, "scripts"))
import trace_scan  # noqa: E402


class TraceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="trace_scan_test_")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def kinds(self, text, allow=(), names=()):
        hard, soft = trace_scan.scan(self.write("d.md", text), set(allow), names)
        return [k for _, k, _, _ in hard], [k for _, k, _, _ in soft]

    def test_builtin_collaborators(self):
        for word in ("分析助手", "取数助手", "Claude", "Codex", "ChatGPT"):
            with self.subTest(word=word):
                self.assertEqual(self.kinds(f"本页数字由{word}复核")[0], ["协作方"])

    def test_latin_code_names_need_letter_boundaries(self):
        names = ["BB"]                                                        # 假代号，用 --names 补
        self.assertEqual(self.kinds("本页数字由BB复核", names=names)[0], ["协作方"])
        self.assertEqual(self.kinds("前10个商品里有一款BB霜", names=names)[0], ["协作方"])   # 紧挨汉字照算
        self.assertEqual(self.kinds("前10个商品里有一款BB霜", allow=["BB"], names=names)[0], [])   # 确属业务用词就 --allow 放行
        self.assertEqual(self.kinds("ABBA 表", names=names)[0], [])                     # 前后是字母才不算

    def test_names_option_adds_your_own(self):
        self.assertEqual(self.kinds("这版数据由阿明补的")[0], [])
        self.assertEqual(self.kinds("这版数据由阿明补的", names=["阿明"])[0], ["协作方"])

    def test_local_paths(self):
        users, home = "/" + "Users/", "/" + "home/"                           # 拼起来写，免得仓库自查时把夹具当成真路径
        for text in ("见 " + users + "someone/x.md", "见 " + home + "someone/x.md", "见 C:\\" + "Users\\someone\\x.md",
                     "改了 _status.md", "放在 round3_ 目录"):
            with self.subTest(text=text):
                self.assertIn("本机路径", self.kinds(text)[0])

    def test_round_numbers_and_soft_ids(self):
        self.assertEqual(self.kinds("R20 的数")[0], ["内部轮次号"])
        self.assertEqual(self.kinds("R20 的数", allow=["R20"])[0], [])
        self.assertEqual(self.kinds("见 S6 包")[1], ["疑似内部包号"])

    def test_clean_text(self):
        self.assertEqual(self.kinds("一、结论与建议\n续费率 W6 起比前 5 周低约 4pt。\n"), ([], []))

    def test_pptx_text_is_read(self):
        path = os.path.join(self.tmp.name, "d.pptx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>本页由取数助手提供</a:t></p:sld>")
            z.writestr("ppt/notesSlides/notesSlide1.xml", "<p:notes><a:t>R3 回包</a:t></p:notes>")
        hard, _ = trace_scan.scan(path, set())
        self.assertEqual(sorted((w, k) for w, k, _, _ in hard),
                         [("第1页", "协作方"), ("第1页备注", "内部轮次号"), ("第1页备注", "过程用词")])

    def test_cli_exit_codes(self):
        script = os.path.join(HERE, "scripts", "trace_scan.py")
        dirty = self.write("dirty.md", "R2 的需求包\n")
        clean = self.write("clean.md", "正文\n")
        run = lambda *a: subprocess.run([sys.executable, script, *a], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run(dirty).returncode, 1)
        self.assertEqual(run(clean).returncode, 0)
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run(self.write("n.md", "阿明\n"), "--names", "阿明").returncode, 1)


if __name__ == "__main__":
    unittest.main()
