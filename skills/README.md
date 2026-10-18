# 技能索引

11 个 Claude Code 技能。复制到 `~/.claude/skills/` 即可用（`bash tools/install.sh` 会连同两位验收员一起装，并先备份同名目录）。每个技能只引用自己目录里的文件和兄弟技能，单独复制也能用。各技能怎么接力、三次完整调用的样子，见 [docs/03 技能体系](../docs/03-技能体系.md)。

| 技能 | 一句话 | 自带的程序和文件 | 依赖 | 要飞书吗 |
|---|---|---|---|---|
| [analysis-brief](analysis-brief/) | 新分析项目开题：五要素 brief，取数前先攻设计 | `assets/brief-template.md` | — | 否 |
| [reproducible-analysis](reproducible-analysis/) | SQL 分步带版本、Excel 留公式、图能重画 | `assets/sql-header-template.sql` | — | 否 |
| [pyramid-storyline](pyramid-storyline/) | 答案先行的骨架、每章首句、指标波动的讲法 | `references/` 6 份 | — | 否 |
| [report-writing](report-writing/) | 面向业务的写法、修正即沉淀、交付前自检 | `scripts/` 6 个程序，`references/` 5 份，`tests/` | Python 3.9+；可选 matplotlib、PyMuPDF | 否（`references/feishu-ops.md` 只在用飞书时读） |
| [slide-deck](slide-deck/) | 正式汇报 PPTX 的规则和自检 | `scripts/check_deck.py`，`tests/` | python-pptx；可选 officecli | 否 |
| [optimization-modeling](optimization-modeling/) | 分配、排班、装箱的建模五步 | `examples/` 2 个完整走查，`requirements.txt` | PuLP 3.x、HiGHS、OR-Tools | 否 |
| [critical-review](critical-review/) | 第一性原理加多视角进攻，P1/P2/P3 | — | — | 否 |
| [data-package-review](data-package-review/) | 审取数助手的数据包，写需求包 | `scripts/` 解包和体检，`assets/` 3 份模板，`tests/` | Python 3.9+ 标准库 | 否 |
| [executive-summary](executive-summary/) | 高管摘要、SCQA（用户明确要求时） | — | — | 否 |
| [feishu-delivery](feishu-delivery/) | 把成品发到飞书，防回环 | — | lark-cli | 是 |
| [workbench-maintenance](workbench-maintenance/) | 更新、体检、备份 | `scripts/backup.sh` | bash、rsync、git | 否 |

两位验收员（子代理）在仓库的 [agents/](../agents/)：`cold-reader`（冷读）和 `chart-number-checker`（看图、核数）。

## 目录约定

每个技能目录照 Agent Skills 的常见布局：

```
<技能名>/
├── SKILL.md        给模型读的主文件：头部写 name、description（什么时候用）、license，正文尽量短
├── references/     按需读的参考，主文件里写明什么时候读哪一份
├── assets/         模板
├── scripts/        可执行程序
└── tests/          程序的测试（在临时目录里造夹具）
```

测试：仓库根目录 `bash tools/run_skill_tests.sh`。
