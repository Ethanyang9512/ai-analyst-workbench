"""status_preview.py 测试：预览内容、子项目、越界引用、退出码与耗时。
运行：python3 test_status_preview.py"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent/'status_preview.py'
HEADER = '## 工作区状态预览（新会话自动附带）'

def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, timeout=10)

class StatusPreviewTests(unittest.TestCase):
    def preview(self, workspace):
        r = run(workspace)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, b'')
        return r.stdout.decode('utf-8')

    def test_latest_local_boundary_reaches_agent_without_full_history(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            p.write_text('# 最新\n只讨论结构，等待取数助手回包。\n\n---\n\n# 旧记录\nOLD_COMPLETED_VERSION\n'+'历史'*20000)
            before=p.read_bytes();files=sorted(w.iterdir());prompt=self.preview(w)
            self.assertTrue(prompt.startswith(HEADER+'\n'))
            self.assertIn('只讨论结构，等待取数助手回包。',prompt)
            self.assertNotIn('OLD_COMPLETED_VERSION',prompt)
            self.assertIn(f'以下是 {p} 的部分预览',prompt)
            self.assertIn('不保证最新内容在前',prompt)
            self.assertEqual(before,p.read_bytes())
            self.assertEqual(files,sorted(w.iterdir()))

    def test_append_only_status_exposes_latest_tail_without_asserting_order(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            p.write_text('# 项目状态\n2026-01-05：等待早期决策\n'+('历史条目\n'*2000)+'## 2026-01-15 中段决定\n'
                         +('历史条目\n'*2000)+'\n## 2026-01-23\n最新决定：只更新文档，PPT待指令。\n')
            prompt=self.preview(w)
            self.assertTrue('最新决定：只更新文档，PPT待指令。' in prompt, '追加在末尾的最新决定必须可见')
            self.assertIn('位置不代表时间顺序',prompt)
            self.assertIn('首部',prompt)
            self.assertIn('尾部',prompt)
            self.assertIn('L2003: ## 2026-01-15 中段决定',prompt)
            self.assertLess(prompt.count('历史条目'),1000)

    def test_large_status_explicitly_reports_omission(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();(w/'_status.md').write_text('# 当前\n'+('长条目\n'*5000))
            prompt=self.preview(w)
            self.assertIn('预览不完整',prompt)
            self.assertLess(prompt.count('长条目'),1500)

    def test_small_status_is_complete_and_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();(w/'_status.md').write_text('# 当前\n等待材料_A\n')
            prompt=self.preview(w)
            self.assertIn('等待材料_A',prompt)
            self.assertNotIn('预览不完整',prompt)
            self.assertEqual(prompt,self.preview(w))

    def test_missing_status_prints_nothing_and_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve()
            self.assertEqual(self.preview(w),'')
            self.assertFalse((w/'_status.md').exists())
            self.assertEqual(self.preview(w/'no-such-dir'),'')

    def test_explicit_child_status_is_previewed_with_source(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve(); sub=w/'project';sub.mkdir()
            (w/'_status.md').write_text('# 入口\n当前项目状态在 `project/_status.md`。\n')
            child=sub/'_status.md';child.write_text('# 2026-02-02 当前\nCHILD_NEW_DECISION：已核验，暂不发 PPT。\n')
            (sub/'_CONVENTIONS.md').write_text('rules')
            before=child.read_bytes();prompt=self.preview(w)
            self.assertIn('CHILD_NEW_DECISION',prompt)
            self.assertIn(f'### 来源：{child}',prompt)
            self.assertIn('补充其预览',prompt)
            self.assertIn(f'子项目约定来源（操作前按需读取）：{sub/"_CONVENTIONS.md"}',prompt)
            self.assertEqual(before,child.read_bytes())

    def test_external_and_symlinked_state_are_not_auto_loaded(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            w=Path(d).resolve();outside=Path(other);(outside/'_status.md').write_text('OTHER_CHAT_PRIVATE_STATE')
            (w/'linked').symlink_to(outside,target_is_directory=True)
            (w/'_status.md').write_text(f'# 入口\n`linked/_status.md`\n`../_status.md`\n`{outside}/_status.md`\n')
            prompt=self.preview(w)
            self.assertNotIn('OTHER_CHAT_PRIVATE_STATE',prompt)

    def test_multiple_children_stay_navigation_not_combined_context(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve()
            for n in ['a','b']:
                (w/n).mkdir();(w/n/'_status.md').write_text('PRIVATE_DETAIL_'+n)
            (w/'_status.md').write_text('# 多项目入口\n`a/_status.md` 与 `b/_status.md`\n')
            prompt=self.preview(w)
            self.assertNotIn('PRIVATE_DETAIL_a',prompt)
            self.assertNotIn('PRIVATE_DETAIL_b',prompt)
            self.assertIn('多个子项目',prompt)

    def test_duplicate_child_reference_loads_once(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();(w/'a').mkdir();(w/'a'/'_status.md').write_text('UNIQUE_CHILD_DECISION')
            (w/'_status.md').write_text('`a/_status.md`\n`a/_status.md`')
            prompt=self.preview(w)
            self.assertEqual(prompt.count('UNIQUE_CHILD_DECISION'),1)

    def test_parent_and_child_preview_remain_bounded_and_show_latest_tail(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();(w/'a').mkdir()
            (w/'_status.md').write_text('# 入口\n`a/_status.md`\n'+'ROOT_HISTORY_LINE\n'*4000)
            (w/'a'/'_status.md').write_text('# 子项目\n'+'CHILD_HISTORY_LINE\n'*4000+'\n## 2026-02-02\nLATEST_CHILD_END')
            prompt=self.preview(w)
            self.assertIn('LATEST_CHILD_END',prompt)
            self.assertLess(prompt.count('ROOT_HISTORY_LINE')+prompt.count('CHILD_HISTORY_LINE'),400)

    def test_always_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md';p.write_text('# 当前\nSECRET_IF_LEAKED\n')
            os.chmod(p,0)
            try:
                r=run(w)
            finally:
                os.chmod(p,0o600)
            self.assertEqual((r.returncode,r.stdout),(0,b''))
            self.assertIn(b'PermissionError',r.stderr)
            p.write_bytes(b'# \xff\xfe bad utf8\nKEPT\n')
            self.assertIn('KEPT',self.preview(w))
            r=run()
            self.assertEqual((r.returncode,r.stdout),(0,b''))

    def test_one_megabyte_status_finishes_within_two_seconds(self):
        block=''.join(f'## 2026-{m:02d}-{d:02d} 进展\n`x{d}/_status.md` 历史条目 HISTORY\n---\n'
                      for m in range(1,13) for d in range(1,29))
        for text in [block*(1_000_000//len(block.encode())+1), '`'+'历史 `a/_status.md'*60000]:
            with tempfile.TemporaryDirectory() as d:
                w=Path(d).resolve();(w/'_status.md').write_text(text)
                self.assertGreaterEqual((w/'_status.md').stat().st_size,1_000_000)
                start=time.monotonic();prompt=self.preview(w);elapsed=time.monotonic()-start
                self.assertLess(elapsed,2,f'{elapsed:.2f}s')
                self.assertIn('预览不完整',prompt)
                self.assertLess(len(prompt),10000)

    # ---- 「现状摘要」标记块 ----
    SUMMARY_HEAD='<!-- 现状摘要:开始 -->\n## 现状摘要（更新于 %s）\n- 目标：SUMMARY_GOAL\n- 下一步：SUMMARY_NEXT\n<!-- 现状摘要:结束 -->\n'

    def test_summary_block_replaces_head_tail_excerpt(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            stamp=time.strftime('%Y-%m-%d %H:%M')
            p.write_text(self.SUMMARY_HEAD%stamp+'\n# 历史\nOLD_HEAD_NOTE\n'+'历史条目\n'*5000+'TAIL_NOTE\n')
            before=p.read_bytes();prompt=self.preview(w)
            self.assertTrue(prompt.startswith(HEADER+'\n'))
            self.assertIn('SUMMARY_GOAL',prompt);self.assertIn('SUMMARY_NEXT',prompt)
            self.assertNotIn('OLD_HEAD_NOTE',prompt);self.assertNotIn('TAIL_NOTE',prompt)
            self.assertNotIn('首部摘录',prompt);self.assertNotIn('可能过期',prompt)
            self.assertLess(len(prompt),1500)
            self.assertEqual(before,p.read_bytes())

    def test_summary_block_warns_when_files_are_newer(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            p.write_text(self.SUMMARY_HEAD%'2026-01-01 08:00'+'# 历史\n')
            (w/'out').mkdir();(w/'out'/'report_v2.md').write_text('new')
            (w/'.hidden').mkdir();(w/'.hidden'/'x').write_text('ignored')
            prompt=self.preview(w)
            self.assertIn('可能过期',prompt);self.assertIn('out/report_v2.md',prompt)
            self.assertIn('SUMMARY_GOAL',prompt)

    def test_summary_block_without_time_or_only_hidden_changes(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            p.write_text('<!-- 现状摘要:开始 -->\n## 现状摘要\nNO_TIME\n<!-- 现状摘要:结束 -->\n')
            self.assertIn('没有写“更新于”时间',self.preview(w))
            p.write_text(self.SUMMARY_HEAD%'2026-01-01 08:00')
            (w/'.claude').mkdir();(w/'.claude'/'settings.json').write_text('{}')
            self.assertNotIn('可能过期',self.preview(w))

    def test_incomplete_or_empty_marker_falls_back_to_old_preview(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            p.write_text('<!-- 现状摘要:开始 -->\n# 当前\n等待材料_B\n')
            prompt=self.preview(w)
            self.assertIn('等待材料_B',prompt);self.assertIn('位置不代表时间顺序',prompt)
            p.write_text('<!-- 现状摘要:开始 -->\n\n<!-- 现状摘要:结束 -->\n# 当前\n等待材料_C\n')
            self.assertIn('位置不代表时间顺序',self.preview(w))

    def test_child_status_summary_block_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();sub=w/'project';sub.mkdir()
            (w/'_status.md').write_text('# 入口\n当前项目状态在 `project/_status.md`。\n')
            stamp=time.strftime('%Y-%m-%d %H:%M')
            (sub/'_status.md').write_text(self.SUMMARY_HEAD%stamp+'# 历史\n'+'CHILD_OLD\n'*3000)
            prompt=self.preview(w)
            self.assertIn('SUMMARY_GOAL',prompt);self.assertLess(prompt.count('CHILD_OLD'),5)

    def test_long_summary_is_truncated_with_notice(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d).resolve();p=w/'_status.md'
            stamp=time.strftime('%Y-%m-%d %H:%M')
            p.write_text('<!-- 现状摘要:开始 -->\n## 现状摘要（更新于 %s）\n'%stamp+'很长的一行\n'*3000+'<!-- 现状摘要:结束 -->\n')
            prompt=self.preview(w)
            self.assertIn('后半部分已省略',prompt);self.assertLess(len(prompt),5000+1500)

if __name__=='__main__':unittest.main()
