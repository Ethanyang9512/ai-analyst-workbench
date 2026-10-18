# 致谢

这套工作台运行在 Claude Code 上，用到一些开源项目和公开方法。下面只列**工作台真正依赖或借鉴**的东西。本仓库没有复制它们的文件，只写名称、用在哪和链接；需要时请到原处按各自的许可证安装。

## 运行环境和工具

| 名称 | 在工作台里的角色 | 链接 |
|---|---|---|
| Claude Code（Anthropic 的产品；仓库公开，但不是开源许可） | 整个工作台的运行环境：技能、子代理、钩子都是它的机制 | https://github.com/anthropics/claude-code |
| Anthropic 官方技能（docx、xlsx、pdf、pptx 等） | 可选配套。其中文档类技能的许可不允许再分发，所以本仓库不含，请自行安装 | https://github.com/anthropics/skills |
| 飞书 lark-cli（@larksuite/cli，MIT）及飞书官方 lark-* 技能 | 发消息、读写飞书文档。进度卡、发送、验收门依赖它；只在终端用时不需要 | https://github.com/larksuite/cli |
| 飞书桥 lark-channel-bridge（仓库名 feishu-claude-code-bridge，MIT） | 把飞书群消息转给本机 Claude Code。本仓库不含桥本身，只说明桥需要提供什么（见 [docs/08](docs/08-安装与配置.md)） | https://github.com/zarazhangrui/feishu-claude-code-bridge |

## 方法来源

| 名称 | 用在哪 | 链接 |
|---|---|---|
| 论文《Skill Training with Corruption and Reconstruction Loop》 | [docs/07 先考试再上线](docs/07-先考试再上线.md) 的方法来源。只借思路，没有复制代码 | https://arxiv.org/abs/2607.27557 |
| Andrej Karpathy 对大模型写代码常见失误的公开观察，以及社区据此整理的 CLAUDE.md | [templates/global-CLAUDE.md](templates/global-CLAUDE.md) 开头的四条底线（中文转述） | 社区整理版之一：https://github.com/multica-ai/andrej-karpathy-skills |
| 金字塔原理与 SCQA（Barbara Minto）、《Say It With Charts》（Gene Zelazny）、《Storytelling with Data》（Cole Nussbaumer Knaflic）、Stephen Few 的图表设计著作、Andrew Abela 的 Chart Chooser、IBCS 国际商务沟通标准 | 汇报骨架和选图方法，见 [skills/pyramid-storyline/references/](skills/pyramid-storyline/references/) | 公开出版物，请检索原书 |

## 检查程序和示例用到的第三方库

这些库不随仓库分发，按需安装（`pip install -r requirements-dev.txt` 或 `npm install`）。

| 名称 | 用在哪 | 许可 |
|---|---|---|
| python-pptx | 汇报片检查（`check_deck.py`） | MIT |
| matplotlib、scipy | 出图模板、出图自检（`figcheck.py`） | matplotlib 许可（BSD 风格）、BSD |
| openpyxl、pandas | 读写 Excel、数据处理 | MIT、BSD |
| PyMuPDF | 可选，只用于 `deckcheck.py pdf` 查导出的 PDF | AGPL-3.0（比本仓库的许可严格，注意） |
| OfficeCLI（@officecli/officecli） | 可选，汇报片的结构校验和转图预览 | Apache-2.0，https://github.com/iOfficeAI/OfficeCLI |
| PuLP、HiGHS、OR-Tools | 优化问题示例（`optimization-modeling`） | MIT、MIT、Apache-2.0 |
| ccusage | 可选，考场里记录每次考试的用量 | MIT |

发现漏列了谁，或链接、许可写错了，欢迎开 issue。
