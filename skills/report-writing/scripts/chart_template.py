# -*- coding: utf-8 -*-
"""黑灰红极简风出图模板 —— 新出图脚本从这里起步。

统一风格：黑=主系列 / 浅灰=次系列 / 红=强调，纯白无框，全数据标签。
**同一套配色也用在汇报 PPT 上**（skills/slide-deck/scripts/check_deck.py 的默认合法色表与本文件逐值对齐），
所以文档里的图和片子里的图观感一致。

硬约束（详见技能目录 references/chart-style-guide.md，冲突时以它为准）：
  · 字体 = 中文字体回落链 PingFang SC → Noto Sans CJK SC → Arial Unicode MS；
    想让拉丁字母和数字用你的品牌字体，设环境变量 AAW_LATIN_FONT（字体 family 名），默认不设
  · **配色只用下面的黑灰红**；绿/红是语义色（正向/负向），成对出现才用
  · **不要用品牌色给图上色** —— 那是页面装饰色
  · 柱宽 单系列 0.30~0.36、簇状 0.22~0.26，默认 0.8 太胖
  · 纯白背景，**不套卡片 / 边框 / 标题条**（套了会像从别的系统截图贴进来）
  · **无 Y 轴标签、无刻度、无左边框**，纵轴含义写进副标题
  · 无网格线（气泡图也不要）
  · **折线一律平滑**：点少用 PCHIP 单调插值（防过冲），点多画 7 天移动平均
  · 双轴图的柱值标签贴柱底、柱内白字，避开累计线
  · **每张图出完先自己 Read 一遍 PNG**：查文字重叠 / 被线穿过 / 出界 / 豆腐块

示例数据：本例数字均为虚构（示例 App 的订阅续费，周次 W1–W8；影响值、占比、合计都由代码现算）。
出图位置：环境变量 CHART_OUT 指定的目录；不设就写到当前目录。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager  # noqa: E402
import matplotlib.pyplot as plt
import numpy as np

OUT = os.environ.get("CHART_OUT") or os.getcwd()

# ---- 全局字体（换字体只设 AAW_LATIN_FONT 一个变量）----
# 拉丁字体只含字母/数字/标点时，中文由 matplotlib 逐字形回落到后面的中文字体。
LATIN_FONT = os.environ.get("AAW_LATIN_FONT", "").strip()
CJK_FONTS = ["PingFang SC", "Noto Sans CJK SC", "Arial Unicode MS"]
_installed = {f.name for f in matplotlib.font_manager.fontManager.ttflist}   # 只留本机装了的，免得每张图都报找不到字体
plt.rcParams["font.family"] = ([LATIN_FONT] if LATIN_FONT else []) + (
    [f for f in CJK_FONTS if f in _installed] or ["sans-serif"])
plt.rcParams["axes.unicode_minus"] = False
BAR_W = 0.32          # 柱宽默认值：单系列 0.30~0.36，别用 matplotlib 默认的 0.8

# ---- 配色：黑灰红（与 slide-deck/scripts/check_deck.py 的默认合法色表逐值对齐）----
# 装饰性区分系列一律黑灰；绿红只作语义编码，且必须成对出现。
# 判断标准：这个颜色是在"区分系列"还是在"表达好坏"？前者黑灰，后者才可以绿红。
BLACK      = "#1A1A1A"   # 主系列 / 主角（一图最多一个）
GRAY       = "#B9B9BC"   # 次系列 / 对标
GRAY_DK    = "#7F7F7F"   # 三段堆叠的中段
GRAY_LT    = "#DDE0E4"   # 背景参照、极淡底线
RED        = "#C0392B"   # 强调线 / 累计线 / 分水岭 / 差异箭头药丸
POS        = "#2E9E5B"   # 语义：正向（拉动）
NEG        = "#D64545"   # 语义：负向（拖累）
HEAT = ["#1B7F4F", "#63B37E", "#F2C94C", "#E8873A", "#D64545"]  # 高→低 五档热力（必须配图例）


def smooth(x, y, n=300):
    """单调三次插值（PCHIP），不会过冲出数据范围；scipy 不可用则原样返回（折线）。"""
    try:
        from scipy.interpolate import PchipInterpolator
        xs = np.linspace(min(x), max(x), n)
        return xs, PchipInterpolator(x, y)(xs)
    except Exception:
        return np.asarray(x, float), np.asarray(y, float)


# ---- 示例数据（虚构）：W6 各获客渠道的到期订阅数和续费率；图 2、图 6 共用 ----
CHANNELS = [("老带新", "直购", 1500, 89.8), ("官网", "直购", 5200, 82.8), ("应用商店", "直购", 4600, 79.0),
            ("邮件召回", "其他", 900, 77.6), ("搜索广告", "投放", 2100, 75.4), ("合作伙伴", "其他", 800, 73.9),
            ("信息流", "投放", 2600, 69.0), ("达人推荐", "投放", 1300, 65.8), ("线下活动", "其他", 400, 62.1),
            ("限时折扣页", "投放", 600, 57.0)]


def channel_table():
    """[(渠道, 类型, 到期订阅数, 占比, 续费率, 影响值pt)]，整体续费率。影响值 = 占比 ×（渠道续费率 − 整体续费率），合计为 0。"""
    total = sum(c[2] for c in CHANNELS)
    overall = sum(c[2] * c[3] for c in CHANNELS) / total
    rows = [(n, t, q, q / total, r, q / total * (r - overall)) for n, t, q, r in CHANNELS]
    return sorted(rows, key=lambda x: -x[5]), overall


def style_line(ax, title):
    """极简坐标轴：去上/右/左边框，只留一条极淡底线，无网格无刻度线。"""
    ax.set_title(title, fontsize=17, fontweight="bold", color=BLACK, pad=42)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#E3E5E8")
    ax.spines["bottom"].set_linewidth(0.9)
    ax.tick_params(axis="both", labelsize=12, colors="#3A3A3A", length=0)
    ax.grid(False)


# ============ 图1 构成（横向堆叠条，黑/灰）============
def chart_mix():
    fig, ax = plt.subplots(figsize=(11, 2.6), dpi=200)
    segs = [("多次续费", 14200, BLACK, "white"),
            ("月付首次", 3000, GRAY_DK, "white"),
            ("年付首次\n（去年优惠）", 2800, GRAY, BLACK)]
    total = sum(s[1] for s in segs)
    left = 0
    for name, val, color, tcolor in segs:
        ax.barh(0, val, left=left, color=color, height=0.55)
        pct = val / total
        ax.text(left + val / 2, 0, f"{pct:.0%}\n{val:,} 个",
                ha="center", va="center", color=tcolor, fontsize=13, fontweight="bold")
        ax.text(left + val / 2, -0.46, name, ha="center", va="top",
                color="#333333", fontsize=12)
        left += val
    ax.set_title("W6 到期订阅的构成：首次续费占 29%",
                 fontsize=17, fontweight="bold", color=BLACK, pad=18)
    ax.set_xlim(0, total); ax.set_ylim(-0.9, 0.45)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(f"{OUT}/c1_mix.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ 图2 影响值（柱状，黑=拉动 灰=拖累）============
def chart_impact():
    rows, _ = channel_table()
    names = [r[0] for r in rows]
    vals = [round(r[5], 2) for r in rows]
    colors = [BLACK if v > 0 else GRAY for v in vals]
    pos, neg = [v for v in vals if v > 0], [v for v in vals if v <= 0]

    fig, ax = plt.subplots(figsize=(12, 6), dpi=200)
    bars = ax.bar(names, vals, color=colors, width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2,
                v + (0.05 if v > 0 else -0.05), f"{v:+.2f}",
                ha="center", va="bottom" if v > 0 else "top",
                fontsize=12, fontweight="bold", color=BLACK)
    ax.axhline(0, color="#333333", lw=1.2)
    ax.set_title("W6 各获客渠道对整体续费率的影响值（百分点）",
                 fontsize=17, fontweight="bold", color=BLACK, pad=34)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.set_yticks([]); ax.set_ylim(min(vals) * 1.45, max(vals) * 1.6)
    ax.tick_params(axis="x", labelsize=13, colors=BLACK, length=0)
    ax.grid(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLACK),
               plt.Rectangle((0, 0), 1, 1, color=GRAY)]
    ax.legend(handles, [f"拉动整体（{len(pos)} 项合计 {sum(pos):+.2f}pt）", f"拖累整体（{len(neg)} 项合计 {sum(neg):+.2f}pt）".replace("-", "−")],
              loc="upper right", frameon=False, fontsize=12.5, handlelength=1.5)
    fig.tight_layout()
    fig.savefig(f"{OUT}/c2_impact.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ 图3 整体周趋势（单线，黑）============
def chart_overall():
    wk = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"]
    y = [80.7, 80.8, 80.8, 80.6, 80.8, 77.0, 76.7, 77.2]
    x = np.arange(len(wk))
    xs, ys = smooth(x, y)

    fig, ax = plt.subplots(figsize=(11, 5.0), dpi=200)
    ax.plot(xs, ys, color=BLACK, lw=3.6, solid_capstyle="round")
    ax.scatter(x, y, color=BLACK, s=52, zorder=3)
    for xi, yi in zip(x, y):
        ax.text(xi, yi + 0.7, f"{yi:.1f}%", ha="center", fontsize=13,
                fontweight="bold", color=BLACK)
    ax.set_title("续费率周趋势：W6 起比前 5 周低约 4pt",
                 fontsize=17, fontweight="bold", color=BLACK, pad=24)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#333333")
    ax.set_yticks([]); ax.set_ylim(74, 84)
    ax.set_xticks(x); ax.set_xticklabels(wk)
    ax.tick_params(axis="x", labelsize=13, colors=BLACK, length=0)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(f"{OUT}/c3_overall.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ 图4 涨价的月付 vs 没涨价的年付（双线 黑+灰）============
def chart_decline():
    wk = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"]
    yi_ = [86.1, 85.9, 86.0, 86.2, 86.0, 86.0, 85.8, 86.1]     # 年付多次续费（没涨价）
    xin = [83.9, 84.2, 84.0, 83.8, 84.0, 82.0, 81.8, 82.1]     # 月付多次续费（W6 起涨价）
    x = np.arange(len(wk))

    fig, ax = plt.subplots(figsize=(11, 5.4), dpi=200)
    for y, color, label, dy in ((xin, BLACK, "月付（W6 起涨价）", -1.3),
                                (yi_, GRAY_DK, "年付（价格没变）", 0.55)):
        xs, ys = smooth(x, y)
        ax.plot(xs, ys, color=color, lw=3.6, solid_capstyle="round", label=label)
        ax.scatter(x, y, color=color, s=52, zorder=3)
        for xi, yv in zip(x, y):
            ax.text(xi, yv + dy, f"{yv:.1f}%", ha="center", fontsize=12.5,
                    fontweight="bold", color=color)
    ax.set_title("只有涨了价的月付续费率下降，年付持平",
                 fontsize=17, fontweight="bold", color=BLACK, pad=40)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#333333")
    ax.set_yticks([]); ax.set_ylim(78.5, 89)
    ax.set_xticks(x); ax.set_xticklabels(wk)
    ax.tick_params(axis="x", labelsize=13, colors=BLACK, length=0)
    ax.grid(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.11), ncol=2,
              frameon=False, fontsize=13.5, handlelength=2.2, columnspacing=3.0)
    fig.tight_layout()
    fig.savefig(f"{OUT}/c4_decline.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    chart_mix(); chart_impact(); chart_overall(); chart_decline()
    for f in ("c1_mix", "c2_impact", "c3_overall", "c4_decline"):
        p = f"{OUT}/{f}.png"
        print(f"  {f}.png  {os.path.getsize(p)/1024:.0f} KB")


# ============ 图5 按订阅类型分区（红绿灯语义配色）============
def chart_zone():
    segs = [("多次续费（月付 + 年付）", 14200, 82.6, HEAT[0]),
            ("月付首次续费", 3000, 68.0, HEAT[3]),
            ("年付首次续费", 2800, 58.0, HEAT[4])]
    total = sum(s[1] for s in segs)
    fig, ax = plt.subplots(figsize=(12, 3.1), dpi=200)
    left = 0
    for name, q, rate, color in segs:
        ax.barh(0, q, left=left, color=color, edgecolor="white", linewidth=2.4, height=0.5)
        ax.text(left + q / 2, 0.03, f"续费率 {rate:.1f}%", ha="center", va="center",
                color="white", fontsize=13.5, fontweight="bold")
        ax.text(left + q / 2, -0.18, f"占 {q/total:.1%}",
                ha="center", va="center", color="white", fontsize=11)
        ax.text(left + q / 2, -0.42, f"{name}\n{q:,} 个", ha="center", va="top",
                color="#333333", fontsize=11.5)
        left += q
    ax.set_title("W6 按订阅类型分：年付首次续费只有 58.0%",
                 fontsize=17, fontweight="bold", color=BLACK, pad=16)
    ax.set_xlim(0, total); ax.set_ylim(-0.95, 0.4); ax.axis("off")
    fig.tight_layout()
    fig.savefig(f"{OUT}/c5_zone.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ 图6 获客渠道主表（数据条：影响值绿正红负）============
def table_main():
    rows, _ = channel_table()
    n = len(rows)
    fig, ax = plt.subplots(figsize=(13, 0.52 * n + 1.5), dpi=200)
    ax.set_xlim(0, 100); ax.set_ylim(-n - 0.9, 1.4); ax.axis("off")

    for t, xp in [("获客渠道", 2), ("类型", 20), ("到期订阅", 29), ("占比", 40)]:
        ax.text(xp, 0.42, t, fontsize=12.5, fontweight="bold", color=BLACK, va="center")
    ax.text(48, 0.42, "续费率", fontsize=12.5, fontweight="bold", color=BLACK, va="center")
    ax.text(76, 0.42, "影响值（pt）", fontsize=12.5, fontweight="bold", color=BLACK, va="center")
    ax.plot([0, 100], [-0.05, -0.05], color=BLACK, lw=1.4)

    BAR_X, BAR_W, ZERO_X, HALF = 48, 22, 84, 8
    mx = max(abs(v) for *_, v in rows)
    for i, (name, rt, q, share, nd, imp) in enumerate(rows):
        y = -i - 0.55
        if i % 2 == 0:
            ax.add_patch(plt.Rectangle((0, y - 0.34), 100, 0.68, color="#F7F7F7", zorder=0))
        ax.text(2, y, name, fontsize=12, color=BLACK, va="center")
        ax.text(20, y, rt, fontsize=11.5, color="#555555", va="center")
        ax.text(29, y, f"{q:,}", fontsize=11.5, color="#555555", va="center")
        ax.text(40, y, f"{share:.1%}", fontsize=11.5, color="#555555", va="center")
        ax.add_patch(plt.Rectangle((BAR_X, y - 0.22), BAR_W, 0.44, color="#EFEFEF", zorder=1))
        ax.add_patch(plt.Rectangle((BAR_X, y - 0.22), BAR_W * nd / 100, 0.44,
                                   color=BLACK if nd >= 80 else (GRAY_DK if nd >= 65 else GRAY), zorder=2))
        ax.text(BAR_X + BAR_W + 1.2, y, f"{nd:.1f}%", fontsize=12,
                fontweight="bold", color=BLACK, va="center", zorder=3)
        w = HALF * abs(imp) / mx
        ax.add_patch(plt.Rectangle((ZERO_X if imp > 0 else ZERO_X - w, y - 0.22), w, 0.44,
                                   color=POS if imp > 0 else NEG, zorder=2))
        ax.plot([ZERO_X, ZERO_X], [y - 0.3, y + 0.3], color="#999999", lw=0.9, zorder=3)
        ax.text(ZERO_X + HALF + 1.5, y, f"{imp:+.2f}", fontsize=11.5, fontweight="bold",
                color=POS if imp > 0 else NEG, va="center")
    ax.set_title("10 个获客渠道明细：续费率与对整体的影响值",
                 fontsize=17, fontweight="bold", color=BLACK, pad=18)
    fig.tight_layout()
    fig.savefig(f"{OUT}/t1_main.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ============ 图7 周趋势热力图（红绿灯色阶）============
def heat(v):
    """续费率 → (底色, 字色)。越高越绿，越低越红。"""
    if v >= 85: return HEAT[0], "white"
    if v >= 80: return HEAT[1], "white"
    if v >= 75: return HEAT[2], BLACK
    if v >= 70: return HEAT[3], "white"
    return HEAT[4], "white"


def table_trend():
    wk = ["W4", "W5", "W6", "W7", "W8"]
    data = [("老带新", [90.1, 89.9, 89.8, 90.0, 89.7], "平稳"),
            ("官网", [85.6, 85.4, 82.8, 82.5, 82.9], "下降 −2.7pt"),
            ("应用商店", [79.4, 79.6, 79.0, 78.8, 79.2], "平稳"),
            ("搜索广告", [77.8, 77.3, 76.6, 76.2, 76.5], "稳中略降"),
            ("信息流", [73.2, 72.8, 69.0, 68.6, 69.3], "下降 −3.9pt"),
            ("限时折扣页", [58.4, 57.9, 57.0, 56.6, 57.2], "低位")]
    n = len(data)
    fig, ax = plt.subplots(figsize=(12, 0.62 * n + 1.9), dpi=200)
    ax.set_xlim(0, 100); ax.set_ylim(-n - 1.5, 1.5); ax.axis("off")
    X0, CW = 24, 11
    for j, w in enumerate(wk):
        ax.text(X0 + j * CW + CW / 2, 0.45, w, fontsize=12, fontweight="bold",
                color=BLACK, ha="center", va="center")
    ax.text(X0 + 5 * CW + 6, 0.45, "趋势", fontsize=12, fontweight="bold", color=BLACK, va="center")
    for i, (name, vs, tr) in enumerate(data):
        y = -i - 0.6
        ax.text(2, y, name, fontsize=12, color=BLACK, va="center")
        for j, v in enumerate(vs):
            bg, fg = heat(v)
            ax.add_patch(plt.Rectangle((X0 + j * CW + 0.6, y - 0.3), CW - 1.2, 0.6, color=bg, zorder=1))
            ax.text(X0 + j * CW + CW / 2, y, f"{v:.1f}%", fontsize=11.5, fontweight="bold",
                    color=fg, ha="center", va="center", zorder=2)
        ax.text(X0 + 5 * CW + 6, y, tr, fontsize=11.5, va="center",
                color=NEG if "下降" in tr else "#555555",
                fontweight="bold" if "下降" in tr else "normal")
    # 图例
    labs = ["≥85%", "80~85%", "75~80%", "70~75%", "<70%"]
    for k, (cl, lb) in enumerate(zip(HEAT, labs)):
        x = X0 + k * 12
        ax.add_patch(plt.Rectangle((x, -n - 1.05), 3.4, 0.42, color=cl))
        ax.text(x + 4.2, -n - 0.84, lb, fontsize=11, color="#333333", va="center")
    ax.set_title("分获客渠道周趋势：绿色为高、红色为低",
                 fontsize=17, fontweight="bold", color=BLACK, pad=18)
    fig.tight_layout()
    fig.savefig(f"{OUT}/t2_trend.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    chart_zone(); table_main(); table_trend()
    for f in ("c5_zone", "t1_main", "t2_trend"):
        print(f"  {f}.png  {os.path.getsize(f'{OUT}/{f}.png')/1024:.0f} KB")
