#!/usr/bin/env python3
"""成对快照 pairsnap.py 的回归测试：python3 tests/test_pairsnap.py（在技能目录下运行）
夹具和存放目录都在临时目录里，不碰真存放目录 ~/aaw-pairs。"""
import contextlib
import datetime
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能目录（本文件在 tests/ 下）
sys.path.insert(0, os.path.join(HERE, "scripts"))
import pairsnap as P  # noqa: E402

DELIVERED_MD = """# 一、结论摘要

第一行保留。

第二行会被删掉。

第三行保留。
第四行原样。
第五行和第六行会被合成一行。
第六行。
第七行保留。
第八行保留。
第九行保留。
第十行保留。
"""
FINAL_MD = """# 一、结论摘要

第一行保留。

第三行保留。
第四行原样。
第五、六行合成一行。
第七行保留。
新加的一行。
第八行保留。
第九行保留。
第十行保留。
"""


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "成对稿")
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def pair(self, i, ext=".md"):
        """造一对内容各不相同的稿子（sha 不重复）。"""
        d = self.write(f"d{i}{ext}", f"交付版第 {i} 份。\n共同的一行。\n")
        f = self.write(f"f{i}{ext}", f"定稿第 {i} 份。\n共同的一行。\n")
        return d, f

    def save(self, i, history=False, project="项目甲", minute=None, **kw):
        d, f = self.pair(i)
        now = datetime.datetime(2026, 3, 18, 9, 0) + datetime.timedelta(minutes=minute if minute is not None else i)
        return P.save(self.root, project, f"文档{i}", d, f, history=history, now=now, **kw)


