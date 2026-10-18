#!/usr/bin/env python3
"""出图自检 figcheck.py 的回归测试（在技能目录下运行，需要 matplotlib）：python3 tests/test_figcheck.py
前 7 个场景是人为造的毛病（应当报出来）或干净的图（应当不报）；最后把 chart_template.py 里认可风格的图全跑一遍，应当零误报。"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能目录（本文件在 tests/ 下）
sys.path.insert(0, os.path.join(HERE, "scripts"))
try:
    import matplotlib  # noqa: E402
except ImportError:                       # 没装 matplotlib：整组跳过，不算失败
    print("跳过：当前解释器没有 matplotlib（pip install matplotlib 后再跑）")
    sys.exit(0)
matplotlib.use("Agg")
import matplotlib.font_manager  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from figcheck import check_figure  # noqa: E402

_installed = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ("PingFang SC", "Noto Sans CJK SC", "Arial Unicode MS") if f in _installed] or ["sans-serif"]
kinds = lambda fig: sorted({i["type"] for i in check_figure(fig)})


def main():
    res = []
    fig, ax = plt.subplots(figsize=(8, 3.5))
    bars = ax.bar(["甲区", "乙区", "丙区"], [12, 9, 15], width=0.32)
    for r, v in zip(bars, [12, 9, 15]):
        ax.text(r.get_x() + r.get_width() / 2, v + 0.3, str(v), ha="center")
    ax.set_ylim(0, 18)
    res.append(("干净的柱图：不报", kinds(fig) == []))

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot([1, 2, 3], [1, 2, 3])
    ax.text(2, 2.6, "每千单退款数 38"); ax.text(2.02, 2.62, "续费率 82.0%"); ax.set_ylim(0, 4)
    res.append(("两个标签叠在一起", "文字重叠" in kinds(fig)))

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot([1, 2, 3, 4], [1, 3, 2, 4])
    ax.text(2.5, 2.5, "W6 回落", ha="center", va="center")
    res.append(("折线穿过文字", "折线穿过文字" in kinds(fig)))

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(["a", "b"], [1, 2])
    fig.text(0.97, 0.5, "这是一段很长很长会超出右边界的注记文字", ha="left")
    res.append(("文字超出画布", "文字超出画布" in kinds(fig)))

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(["a", "b"], [1, 2])
    ax.text(1.45, 1.0, "B 区", clip_on=True)
    res.append(("文字被坐标区裁掉", "文字被坐标区裁掉" in kinds(fig)))

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(["a", "b"], [1, 2])
    ax.text(1.4, 1.0, "被裁掉的长标签文字文字文字", clip_on=True)
    res.append(("又被裁掉又出画布：至少报一种", bool({"文字被坐标区裁掉", "文字超出画布"} & set(kinds(fig)))))

    fig, ax = plt.subplots(figsize=(3, 2.2))
    ax.bar([f"2026-09-{d:02d}" for d in range(1, 15)], range(14))
    res.append(("横轴日期挤在一起", "文字重叠" in kinds(fig)))
    plt.close("all")

    # 认可风格的模板图：零误报
    tmp = tempfile.mkdtemp(prefix="figcheck-")
    env = {k: v for k, v in os.environ.items() if k != "CHART_OUT"}       # 出图落在临时目录，不写进使用者设的目录
    p = subprocess.run([sys.executable, os.path.join(HERE, "scripts", "figcheck.py"), os.path.join(HERE, "scripts", "chart_template.py")],
                       cwd=tmp, capture_output=True, text=True, env=env)
    lines = [x for x in p.stdout.splitlines() if "[出图自检]" in x]
    res.append((f"模板图 {len(lines)} 张零误报", len(lines) >= 7 and not any("⚠" in x for x in lines)))

    bad = 0
    for name, good in res:
        if not good:
            bad += 1
            print("FAIL", name)
    print(f"{len(res) - bad}/{len(res)} 通过")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
