---
name: optimization-modeling
description: 遇到“怎么分、怎么排、怎么装才最划算”这类优化问题时使用：分配（任务、来电、预算分给谁）、排班、装箱。用 PuLP 做线性和整数规划、OR-Tools CP-SAT 做排班和装箱，并和现状对比、做敏感性检查。Use for allocation, scheduling or bin-packing optimization questions. 纯测算、归因、取数、口径核对不用本技能。
license: CC-BY-4.0（文字）；examples/ 下的程序为 MIT
compatibility: pip install -r requirements.txt（PuLP 3.x、HiGHS、OR-Tools、pandas、openpyxl）
---

# 优化求解

## 什么时候用

问题的形状是“在若干限制下，挑一个总成本最低或产出最高的方案”：

| 类型 | 例 | 工具 | 本技能的完整示例 |
|---|---|---|---|
| 分配 | 三个地区的来电分给两个客服中心，不超容量、总成本最低 | PuLP | `examples/allocation_pulp.py` |
| 排班 | 已知每小时要几个人，用固定时长的班次排，总人数最少 | OR-Tools CP-SAT | `examples/shift_cpsat.py` |
| 装箱 | 一批物品装进尽量少的容器 | OR-Tools CP-SAT 或 PuLP 整数规划 | 没有现成示例，照分配示例的五步自己写 |

不用：只是算一个数（测算）、解释为什么变了（归因）、取数对账。规模小、要给业务自己改的分配题，Excel 自带的规划求解可能更合适，先和用户确认交付形式。

## 环境

- 建一个虚拟环境装依赖：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`。
- **PuLP 固定在 3.x**：4.0 改了建变量的写法，网上常见的和模型熟悉的都是 3.x 写法。
- 求解器：默认 CBC；规模大、慢时换 `pulp.HiGHS(msg=False)`，模型代码不用改。
- 两个示例复制到项目目录后，只改文件顶部的 DATA 区。

## 五步，缺一步不交付

`examples/allocation_pulp.py` 把五步完整走了一遍，可以照着改。

1. **先把业务问题翻成三件事，和用户确认**：要定什么（决策变量）、有哪些限制（容量、时效、班次、预算）、按什么算好坏（目标）。这属于口径，先拍板再求解。
2. **先算现状做基线**：用现在的分法、排法算出同一个目标值。最优解不能比基线差，否则模型有错。
3. **求解后逐条回代检查限制**：每条约束都用结果代回去验（示例里有 assert），不能只看求解器说 Optimal。
4. **看方案稳不稳**：关键参数（量、单位成本、每人每小时处理量）各上下浮动约 10% 重算；分配结构变了，就在结论里说明“在什么条件下方案会变”。
5. **交付**：
   - 方案表和现状对比表：省多少、代价是什么；
   - 一段大白话的方法说明，讲清定什么、受什么限制、按什么算好坏；不写“线性规划”“目标函数”，必须用时第一次出现加注；
   - 脚本存在项目目录，参数放在 DATA 区，按 `reproducible-analysis` 能复核；
   - 只用取数助手交来的、分析用得到的字段，结论里写明数据范围和时间窗。
