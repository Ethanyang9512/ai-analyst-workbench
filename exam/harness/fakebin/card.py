#!/usr/bin/env python3
# 考场用的假工作区脚本（card.py、p、t、newproject、status-all 都是它的副本）：
# 只把调用记到本场考试的 calls.log，不发卡、不发消息、不碰线上进度卡的状态文件。
import os, sys, time
run = os.environ.get("AAW_EXAM_RUN") or os.environ.get("AAW_EXAM_ROOT") or "/tmp/aaw-exam"
name = os.path.basename(sys.argv[0])
try:
    with open(os.path.join(run, "calls.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S") + "\t" + name + " " + " ".join(sys.argv[1:]) + "\n")
except OSError:
    pass
print("0:00" if name == "t" else '{"ok": true, "note": "exam sandbox fake %s, nothing was sent"}' % name)
