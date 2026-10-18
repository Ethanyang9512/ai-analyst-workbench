# 检查程序对本例的真实输出

这个目录里的每个 `.txt` 都是程序真实跑出来的结果，不是手写的样子。重新生成（只用 Python 标准库，在临时目录里跑，不碰你的工作区）：

```bash
bash examples/续费率下滑归因/outputs/regenerate.sh
```

| 文件 | 哪个程序 | 演示什么 |
|---|---|---|
| [01_style_lint.txt](01_style_lint.txt) | `report-writing/scripts/style_lint.py` | 交付版里 4 处硬禁词，退出码 1，交付前必须改到 0 |
| [02_trace_scan.txt](02_trace_scan.txt) | `report-writing/scripts/trace_scan.py` | 给业务看的稿子里出现了协作方名字和“回包” |
| [03_deckcheck_text.txt](03_deckcheck_text.txt) | `report-writing/scripts/deckcheck.py text` | 读本项目 `_CONVENTIONS.md` 的 json 块：用户纠正过两次的词，下一次由程序拦下 |
| [04_pkgcheck_说改了没重跑.txt](04_pkgcheck_说改了没重跑.txt) | `data-package-review/scripts/pkgcheck.py` | 第 2 轮说明里写“已修复”，数据文件指纹却没变，退出码 3 |
| [05_gate_拦下.txt](05_gate_拦下.txt) | `runtime/hooks/gate.py`（强制模式） | 没有验收记录就发 PDF，命令在执行前被拦下，并告诉助手该怎么做 |
| [06_验收记录.txt](06_验收记录.txt) | `runtime/tools/accept_record.py write` | 验收记录长什么样：按文件内容指纹记一行 |
| [07_gate_放行.txt](07_gate_放行.txt) | `runtime/hooks/gate.py` | 写了记录之后再发，验收门不输出任何东西，就是放行 |
| [08_进度卡.txt](08_进度卡.txt) | `runtime/bin/card.py` 的 `build()` | 飞书进度卡上的文字（只渲染，不发送） |
| [09_recompute.txt](09_recompute.txt) | `analysis/recompute.py` | 报告里的每个数从哪来 |

两位验收员（`cold-reader`、`chart-number-checker`）的报告是模型的输出，每次措辞不同，这里不放手写的样子，免得被当成真实输出。它们交回的格式见仓库 `agents/` 里两个文件的最后一节。
