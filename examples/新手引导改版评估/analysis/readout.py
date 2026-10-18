#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新手引导改版实验的读数（本例数据全部虚构）。只用标准库。

用法：python3 analysis/readout.py      # 在示例目录下运行

判定规则在看数据之前就写进了 brief.md（这里照抄成参数，改规则要先改 brief）：
  主指标：新用户 7 日内完成首次导出的比例（7 日激活率），改版组减对照组，单位 pt
  可忽略带：±0.5pt；采用线：+1.0pt；区间：95%（正态近似）
  四档：区间下界 ≥ 采用线 → 采用；区间上界 < 0 → 拒绝；
        区间整个落在可忽略带里 → 维持现状（差别小到可以忽略）；其余 → 分辨不出，继续收集
分组（新设备 / 老设备）不在事先登记的结论里，只作描述，不拿来下结论。
"""
import csv
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NEGLIGIBLE, ADOPT, Z = 0.005, 0.010, 1.96          # 事先定的判定规则（见 brief.md）
WEEKLY_NEW_USERS_PER_ARM = 6000                     # 现在每组每周进来的新用户（虚构）


def load():
    with open(os.path.join(HERE, os.pardir, "data", "experiment_summary.csv"), encoding="utf-8") as f:
        return [dict(r, new_users=int(r["new_users"]), activated_7d=int(r["activated_7d"])) for r in csv.DictReader(f)]


def diff_ci(n1, x1, n2, x2):
    """对照 (n1, x1)、改版 (n2, x2) → (对照率, 改版率, 差, 下界, 上界)。"""
    p1, p2 = x1 / n1, x2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p2 - p1
    return p1, p2, d, d - Z * se, d + Z * se


def decide(lo, hi):
    if lo >= ADOPT:
        return "采用"
    if hi < 0:
        return "拒绝"
    if -NEGLIGIBLE <= lo and hi <= NEGLIGIBLE:
        return "维持现状（差别小到可以忽略）"
    return "分辨不出，继续收集"


def total(rows, group, device=None):
    rs = [r for r in rows if r["group"] == group and (device is None or r["device"] == device)]
    return sum(r["new_users"] for r in rs), sum(r["activated_7d"] for r in rs)


def main():
    rows = load()
    n1, x1 = total(rows, "对照组")
    n2, x2 = total(rows, "改版组")
    p1, p2, d, lo, hi = diff_ci(n1, x1, n2, x2)
    print(f"对照组 {n1:,} 人，7 日激活率 {p1:.1%}；改版组 {n2:,} 人，{p2:.1%}")
    print(f"差 {d * 100:+.1f}pt，95% 区间 {lo * 100:+.1f}pt 到 {hi * 100:+.1f}pt（可忽略带 ±{NEGLIGIBLE * 100:.1f}pt，采用线 +{ADOPT * 100:.1f}pt）")
    print(f"判定：{decide(lo, hi)}")
    # 要把区间半宽缩到可忽略带以内，每组大约要多少人、按现在的流量还要几周
    p = (x1 + x2) / (n1 + n2)
    need = math.ceil(Z ** 2 * 2 * p * (1 - p) / NEGLIGIBLE ** 2)
    weeks = math.ceil(max(need - min(n1, n2), 0) / WEEKLY_NEW_USERS_PER_ARM)
    print(f"区间半宽缩到 ±{NEGLIGIBLE * 100:.1f}pt 需要每组约 {need:,} 人；按每组每周 {WEEKLY_NEW_USERS_PER_ARM:,} 人，还要约 {weeks} 周")
    print("分组描述（事先没登记，不作结论）：")
    for dev in ("新设备", "老设备"):
        a, b, dd, l2, h2 = diff_ci(*total(rows, "对照组", dev), *total(rows, "改版组", dev))
        print(f"  {dev}：{a:.1%} → {b:.1%}，差 {dd * 100:+.1f}pt，区间 {l2 * 100:+.1f}pt 到 {h2 * 100:+.1f}pt")


if __name__ == "__main__":
    main()
