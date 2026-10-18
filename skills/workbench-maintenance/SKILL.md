---
name: workbench-maintenance
description: Claude Code 和工作台环境的维护：更新 CLI 和技能、体检运行时和钩子、备份配置。用户说“更新 claude code”“更新技能”“升级插件”“环境体检”“助手没反应”时使用；不要只跑一句 claude update 就结束。Use for updating Claude Code, health-checking the workbench runtime and backing up configuration. 只说“更新一下”而没提 Claude、技能或插件时，多半是业务改稿，不是维护。
license: CC-BY-4.0（文字）；scripts/ 下的程序为 MIT
compatibility: macOS/Linux（备份脚本用 bash、rsync、git）
---

# 环境维护：更新、体检、备份

三件一起做。技能目录、记忆和设置被误删或误覆盖之后很难恢复，所以每次维护顺手备份一次。

## 一、更新

```bash
claude update
```

- 你装的第三方技能源各自 `git pull`：只拉确实存在的仓库，拉之前看 `git status`，确认没有本地改动会被冲掉；没有 `.git` 的技能目录（从别处复制来的）不要拉，要更新就从源头重新下载。
- 用到飞书时，`lark-cli` 也按它自己的说明更新。
- 插件用 `claude plugin list` 看，用插件自己的命令更新。

## 二、体检

工作台的运行时在 `$AAW_RUNTIME`（变量说明见仓库的 `runtime/config.example.env`）。`claude update` 之后跑：

```bash
bash "$AAW_RUNTIME/doctor.sh"
for t in "$AAW_RUNTIME"/hooks/test_*.py; do python3 "$t" || echo "失败：$t"; done
```

`doctor.sh` 只读，不改任何东西。结论不是“正常”、或钩子自测有失败时，先告诉用户卡在哪一项，再按仓库 `docs/08-安装与配置.md` 的常见问题排查，不自己发明修法。桥（把飞书消息转给 `claude -p` 的程序）的启停按你所用的桥的说明做，维护时不顺手改它的启动配置。

## 三、备份

```bash
bash <本技能目录>/scripts/backup.sh --dry-run   # 先看会备份什么
bash <本技能目录>/scripts/backup.sh             # 真正备份并提交到本地 git
```

备份 `~/.claude` 下的 `CLAUDE.md`、设置、真实目录的技能、各项目的记忆、子代理，以及工作台的运行目录和各工作区设置，存到 `${AAW_BACKUP:-~/Backups/claude-config}`，用本地 git 记版本。符号链接的技能只记清单。

**备份目录里有你的记忆和配置，可能含代理地址、令牌。** 它只能留在本机或私有存储里，**绝不能推到公开的远程仓库**。脚本会在备份目录写一份 `.gitignore`，默认不收工作区设置（代理、令牌通常写在那里）；确实要备份它们时设 `AAW_BACKUP_WORKSPACE_SETTINGS=1`。

## 四、收尾汇报

写清：CLI 版本旧 → 新；各技能源有没有更新（几个提交）；体检结论和钩子自测结果；备份有没有生成新提交。修不了的，明确告诉用户卡在哪。
