# tools：安装、自查、一键测试，以及检查程序总索引

工作台的规矩尽量写成程序来查，不靠记性。检查程序放在用到它的技能目录里（技能复制到 `~/.claude/skills/` 后，程序跟着走）；这一页是总索引。程序都只读输入、不改原件、不联网；路径和存放处都能用参数或环境变量改，代码里没有写死的本机路径。

## 本目录的四个脚本

| 脚本 | 做什么 |
|---|---|
| `install.sh` | 把 `skills/` 和 `agents/` 装到 `~/.claude/`；同名的旧版本先挪到备份目录；`--dry-run` 只列出不装 |
| `check_repo.py` | 仓库自查：技能和子代理的头部信息、技能内引用、文档链接、本机路径、密钥形态、两份模板是否同步、二进制文件 |
| `run_skill_tests.sh` | 跑 `skills/` 下全部检查程序的测试 |
| `run_all_tests.sh` | 仓库自查 + 技能测试 + `runtime/` 的 6 组测试 + 两个示例脚本；CI 跑的就是它 |

## 检查程序在哪、查什么

| 程序 | 位置 | 查什么 | 什么时候跑 |
|---|---|---|---|
| `style_lint.py` | `skills/ethan-report-writing/scripts/` | 硬禁词（读台账 `references/style-lexicon.md`）和 %/pt、LaTeX、第二人称三条警告 | 每份给业务看的文档交付前 |
| `trace_scan.py` | `skills/ethan-report-writing/scripts/` | 内部痕迹：协作方名字（`--names` 补你自己的）、过程用词、本机路径、轮次号 | 同上 |
| `figcheck.py` | `skills/ethan-report-writing/scripts/` | 出图的文字重叠、折线穿字、出界 | 每张 matplotlib 图保存时 |
| `deckcheck.py` | `skills/ethan-report-writing/scripts/` | 飞书幻灯片快照和导出 PDF：用词、编号、页码引用、拆词、出界；`scope` 算改动范围和验收范围 | 每次改片、交验收员之前 |
| `pairsnap.py` | `skills/ethan-report-writing/scripts/` | 存“交付版 → 用户定稿”成对稿、算手改比例、留考题 | 用户手改定稿之后 |
| `check_deck.py` | `skills/ethan-slide-deck/scripts/` | PPTX 七项：完整性、非法色值、越界、重叠、黑名单、文字溢出、图表标签位置 | 每份 PPTX 交付前 |
| `pkgcheck.py` | `skills/ethan-data-package-review/scripts/` | 取数助手交来的数据包：说改了没重跑、公式缓存为空、明文个人信息、时间窗缺天 | 每轮收包解包后、人工审核前 |
| `extract_package.py` | `skills/ethan-data-package-review/scripts/` | 安全解包：拒绝越界路径、软链、重名、覆盖旧目录 | 收到 zip 包时 |

运行时（钩子、验收记录、历史命令回放）和考场（打分脚本）的程序分别在 `runtime/` 和 `exam/`，各自目录里有说明。每个程序跑出来是什么样，见 [examples/续费率下滑归因/outputs/](../examples/续费率下滑归因/outputs/)。

## 依赖

| 依赖 | 谁要 | 没有会怎样 |
|---|---|---|
| Python 3.9+ 标准库 | style_lint、trace_scan、pairsnap、pkgcheck、extract_package、deckcheck 的 text/scope、全部钩子、check_repo | — |
| matplotlib、numpy（scipy 可选） | figcheck、chart_template | figcheck 的测试显示“跳过” |
| PyMuPDF（`import fitz`） | deckcheck 的 pdf 子命令 | deckcheck 的 PDF 测试组跳过 |
| python-pptx | check_deck | check_deck 的测试跳过 |
| PuLP 3.x、HiGHS、OR-Tools | ethan-optimization-modeling 的两个例子 | 例子跳过 |

一次装齐：`pip install -r requirements-dev.txt`（仓库根目录）。`pairsnap.py` 用到 `fcntl`，只能在 macOS / Linux 上跑；Windows 请用 WSL。

## 一键测试

```bash
bash tools/run_all_tests.sh        # 整个仓库
bash tools/run_skill_tests.sh      # 只跑技能
# 有专门装依赖的解释器时：
AAW_PY=/path/to/python-with-pymupdf-and-pptx PULP_PY=/path/to/python-with-pulp bash tools/run_all_tests.sh
```

测试的夹具都在临时目录里现造，数字、编号、地区全部虚构，不读任何真实业务文件。
