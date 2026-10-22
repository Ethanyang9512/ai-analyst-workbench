# 参与贡献

谢谢你愿意改进这套工作台。这一页说清：欢迎什么样的改动、怎么提交、改规则和改代码各要附什么、提交前怎么自查有没有泄露、怎么跑测试。参与讨论请遵守[行为准则](CODE_OF_CONDUCT.md)。

## 欢迎的改动

- **新的程序检查**：把“靠人记住的规矩”变成程序能查的检查。这是最有价值的一类改动。
- **模板改进**：`templates/` 里的工作区、知识库、需求包模板更好用、更通用。
- **其他场景的适配**：非中文的写作规范、飞书以外的聊天工具、其他行业的分析示例。
- **Windows 支持**：钩子入口、考场隔离在 Windows 上的替代做法。
- **文档纠错**：说得不清楚、和代码对不上的地方。

## 怎么提交

1. Fork 本仓库，从 `main` 开一个新分支，一个分支只做一件事。
2. 改完跑 `bash tools/run_all_tests.sh`，全部通过。缺可选依赖的组显示“跳过”可以接受，在 PR 里写明跳过了哪些；想全跑就先 `pip install -r requirements-dev.txt`。
3. 照下文“提交前自查”过一遍。
4. 用户能感知到的改动，在 [CHANGELOG.md](CHANGELOG.md) 的“未发布”一节加一行。
5. 提 Pull Request，按模板写改前、改后、样例，勾自查项。CI 会在 Ubuntu 和 macOS 上再跑一遍测试。

**授权**：你提交的改动按它所属那一类的许可证授权给本仓库和所有使用者：代码（`.py`、`.sh` 等脚本和配置）用 MIT，文档（所有 `.md`，以及示例和模板里的数据、SQL）用 CC BY 4.0，划分见 [README 的许可证一节](README.md#许可证)。提交即表示你有权这样授权。

## 改规则或技能

技能和规则是给智能体读的说明书，改一句就会影响所有会话，所以要求比改代码更严：

1. **附“改前 / 改后 / 一个样例”**：用大白话写清行为有什么不同，再给一个具体例子。
2. **正文只写规则本身**：不写日期、项目名、业务数字，也不写“某次发生了什么”这类事故经过。规则从哪来，写在提交说明里。
3. **总字数不增**：新增一条，最好同时合并或删掉等量的旧内容；作废的规则挪到归档文件，不直接删（见 [docs/05](docs/05-规矩怎么演进.md)）。
4. **能写成程序检查的，优先写成程序**，而不是再加一句叮嘱。
5. **技能只引用自己目录里的文件**（`assets/`、`references/`、`scripts/`）或兄弟技能；提到仓库其他目录时写明“仓库”，因为用户可能只复制了 `skills/`。`tools/check_repo.py` 会查。
6. 有自己的成对稿（“交付版 → 你改过的定稿”）的话，改动前后各考一次，把结果附上（见 [docs/07](docs/07-先考试再上线.md)）。

## 改钩子和运行时

钩子在每条命令执行前运行，出错会影响所有会话，所以：

1. 跑全部测试，全部通过才提交。
2. 有自己的历史会话记录的话，跑一遍历史命令回放，看新规则会不会误拦：
   ```bash
   AAW_HOOK_STATE=$(mktemp -d) python3 runtime/tools/replay_history.py runtime
   ```
3. 在提交说明里写清：这次拦什么、不拦什么、哪些写法挡不住。
4. 保持“钩子自己出错一律放行”的原则，不要让一个异常拦住所有命令。

## 绝不提交的内容

- 真实业务数据、取数 SQL、业务口径和指标卡的具体内容、项目结论；
- 公司名、品牌名、内部系统名、表名库名、同事姓名；
- 飞书的群号、用户号、应用号，令牌、密钥、口令、代理地址；
- 本机用户名和绝对路径（用环境变量或 `~` 代替）。

## 提交前自查

1. **跑仓库自查**：`python3 tools/check_repo.py`。它查本机绝对路径、常见格式的密钥、断掉的链接、技能的头部信息和引用、两份需求包模板是否同步、有没有二进制文件。它也包含在 `run_all_tests.sh` 里。
2. **查明文个人信息**：用数据包体检程序扫你改过或新加的文件所在的目录（手机号、身份证号、邮箱、口令）：
   ```bash
   python3 skills/ethan-data-package-review/scripts/pkgcheck.py <要提交的目录>
   ```
   不要整仓扫：测试文件故意造了假手机号、假口令来测检查程序，会被当成命中。
3. **用你自己的敏感词表再扫一遍**：仓库自查只认格式，认不出业务内容。建议在本机维护一份敏感词表（你的公司名、同事名、表名、群名、项目代号……），只放在本机、不提交，提交前用它扫一遍要提交的文件，例如 `grep -rnFf ~/my-deny-words.txt <要提交的文件>`。
4. **例子一律虚构**：对象用“甲区、乙区”“A 店”“示例 App”这类名字，编号用 1001 这类，数字现编，并在文件开头注明“本例数字均为虚构”。改写真实材料时，不要只换名字：指标组合、事件经过、时间点能对上原项目，一样会被认出来。

**发现仓库里有泄露**：不要在公开 issue 里贴原文，见 [SECURITY.md](SECURITY.md)。

## 测试命令

一条命令跑完全部（仓库自查、技能、运行时、两个示例）：

```bash
bash tools/run_all_tests.sh
```

也可以逐条跑。`${AAW_PY:-python3}` 表示设了 `AAW_PY` 就用它（装了 matplotlib、python-pptx、PyMuPDF 的解释器），没设就用 `python3`。

```bash
python3 tools/check_repo.py
python3 skills/ethan-report-writing/tests/test_style_lint.py
python3 skills/ethan-report-writing/tests/test_pairsnap.py
python3 skills/ethan-report-writing/tests/test_trace_scan.py
${AAW_PY:-python3} skills/ethan-report-writing/tests/test_figcheck.py       # 需要 matplotlib；没装会打印“跳过”
${AAW_PY:-python3} skills/ethan-report-writing/tests/test_deckcheck.py -v   # PDF 那组要 PyMuPDF；没有就跳过并写明
${AAW_PY:-python3} skills/ethan-slide-deck/tests/test_check_deck.py -v      # 需要 python-pptx
python3 skills/ethan-data-package-review/tests/test_pkgcheck.py
python3 runtime/hooks/test_guard.py
python3 runtime/hooks/test_gate.py
python3 runtime/hooks/test_remind.py
python3 runtime/hooks/test_progress.py
python3 runtime/tools/test_accept_record.py
python3 runtime/test_status_preview.py
python3 skills/ethan-optimization-modeling/examples/allocation_pulp.py     # 装了 pulp 时
bash runtime/doctor.sh            # 在已装好并登录 Claude Code 的电脑上、用临时的 AAW_* 环境跑，应只报“关注”
```

钩子测试全部在临时目录里跑，不会碰你真实的工作区。

## 语言

- 文档以中文为主，写法照本仓库自己的规范：结论先行、标题用名词短语、大白话、术语第一次出现就解释。英文入口在 [README.en.md](README.en.md)。
- 代码注释中文、英文都可以。
