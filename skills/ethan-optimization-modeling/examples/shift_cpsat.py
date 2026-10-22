# -*- coding: utf-8 -*-
"""排班类模板（OR-Tools CP-SAT）：客服中心已知每小时要多少人，用 8 小时班次排人，总人数最少。
和现状（两班倒、各按本班高峰配人）比一次。数字是编的示例。
运行：pip install -r ../requirements.txt 之后，python shift_cpsat.py
"""
from ortools.sat.python import cp_model

# ---------- DATA（示例） ----------
need = [3, 3, 4, 6, 9, 12, 12, 10, 8, 8, 10, 13, 14, 12, 9, 6]   # 第 0..15 小时各需要几人
SHIFT = 8                                                          # 每个班 8 小时
starts = range(len(need) - SHIFT + 1)                              # 可选的上班时刻
baseline = max(need[:SHIFT]) + max(need[SHIFT:])                   # 现状：第 0、8 小时两班，各按本班高峰配人

# ---------- 模型 ----------
m = cp_model.CpModel()
n = {s: m.NewIntVar(0, 50, f"start_{s}") for s in starts}          # 决策：每个时刻安排几人上班
for h, req in enumerate(need):                                     # 限制：每小时在岗人数 ≥ 需求
    m.Add(sum(n[s] for s in starts if s <= h < s + SHIFT) >= req)
m.Minimize(sum(n.values()))                                        # 目标：总人数最少

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 10
st = solver.Solve(m)
print("状态:", solver.StatusName(st), " 最少人数:", int(solver.ObjectiveValue()))
for s in starts:
    if solver.Value(n[s]):
        print(f"  第 {s} 小时上班: {solver.Value(n[s])} 人")
on = [sum(solver.Value(n[s]) for s in starts if s <= h < s + SHIFT) for h in range(len(need))]
assert all(o >= r for o, r in zip(on, need))                       # 自检：每小时都够人
print("  每小时在岗:", on)
best = int(solver.ObjectiveValue())
assert best <= baseline                                            # 最优不应比现状差
print(f"  现状两班倒需要 {baseline} 人，错峰排班需要 {best} 人，少 {baseline - best} 人")
