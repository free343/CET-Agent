# CET-Agent

CET-Agent is an adaptive desktop vocabulary learning agent for CET-4/CET-6 students.

它面向中国大学生，以本地学习记录为依据主动安排复习、发现个人易混词模式，并在需要解释时调用小型本地 LLM。它不是通用聊天机器人，也不让生成式模型控制学习调度。

> **Algorithms discover problems. LLMs explain problems.**
>
> The LLM does not control spaced repetition scheduling.

## 已实现的 MVP

- PySide6 桌面端：学习概览、单词复习、易混词分析、AI 助手和设置；
- SQLite + SQLAlchemy 2.x 本地数据层，显式版本迁移、首次启动自动建表并幂等导入示例词汇；
- FSRS-compatible 调度器，维护 Difficulty、Stability 与下一次复习时间；
- 完整 ReviewLog：评分、正确性、耗时、题型、答案和调度前后状态；
- 确定性复习队列、统计和主动提醒策略，支持 30 分钟 Snooze；
- Personal Vocabulary Confusion Graph 与 connected-components 词簇；
- 拼写、语义、共错和时间相关度的混合评分；
- Ollama 与 OpenAI-compatible LLM Provider 接口；
- Pydantic 结构化输出、一次 JSON 重试、安全降级与 AI 结果缓存；
- 独立 Embedding Provider 及 SQLite 缓存；
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

1. FSRS-compatible spaced repetition；
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
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS/Linux 激活命令为 `source .venv/bin/activate`，复制配置可使用 `cp .env.example .env`。

## 启动

```powershell
python main.py
```

第一次运行会自动创建 `data/cet_agent.db`，按顺序升级到当前 schema 版本、导入 `data/sample_words.csv`，并为每个词建立默认 `LearningState`。升级和导入均可重复执行；升级失败会回滚，数据库版本高于应用支持范围时会拒绝启动，避免旧程序误写新结构。

复习快捷键：

- `Space`：显示释义；
- `1`：Again；
- `2`：Hard；
- `3`：Good；
- `4`：Easy。

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

先在 Ollama 中准备对应模型，再启动 CET-Agent。Ollama chat 使用 `/api/chat`，Embedding 使用 `/api/embed`；结构化错词分析将 Pydantic JSON Schema 传入请求并在本地再次验证。模型未启动、模型不存在、网络错误或非法 JSON 都会显示可恢复的降级结果。

Windows 可直接使用本机 Ollama 可执行文件下载并验证：

```powershell
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' pull qwen2.5:3b
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' pull nomic-embed-text
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' list
python scripts/validate_local_ai.py
```

最后一个脚本会幂等准备 Demo 数据，并通过项目自身 Provider/Service 验证聊天、Embedding 缓存、语义图重建、Pydantic 结构化词簇分析和 AI 缓存复用。Ollama 直连会绕过操作系统代理设置，避免 localhost 请求被代理捕获。

若使用兼容接口，可设置 `LLM_PROVIDER=openai-compatible`。API key 只能写入本地 `.env` 的 `LLM_API_KEY`，不会写死或输出到日志。高级模型路由接口已预留，第一版未默认配置云端服务。

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

```powershell
python -m pytest -q
```

测试覆盖 FSRS 调度、复习事务、UI 复习闭环、编辑距离、四类关系分数、Embedding 缓存、图连通分量、AI JSON 校验与缓存，以及提醒策略。无显示环境可做启动检查：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python main.py --smoke-test
```

## 关键技术决策

- SQLite 时间通过自定义 SQLAlchemy 类型统一存储为 UTC，并在读取时恢复时区；
- 数据库使用单行 `schema_version` 和显式连续迁移注册表；SQLite 升级前获取写锁，并在同一事务中更新结构与版本；
- 简化 FSRS-compatible 实现隔离在 Domain 层，未来可替换成熟 FSRS 库；
- 共错采用 24 小时窗口内的一对一贪心匹配，避免单条错误重复放大；
- Temporal score 对每次错误寻找另一词最近错误并计算 `exp(-Δt/τ)`；
- 超过 8 个词的 cluster 只把加权度最高的核心词提供给 LLM；
- Prompt 只存在于 `app/ai/prompts.py`，输入仅含 Service 提取的必要结构化统计；
- 提醒策略是纯函数；系统托盘消息与应用内“开始复习 / 30 分钟后提醒”操作分离。

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
data/                # 示例词库；运行时 SQLite 被 gitignore
scripts/             # demo 数据生成
tests/               # 核心算法和服务测试
```

日志写入 `logs/cet-agent.log` 并轮转。日志记录启动、复习、提醒、图分析和模型错误，但不记录 API key。
