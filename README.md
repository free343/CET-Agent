# CET-Agent

CET-Agent is an adaptive desktop vocabulary learning agent for CET-4/CET-6 students.

本项目代码以 MIT License 发布，版权标识为 `__free`（2026）。许可证全文见根目录 [`LICENSE`](LICENSE)。

需要特别区分代码与数据：`data/` 中的词库、词典事实、来源候选及其生成产物遵守各自的来源许可证和 provenance 说明；第三方依赖与数据的版权、署名和再分发要求见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)、[`data/OPEN_VOCABULARY_LICENSE.md`](data/OPEN_VOCABULARY_LICENSE.md) 及各数据旁的 provenance 文件。根目录 MIT 许可证不会覆盖这些具有独立许可声明的材料。

它面向中国大学生，以本地学习记录为依据主动安排复习、发现个人易混词模式，并在需要解释时调用小型本地 LLM。它不是通用聊天机器人，也不让生成式模型控制学习调度。

> **Algorithms discover problems. LLMs explain problems.**
>
> The LLM does not control spaced repetition scheduling.

## 已实现的 MVP

- PySide6 桌面端：学习概览、学习新词、到期复习、自由复习、收藏词本、已掌握单词恢复、易混词分析、AI 助手和设置；三个学习工作区右侧都提供可折叠的当前词卡 AI 助手；
- 主窗口默认以 1280×760 打开（最小 960×620），三个学习工作区的右侧助手默认约 400px、最小 340px，在常见桌面分辨率下为词卡与问答各保留更充足空间；
- SQLite + SQLAlchemy 2.x 本地数据层，显式版本迁移、首次启动自动建表并幂等导入经验证的开放词库；
- 官方 FSRS-6 调度器，维护 Difficulty、Stability、学习阶段与下一次复习时间；
- 完整 ReviewLog：评分、正确性、耗时、题型、答案和调度前后状态；三阶段新词尝试另写追加式 `AcquisitionAttempt`，不会伪造 ReviewLog 或 FSRS 评分；
- 本地词库驱动的确定性中文释义四选一；干扰项不由 LLM 生成，回答错误时只允许 Again，选项不足时安全退回主动回忆；
- 学习与复习使用两条明确路线：学习新词采用持久化熟练度 0→1→2→3 的三阶段轮转队列（中文释义选择、例句挖空选择、中文到英文拼写/直接确认），到期复习只取已完成新词学习且到达 FSRS 时间的卡片；
- 每张卡都可独立标记“完全掌握”。标记成功后从新词、到期复习、自由复习、提醒和混淆分析中排除；“已掌握单词”页面可用“恢复学习”撤销标记，保留熟练度、复习日期、收藏和全部历史；
- 自由复习可按“昨天学过 / 最近学习 / 历史错词 / 收藏单词”练习旧词；结果写入独立 `PracticeLog`，不会提前或推迟正式 FSRS 复习；
- 当前待学新词组完成后可主动领取默认 5 个从未学习的同等级新词；组大小与加练包大小可在 `.env` 通过 `NEW_WORD_GROUP_SIZE` / `EXTRA_NEW_WORD_COUNT` 调整（均有边界校验），已学习卡片、已掌握卡片和另一等级不会被移动；
- 确定性复习队列、统计和主动提醒策略，支持带操作按钮的 Windows 原生通知、持久化的精确 30 分钟 Snooze、后台原子通知领取和多窗口复习租约；
- Personal Vocabulary Confusion Graph 与 connected-components 词簇；
- 拼写、语义、共错和时间相关度的混合评分；
- Ollama 与 OpenAI-compatible LLM Provider 接口；
- Pydantic 结构化输出、一次 JSON 重试、安全降级与 AI 结果缓存；
- AI 输入、Provider 输出 token、结构化字段/列表和界面文本块均有显式容量上限；
- AI 助手支持有界的会话内追问：最多保留最近 4 组成功问答和 6,000 个历史字符，关闭应用后自动清空；学习页右侧助手会在每张新词卡出现时立即清空对话，旧卡片的迟到回答不会进入新卡片；
- 右侧“怎么记”默认不调用 3B 模型，而是根据当前词卡确定性生成核心义、搭配锚点、完整词形挖空例句、词族串联和十秒回忆题；无例句时使用中文义到英文拼写回忆，隐藏答案阶段不会调用模型猜测；
- 对话中的用户、助手、处理中和错误消息保留明确文字标签，并使用不同的高对比度颜色；所有动态文本在富文本显示前都会转义；
- 每个 AI 助手都在输入框上方提供“自动选择 / 本地模型 / 高级模型”三档；自动档对普通问题使用本地模型，并在复杂任务或近义词、反义词扩展前请求确认，高级档则对当前范围内的问题明确调用独立高级 Provider；
- 本地模型成功生成回答且高级通道可用时，回答下方会出现“对内容不满意？试试高级模型”；点击后自动用原问题、原词卡快照和回答前的会话历史重答，不把不满意的本地答案作为高级模型上下文。界面只标明回答来源，不向用户展示内部置信度；
- 4,611 个词条的独立学习辅助层：开放词例句、固定搭配和可靠同族/派生词经完整离线校验后导入；多项内容逐行显示，窄窗口溢出内容可用鼠标滚轮查看，AI 生成材料使用不换行的审核状态徽标（完整说明见悬停提示），并支持本地问题反馈；
- 复习页右侧“辨析”会携带当前词卡的释义、例句、固定搭配和同族词进入专用提示词，只解释有上下文依据的核心用法与误用边界；
- 独立 Embedding Provider 及 SQLite 缓存；
- 可解释的确定性问题路由：本地回答、确认高级模型或直接拒绝越界请求；
- demo 学习历史和 pytest 核心测试。

