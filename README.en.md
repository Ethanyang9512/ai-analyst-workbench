# ai-analyst-workbench

[![tests](https://github.com/Ethanyang9512/ai-analyst-workbench/actions/workflows/tests.yml/badge.svg)](https://github.com/Ethanyang9512/ai-analyst-workbench/actions/workflows/tests.yml)
[![code: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![docs: CC BY 4.0](https://img.shields.io/badge/docs-CC%20BY%204.0-lightgrey.svg)](LICENSE-docs)

**中文：** 见 [README.md](README.md)。

Claude Code skills, hooks and two read-only reviewer sub-agents for data / BI analysts. The goal: let an AI assistant draft analysis reports, build slide decks and review data packages **while every number stays traceable from the source data to the final chart**.

Most of the documentation, skill text and examples are in Chinese. This page is the English entry point: what the project is, how to try it in 30 seconds, and where everything lives. Every example in the repository is fictional.

## Try it in 30 seconds

No dependencies needed. From the repository root:

```bash
python3 skills/report-writing/scripts/style_lint.py exam/example-paper/delivered.md
python3 examples/续费率下滑归因/analysis/recompute.py
```

The first command lints the first draft of the sample report against a banned-phrase ledger and reports 4 hard hits (exit code 1). The second recomputes every number in the sample report from the data: the renewal rate fell 3.8 points from W5 to W6, of which 2.3 points come from a change in the mix of expiring subscriptions and 1.5 points from a price increase on the monthly plan. More real outputs (the acceptance gate blocking an unreviewed file, the data-package check catching “claimed fixed but not re-run”, the progress card) are in [examples/续费率下滑归因/outputs/](examples/续费率下滑归因/outputs/).

## What problems it addresses

1. **Endless rework on wording.** Corrections come back in a different form; AI self-review makes drafts longer. → A ledger of banned phrases checked by a script, and a “correct once, codify on the second occurrence” protocol.
2. **Unreliable data.** A note says “fixed” but the data was never re-run. → Data packages are compared by file fingerprint; numbers must come from code.
3. **Hard to read, hard to retell.** Deliverables go to business stakeholders. → Answer-first storylines, a glossary per project, and two reviewer sub-agents (a cold reader and a chart/number checker) before anything is sent.

## Design principles

1. Numbers come only from code and data; assumptions are labelled and parameterised.
2. Write/review separation: the author never signs off its own work.
3. If a rule can be checked by a program, write the program.
4. Corrections are recorded in the same turn; the second occurrence becomes a project convention.
5. Do only what was asked.
6. Test before release: rule changes are measured on the same exam paper before and after.
7. Make output easy to digest: glossary, charts first, explain *why* a number is computed this way.

Trade-offs behind each design (what was rejected, what it costs, when to switch) are in [docs/09](docs/09-设计取舍与替代方案.md) (Chinese).

## What is in the repository

| Path | Contents |
|---|---|
| [skills/](skills/) | 11 Claude Code skills (index: [skills/README.md](skills/README.md)) |
| [agents/](agents/) | Two read-only reviewer sub-agents: `cold-reader`, `chart-number-checker` |
| [runtime/](runtime/) | Runtime for running the assistant behind a Feishu/Lark group-chat bridge: execution workflow, hooks (reminders, progress card, guardrails, acceptance gate) with tests, acceptance-record tool |
| [exam/](exam/) | “Test before release” harness: sandboxed exam runner (macOS), scoring scripts, a fictional sample exam paper |
| [templates/](templates/) | Empty templates: workspace files, knowledge base, data-request package, SQL and metric-definition skills |
| [examples/](examples/) | Two complete fictional projects (see below) |
| [docs/](docs/) | Ten design and operations documents (Chinese) |
| [tools/](tools/) | Installer, repository self-check, one-command test runner |

### Skills

| Skill | Use it when |
|---|---|
| `analysis-brief` | Starting a new analysis: five-element brief, attack the analysis design before pulling data |
| `reproducible-analysis` | Any analysis: versioned step-by-step SQL with rationale headers, formulas kept in Excel, charts that can be redrawn |
| `pyramid-storyline` | Before writing a report or deck: answer-first skeleton, one lead sentence per chapter, how to explain a metric change |
| `report-writing` | Writing business-facing reports; ships five check scripts (banned phrases, chart overlap, internal traces, slide checks, paired-draft snapshots) |
| `slide-deck` | Formal PPTX decks with python-pptx; ships `check_deck.py` |
| `optimization-modeling` | Allocation, scheduling, bin-packing with PuLP / OR-Tools, with baseline and sensitivity |
| `critical-review` | Default quality gate before shipping: first principles plus adversarial review, findings rated P1/P2/P3 |
| `data-package-review` | Reviewing a data package from another agent or colleague; writing the data request |
| `executive-summary` | Only when an executive summary / SCQA is explicitly requested |
| `feishu-delivery` | Sending finished work to Feishu/Lark safely (bot identity, target, receipts, no echo loops) |
| `workbench-maintenance` | Updating Claude Code, health checks, local configuration backup |

### Examples

| Example | Shows |
|---|---|
| [Renewal-rate decline](examples/续费率下滑归因/) | A full nine-step project; decomposing a rate change into mix effect and rate effect; using an unaffected plan as a control group; real outputs of every check |
| [Onboarding A/B test readout](examples/新手引导改版评估/) | Pre-registered decision rules; how to report an inconclusive result; how much more data is needed; why a tempting post-hoc subgroup is not a conclusion |

## Quick start

Requirements: Claude Code installed and logged in, Python 3.9+.

```bash
git clone <this repository> && cd ai-analyst-workbench
bash tools/install.sh --dry-run   # see what would be installed
bash tools/install.sh             # copies skills/ and agents/ into ~/.claude, backing up same-name folders first
bash tools/run_all_tests.sh       # standard library only; groups needing optional packages are skipped
```

Optional packages for the remaining test groups and chart/PDF/PPTX checks: `pip install -r requirements-dev.txt`.

Then merge what you like from [templates/global-CLAUDE.md](templates/global-CLAUDE.md) into `~/.claude/CLAUDE.md`, copy the workspace templates into a project folder, and start `claude` there. Connecting the assistant to a Feishu/Lark group requires a third-party bridge; what the bridge must provide is described in [docs/08](docs/08-安装与配置.md) and [runtime/接入飞书桥.md](runtime/接入飞书桥.md).

## Limitations

- Built from one analyst's workflow; the exam results quoted in the docs are a single-person, small, open-book sample.
- Defaults to Chinese, Feishu/Lark and Claude Code.
- Company-specific parts (SQL, metric definitions, slide masters) are templates only.
- Hooks are guardrails against mistakes and injected instructions, not a security boundary.
- Hook, sub-agent and settings behaviour may change between Claude Code versions.

## License

Code is licensed under [MIT](LICENSE): every `.py` and `.sh` file (including the scripts in `examples/`), `*.sb.template`, the extension-less scripts in `runtime/bin/` and `exam/harness/fakebin/`, the `.yml` files under `.github/`, the `.json` and `.env` samples under `runtime/`, and `requirements*.txt`. Everything else, including all `.md` files and the `.csv`, `.sql`, `.txt` and `.json` files in the examples, templates and the sample exam paper, is documentation licensed under [CC BY 4.0](LICENSE-docs).

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) (Chinese). Please report suspected leaks or guardrail bypasses privately via GitHub Security Advisories; see [SECURITY.md](SECURITY.md). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).