class TestSave(Base):
    def test_files_and_index(self):
        d = self.write("交付.md", DELIVERED_MD)
        f = self.write("定稿.md", FINAL_MD)
        before = (read(d, "rb"), read(f, "rb"))
        row = P.save(self.root, "proj-a/分析", "主文档: v1/终版", d, f, source="docx_token_x", note="备注",
                     now=datetime.datetime(2026, 3, 18, 14, 30))
        out = os.path.join(self.root, row["path"])
        self.assertEqual(row["path"], os.path.join("proj-a_分析", "20260318-1430_主文档_ v1_终版"))
        self.assertNotIn("/", os.path.basename(out))
        for name in ("delivered.md", "final.md", "diff.txt", "meta.json", "delivered_src.md", "final_src.md"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        self.assertEqual((read(d, "rb"), read(f, "rb")), before)   # 原件没动
        idx = P.read_index(self.root)
        self.assertEqual(len(idx), 1)
        for k in ("id", "project", "doc", "time", "heldout", "history", "edit_ratio", "delete_blocks", "insert_blocks",
                  "replace_blocks", "delivered_chars", "final_chars", "length_ratio", "source", "note",
                  "delivered_sha256", "final_sha256"):
            self.assertIn(k, idx[0])
        self.assertEqual(idx[0]["id"], "P0001")
        self.assertEqual(idx[0]["source"], "docx_token_x")
        self.assertEqual(idx[0]["delivered_sha256"], P.sha256(d))
        meta = json.loads(read(os.path.join(out, "meta.json")))
        self.assertEqual(meta["delivered_file"], os.path.abspath(d))
        self.assertEqual(meta["edit_ratio"], row["edit_ratio"])
        diff = read(os.path.join(out, "diff.txt"))
        self.assertIn("-第二行会被删掉。", diff)
        self.assertIn("+新加的一行。", diff)

    def test_duplicate_refused(self):
        d, f = self.pair(1)
        P.save(self.root, "甲", "文档", d, f)
        with self.assertRaises(P.PairsnapError):
            P.save(self.root, "甲", "另一个名字", d, f, history=True)
        self.assertEqual(len(P.read_index(self.root)), 1)

    def test_same_minute_gets_suffix(self):
        a = self.save(1, minute=0)
        d, f = self.pair(2)
        b = P.save(self.root, "项目甲", "文档1", d, f, now=datetime.datetime(2026, 3, 18, 9, 0))
        self.assertNotEqual(a["path"], b["path"])
        self.assertTrue(b["path"].endswith("-2"))

    def test_exam_candidate(self):
        row = self.save(1, note="新稿，可当推广考题", exam_candidate=True)
        meta = json.loads(read(os.path.join(self.root, row["path"], "meta.json")))
        self.assertTrue(meta["exam_candidate"])
        self.assertFalse(meta["heldout"])
        self.assertNotIn("exam_candidate", self.save(2))

    def test_bad_inputs(self):
        d, f = self.pair(1)
        with self.assertRaises(P.PairsnapError):
            P.save(self.root, "甲", "x", d, os.path.join(self.tmp.name, "不存在.md"))
        docx = self.write("a.docx", "x")
        with self.assertRaises(P.PairsnapError):
            P.save(self.root, "甲", "x", docx, f)
        empty = self.write("空.md", "\n\n   \n")
        with self.assertRaises(P.PairsnapError):
            P.save(self.root, "甲", "x", empty, f)
        with self.assertRaises(P.PairsnapError):
            P.save(self.root, "///", "x", d, f)
        self.assertEqual(P.read_index(self.root), [])


class TestHeldout(Base):
    def test_every_third_new_pair(self):
        rows = [self.save(i) for i in range(1, 8)]
        self.assertEqual([r["heldout"] for r in rows], [False, False, True, False, False, True, False])
        self.assertEqual([r["seq"] for r in rows], [1, 2, 3, 4, 5, 6, 7])

    def test_history_not_counted(self):
        out = []
        for i, hist in enumerate([True, True, False, True, False, False, False, True], start=1):
            out.append(self.save(i, history=hist))
        hist_rows = [r for r in out if r["history"]]
        new_rows = [r for r in out if not r["history"]]
        self.assertTrue(all(r["heldout"] is False and r["seq"] is None for r in hist_rows))
        self.assertEqual([r["seq"] for r in new_rows], [1, 2, 3, 4])
        self.assertEqual([r["heldout"] for r in new_rows], [False, False, True, False])
        self.assertEqual([r["id"] for r in out], [f"P{i:04d}" for i in range(1, 9)])

    def test_history_time_from_final_mtime(self):
        d, f = self.pair(1)
        ts = datetime.datetime(2026, 1, 29, 14, 9).timestamp()
        os.utime(f, (ts, ts))
        row = P.save(self.root, "甲", "续费率", d, f, history=True)
        self.assertEqual(row["time"], "2026-01-29 14:09")
        self.assertIn("20260129-1409_续费率", row["path"])


class TestExtract(Base):
    XML = ('<title id="t1">报告标题</title><h1 id="h">一、结论与建议</h1>'
           '<p id="p1">第一段<b>加粗</b>文字。</p>'
           '<ol><li seq="1" seq-marker="1. "><b>要点一</b>说明</li><li><p>要点二</p></li></ol>'
           '<p>[[IMG:A1]]</p><img name="x.png" alt="飞书自动写的图片描述" src="tok"/>'
           '<table><thead><tr><th>指标</th><th>数值</th></tr></thead>'
           '<tbody><tr><td><p>到期订阅</p></td><td><p>2.0万</p></td></tr>'
           '<tr><td><img src="a"/></td><td><img src="b"/></td></tr></tbody></table>'
           '<whiteboard type="mermaid" path="x.mmd"></whiteboard><hr/>'
           '<p>A &amp; B</p>')
    PLAIN = ["报告标题", "# 一、结论与建议", "第一段加粗文字。", "- 要点一说明", "- 要点二",
             "指标 | 数值", "到期订阅 | 2.0万", "A & B"]
    MD = ("<title>报告标题</title>\n\n# 一、结论与建议\n\n第一段**加粗**文字。\n\n"
          "1. **要点一**说明\n2. 要点二\n\n【图】\n\n![飞书自动写的另一段描述](https://x/y?code=abc)\n\n"
          "| 指标 | 数值 |\n|-|-|\n| 到期订阅 | 2.0万 |\n| 【图】 | 【图】 |\n\n"
          "```mermaid\nflowchart LR\n  A --> B\n```\n\n---\n\nA & B\n")

    def test_xml(self):
        text, how = P.extract_text(self.write("a.xml", self.XML))
        self.assertEqual(P.text_lines(text), self.PLAIN)
        self.assertEqual(how, "xml 去标签")
        self.assertNotIn("图片描述", text)

    def test_md_same_as_xml(self):
        text, _ = P.extract_text(self.write("a.md", self.MD))
        self.assertEqual(P.text_lines(text), self.PLAIN)
        m = P.compute_metrics(P.extract_text(self.write("b.xml", self.XML))[0], text)
        self.assertEqual(m["edit_ratio"], 0)

    def test_md_code_block_kept_without_fences(self):
        text, _ = P.extract_text(self.write("c.md", "前文\n```Plain Text\n步骤1 取数\n```\n后文 15\\~40 分钟\n> 引用一句\n"))
        self.assertEqual(P.text_lines(text), ["前文", "步骤1 取数", "后文 15~40 分钟", "引用一句"])

    def test_json_lark_fetch(self):
        obj = {"ok": True, "data": {"document": {"content": self.XML, "revision_id": 3}},
               "_notice": {"update": {"message": "lark-cli 有新版本"}}}
        text, how = P.extract_text(self.write("a.json", json.dumps(obj, ensure_ascii=False)))
        self.assertEqual(P.text_lines(text), self.PLAIN)
        self.assertNotIn("新版本", text)
        self.assertEqual(how, "json 取文本字段 + 去标签")

    def test_json_generic_text_fields(self):
        obj = {"blocks": [{"type": "p", "text": "第一块"}, {"children": [{"content": "第二块"}]},
                          {"markdown": "第三块"}], "message": "不要这个"}
        text, how = P.extract_text(self.write("b.json", json.dumps(obj, ensure_ascii=False)))
        self.assertEqual(P.text_lines(text), ["第一块", "第二块", "第三块"])
        self.assertEqual(how, "json 取文本字段")

    def test_json_without_text_fails(self):
        with self.assertRaises(P.PairsnapError):
            P.extract_text(self.write("c.json", json.dumps({"ok": True, "data": {"id": 1}})))
        with self.assertRaises(P.PairsnapError):
            P.extract_text(self.write("d.json", "{不是 json"))
        with self.assertRaises(P.PairsnapError):
            P.extract_text(self.write("e.json", json.dumps({"content": "   "})))

    def test_json_data_null_or_list(self):
        # lark-cli 读取失败时 data 可能是 null 或列表：要报程序自己的错，不是 AttributeError
        for obj in ({"ok": False, "data": None, "error": {"message": "读取失败"}}, {"ok": False, "data": [1, 2]}):
            with self.assertRaises(P.PairsnapError):
                P.extract_text(self.write("n.json", json.dumps(obj, ensure_ascii=False)))
        text, _ = P.extract_text(self.write("l.json", json.dumps({"data": [{"text": "第一块"}]}, ensure_ascii=False)))
        self.assertEqual(P.text_lines(text), ["第一块"])

    def test_xml_without_text_fails(self):
        with self.assertRaises(P.PairsnapError):
            P.extract_text(self.write("f.xml", '<p></p><img src="x"/><p>[[IMG:K1]]</p>'))

    def test_txt_raw(self):
        text, how = P.extract_text(self.write("a.txt", "**原样**\n| 不动 |\n"))
        self.assertEqual(P.text_lines(text), ["**原样**", "| 不动 |"])
        self.assertEqual(how, "原文")


class TestMetrics(unittest.TestCase):
    def test_counts(self):
        m = P.compute_metrics(DELIVERED_MD, FINAL_MD)
        # 交付版非空 11 行；删 1 行、2 行换成 1 行（按 2 算）、加 1 行 → 4 行
        self.assertEqual(m["delivered_lines"], 11)
        self.assertEqual(m["final_lines"], 10)
        self.assertEqual(m["changed_lines"], 4)
        self.assertEqual(m["edit_ratio"], round(4 / 11, 4))
        self.assertEqual((m["delete_blocks"], m["insert_blocks"], m["replace_blocks"]), (1, 1, 1))
        dc = len("".join(DELIVERED_MD.split()))
        fc = len("".join(FINAL_MD.split()))
        self.assertEqual((m["delivered_chars"], m["final_chars"]), (dc, fc))
        self.assertEqual(m["length_ratio"], round(fc / dc, 4))

    def test_identical_and_large_insert(self):
        self.assertEqual(P.compute_metrics("a\n\nb\n", "a\nb\n")["edit_ratio"], 0)
        m = P.compute_metrics("a\nb\n", "a\nb\nc\nd\ne\n")
        self.assertEqual(m["edit_ratio"], 1.5)
        self.assertEqual(m["insert_blocks"], 1)


class TestFormat(Base):
    def fmt(self, a, b, ea=".md", eb=None):
        return P.format_changes(*P.load_source(self.write("fa" + ea, a)), *P.load_source(self.write("fb" + (eb or ea), b)))

    def test_md_format_only(self):
        d = self.write("交付.md", "前文\n```Plain Text\n步骤1 取数\n```\n第一段**加粗**文字。\n1. 要点一\n2. 要点二\n> 引用一句\n后文\n")
        f = self.write("定稿.md", "前文\n步骤1 取数\n第一段加粗文字。\n- 要点一\n- 要点二\n引用一句\n后文\n")
        row = P.save(self.root, "甲", "稿", d, f, now=datetime.datetime(2026, 3, 18, 9, 0))
        self.assertEqual(row["edit_ratio"], 0)               # 正文一样
        self.assertEqual(row["format_changed"], 6)           # 两行围栏、加粗、两行编号、引用
        out = os.path.join(self.root, row["path"])
        self.assertTrue(read(os.path.join(out, "diff.txt")).startswith("# 另有 6 行只动了格式"))
        fd = read(os.path.join(out, "format_diff.txt"))
        for s in ("-```Plain Text", "-第一段**加粗**文字。", "+第一段加粗文字。", "-1. 要点一", "+- 要点一", "-> 引用一句"):
            self.assertIn(s, fd)
        self.assertEqual(json.loads(read(os.path.join(out, "meta.json")))["format_changed"], 6)

    def test_format_next_to_content_change(self):
        n, _ = self.fmt("甲\n**乙**\n丙\n", "甲\n乙\n丁\n")
        self.assertEqual(n, 1)

    def test_images_and_diagrams_not_format(self):
        n, _ = self.fmt("甲\n![图](x)\n【图】\n```mermaid\nA-->B\n```\n| a | b |\n|-|-|\n| 1 | 2 |\n乙\n",
                        "甲\n| a | b |\n|:-|:-|\n| 1 | 2 |\n乙\n")
        self.assertEqual(n, 0)

    def test_xml_format_only(self):
        a = ('<p id="a1">甲</p><ol><li seq="1" seq-marker="1. ">一</li><li>二</li></ol>'
             '<table><tr><td><img src="x"/></td></tr></table><p>[[IMG:K1]]</p><p>丙</p><p></p>')
        b = '<p id="b9">甲</p><ul><li>一</li><li>二</li></ul><p><b>丙</b></p>'
        self.assertEqual(P.compute_metrics(P.extract_text(self.write("ea.xml", a))[0], P.extract_text(self.write("eb.xml", b))[0])["edit_ratio"], 0)
        n, hunks = self.fmt(a, b, ".xml")
        self.assertEqual(n, 3)                               # ol→ul 两行、加粗一行；块 id、图片、空段落不算
        self.assertIn((["</ol>", "<p>丙</p>"], ["</ul>", "<p><b>丙</b></p>"]), hunks)

    def test_json_block_ids_not_format(self):
        wrap = lambda c: json.dumps({"data": {"document": {"content": c}}}, ensure_ascii=False)
        n, _ = self.fmt(wrap('<p id="x1">甲</p><p id="x2">乙</p>'), wrap('<p id="y1">甲</p><p id="y2">乙</p>'), ".json")
        self.assertEqual(n, 0)

    def test_mixed_kinds_is_null(self):
        d = self.write("交付.xml", "<p>**甲**</p>")
        f = self.write("定稿.md", "**甲**\n")
        row = P.save(self.root, "甲", "稿", d, f)
        self.assertIsNone(row["format_changed"])
        self.assertFalse(os.path.exists(os.path.join(self.root, row["path"], "format_diff.txt")))
        self.assertFalse(read(os.path.join(self.root, row["path"], "diff.txt")).startswith("#"))


class TestIndex(Base):
    def test_bad_line_is_friendly(self):
        self.save(1)
        idx = os.path.join(self.root, "index.jsonl")
        for bad in ("{坏了\n", "123\n"):
            with open(idx, encoding="utf-8") as f:
                good = f.readline()
            with open(idx, "w", encoding="utf-8") as f:
                f.write(good + bad)
            with self.assertRaises(P.PairsnapError) as cm:
                P.read_index(self.root)
            self.assertIn("第 2 行", str(cm.exception))
            with self.assertRaises(P.PairsnapError):
                self.save(2)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(P.main(["--root", self.root, "list"]), 1)
            self.assertIn("第 2 行", err.getvalue())


class TestMark(Base):
    def save_at(self, i, mtime, **kw):
        d, f = self.pair(i)
        ts = mtime.timestamp()
        os.utime(f, (ts, ts))
        return P.save(self.root, "项目甲", f"文档{i}", d, f,
                      now=datetime.datetime(2026, 3, 18, 12, 57) + datetime.timedelta(minutes=i), **kw)

    def test_mark_last_new_as_history(self):
        self.save_at(1, datetime.datetime(2026, 2, 1, 10, 0))
        r2 = self.save_at(2, datetime.datetime(2026, 2, 26, 11, 5), exam_candidate=True)
        self.assertEqual((r2["seq"], r2["time"]), (2, "2026-03-18 12:59"))
        m = P.mark_history(self.root, "P0002", "重写稿，不该占新稿序号", now=datetime.datetime(2026, 3, 18, 15, 0))
        self.assertEqual((m["history"], m["heldout"], m["seq"], m["time"]), (True, False, None, "2026-02-26 11:05"))
        self.assertEqual(m["path"], os.path.join("项目甲", "20260226-1105_文档2"))
        self.assertTrue(m["exam_candidate"])
        self.assertEqual(m["relabeled"]["from"], {"history": False, "heldout": False, "seq": 2,
                                                  "time": "2026-03-18 12:59", "path": r2["path"]})
        self.assertEqual(m["relabeled"]["reason"], "重写稿，不该占新稿序号")
        self.assertFalse(os.path.exists(os.path.join(self.root, r2["path"])))
        meta = json.loads(read(os.path.join(self.root, m["path"], "meta.json")))
        self.assertEqual((meta["history"], meta["seq"], meta["path"]), (True, None, m["path"]))
        self.assertEqual(meta["relabeled"]["from"]["seq"], 2)
        idx = P.read_index(self.root)
        self.assertEqual([r["id"] for r in idx], ["P0001", "P0002"])
        self.assertEqual(idx[1], m)
        nxt = [self.save(i) for i in (3, 4)]                   # 接着从第 2 份数：第 3 份新稿是考题
        self.assertEqual([(r["seq"], r["heldout"]) for r in nxt], [(2, False), (3, True)])
        self.assertIn("推广考题候选", P.metrics_report(P.read_index(self.root)).split("== 历史回填")[1])

    def test_mark_refused(self):
        self.save_at(1, datetime.datetime(2026, 2, 1, 10, 0))
        self.save_at(2, datetime.datetime(2026, 2, 2, 10, 0))
        self.save(3, history=True)
        before = read(os.path.join(self.root, "index.jsonl"))
        for pid, reason, msg in (("P0001", "x", "后面又存过新稿"), ("P0003", "x", "已经是历史"),
                                 ("P0009", "x", "没有"), ("P0002", "  ", "--reason")):
            with self.assertRaises(P.PairsnapError) as cm:
                P.mark_history(self.root, pid, reason)
            self.assertIn(msg, str(cm.exception))
        self.assertEqual(read(os.path.join(self.root, "index.jsonl")), before)

    def test_mark_cli(self):
        self.save_at(1, datetime.datetime(2026, 2, 1, 10, 0))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(P.main(["--root", self.root, "mark", "--id", "P0001", "--history", "--reason", "存错了"]), 0)
        self.assertIs(json.loads(buf.getvalue())["history"], True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            P.main(["--root", self.root, "mark", "--id", "P0001", "--reason", "没写 --history"])


class TestReports(Base):
    def test_metrics_report(self):
        self.save(1, history=True, project="项目甲")
        self.save(2, history=True, project="项目乙")
        for i in range(3, 8):
            self.save(i, project="项目甲")
        self.save(8, project="项目乙")
        rows = P.read_index(self.root)
        ratios = {r["id"]: r["edit_ratio"] for r in rows}
        rep = P.metrics_report(rows)
        self.assertIn("[项目甲] 共 5 份", rep)
        self.assertIn("[项目乙] 共 1 份", rep)
        expect = sum(ratios[k] for k in ("P0005", "P0006", "P0007")) / 3
        self.assertIn(f"最近 3 份 edit_ratio 均值 {expect:.3f}", rep)
        self.assertIn("[全部项目]", rep)
        hist = rep.split("== 历史回填")[1]
        self.assertIn("P0001", hist)
        self.assertIn("P0002", hist)
        self.assertNotIn("P0003", hist)
        self.assertIn("历史 2 份", hist)
        self.assertNotIn("P0001", rep.split("== 历史回填")[0])
        only = P.metrics_report(rows, "项目乙")
        self.assertIn("P0008", only)
        self.assertNotIn("P0003", only)
        self.assertNotIn("[全部项目]", only)
        self.assertIn("没有", P.metrics_report(rows, "不存在的项目"))
        self.assertIn("考题", P.list_rows(rows))

    def test_cli_with_env_root(self):
        d = self.write("交付.md", DELIVERED_MD)
        f = self.write("定稿.md", FINAL_MD)
        old = os.environ.get("PAIRSNAP_ROOT")
        os.environ["PAIRSNAP_ROOT"] = self.root
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = P.main(["save", "--project", "甲", "--doc", "稿", "--delivered", d, "--final", f, "--note", "n"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["id"], "P0001")
            self.assertIs(out["heldout"], False)
            self.assertIn("edit_ratio", out)
            self.assertTrue(os.path.isfile(os.path.join(self.root, "index.jsonl")))
            for cmd in (["list"], ["metrics"], ["metrics", "--project", "甲"]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(P.main(cmd), 0)
                self.assertIn("P0001", buf.getvalue())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = P.main(["save", "--project", "甲", "--doc", "稿", "--delivered", d, "--final", f])
            self.assertEqual(rc, 1)
            self.assertIn("已经存过", err.getvalue())
            for i in (2, 3):                                   # 第 3 份新稿是考题：stderr 提醒哪里都要标
                d2, f2 = self.pair(i)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(P.main(["save", "--project", "甲", "--doc", f"稿{i}", "--delivered", d2, "--final", f2]), 0)
                self.assertEqual(len(out.getvalue().splitlines()), 1)   # stdout 仍是一行 JSON
            self.assertIs(json.loads(out.getvalue())["heldout"], True)
            for s in ("考题来源：P0003", "台账", "项目约定页", "项目状态", "记忆"):
                self.assertIn(s, err.getvalue())
        finally:
            if old is None:
                os.environ.pop("PAIRSNAP_ROOT", None)
            else:
                os.environ["PAIRSNAP_ROOT"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