## Core Architecture

```text
Review Logs
      ↓
Deterministic Analysis
      ↓
Confusion Graph
      ↓
Cluster Detection
      ↓
LLM Explanation
      ↓
Personalized Review
```

应用采用四层边界：

```text
PySide6 UI
    ↓
Application Services
    ↓
Deterministic Domain Algorithms
    ↓
SQLite / LLM / Embedding / Notification Adapters
```

UI 不直接查询数据库，也不直接调用模型。`ReviewService` 在同一事务里更新 `LearningState` 并创建 `ReviewLog`；`AnalysisService` 先筛选近 30 天至少错误两次的候选，最多处理 100 个词，再做候选内两两关系计算。Embedding 或 LLM 不可用时，确定性学习功能仍然工作。

## Technical Highlights

1. Official FSRS-6 spaced repetition；
2. Personal Vocabulary Confusion Graph；
3. Hybrid error relation scoring；
4. Algorithm + LLM separation；
5. Local-first LLM；
6. Structured LLM output；
7. AI result caching；
8. Deterministic proactive reminder policy。

混淆边使用以下配置化公式：

```text
R(a,b) = 0.30 × semantic
       + 0.25 × spelling
       + 0.30 × co-error
       + 0.15 × temporal
```

默认阈值为 `0.65`。Embedding 服务离线时 semantic score 降为 0，分析不会使 GUI 崩溃。

## 环境要求

- Python 3.11+
- Windows、macOS 或 Linux 桌面环境
- 可选：Ollama 与一个 3B/4B instruction model

