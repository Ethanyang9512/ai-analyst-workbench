#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库自查（只用标准库，只读）：python3 tools/check_repo.py

查六样，任何一样不过就退出 1：
  1. 每个技能的 SKILL.md、每个子代理的 .md 有 frontmatter，name 和目录名（或文件名）一致，description 不为空。
  2. 技能文件里写的本技能内路径（`assets/…`、`references/…`、`scripts/…`、`examples/…`、`tests/…`）
     和兄弟技能路径（`<技能名>/…`）都真实存在——技能单独复制到 ~/.claude/skills/ 后也不会断。
  3. 技能文件里提到仓库其他目录（templates/、docs/、runtime/、examples/、exam/）的那一行，要写明“仓库”，
     读的人才知道没装仓库时可以忽略。
  4. 所有 .md 里的相对链接 `](…)` 指向存在的文件或目录。
  5. 没有写死的本机绝对路径（macOS、Linux 的用户主目录，Windows 的 C 盘用户目录）。
  6. templates/fetch-request/ 和 skills/data-package-review/assets/ 里的同名模板逐字一致；仓库里没有二进制文件。
  7. 没有常见格式的密钥（OpenAI/Anthropic 风格的 sk- 串、GitHub 令牌、AWS 访问密钥、私钥头）。
它查不了业务内容是否脱敏：公司名、同事名、表名这类词，请用你自己本机的敏感词表另扫（见 CONTRIBUTING.md）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "_build", "__pycache__", ".venv", "venv", "node_modules"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".xlsx", ".docx", ".zip", ".pyc", ".mp4", ".wav"}
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
HOME_DIRS = ("/" + "Users/", "/" + "home/")          # 拼起来写，免得本文件自己被别的扫描工具当成本机路径
LOCAL_PATH = re.compile("|".join(re.escape(h) + r"[A-Za-z0-9_.-]+" for h in HOME_DIRS) + r"|[A-Za-z]:\\\\?Users\\\\?")
problems = []


def walk():
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            yield os.path.join(dp, f)


def rel(p):
    return os.path.relpath(p, ROOT)


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            meta[k.strip()] = v.strip()
    return meta


# 1 + 2 + 3：技能和子代理
skills_dir = os.path.join(ROOT, "skills")
skill_names = sorted(d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d)))
for name in skill_names:
    sd = os.path.join(skills_dir, name)
    meta = frontmatter(os.path.join(sd, "SKILL.md")) if os.path.exists(os.path.join(sd, "SKILL.md")) else None
    if meta is None:
        problems.append(f"skills/{name}/SKILL.md：缺 frontmatter")
        continue
    if meta.get("name") != name:
        problems.append(f"skills/{name}/SKILL.md：name 是 {meta.get('name')!r}，和目录名不一致")
    if not meta.get("description"):
        problems.append(f"skills/{name}/SKILL.md：description 为空")
    md_files = [os.path.join(dp, f) for dp, _, fn in os.walk(sd) for f in fn if f.endswith(".md")]
    for mf in md_files:
        for ln, line in enumerate(open(mf, encoding="utf-8"), 1):
            for tok in re.findall(r"`([^`\s]+)`", line):
                tok = tok.rstrip("/").split("#")[0]
                if re.match(r"(assets|references|scripts|examples|tests)/[^<>*{}$]+$", tok):
                    if not os.path.exists(os.path.join(sd, tok)):
                        problems.append(f"{rel(mf)}:{ln}：本技能里没有 {tok}")
                first = tok.split("/")[0]
                if first in skill_names and "/" in tok and not re.search(r"[<>*{}$]", tok):
                    if not os.path.exists(os.path.join(skills_dir, tok)):
                        problems.append(f"{rel(mf)}:{ln}：兄弟技能里没有 {tok}")
            if re.search(r"(?<![\w./-])(templates|docs|runtime|exam)/", line) and "仓库" not in line:
                problems.append(f"{rel(mf)}:{ln}：提到仓库其他目录，却没写明“仓库”（技能单独安装时会找不到）")

agents_dir = os.path.join(ROOT, "agents")
for f in sorted(os.listdir(agents_dir)):
    if f.endswith(".md"):
        meta = frontmatter(os.path.join(agents_dir, f))
        if not meta or meta.get("name") != f[:-3] or not meta.get("description"):
            problems.append(f"agents/{f}：frontmatter 缺失，或 name 和文件名不一致，或 description 为空")

# 4 + 5 + 6
for path in walk():
    r = rel(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in BINARY_EXT:
        problems.append(f"{r}：仓库里不放二进制文件")
        continue
    try:
        text = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        continue
    for ln, line in enumerate(text.splitlines(), 1):
        if LOCAL_PATH.search(line):
            problems.append(f"{r}:{ln}：写死了本机绝对路径")
        if SECRET.search(line):
            problems.append(f"{r}:{ln}：像是一段密钥或令牌")
    if ext == ".md":
        in_code = False
        for ln, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
            if in_code:
                continue
            for target in re.findall(r"\]\(([^)\s]+)\)", line):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                t = target.split("#")[0]
                if t and not os.path.exists(os.path.join(os.path.dirname(path), t)):
                    problems.append(f"{r}:{ln}：链接指向不存在的 {target}")

tpl, assets = os.path.join(ROOT, "templates", "fetch-request"), os.path.join(skills_dir, "data-package-review", "assets")
for f in sorted(os.listdir(assets)):
    a, b = os.path.join(assets, f), os.path.join(tpl, f)
    if os.path.exists(b) and open(a, encoding="utf-8").read() != open(b, encoding="utf-8").read():
        problems.append(f"skills/data-package-review/assets/{f} 和 templates/fetch-request/{f} 不一致：改一处要同步另一处")

if problems:
    print(f"仓库自查：{len(problems)} 处问题")
    for p in problems:
        print("  " + p)
    sys.exit(1)
print(f"仓库自查通过：{len(skill_names)} 个技能、{len([f for f in os.listdir(agents_dir) if f.endswith('.md')])} 个子代理；链接、本机路径、密钥形态、模板同步、二进制文件都查过")
