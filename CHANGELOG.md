# 更新记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。规则和技能的改动，在条目里写清“改前 / 改后”。

## [未发布]

（还没有。）

## [0.3.0] - 2026-11-09

把分析助手 11 月新加的做法带进来。改动集中在故事线、拆解归因和写细需求三处。

### 新增

- `ethan-pyramid-storyline`：
  - 「取数之前先写故事线清单」一节：开新分析、发第一份取数需求之前，先写下“第一天的答案”和每章一句结论，标上待验证 / 已证实 / 被推翻，再拿数据去证实或推翻。改前：骨架在分析做完后才定。
  - 「诊断专题的骨架」一节：结论与建议（含问题、原因、建议总表）在最前；推理按界定问题 → 问题树逐层缩小范围 → 因果分强弱 → 建议和原因一一对上，查过的原因汇成附录一；另附建议要回答的四件事。
  - 已知一处：示例考卷的用户定稿（`exam/example-paper/final.md`）保留了一句“需要业务确认”，新的 `style_lint.py` 会对它给警告（只提示，不拦）。考卷按用户定稿为准，没改。
  - 新参考件 `references/storyline-ledger.md`（清单模板和续费率例子）、`references/metric-bridges.md`（比率变化的两种拆法、瀑布图对账、还没定的几个数和参考值）。
- `ethan-data-package-review`：第五节「需求和修改意见写细」：修改意见和取数项各写六栏，自查写不变量，SQL 没跑过的标“未实跑”，回执带文件指纹，审回包按六步走。
- `ethan-report-writing`：「限定、待确认、备选数：只留必要的」一节；`style_lint.py` 对“尚未确认”“需业务确认”这类防御性写法给警告（不拦；“原因待××确认”不报），附测试。
- `ethan-data-package-review`：审核报告模板开头加“结论”一块，本轮发现改成六栏；需求包模板的“要做的”改成六栏，末尾加修改回执。

### 变更

- `ethan-pyramid-storyline`：「分析类汇报的四条」扩成六条（加“先判有没有问题”“原因判断分强弱、全篇一个标准”；关键数配对标；拆解只回答变化落在哪）。「指标波动的讲法」加四条：拆之前先验指标本身、下钻前先算各维度的贡献、拆解顺序讲得出理由、用天然对照组排除外部因素。另加定义卡、算式图、统计后紧跟真实案例三个做法；跑题的旁枝不进正文；结构不同的两边先调平再比，全篇比较期固定。“需要关注”统一只收要别人配合做的事和会改变决策的风险；“没确认的原因”统一写成一行“原因待××确认”。
- `ethan-analysis-brief`：取数前的设计检查，第一条改成先写故事线清单。
- `ethan-critical-review`：给业务看的稿子被认为“可能误解”时，修法依次是改准、删掉、最后才加限定；作者假设在成稿里写成“按 X 测算；若为 Y，结果变为 Z”。
- `ethan-report-writing`：诊断类报告的第一章写法；选图先想观点、少用流程图凑数、不用要先学记法的图元。
- 验收员：`cold-reader` 拿到章首句和状态时，查“待验证”有没有写成结论；`chart-number-checker` 的讲法检查加一条“关键数配了对标”，瀑布图加查单位和分不到类的部分。

## [0.2.0] - 2026-10-22

### 变更

- 11 个技能统一加 `ethan-` 前缀，便于和其他来源的技能区分、单独上架到技能市场。改前 `critical-review`，改后 `ethan-critical-review`，其余同理。目录名、`name` 字段、技能之间的互相引用、文档、测试脚本已同步。**升级提示**：用 `tools/install.sh` 装过 0.1.0 的，`~/.claude/skills/` 里的旧名目录不会自动删除，请手动删掉，免得同一个技能出现两份。

### 新增

- `.claude-plugin/marketplace.json`：可以在 Claude Code 里用 `/plugin marketplace add Ethanyang9512/ai-analyst-workbench` 加入，再 `/plugin install ethan-analyst@ethan-skills` 一步装好全部技能和验收员。

## [0.1.0] - 2026-10-18

首次公开发布。

### 新增

- 11 个 Claude Code 技能：`analysis-brief`、`reproducible-analysis`、`pyramid-storyline`、`report-writing`、`slide-deck`、`optimization-modeling`、`critical-review`、`data-package-review`、`executive-summary`、`feishu-delivery`、`workbench-maintenance`。每个技能只引用自己目录里的文件。
- 两位只读的验收员子代理：`cold-reader`（冷读）、`chart-number-checker`（看图、核数）。
- 检查程序：`style_lint.py`、`figcheck.py`、`trace_scan.py`、`deckcheck.py`、`pairsnap.py`、`check_deck.py`、`pkgcheck.py`、`extract_package.py`，各带测试。
- 飞书场景的运行时：执行流程、共享手册，四类钩子（每轮提醒、进度卡、护栏、验收门）及测试，验收记录工具，历史命令回放，体检脚本。
- 先考试再上线：沙盒考场（macOS）、打分脚本、一份虚构的示例考卷。
- 模板：全局工作协议、项目工作区、知识库、需求包和审核报告、取数技能和口径技能、记忆索引。
- 两个全虚构的完整示例：续费率下滑归因、新手引导改版评估，各带能复现全部数字的脚本；主例附检查程序的真实输出。
- 文档 10 篇，含设计取舍与替代方案、踩坑清单；英文入口 `README.en.md`。
- 工具：`tools/install.sh`（安装并备份同名旧版本）、`tools/check_repo.py`（仓库自查）、`tools/run_all_tests.sh`；GitHub Actions 在 Ubuntu 和 macOS 上跑测试。

[未发布]: https://github.com/Ethanyang9512/ai-analyst-workbench/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Ethanyang9512/ai-analyst-workbench/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Ethanyang9512/ai-analyst-workbench/releases/tag/v0.1.0
