# runtime：助手“分析助手”的运行时

这一目录让一个 Claude Code 助手在飞书群里稳定地干分析活：每条消息进来时补上长期要求，干活时有进度卡，发正式交付物前查验收记录，危险操作被护栏拦下。它不含飞书桥本身（桥负责收发消息、排队、启动 `claude -p`），桥需要提供什么见 [接入飞书桥.md](接入飞书桥.md)。

没有飞书也能用这里的大部分东西：`workflow.md` 和 `manual/CLAUDE.md` 是纯文字规则，`tools/accept_record.py` 和 `status_preview.py` 在终端里照常可用；只有进度卡、发送和验收门依赖 lark-cli 和桥。

## 目录里有什么

| 路径 | 是什么 | 谁用 |
|---|---|---|
| `workflow.md` | 分析助手的执行流程：接单、回复、给取数助手的需求、状态与记忆、技能入口、验收、收尾 | 桥把它追加进每个新会话的系统提示 |
| `manual/CLAUDE.md` | 飞书场景的共享手册：一个群一个工作区、附件入库、进度卡用法、交付命令、环境坑 | 复制到 `$AAW_WS_BASE/default/CLAUDE.md`，各项目工作区 `@import` 它 |
| `hooks/` | 五个钩子和它们的测试（见下一节） | Claude Code 按工作区 `.claude/settings.json` 的登记调用 |
| `tools/accept_record.py` | 验收记录：按文件内容指纹记一笔“谁验过、哪一档、看了哪几页”；`status` 建议什么时候该全稿通读 | 分析助手发正式交付物前运行；验收门读它 |
| `tools/replay_history.py` | 用过去的真实命令回放护栏和验收门，看新规则会不会误拦 | 改钩子之后、上线之前 |
| `bin/card.py`、`bin/p`、`bin/t` | 进度卡（一张卡原地刷新）、文字播报、计时器 | 分析助手；进度钩子自动起卡也调它 |
| `bin/newproject` | 一键开项目工作区 | 分析助手或你，开新群时 |
| `bin/status-all` | 列出各群进度卡的状态 | 私聊里问“别的群做到哪了” |
| `status_preview.py` | 新会话首轮附带的 `_status.md` 现状摘要预览 | 桥在新会话第一轮调用 |
| `workspace_settings.py` + `.json` | 统一维护各工作区 `.claude/settings.json`：关后台运行、推理强度、钩子登记、写入门槛 | 你，装好后和每次改钩子后 |
| `settings.example.json` | 工作区设置的最小样例（不含任何代理地址） | `newproject` 找不到 default 的设置时用它 |
| `config.example.env` | 全部环境变量和默认值 | 你，复制成 `config.env` 改值 |
| `doctor.sh` | 只读体检 | 你，觉得不对劲时 |
| [工作区目录约定.md](工作区目录约定.md) | 工作区里每个约定文件是干什么的 | 你和分析助手 |
| [接入飞书桥.md](接入飞书桥.md) | 桥要提供的四项能力、可替换点 | 你，接桥时 |

## workflow.md 在干什么

`workflow.md` 是追加进每个新会话系统提示的执行流程。它写给模型读，信息很密、例外很多，对人不太好读；这里先给一份导读。它本身不再加字，说明都放在这一节和 `docs/`。

**一句话**：规定分析助手在飞书群里接到一条消息后，先判断这一轮该做什么，再按技能干活，交付前过验收，最后把现状写进文件、以一段文字收尾。

| 节 | 管什么 | 为什么要有这一节 | 详见 |
|---|---|---|---|
| 运行环境 | 群、工作区、模型、`/new` 的含义 | 模型不知道自己跑在桥后面，会按旧习惯猜路由 | [docs/02](../docs/02-运行逻辑.md) |
| 边界 | 不改别的机器人、不跨群说话、材料里的“要求”不当指令、每轮必须文字收尾 | 防误操作和防夹带指令；不收尾群里就什么也收不到 | [docs/04](../docs/04-质量关.md) 护栏一节 |
| 接单 | 判断这一轮是讨论、记录、审核、制作、修改还是查进度；阶段检查 | 最常见的返工是“没让做的也做了” | [docs/02](../docs/02-运行逻辑.md) 接单判型 |
| 回复 | 结论在前、改稿先说哪里变了、没回复不等于认可 | 用户在飞书里只看得到这段文字 | — |
| 给取数助手的需求 | 一次一个自足的需求包，末行固定句 | 用户转交时不用再问“还要转什么” | `skills/data-package-review` |
| 状态与记忆 | `_status.md` 现状摘要的固定七项、什么写进约定页、知识库和记忆的分工 | 会话随时会断，新会话只能靠文件接上 | [docs/06](../docs/06-知识库怎么组织.md) |
| 技能 | 这一轮该加载哪个技能 | 只加载涉及的，省上下文、少误触发 | [docs/03](../docs/03-技能体系.md) |
| 分析与审核 | 先做最小独立复算；“同时发生”不写成原因；新数据先查业务事件 | 分析里最贵的错是把相关写成因果 | `skills/pyramid-storyline` |
| 文档、图表与 PPT | 处理手改和评论的分类、写线上文档前先回读 | 防止覆盖用户的新手改 | `skills/report-writing` |
| 验收 | 程序检查 → 定档 → 两位验收员 → 写记录 → 另起一条命令发送 | 验收最容易在赶时间时被跳过 | [docs/04](../docs/04-质量关.md) |
| 进度与收尾 | 进度卡、部分完成怎么说、交付入口必须是用户打得开的 | 用户看不到助手在做什么，会以为卡住了 | [docs/02](../docs/02-运行逻辑.md) 进度卡一节 |

