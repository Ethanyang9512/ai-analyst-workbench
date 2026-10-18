# report-writing 的检查程序

`SKILL.md` 是给 Claude 读的写作规范；这一页给人看：目录里每个程序做什么、怎么跑、怎么测。程序都只读稿件，不改原件，不联网。

## 目录

| 位置 | 是什么 |
|---|---|
| `SKILL.md` | 写作规范主文件 |
| `references/` | 按需读的参考：出图规范、改稿规律、飞书实操、禁用词台账及其归档 |
| `scripts/` | 检查程序和出图模板（下表） |
| `tests/` | 各程序的测试，全部在临时目录里造夹具 |

## 程序

| 程序 | 查什么 | 用法 | 依赖 |
|---|---|---|---|
| `scripts/style_lint.py` | 硬禁词（读 `references/style-lexicon.md` 的「一、硬禁」表）和三条警告 | `python3 scripts/style_lint.py 稿件.md [更多稿件]`；有硬禁命中退出 1 | 标准库 |
| `scripts/figcheck.py` | 出图的文字重叠、折线穿字、文字出界或被裁 | `python3 scripts/figcheck.py 出图脚本.py`（不用改脚本），或在脚本里 `save_checked(fig, path)` | matplotlib、numpy |
| `scripts/trace_scan.py` | 给读者的稿子里不该有的内部痕迹：协作方名字、过程用词、本机路径、轮次号 | `python3 scripts/trace_scan.py 稿件.md 片子.pptx [--allow 词] [--names 你的协作方名字]`；有命中退出 1 | 标准库 |
| `scripts/deckcheck.py` | 飞书幻灯片快照（xml/json/md）和导出的 PDF：不用的词、系统原名、对象编号、页码引用、拆词、出界；`scope` 算出这次改了哪几页、该请验收员看哪几页 | `${AAW_PY:-python3} scripts/deckcheck.py text|pdf|scope …`；0 通过 / 1 有必须改 / 2 没查成 | text、scope 用标准库；pdf 要 PyMuPDF |
| `scripts/pairsnap.py` | 存“交付版 → 用户定稿”成对稿，算手改比例，每 3 份留 1 份当考题 | `python3 scripts/pairsnap.py save|list|metrics|mark …`，`--root` 写在子命令前后都行 | 标准库（用到 `fcntl`，Windows 请用 WSL） |
| `scripts/chart_template.py` | 不是检查程序：出图模板，7 张示例图（数据虚构） | `CHART_OUT=输出目录 python3 scripts/chart_template.py` | matplotlib；有 scipy 时折线用 PCHIP 平滑 |

`deckcheck.py` 从稿件所在目录逐级往上找项目的 `_CONVENTIONS.md`，读其中“程序检查用”的 json 块。键：`banned`（不用的词）、`display_names`（系统原名 → 展示名）、`codes`（对象名 → 编号，设了才查“名字前漏了编号”）、`terms`（专有词，导出 PDF 后不许拆在两行）、`variants`（同一个东西的几种写法）、`allow`（被误报的合法长词）。模板见仓库 `templates/workspace/_CONVENTIONS.md`。

## 30 秒试一下

在仓库根目录，用示例考卷的交付版跑两个检查（真实输出见仓库 examples/续费率下滑归因/outputs/）：

```bash
python3 skills/report-writing/scripts/style_lint.py exam/example-paper/delivered.md   # 在仓库根目录运行
python3 skills/report-writing/scripts/trace_scan.py exam/example-paper/delivered.md   # 在仓库根目录运行
```

## 环境变量

| 变量 | 给谁用 | 默认 |
|---|---|---|
| `AAW_PY` | 跑 `deckcheck.py pdf` 和它的测试：装了 PyMuPDF 的解释器 | 不设就用 `python3` |
| `PAIRSNAP_ROOT` | `pairsnap.py` 的成对稿存放处（也可用 `--root`） | `~/aaw-pairs` |
| `CHART_OUT` | `chart_template.py` 的出图目录 | 当前目录 |
| `AAW_LATIN_FONT` | `chart_template.py` 的西文字体 | 不设，只用中文字体回落链 |

## 测试

在本目录下运行：

```bash
python3 tests/test_style_lint.py       # 只用标准库；最后一条读真台账，只断言能解析
python3 tests/test_trace_scan.py       # 只用标准库
python3 tests/test_pairsnap.py         # 只用标准库（macOS / Linux）
python3 tests/test_figcheck.py         # 要 matplotlib；最后一条把 chart_template.py 的 7 张图跑一遍，要求零误报
${AAW_PY:-python3} tests/test_deckcheck.py -v   # PDF 那组要 PyMuPDF，没装就跳过并写明
```

一次跑完全部技能的测试：仓库根目录的 `bash tools/run_skill_tests.sh`。
