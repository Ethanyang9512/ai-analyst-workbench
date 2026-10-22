# -*- coding: utf-8 -*-
"""出图自检：用程序查三类肉眼容易漏的问题。

  1. 两段文字互相重叠
  2. 折线穿过文字
  3. 文字超出画布，或被坐标区裁掉

用法（出图脚本里，代替 fig.savefig）：

    import sys; sys.path.insert(0, "<ethan-report-writing/scripts 目录>")
    from figcheck import save_checked
    save_checked(fig, "out/f01.png")

它照常保存图片，并在旁边写 f01.png.check.json；发现问题会打印出来。
有问题就先改图再发。程序查不出“颜色难分”“图不表达结论”，这些仍要看图判断。
"""
import json
import os

import numpy as np
from matplotlib.text import Text

OVERLAP_RATIO = 0.08      # 交叠面积占较小文字框的比例，超过才算重叠
EDGE_PX = 2.0             # 超出画布多少像素才算出界
SAMPLES_PER_SEGMENT = 12  # 判断折线是否穿过文字时，每段线的采样点数


def _label(text):
    s = " ".join(str(text.get_text()).split())
    return s[:18] + ("…" if len(s) > 18 else "")


def _hidden_tick_labels(fig):
    """坐标轴范围以外的刻度文字：matplotlib 不会画出来，不能算问题。"""
    hidden = set()
    for ax in fig.axes:
        for axis, limits in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            lo, hi = sorted(limits)
            pad = (hi - lo) * 1e-9
            axis_off = (not ax.axison) or (not axis.get_visible())
            if axis_off:
                hidden.add(id(axis.label))
                hidden.add(id(axis.get_offset_text()))
            for which in (False, True):
                try:
                    ticks = axis.get_minor_ticks() if which else axis.get_major_ticks()
                    locs = axis.get_ticklocs(minor=which)
                except Exception:
                    continue
                for loc, tick in zip(locs, ticks):
                    out_of_range = loc < lo - pad or loc > hi + pad
                    for label in (tick.label1, tick.label2):
                        if axis_off or out_of_range or not label.get_visible():
                            hidden.add(id(label))
    return hidden


def _tick_label_ids(fig):
    ids = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                ids.add(id(tick.label1))
                ids.add(id(tick.label2))
    return ids


def _texts(fig, renderer):
    out = []
    hidden = _hidden_tick_labels(fig)
    for t in fig.findobj(Text):
        try:
            if id(t) in hidden:
                continue
            if not t.get_visible() or not str(t.get_text()).strip():
                continue
            box = t.get_window_extent(renderer)
        except Exception:
            continue
        if box.width <= 1 or box.height <= 1:
            continue
        out.append((t, box))
    return out


def _overlap(a, b):
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    return (w * h) / max(1.0, min(a.width * a.height, b.width * b.height))