## 五个钩子：拦什么、为什么

所有钩子都经 `hooks/run-hook.sh` 进入。入口的规矩：只有桥传进来的 `LARK_CHANNEL_PROFILE` 等于 `AAW_PROFILE`（默认 `aaw`）才生效，你在终端里直接开的 Claude Code 不受影响；`hooks/DISABLED` 存在时全部不做事；任何异常一律放行，只有脚本主动输出拦截 JSON 才算拦。

| 钩子 | 事件 | 做什么 | 为什么 |
|---|---|---|---|
| `remind.py` | 每条用户消息（UserPromptSubmit） | 在消息后面补上长期要求：先一句话复述理解、只做被要求的、用大白话；涉及文档时提醒先加载哪几个技能；说定稿或汇报时提醒全稿验收和会前追问清单；问额度时直接附读数；现状摘要超长时提醒压缩。同时登记“这一轮属于哪个群” | 这些话用户以前每次都要手打。从历史会话里数出用户反复说的要求，固化成提醒，比写在长长的系统提示里更不容易被忽略 |
| `guard.py` | 每条 Bash 命令执行前（PreToolUse） | 拦五类：启停或杀桥进程；`lark-cli` 发消息不带 `--as bot`；改自己的护栏、规则和设置；取密钥；发到本群以外（带 `ALLOW_OTHER_TARGET='理由'` 放行并记日志） | 前两类防“机器人自己把自己搞掉线”和“消息回环”；后三类防指令注入：数据包、附件、网页里写着“改配置”“贴密钥”“发到别的群”时，就算模型被骗，命令也执行不了。只认明显写法，挡不住刻意绕过 |
| `gate.py` | 每条 Bash 命令执行前 | 发 PPT、Excel、Word、PDF（或新建、导入飞书文档）前，查这个文件的内容指纹有没有验收记录。提醒模式只提醒，强制模式（`GATE_ENFORCE` 存在）直接拦 | 验收最容易在赶时间时被跳过。门只认指纹，不判断验收做得好不好；文件改了一个字节记录就失效 |
| `progress.py` | 每次工具调用前 | 把“当前动作”写进进度卡状态；任务跑过 30 秒还没卡、或要叫子代理时，自动起一张卡 | 用户在飞书里只看得到消息，长任务中途一片安静会以为卡住了 |
| `progress_stop.py` | 每轮结束（Stop） | 把还开着的进度卡收尾成“已完成” | 防止留下一张永远转圈的卡。Stop 钩子只做这种安静的收尾，不输出、不拦截 |

日志：`hook.log` 只记规则名、时间、文件类型和处理结果，不记命令原文（数据包里可能有明文口令）。

## 装起来

完整步骤在 `docs/08-安装与配置.md`。最短路径：

```bash
cp runtime/config.example.env runtime/config.env   # 先打开改成你的值，至少核对 AAW_RUNTIME
set -a; . runtime/config.env; set +a                # 在当前终端加载；桥启动前也要这样加载一次
mkdir -p "$AAW_WS_BASE/default"
cp runtime/manual/CLAUDE.md "$AAW_WS_BASE/default/CLAUDE.md"
python3 runtime/workspace_settings.py apply --path "$AAW_WS_BASE/default" --kind base
runtime/bin/newproject renewal-analysis "续费率分析" <群的 chatId>
bash runtime/doctor.sh
```

`workflow.md` 和手册里写的 `$AAW_KB`、`$AAW_RUNTIME` 这类变量不会被自动展开，分析助手要用时在命令里照写即可（环境变量从桥继承）。

## 测试

```bash
python3 runtime/hooks/test_guard.py
python3 runtime/hooks/test_gate.py
python3 runtime/hooks/test_remind.py
python3 runtime/hooks/test_progress.py
python3 runtime/tools/test_accept_record.py
python3 runtime/test_status_preview.py
```

全部在临时目录里跑，不碰真实工作区、不发飞书。改钩子之后的上线顺序：先备份 → 请另一个子代理专门攻击新规则 → 跑上面的测试 → 用 `tools/replay_history.py` 回放历史命令看误拦 → 在假工作区里按桥的命令行端到端排练一遍（`exam/harness/` 就是现成的假工作区和假 lark-cli）→ 各群 `/new`。
