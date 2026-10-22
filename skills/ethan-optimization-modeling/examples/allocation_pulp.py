# -*- coding: utf-8 -*-
"""分配类完整走查（PuLP）：两个客服中心承接三个地区的来电，在坐席容量内让每天的处理成本最低。

按技能里的五步走一遍：①定变量、限制、目标 ②算现状基线 ③求最优并逐条回代检查 ④来电量 ±10% 重算看稳不稳
⑤打印一段给业务的大白话说明。数字都是编的示例；换成真实数据时只改 DATA 区。
运行：pip install -r ../requirements.txt 之后，python allocation_pulp.py
"""
import pulp

# ---------- DATA（示例，全部虚构） ----------
demand = {"甲区": 900, "乙区": 700, "丙区": 400}                 # 每个地区每天的来电量
capacity = {"甲中心": 1200, "乙中心": 1200}                       # 每个中心每天最多接多少通
cost = {                                                          # 每通电话的处理成本（元）
    ("甲中心", "甲区"): 6.0, ("甲中心", "乙区"): 7.0, ("甲中心", "丙区"): 11.0,
    ("乙中心", "甲区"): 12.0, ("乙中心", "乙区"): 11.0, ("乙中心", "丙区"): 7.5,
}
baseline_rule = {"甲区": "甲中心", "乙区": "乙中心", "丙区": "乙中心"}   # 现状：每个地区固定由一个中心接


def solve(dem):
    """返回 (状态, 总成本, 分配表)。"""
    m = pulp.LpProblem("allocation", pulp.LpMinimize)
    x = {k: pulp.LpVariable(f"x_{i}", lowBound=0) for i, k in enumerate(cost)}       # ① 变量：中心→地区 分多少通
    m += pulp.lpSum(cost[k] * x[k] for k in cost)                                     # ① 目标：总成本最低
    for r, d in dem.items():                                                          # ① 限制 1：每个地区的来电都要有人接
        m += pulp.lpSum(x[(c, r)] for c in capacity) == d, f"demand_{r}"
    for c, cap in capacity.items():                                                   # ① 限制 2：不超过中心容量
        m += pulp.lpSum(x[(c, r)] for r in dem) <= cap, f"cap_{c}"
    m.solve(pulp.HiGHS(msg=False) if pulp.HiGHS().available() else pulp.PULP_CBC_CMD(msg=False))
    plan = {k: v.value() for k, v in x.items()}
    # ③ 逐条回代检查，不能只看 Optimal
    assert all(abs(sum(plan[(c, r)] for c in capacity) - d) < 1e-6 for r, d in dem.items())
    assert all(sum(plan[(c, r)] for r in dem) <= cap + 1e-6 for c, cap in capacity.items())
    return pulp.LpStatus[m.status], pulp.value(m.objective), plan


# ② 现状基线：按固定规则算同一个目标值
base_load = {c: sum(d for r, d in demand.items() if baseline_rule[r] == c) for c in capacity}
assert all(base_load[c] <= capacity[c] for c in capacity), "现状规则本身就超了容量"
base_cost = sum(cost[(baseline_rule[r], r)] * d for r, d in demand.items())

status, best, plan = solve(demand)
assert status == "Optimal" and best <= base_cost + 1e-6, "最优解不应比现状差：模型有错"

print(f"状态：{status}")
print(f"现状每天成本：{base_cost:,.0f} 元；最优：{best:,.0f} 元；每天省 {base_cost - best:,.0f} 元（{(base_cost - best) / base_cost:.1%}）")
print("方案和现状对比（通/天）：")
print("  中心 → 地区 | 现状 | 最优")
for (c, r), v in plan.items():
    now = demand[r] if baseline_rule[r] == c else 0
    if now or v > 1e-6:
        print(f"  {c} → {r} | {now:,.0f} | {v:,.0f}")

# ④ 稳不稳：来电量整体 ±10% 各重算一次，看方案的结构变没变
print("来电量 ±10% 重算：")
for f in (0.9, 1.1):
    st, c2, p2 = solve({r: d * f for r, d in demand.items()})
    same = all((p2[k] > 1e-6) == (plan[k] > 1e-6) for k in plan)
    print(f"  ×{f:.1f}：{st}，成本 {c2:,.0f} 元，{'分配结构不变' if same else '分配结构变了，结论里要说明'}")

# ⑤ 给业务的大白话（不写“线性规划”“目标函数”）
moved = plan[("甲中心", "乙区")]
print(f"说明：乙区的来电里有 {moved:,.0f} 通改由甲中心接（甲中心接乙区每通便宜 {cost[('乙中心', '乙区')] - cost[('甲中心', '乙区')]:.1f} 元，"
      f"而且还有空余坐席），其余照旧；两边都不超过每天 {capacity['甲中心']:,} 通的容量。")