def check_figure(fig):
    """返回问题清单；每项是 {'type': ..., 'detail': ...}。空列表表示没查出问题。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = _texts(fig, renderer)
    issues = []

    # 1. 文字互相重叠
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (ta, ba), (tb, bb) = items[i], items[j]
            if _overlap(ba, bb) > OVERLAP_RATIO:
                issues.append({"type": "文字重叠", "detail": f"「{_label(ta)}」与「{_label(tb)}」"})

    # 2. 折线穿过文字
    for ax in fig.axes:
        for line in ax.get_lines():
            if not line.get_visible():
                continue
            try:
                xy = ax.transData.transform(np.column_stack([
                    np.asarray(line.get_xdata(orig=False), dtype=float),
                    np.asarray(line.get_ydata(orig=False), dtype=float)]))
            except Exception:
                continue
            if len(xy) < 2:
                continue
            pts = []
            for k in range(len(xy) - 1):
                if not (np.all(np.isfinite(xy[k])) and np.all(np.isfinite(xy[k + 1]))):
                    continue
                for f in np.linspace(0.0, 1.0, SAMPLES_PER_SEGMENT, endpoint=False):
                    pts.append(xy[k] + (xy[k + 1] - xy[k]) * f)
            if not pts:
                continue
            pts = np.array(pts)
            for t, box in items:
                if t.axes is not ax or t in ax.get_xticklabels() + ax.get_yticklabels():
                    continue
                inside = ((pts[:, 0] > box.x0 + 1) & (pts[:, 0] < box.x1 - 1)
                          & (pts[:, 1] > box.y0 + 1) & (pts[:, 1] < box.y1 - 1))
                if inside.any():
                    issues.append({"type": "折线穿过文字", "detail": f"「{_label(t)}」"})

    # 3. 出界 / 被裁
    width, height = fig.canvas.get_width_height()
    tick_ids = _tick_label_ids(fig)
    for t, box in items:
        if id(t) in tick_ids:        # 刻度文字只查重叠，不查出界
            continue
        if (box.x0 < -EDGE_PX or box.y0 < -EDGE_PX
                or box.x1 > width + EDGE_PX or box.y1 > height + EDGE_PX):
            issues.append({"type": "文字超出画布", "detail": f"「{_label(t)}」"})
        elif t.axes is not None and t.get_clip_on() and t.get_clip_box() is not None:
            ab = t.axes.get_window_extent(renderer)
            if (box.x0 < ab.x0 - EDGE_PX or box.x1 > ab.x1 + EDGE_PX
                    or box.y0 < ab.y0 - EDGE_PX or box.y1 > ab.y1 + EDGE_PX):
                issues.append({"type": "文字被坐标区裁掉", "detail": f"「{_label(t)}」"})

    seen, unique = set(), []
    for it in issues:
        key = (it["type"], it["detail"])
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique


def save_checked(fig, path, **savefig_kwargs):
    """保存图片并自检。返回问题清单。"""
    savefig_kwargs.setdefault("bbox_inches", "tight")
    savefig_kwargs.setdefault("facecolor", "white")
    try:
        issues = check_figure(fig)
        error = None
    except Exception as e:      # 自检出错不能挡住出图
        issues, error = [], f"{type(e).__name__}: {e}"
    fig.savefig(path, **savefig_kwargs)
    record = {"file": os.path.basename(path), "issues": issues, "checked": error is None}
    if error:
        record["error"] = error
    try:
        with open(path + ".check.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    name = os.path.basename(path)
    if error:
        print(f"[出图自检] {name}：自检没跑成（{error}），请直接看图")
    elif issues:
        print(f"[出图自检] ⚠ {name}：{len(issues)} 处问题，先改再发")
        for it in issues[:12]:
            print(f"    - {it['type']}：{it['detail']}")
    else:
        print(f"[出图自检] {name}：没查出文字重叠、折线穿字或出界（颜色和表达仍要看图判断）")
    return issues


def _patch_savefig():
    """让脚本里所有 fig.savefig(...) 都顺带自检（不用改脚本）。"""
    from matplotlib.figure import Figure
    original = Figure.savefig

    def savefig(self, fname, *args, **kwargs):
        result = original(self, fname, *args, **kwargs)
        if isinstance(fname, (str, os.PathLike)) and str(fname).lower().endswith((".png", ".jpg", ".jpeg")):
            path = os.fspath(fname)
            try:
                issues = check_figure(self)
                record = {"file": os.path.basename(path), "issues": issues, "checked": True}
            except Exception as e:
                issues = []
                record = {"file": os.path.basename(path), "issues": [], "checked": False,
                          "error": f"{type(e).__name__}: {e}"}
            try:
                with open(path + ".check.json", "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=1)
            except OSError:
                pass
            name = os.path.basename(path)
            if not record["checked"]:
                print(f"[出图自检] {name}：自检没跑成（{record['error']}），请直接看图")
            elif issues:
                print(f"[出图自检] ⚠ {name}：{len(issues)} 处问题，先改再发")
                for it in issues[:12]:
                    print(f"    - {it['type']}：{it['detail']}")
            else:
                print(f"[出图自检] {name}：没查出文字重叠、折线穿字或出界")
        return result

    Figure.savefig = savefig


if __name__ == "__main__":
    # 用法: python3 figcheck.py <出图脚本.py> [脚本参数…]
    # 不改脚本，直接让它保存的每张图都过一遍自检。
    import runpy
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        print("也可以：python3 figcheck.py <出图脚本.py> [脚本参数…]  —— 不改脚本，保存的每张图都自检")
        sys.exit(2)
    import matplotlib
    matplotlib.use("Agg")
    _patch_savefig()
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    runpy.run_path(script, run_name="__main__")