安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
Copy-Item .env.example .env
```

macOS/Linux 激活命令为 `source .venv/bin/activate`，复制配置可使用 `cp .env.example .env`。
`requirements.txt` 保留直接依赖的兼容范围，`requirements.lock` 固定经过验证的完整运行时依赖树。

## 启动

```powershell
python main.py
```

第一次运行会自动创建 `data/cet_agent.db`，按顺序升级到当前 schema v14，并导入 13 条人工示例词、4,598 条开放 CET 词汇及其 4,611 条三阶段学习状态。`STUDY_LEVEL=CET4` 或 `CET6` 决定学习/复习队列、提醒和仪表盘统计的范围；每个级别在首次实际启用时独立按词频每天最多释放默认 20 个从未复习的开放词条（可用 `DAILY_NEW_WORD_LIMIT` 调整），因此安装很久后再切换等级也不会瞬间形成数千条积压；该设置只对尚未启用的等级生效。“学习新词”按持久化熟练度 0→3 轮转，完成当前组后，可在完成页主动领取默认 5 个同等级新词；`NEW_WORD_GROUP_SIZE` 和 `EXTRA_NEW_WORD_COUNT` 可在边界内调整。达到熟练度 3 的词恰好在 24 小时后进入正式到期复习；“自由复习”只读取已有学习历史并写独立练习日志。人工示例词保持立即可用，已有复习历史、熟练度、收藏和 FSRS 状态绝不会因等级切换或自由练习而移动。标记“完全掌握”的词从所有主动任务中排除，可在“已掌握单词”页面恢复。升级和导入均可重复执行；schema v14 会安全移除没有任何正式或候选内容的历史占位行；升级失败会回滚，数据库版本高于应用支持范围时会拒绝启动，避免旧程序误写新结构。

学习概览把“待学新词”和“到期复习”分开计数。若检测到真实 `ReviewLog` 晚于当前系统时间 5 分钟以上，界面会提示先校准 Windows 日期、时间和时区；应用会排除这些未来事件对今日统计的影响，但不会擅自改写用户历史。

源码运行时数据库、日志和 `.env` 仍位于项目目录。冻结后的 Windows 版本从发行包读取词库，将数据库、日志、`.env` 与自动复制的 `.env.example` 写入 `%LOCALAPPDATA%\CET-Agent`，不会修改安装目录。

开放词库由固定版本的 ECDICT 和 FreeDict eng-zho 交叉构建。构建器会下载后核验来源哈希，只保留同时具有开放双语词条、音标和 CET 标签的单词，再生成可审计的来源清单：

```powershell
python scripts/build_open_vocabulary.py
```

生成结果为 `data/cet_vocabulary_open.csv`，来源版本、哈希、行数和生成文件哈希记录在同名 `.provenance.json` 中。数据的归属、修改说明和 CC BY-SA 3.0 分发条款见 `data/OPEN_VOCABULARY_LICENSE.md`；第三方声明见 `THIRD_PARTY_NOTICES.md`。

学习与复习快捷键：

- “学习新词”按熟练度分三阶段：0 级选择中文释义，1 级选择例句挖空的英文词形，2 级输入拼写或使用“直接完成”；反馈保存后按 `Space` 进入本组下一张卡；
- “到期复习 / 自由复习”中，`Space` 显示释义并进入反馈；
- 正式复习四选一尚未作答时，`1/2/3/4` 选择对应中文释义；新词学习的 0/1 级分别选择中文/英文选项；
- 查看反馈后，`1/2/3/4` 分别表示 Again/Hard/Good/Easy；答错时只有 Again 可用；
- “自由复习”反馈阶段只使用 `1`（没想起）和 `2`（想起来），并明确保持原 FSRS 日期；
- 右侧 AI 输入框获得焦点时，复习快捷键不会截获其中的空格或数字。

## 本地模型

默认 `.env.example` 使用：

```text
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
LLM_BASE_URL=http://127.0.0.1:11434
EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://127.0.0.1:11434
EMBEDDING_MODEL=nomic-embed-text
```

先在 Ollama 中准备对应模型，再启动 CET-Agent。Ollama chat 使用 `/api/chat`，Embedding 使用 `/api/embed`；结构化错词分析将 Pydantic JSON Schema 传入请求并在本地再次验证。普通词汇问答会在当前界面内携带最多 4 组完整成功问答作为追问上下文，但不会把对话写入数据库。学习页右侧助手只携带发送瞬间的当前词卡快照；上下文在 Prompt 层限制为 2,500 字符，模型不能借此读取其他学习记录。每次显示新卡片都会清空右栏文本和历史，并使上一卡片尚未返回的结果失效。“怎么记”在自动/本地档由本地规则直接生成核心义、词卡搭配、挖空例句、词族链接和十秒自测，不调用 3B Provider；选择高级档后才会使用更强模型。本地 Provider 成功作答后可一键用高级 Provider 重答同一问题，重答不会携带刚才不满意的本地答案；换卡、新提问、降级/失败或本地规则回答都会隐藏或作废该入口。近义词/反义词请求在自动档会建议升级，高级模型可围绕词卡义项补充词卡外的常用候选、用法差异和例句，但应用会固定标注为未经过当前词卡人工审核，也不会把它们写回词卡、词库或学习记录。模型未启动、模型不存在、网络错误或非法 JSON 都会显示可恢复的降级结果。

Windows 可直接使用本机 Ollama 可执行文件下载并验证：

```powershell
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' pull qwen2.5:3b
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' pull nomic-embed-text
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' list
python scripts/validate_local_ai.py
```

最后一个脚本会幂等准备 Demo 数据，并通过项目自身 Provider/Service 验证聊天、Embedding 缓存、语义图重建、Pydantic 结构化词簇分析和 AI 缓存复用。Ollama 直连会绕过操作系统代理设置，避免 localhost 请求被代理捕获。

若本地默认模型使用兼容接口，可设置 `LLM_PROVIDER=openai-compatible`。高级模型是完全独立的可选 Provider，不会改变本地 Ollama。源码模式编辑 `D:\work\english\.env`，安装版编辑 `%LOCALAPPDATA%\CET-Agent\.env`，保存后重启应用；“设置”页也会显示实际路径、启用状态和可复制的配置模板。

当前官方 DeepSeek OpenAI-compatible 端点可使用下面的配置：

```text
ADVANCED_LLM_PROVIDER=openai-compatible
ADVANCED_LLM_MODEL=deepseek-v4-flash
ADVANCED_LLM_BASE_URL=https://api.deepseek.com
ADVANCED_LLM_API_KEY=
DEEPSEEK_API_KEY=<仅保存在本地 .env>
```

当且仅当高级地址是官方 `api.deepseek.com` 且 `ADVANCED_LLM_API_KEY` 为空时，应用会安全复用同一 `.env` 中的 `DEEPSEEK_API_KEY`，无需粘贴两次；其他地址绝不会继承这把密钥。也可显式填写独立的 `ADVANCED_LLM_API_KEY`，或把高级 Provider 设为 `ollama` 并选择一个更大的本地模型。DeepSeek 当前模型标识以其[官方模型列表](https://api-docs.deepseek.com/api/list-models/)为准；这里使用响应更快、成本较低的 `deepseek-v4-flash`，需要时可改成 `deepseek-v4-pro`。

聊天框中的模型档位含义：

- `自动选择（推荐）`：普通问题走本地模型；长文本、高复杂度任务、近义词和反义词扩展会先显示确认条；
- `本地`：始终保留在本机，适合例句解释；“怎么记”继续使用零模型调用的确定性卡片；
- `高级`：对当前范围内的每次提问直接调用已配置 Provider，界面明确提示可能产生网络流量和 API 费用。

所有 API key 只能写入被 Git 忽略的本地 `.env`；设置对象的文本表示、UI 和日志均不会包含密钥。未配置 `ADVANCED_LLM_PROVIDER` 时，高级档会在选择器中显示但不可选，设置页会给出启用方法。

## Demo 数据

以下脚本会幂等生成三组相关错误历史并重建图：

```powershell
python scripts/create_demo_data.py
```

预期至少出现：

- `adapt / adopt / adept`；
- `economic / economical`；
- `complement / compliment`。

随后打开“易混词分析”，即可查看 cluster 并点击“AI 分析所选词簇”。

## 测试

开发环境使用包含 pytest、Ruff 和 Mypy 的固定依赖：

```powershell
python -m pip install -r requirements-dev.lock
```

```powershell
python -m pytest -q
python -m ruff check app scripts tests main.py
python -m ruff format --check app scripts tests main.py
python -m mypy
```

测试覆盖 FSRS-6 官方参考向量、schema v14 升级与空占位清理、三阶段新词/到期复习队列分流、完全掌握排除与恢复、不会改写 FSRS 的自由练习日志、确定性四选一、主动加练、未来时钟异常提示、右侧上下文助手、收藏词本、学习辅助状态与反馈、UI 学习闭环、编辑距离、四类关系分数、Embedding 缓存、图连通分量、AI JSON 校验与缓存，以及提醒策略。无显示环境可做启动检查：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python main.py --smoke-test
```

