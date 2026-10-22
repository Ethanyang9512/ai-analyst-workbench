# 更新记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。规则和技能的改动，在条目里写清“改前 / 改后”。

## [未发布]

（还没有。）

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
