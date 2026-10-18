#!/usr/bin/env python3
"""验收记录：正式交付物（文档、PPT、Excel）发出前，把验收结果记一笔。

  accept_record.py write --file <交付物> [--file ...] [--doc "<飞书文档标题或链接>"] \\
                         [--tier small|page|full] [--pages "5,6,24"] \\
                         --reader "<读者验收的一句话结果>" --visual "<图表与数字验收的一句话结果>" [--note "..."]
  accept_record.py check --file <交付物>     # 这个文件（按内容指纹）有记录就返回 0
  accept_record.py list                      # 列出当前工作区最近的记录
  accept_record.py status [--file <交付物>] [--json]
                                             # 起点以来记了几条、涉及哪些页，该不该全稿通读一次
                                             # （起点＝最近一次全稿验收；设了 AAW_TIER_START 时，
                                             #   取它和最近一次全稿验收两者中较晚的那个）

--tier 是这次验收的档位：small 小改、page 大改（看改动范围）、full 全稿通读。不写记为 unspecified，不算全稿验收。
--pages 写这次涉及的页，自由文本（“5,6,24”“5-7”“第3页、封面”都行）。
记录写在“文件所在的工作区”最上层的 _acceptance/records.jsonl（只记飞书文档、不带文件时，写在当前工作区）。
在哪个目录里运行都一样（status 找工作区的方式和 write 一样）。文件内容变了，要重新验收、重新记录。
发送前的“验收门”钩子（hooks/gate.py）读的就是这份记录。

环境变量：
  AAW_WS_BASE     各项目工作区的总目录（默认 ~/aaw-workspaces），用来找“文件所在的工作区”
  AAW_TIER_START  分档上线时间（ISO 写法，如 2026-01-14T20:00:00+08:00）。中途才开始分档时设它：
                     这之前的旧记录没有分档，status 不拿它们做判断，只说明“分档上线前另有 N 条旧记录”。不设就全部记录都算。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

DIR_NAME = "_acceptance"
FILE_NAME = "records.jsonl"
WS_BASE = os.environ.get("AAW_WS_BASE") or os.path.expanduser("~/aaw-workspaces")
TIERS = ("small", "page", "full")


def _tier_start():
    """分档上线时间（AAW_TIER_START）。这之前的记录没有分档，status 不拿它们做下面三条判断，
    只在输出里说明“分档上线前另有 N 条旧记录”——免得上线后第一次跑就逼出一次全稿通读。不设或写错返回 None。"""
    raw = (os.environ.get("AAW_TIER_START") or "").strip()
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone(timedelta(hours=8)))


TIER_START = _tier_start()

# status 建议“下一次改稿后全稿通读一次”的条件，满足任意一条就建议。
# 都从“起点”算起：最近一次 --tier full 记录；没有全稿记录时，从分档上线时间（没设就从第一条记录）算起。
FULL_AFTER_RECORDS = 5      # 起点之后的验收记录达到 5 条
FULL_AFTER_PAGES = 8        # 起点之后涉及的页（各条 --pages 合并去重）达到 8 页
FULL_AFTER_DAYS = 3         # 距起点超过 3 天


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_root(start):
    """记录所在的目录：分析助手工作区的最上层（不随 cd 到子目录而变）。不在任何工作区里就用所在目录。"""
    p = os.path.realpath(start)
    base = os.path.realpath(WS_BASE)
    if p.startswith(base + os.sep):
        return os.path.join(base, p[len(base) + 1:].split(os.sep)[0])
    return p


def in_workspace(path):
    """path 在不在某个分析助手工作区里（工作区总目录本身不算）。"""
    return os.path.realpath(path).startswith(os.path.realpath(WS_BASE) + os.sep)


def file_root(path):
    """一个文件的记录应当放在哪：它所在的工作区。"""
    return find_root(os.path.dirname(os.path.realpath(path)))


def records_path(root):
    return os.path.join(root, DIR_NAME, FILE_NAME)


def load(root):
    """读出全部记录。坏行、不是对象的行一律跳过。"""
    path = records_path(root)
    out = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    return out


def digests(root):
    """这个工作区里所有有记录的文件指纹。"""
    out = set()
    for r in load(root):
        files = r.get("files")
        for f in files if isinstance(files, list) else []:
            if isinstance(f, dict) and isinstance(f.get("sha256"), str):
                out.add(f["sha256"])
    return out


def has_record(root, digest):
    return digest in digests(root)


def recent_doc_record(root, hours=6):
    limit = time.time() - hours * 3600
    for r in load(root):
        epoch = r.get("epoch")
        if r.get("doc") and isinstance(epoch, (int, float)) and epoch >= limit:
            return True
    return False


def page_items(text):
    """一条记录的 --pages 拆成页：数字页记成整数（“5-7”“第5页”“P5”都认），别的写法（如“封面”）原样留着。"""
    text = re.sub(r"\s*([-~～–—至到])\s*", r"\1", str(text or ""))
    text = re.sub(r"(第|(?<![A-Za-z])[Pp]\.?)\s+(?=\d)", r"\1", text)     # “第 3 页”“P 3”不拆成几项
    text = re.sub(r"(?<=\d)\s+(?=页)", "", text)
    out = []
    for tok in re.split(r"[,，、;；\s]+", text):
        if not tok:
            continue
        m = re.fullmatch(r"(?:第|[Pp]\.?)?(\d+)页?(?:[-~～–—至到](?:第|[Pp]\.?)?(\d+)页?)?", tok)
        a = int(m.group(1)) if m else 0
        b = int(m.group(2) or m.group(1)) if m else -1
        if a <= b <= a + 1000:
            out.extend(range(a, b + 1))
        else:
            out.append(tok)
    return out


def epoch_of(r):
    """记录里的时间戳；没有或不是数字返回 None。"""
    e = r.get("epoch")
    return e if isinstance(e, (int, float)) and not isinstance(e, bool) else None


def status(root, now=None):
    """起点（最近一次全稿验收和分档上线两者中较晚的那个）以来的累计情况，和要不要建议全稿通读。"""
    now = time.time() if now is None else now
    records = load(root)
    has_start = TIER_START is not None
    if has_start:
        tier_start = TIER_START.timestamp()
    else:                                                        # 没设分档上线时间：全部记录都算，起点是第一条记录
        epochs = [e for e in (epoch_of(r) for r in records) if e is not None]
        tier_start = min(epochs) if epochs else now
    is_new = lambda r: (not has_start) or (epoch_of(r) or 0) >= tier_start     # 分档上线之后写的记录
    fulls = [i for i, r in enumerate(records) if r.get("tier") == "full"]
    full_epoch = epoch_of(records[fulls[-1]]) if fulls else None
    from_full = full_epoch is not None and (not has_start or full_epoch >= tier_start)
    start = full_epoch if from_full else tier_start
    since = [r for r in (records[fulls[-1] + 1:] if fulls else records) if is_new(r)]
    pages = []
    for r in since:
        for p in page_items(r.get("pages")):
            if p not in pages:
                pages.append(p)
    pages = sorted(p for p in pages if isinstance(p, int)) + [p for p in pages if not isinstance(p, int)]
    days = (now - start) / 86400 if records else None      # 一条记录都没有的工作区不催
    reasons = []
    if len(since) >= FULL_AFTER_RECORDS:
        reasons.append(f"此后已有 {len(since)} 条记录（满 {FULL_AFTER_RECORDS} 条就建议）")
    if len(pages) >= FULL_AFTER_PAGES:
        reasons.append(f"此后涉及 {len(pages)} 页（满 {FULL_AFTER_PAGES} 页就建议）")
    if days is not None and days > FULL_AFTER_DAYS:
        if from_full:
            what = f"最近一次全稿验收已是 {days:.1f} 天前"
        elif has_start:
            what = f"分档上线已 {days:.1f} 天，还没有全稿验收"
        else:
            what = f"第一条验收记录已是 {days:.1f} 天前，还没有全稿验收"
        reasons.append(f"{what}（超过 {FULL_AFTER_DAYS} 天就建议）")
    return {
        "workspace": root,
        "in_workspace": in_workspace(root),
        "total_records": len(records),
        "old_records": sum(1 for r in records if not is_new(r)),
        "tier_start": TIER_START.strftime("%Y-%m-%d %H:%M") if has_start else None,
        "counted_from": "last_full" if from_full else "tier_start",
        "last_full_ts": records[fulls[-1]].get("ts") if from_full else None,
        "records_since": len(since),
        "pages_since": pages,
        "page_count_since": len(pages),
        "days_since": None if days is None else round(days, 2),
        "suggest_full": bool(reasons),
        "reasons": reasons,
        "thresholds": {"records": FULL_AFTER_RECORDS, "pages": FULL_AFTER_PAGES, "days": FULL_AFTER_DAYS},
    }


def status_text(s):
    """status 的中文一小段。"""
    if not s["total_records"]:
        return f"验收记录（{s['workspace']}）：这个工作区还没有验收记录。"
    n = s["records_since"]
    if s["counted_from"] == "last_full":
        head = f"最近一次全稿验收（--tier full）在 {s['last_full_ts']}；" + (f"此后 {n} 条记录" if n else "此后还没有新记录")
    elif s["tier_start"]:
        head = (f"分档上线（{s['tier_start']}）以来还没有全稿验收（--tier full）；"
                + (f"上线以来 {n} 条记录" if n else "上线以来还没有新记录"))
    else:
        head = f"还没有全稿验收（--tier full）；共 {n} 条记录"
    pages = "、".join(str(p) for p in s["pages_since"])
    if n:
        head += f"，涉及的页：{pages}（共 {s['page_count_since']} 页）" if pages else "，都没写涉及的页"
    head += "。"
    if s["old_records"]:
        head += f"分档上线前另有 {s['old_records']} 条旧记录，不参与判断。"
    if s["suggest_full"]:
        tail = "建议：下一次改稿后全稿通读一次（--tier full）。原因：" + "；".join(s["reasons"]) + "。"
    else:
        t = s["thresholds"]
        tail = (f"建议：暂不需要全稿通读（此后满 {t['records']} 条记录、涉及满 {t['pages']} 页，"
                f"或超过 {t['days']} 天时再做）。")
    return f"验收记录（{s['workspace']}）：{head}{tail}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["write", "check", "list", "status"])
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--doc", default="")
    ap.add_argument("--tier", choices=TIERS)
    ap.add_argument("--pages", default="")
    ap.add_argument("--reader", default="")
    ap.add_argument("--visual", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--json", action="store_true", help="status 用：输出 JSON")
    args = ap.parse_args()
    here = find_root(os.getcwd())

    if args.action == "status":
        roots = []
        for path in args.file:
            if not os.path.isfile(path):
                print(f"找不到文件: {path}", file=sys.stderr)
                return 2
            roots.append(file_root(path))
        if not roots and not in_workspace(os.getcwd()):
            msg = f"当前目录不在分析助手的工作区里（{os.getcwd()}）：到工作区里运行，或用 --file 指定交付物。"
            print(json.dumps({"in_workspace": False, "cwd": os.getcwd(), "message": msg}, ensure_ascii=False)
                  if args.json else msg)
            return 0
        for root in list(dict.fromkeys(roots)) or [here]:
            s = status(root)
            print(json.dumps(s, ensure_ascii=False) if args.json else status_text(s))
        return 0

    if args.action == "list":
        for r in load(here)[-10:]:
            files = r.get("files") if isinstance(r.get("files"), list) else []
            names = ", ".join(str(f.get("path", "")) for f in files if isinstance(f, dict)) or r.get("doc", "")
            print(f"{r.get('ts')} | {names} | 读者: {r.get('reader')} | 图表数字: {r.get('visual')}")
        return 0

    if args.action == "check":
        if not args.file:
            print("check 需要 --file", file=sys.stderr)
            return 2
        ok = True
        for path in args.file:
            found = os.path.isfile(path) and has_record(file_root(path), sha256(path))
            print(f"{path}: {'有验收记录' if found else '没有验收记录'}")
            ok = ok and found
        return 0 if ok else 1

    # write
    if not (args.file or args.doc):
        print("write 需要 --file 或 --doc", file=sys.stderr)
        return 2
    if not args.reader.strip() or not args.visual.strip():
        print("write 需要同时给出 --reader 和 --visual 的结果（哪一项确实不适用，就写“不适用：原因”）", file=sys.stderr)
        return 2
    by_root = {}
    for path in args.file:
        if not os.path.isfile(path):
            print(f"找不到文件: {path}", file=sys.stderr)
            return 2
        root = file_root(path)
        by_root.setdefault(root, []).append(
            {"path": os.path.relpath(os.path.realpath(path), root), "sha256": sha256(path)})
    if args.doc.strip() or not by_root:
        by_root.setdefault(here, [])
    for root, files in by_root.items():
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": int(time.time()),
            "files": files,
            "doc": args.doc.strip(),
            "tier": args.tier or "unspecified",
            "pages": args.pages.strip(),
            "reader": args.reader.strip(),
            "visual": args.visual.strip(),
            "note": args.note.strip(),
        }
        os.makedirs(os.path.join(root, DIR_NAME), exist_ok=True)
        with open(records_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print("已记录验收：" + (", ".join(x["path"] for x in files) or record["doc"]) + f"（记录在 {records_path(root)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