`.github/workflows/ci.yml` 在 Windows 的 Python 3.11 和 3.13 上自动执行锁文件安装校验、Ruff、格式检查、Mypy、完整测试和离屏启动烟测。更新顶层依赖后，用固定的 pip-tools 版本重新生成锁文件：

```powershell
python -m pip install pip-tools==7.6.1
python -m piptools compile --resolver=backtracking --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file=requirements.lock requirements.txt
python -m piptools compile --resolver=backtracking --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file=requirements-dev.lock requirements-dev.txt
```

最大候选规模的可重复性能基线使用临时数据库、100 个候选、4,950 条全连接边和确定性向量，不读取或修改真实学习数据：

```powershell
python scripts/benchmark_confusion_graph.py
```

脚本默认运行三次，并在中位重建时间超过 5 秒时返回失败状态；可通过 `--iterations` 和 `--max-median-seconds` 调整测量次数和预算。

## 关键技术决策

- SQLite 时间通过自定义 SQLAlchemy 类型统一存储为 UTC，并在读取时恢复时区；
- 数据库使用单行 `schema_version` 和显式连续迁移注册表；当前 schema v14 包含 `word_acquisition_states`、追加式 `acquisition_attempts`、可撤销的 `mastered_words`、隔离候选关系列，以及对双层空词卡占位行的安全清理；SQLite 升级前获取写锁，并在同一事务中更新结构与版本；
- 调度边界使用 MIT 许可的 [`py-fsrs` 6.3.2](https://github.com/open-spaced-repetition/py-fsrs)：目标记忆率 90%，学习与重学各使用一个 10 分钟步骤，并关闭 interval fuzzing 以保持确定性；
- `LearningState` 持久化 FSRS Learning/Review/Relearning 状态和步骤，schema v2 会把旧的已复习卡安全接管为 Review；
- 三阶段新词学习只写 `AcquisitionAttempt`，熟练度 3 完成时把第一次正式复习安排在恰好 +24 小时；正式学习/复习写 `ReviewLog` 并推进 FSRS；自由复习只写 schema v10 的 `practice_logs`，三类历史在数据库和服务边界上隔离；
- “完全掌握”是独立、幂等、可恢复的用户状态；所有主动学习/复习/练习、提醒、数量和混淆候选都以同一确定性资格条件排除它，不会重置原有熟练度、FSRS 或历史；
- 共错采用 24 小时窗口内的一对一贪心匹配，避免单条错误重复放大；
- Temporal score 对每次错误寻找另一词最近错误并计算 `exp(-Δt/τ)`；
- 超过 8 个词的 cluster 只把加权度最高的核心词提供给 LLM；
- Prompt 只存在于 `app/ai/prompts.py`，输入仅含 Service 提取的必要结构化统计；
- 聊天问题由 `app/domain/query_routing.py` 先做确定性范围和复杂度判断；路由会在内部返回决策、置信度与原因，但置信度不面向用户展示，LLM 也不参与选择自身或高级模型；
- 提醒策略是纯函数；Windows 原生 Toast 与应用内 banner 均提供“开始复习 / 30 分钟后提醒”，原生回调经 Qt 信号切回 GUI 线程，初始化或发送失败时退回系统托盘气泡。多窗口通过原子 cooldown 领取避免重复通知，并用每实例短期租约共享“正在复习”状态。

## Windows 发行构建

开发依赖锁已固定 PyInstaller。构建可重复的 windowed onedir 发行目录：

```powershell
python -m pip install -r requirements-dev.lock
python -m PyInstaller --noconfirm --clean packaging/CET-Agent.spec
```

结果位于 `dist/CET-Agent/CET-Agent.exe`。可在隔离的可写目录中做启动检查：

```powershell
$env:LOCALAPPDATA = Join-Path $env:TEMP 'cet-agent-package-smoke'
$env:QT_QPA_PLATFORM = 'offscreen'
$process = Start-Process -FilePath 'dist/CET-Agent/CET-Agent.exe' `
  -ArgumentList '--smoke-test' -WindowStyle Hidden -Wait -PassThru
$process.ExitCode
```

发行包包含运行所需词库、来源记录、许可证和 `.env.example`；FSRS 的未使用 Optimizer 训练栈不会被打包。

在 onedir 构建成功后，可用 Inno Setup 6 或 7 生成当前用户范围的无签名安装器：

```powershell
python scripts/build_windows_installer.py
```

结果为 `dist/installer/CET-Agent-Setup-0.1.0.exe`。安装器默认写入 `%LOCALAPPDATA%\Programs\CET-Agent`，创建带专属 AppUserModelID 的开始菜单快捷方式，并提供可选桌面快捷方式。卸载只删除程序文件，学习数据库、日志和本地模型配置仍保留在 `%LOCALAPPDATA%\CET-Agent`，避免误删用户学习记录；如需彻底清理，可在确认不再需要数据后手动删除该目录。

## 项目结构

```text
app/
├── ai/              # LLM、Embedding、Prompt、Pydantic schema
├── db/              # SQLAlchemy models、repositories、migrations、seed
├── domain/          # FSRS、相似度、混淆图、聚类、提醒策略
├── infrastructure/  # 桌面通知适配器
├── services/        # 业务用例与事务边界
├── ui/              # PySide6 页面与组件
└── utils/           # UTC 与稳定 hash 工具
data/                # 人工示例词、开放 CET 词库及可追溯来源；运行时 SQLite 被 gitignore
scripts/             # 词库构建、demo 数据和本地 AI 验证
tests/               # 核心算法和服务测试
```

日志写入 `logs/cet-agent.log` 并轮转。日志记录启动、复习、提醒、图分析和模型错误，但不记录 API key。

## 许可证与贡献

代码贡献请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。安全问题请按 [`SECURITY.md`](SECURITY.md) 的方式私下报告，不要在公开 Issue 中提交密钥或个人学习数据库。
