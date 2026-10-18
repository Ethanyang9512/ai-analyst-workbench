#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 data/weekly_by_segment.csv 重算报告里的每一个数（本例数据全部虚构）。

用法：python3 analysis/recompute.py            # 在示例目录下运行，打印报告用到的全部数
      python3 analysis/recompute.py --json     # 同样的数，JSON 格式，方便核对程序读

口径（和 _CONVENTIONS.md 第 3、4 条一致）：
  续费率   = 当周到期且在宽限期内续费成功的订阅数 ÷ 当周到期订阅数
  主动取消 = 到期前用户关掉了自动续费；扣款失败 = 自动续费开着但没扣成
  三者相加 = 到期订阅数，所以 续费率 + 主动取消占比 + 扣款失败占比 = 100%
拆解（W5 → W6，四个分组：方案 × 首次/多次续费）：
  构成变化 = Σ（W6 分组占比 − W5 分组占比）× W5 分组续费率
  续费率变化 = Σ W6 分组占比 ×（W6 分组续费率 − W5 分组续费率）
  两项相加正好等于整体续费率的变化，没有余项。
只用标准库。
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, os.pardir, "data", "weekly_by_segment.csv")


def load():
    with open(DATA, encoding="utf-8") as f:
        return [dict(r, **{k: int(r[k]) for k in ("expiring", "renewed", "cancelled", "payment_failed")})
                for r in csv.DictReader(f)]


def weekly(rows):
    out = {}
    for r in rows:
        w = out.setdefault(r["week"], {"expiring": 0, "renewed": 0, "cancelled": 0, "payment_failed": 0, "first": 0})
        for k in ("expiring", "renewed", "cancelled", "payment_failed"):
            w[k] += r[k]
        if r["cohort"] == "首次续费":
            w["first"] += r["expiring"]
    for w in out.values():
        assert w["renewed"] + w["cancelled"] + w["payment_failed"] == w["expiring"]
        e = w["expiring"]
        w["rate"], w["cancel_share"], w["fail_share"], w["first_share"] = (
            w["renewed"] / e, w["cancelled"] / e, w["payment_failed"] / e, w["first"] / e)
    return out


def segments(rows, week):
    seg = {(r["plan"], r["cohort"]): r for r in rows if r["week"] == week}
    total = sum(r["expiring"] for r in seg.values())
    return {k: {"share": r["expiring"] / total, "rate": r["renewed"] / r["expiring"], "expiring": r["expiring"]}
            for k, r in seg.items()}


def decompose(rows, a="W5", b="W6"):
    sa, sb = segments(rows, a), segments(rows, b)
    mix = sum((sb[k]["share"] - sa[k]["share"]) * sa[k]["rate"] for k in sa)
    rate = {k: sb[k]["share"] * (sb[k]["rate"] - sa[k]["rate"]) for k in sa}
    return sa, sb, mix, rate


def pct(x):
    return f"{x * 100:.1f}%"


def pt(x):
    return f"{x * 100:+.1f}pt"


def main():
    rows = load()
    wk = weekly(rows)
    sa, sb, mix, rate = decompose(rows)
    total_change = wk["W6"]["rate"] - wk["W5"]["rate"]
    assert abs(mix + sum(rate.values()) - total_change) < 1e-12
    before = [wk[f"W{i}"]["rate"] for i in range(1, 6)]
    after = [wk[f"W{i}"]["rate"] for i in range(6, 9)]
    res = {
        "weekly": {w: {"到期订阅数": v["expiring"], "续费率": pct(v["rate"]), "主动取消占比": pct(v["cancel_share"]),
                       "扣款失败占比": pct(v["fail_share"]), "首次续费占比": pct(v["first_share"])} for w, v in wk.items()},
        "W1-W5 续费率区间": f"{pct(min(before))}–{pct(max(before))}",
        "W6-W8 续费率区间": f"{pct(min(after))}–{pct(max(after))}",
        "W5→W6 整体变化": pt(total_change),
        "其中 构成变化（首次续费变多）": pt(mix),
        "其中 各组续费率变化": pt(sum(rate.values())),
        "各组续费率变化的贡献": {f"{p}-{c}": pt(v) for (p, c), v in rate.items()},
        "分组续费率 W5→W6": {f"{p}-{c}": f"{pct(sa[(p, c)]['rate'])}→{pct(sb[(p, c)]['rate'])}" for (p, c) in sa},
        "主动取消占比变化": pt(wk["W6"]["cancel_share"] - wk["W5"]["cancel_share"]),
        "扣款失败占比变化": pt(wk["W6"]["fail_share"] - wk["W5"]["fail_share"]),
    }
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print("周 | 到期订阅数 | 续费率 | 主动取消 | 扣款失败 | 首次续费占比")
    for w, v in res["weekly"].items():
        print(f"{w} | {v['到期订阅数']:,} | {v['续费率']} | {v['主动取消占比']} | {v['扣款失败占比']} | {v['首次续费占比']}")
    for k, v in res.items():
        if k != "weekly":
            print(f"{k}：{v}")


if __name__ == "__main__":
    main()
