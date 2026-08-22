# CET-Agent 开发交接

> 归档说明（2026-08-22）：本文件是上一阶段的详细审计快照，模型下载状态已过期。当前架构、完成情况、验证证据、未完成任务、关键决策与开发约束统一以根目录 `AGENTS.md` 为准。

更新时间：2026-08-21（Asia/Shanghai）  
工作区：`D:\work\english`  
项目状态：MVP 主链路已实现并通过自动化测试；当前会话正在补齐真实 Ollama 模型下载与端到端验证。

## 新会话先读什么

1. 本文档：保存当前会话中尚未固化在代码里的判断、验证结果和下一步优先级。
2. `D:\work\english\README.md`：项目架构、安装、启动、Demo 与设计决策。
3. `D:\work\english\docs\handoff\NEXT_SESSION_PROMPT.md`：可直接粘贴到下一轮新对话的工作提示词。
4. 原始需求位于 Codex 附件目录，不应依赖其在未来会话中持续可用；九阶段要求已在下文映射到当前实现。

## 当前基线

- 技术栈：Python 3.11+、PySide6、SQLite、SQLAlchemy 2.x、Pydantic、pytest。
- 架构边界保持为 UI → Service → Domain → Infrastructure。UI 不直接访问数据库或具体模型。
- 确定性算法负责复习调度、统计、提醒策略、关系评分、图与聚类；LLM 只做解释、辨析和练习生成。
- 当前目录不是 Git 仓库，因此没有可引用的 branch、commit 或 diff。修改前必须直接检查文件，不能假设存在版本回退点。
- 当前自动化基线：`python -m pytest -q` 为 34 项通过；`QT_QPA_PLATFORM=offscreen` 的 `python main.py --smoke-test` 退出码为 0。
- 本机 Ollama 程序：`C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe`。
- Ollama 服务地址：`http://127.0.0.1:11434`；本轮开始时版本为 0.32.13，模型下载与真实调用验证状态见“真实模型验证”。

## 九个开发 Phase 的完成情况

### Phase 1：项目骨架、配置、数据库、模型、Seed

状态：已完成。

- 入口：`main.py`；启动组合：`app/bootstrap.py`。
- 环境配置集中在 `app/config.py`，示例配置在 `.env.example`。
- SQLAlchemy 引擎、Session 与建表逻辑在 `app/db/database.py`。
- Word、LearningState、ReviewLog、ConfusionEdge、AIAnalysis、EmbeddingCache 和提醒状态等模型在 `app/db/models.py`。
- `app/db/seed.py` 会幂等导入 `data/sample_words.csv` 并补齐 LearningState。
- 首次启动可自动建表、导词和创建学习状态。

遗留：没有数据库迁移框架；当前依靠 `create_all`，以后字段变更无法安全升级已有用户数据库。

### Phase 2：FSRS-compatible 调度、ReviewService、ReviewLog

状态：MVP 已完成。

- 调度算法独立在 `app/domain/fsrs_scheduler.py`，输入评分后返回新的难度、稳定度、下次复习时间和间隔。
- `app/services/review_service.py` 生成到期队列，并在同一事务内更新 LearningState、写入 ReviewLog。
- 队列按逾期时长、lapse_count、error_count 的确定性优先级排序。
- 单元测试覆盖 Good/Again/Easy 调度行为和复习事务闭环。

遗留：这是简化的 FSRS-compatible 公式，不是官方或完整 FSRS 参数体系；上线前应决定引入轻量库还是继续自研并做参数校准。

### Phase 3：Review UI 与 Dashboard

状态：已完成 MVP。

- `app/ui/review_page.py` 支持显示答案、Again/Hard/Good/Easy 和 Space/1/2/3/4 快捷键。
- `app/ui/dashboard_page.py` 展示待复习、今日完成、七日正确率、连续学习和高频错词。
- `app/ui/main_window.py` 负责页面组合和后台 AI 线程生命周期。
- 修复了单批 30 词完成后仍有到期词却误判“今日全部完成”的问题；现在会继续加载下一批。
- 修复了窗口关闭时 AI QThread 仍运行导致崩溃的问题；关闭动作会等待工作线程结束。

遗留：目前主要完成自动化 UI 与 offscreen 启动验证，仍建议在真实 Windows 桌面完成一次人工键盘复习和关闭窗口验收。

### Phase 4：拼写、语义、共错和时间相关度

状态：代码与单测已完成。

- `app/domain/similarity.py` 实现 Levenshtein、拼写相似度、cosine、共错和时间分数。
- cosine 结果现在裁剪到 0~1，不再使用 `(cos + 1) / 2` 人为抬高负相关向量。
- Embedding 抽象、Ollama `/api/embed` 适配器和 SQLite 缓存在 `app/ai/embedding_provider.py`。
- Embedding 缓存键包含 Provider 类型、base URL 和模型，避免不同端点同名模型相互污染。
- 共错使用时间窗内一对一匹配；temporal 使用最近错误间隔的指数衰减。

遗留：向量模型的真实维度、响应时延和缓存命中将在本轮下载后验证并记录。

### Phase 5：Confusion Graph、Connected Components、AnalysisService

状态：已完成 MVP。

- `app/services/analysis_service.py` 仅选择近 30 天至少错两次的词，最多 100 个候选，避免全词库 O(N²)。
- 混合权重和阈值均来自配置；边统一满足较小 word_id 在前。
- `app/domain/confusion_graph.py` 计算边；`app/domain/clustering.py` 求 connected components，并限制大簇提供给 LLM 的核心词数。
- 统计和错误次数统一使用与候选相同的 30 天窗口，已修复历史总量与窗口数据混用问题。
- `scripts/create_demo_data.py` 幂等生成 adapt/adopt/adept、economic/economical、complement/compliment 三组相关错误历史。

遗留：Demo 脚本自身默认不注入 Embedding Provider，因此它可离线生成图，但不能单独证明 semantic score 使用了真实向量；真实集成验证需显式创建 Embedding Provider。

### Phase 6：LLM Provider、Ollama、结构化输出、AI 缓存

状态：代码已完成；真实模型验证由本轮补齐。

- 抽象接口：`app/ai/llm_provider.py`。
- Ollama `/api/chat`：`app/ai/ollama_provider.py`。
- OpenAI-compatible 适配器：`app/ai/openai_compatible_provider.py`。
- Provider 构造集中在 `app/ai/factory.py`。
- LLM 与 Embedding 已分离 Provider、base URL 和模型配置；OpenAI-compatible URL 会兼容处理 `/v1`。
- Cluster 输出由 `app/ai/schemas.py` 的 Pydantic Schema 验证；失败最多重试一次，再安全降级。
- AI cache 的内容哈希包含 prompt version、Provider 类型、模型和 base URL，避免切换端点继续复用旧答案。

遗留：本地小模型的首次加载时延、中文输出质量和结构化 JSON 稳定性需以本轮真实验证结果为准。

### Phase 7：AI 错词分析与 AI Assistant

状态：已完成 MVP。

- `app/services/ai_service.py` 接收 AnalysisService 产出的结构化词簇，不让模型自行发现统计关系。
- `app/ai/prompts.py` 集中管理提示词；业务代码没有散落 Prompt。
- `app/ui/analysis_page.py` 可选择词簇并触发结构化分析。
- `app/ui/chat_page.py` 提供受限的四六级词汇、基础语法、辨析和记忆问答。
- LLM 不可用、非法 JSON 和缓存损坏均有可恢复路径。

遗留：高级模型 Provider 只预留接口与 UI 提示，未真正配置；confidence 是硬编码启发式；聊天没有多轮上下文持久化。

### Phase 8：ReminderService、桌面通知与 Snooze

状态：已完成 MVP。

- `app/domain/reminder_policy.py` 是可单测的纯策略：无到期词、学习中、冷却期、8:00 前、23:00 后、今日完成时不提醒。
- `app/services/reminder_service.py` 负责策略输入与状态持久化。
- 已修复提醒状态只保存在内存的问题；重启后 last notification、snooze、today completed 能从数据库恢复。
- 已修复同一天后来又出现新到期词时 completed 状态不清除的问题。
- `app/infrastructure/notification_adapter.py` 和应用内 banner 提供通知；banner 有“开始复习 / 30 分钟后提醒”操作。

遗留：原生操作系统通知本身没有动作按钮，操作按钮位于应用内 banner；不同桌面环境的通知行为仍需人工验收。

### Phase 9：README、Demo、异常处理、日志与最终测试

状态：MVP 基线已完成。

- `README.md` 已包含架构、Algorithm First 原则、配置、启动、Demo、测试和关键决策。
- 日志写入 `logs/cet-agent.log` 并轮转；不应记录 API key。
- 测试使用 `pytest.ini` 禁用 cacheprovider，避免受限环境写 `.pytest_cache` 失败。
- 34 项测试通过，覆盖核心算法、服务、缓存、提醒和 UI 复习闭环。

遗留：没有打包安装器、CI、依赖锁文件、迁移测试或完整 CET 词库；示例词库当前仅 13 个词。

## 本轮已修复的关键问题

1. 复习超过 30 个到期词时会继续下一批，而不是提前标记完成。
2. cosine similarity 对负值直接裁剪到 0，符合需求的 0~1 语义相似度定义。
3. AnalysisService 的 cluster 错误统计与候选筛选统一为近 30 天窗口。
4. LLM 与 Embedding 配置完全分离，并修复兼容 API 的 `/v1` 地址规范化。
5. AI cache 与 Embedding cache 均加入端点身份，避免跨 Provider/端点污染。
6. 提醒状态持久化；同日新到期任务会恢复提醒资格。
7. 主窗口延迟关闭，避免后台 AI QThread 未结束时销毁。
8. 测试环境禁用 pytest cacheprovider，解决缓存目录写入问题。

## 真实模型验证

本轮目标模型：

- Chat：`qwen2.5:3b`
- Embedding：`nomic-embed-text`

交接文档生成时下载仍在进行。最终状态应以本轮结束前的 `ollama list`、真实 `/api/chat`、`/api/embed` 和项目 Service 集成输出为准；若当前文档未被更新为明确结果，新会话必须首先重新执行验证，不能把“模型存在”等同于“项目集成成功”。

## 已知问题与建议优先级

### P1：影响长期正确性或数据演进

1. 评估并替换/校准简化 FSRS-compatible 调度器，增加参考向量测试。
2. 引入 Alembic 或等价轻量迁移机制，提供现有 SQLite 升级路径。
3. 扩充并校验合法来源的 CET4/CET6 词库；当前 13 词只适合演示。

### P2：功能完整性与真实桌面体验

1. 为原生 Windows 通知实现可点击动作，或明确应用内 banner 是唯一动作入口。
2. 完成高级模型 Provider 的配置闭环，并把 confidence 从简单关键词启发式升级为可测试规则。
3. 设计受控的多轮词汇问答上下文，避免聊天无限增长或越权到通用助手。
4. 完成真实 Windows 桌面人工验收：快捷键、系统托盘、通知、Snooze、AI 请求中关闭窗口。

### P3：交付工程化

1. 增加 CI、格式/静态检查和确定性依赖锁定。
2. 生成 Windows 安装包并验证数据目录、日志目录和升级行为。
3. 建立性能基线：100 个候选图重建耗时、Embedding 缓存命中、模型冷/热启动时延。

## 下一轮立即执行顺序

1. 完整阅读本文和 `README.md`，再检查工作区文件；不要重新生成项目骨架。
2. 运行 `python -m pytest -q`，确认基线没有漂移。
3. 用下列命令核对 Ollama 与模型：

   ```powershell
   & 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' list
   ```

4. 如果“真实模型验证”没有明确记为通过，先补做 chat、embedding、结构化 cluster 和缓存命中验证。
5. 选择一个完整、可测试的 P1 里程碑继续实现；优先数据库迁移，然后再处理 FSRS 校准或词库扩充。
6. 每次修改后运行相关测试；完成里程碑后复跑全部测试和 offscreen smoke。

## 常用命令

```powershell
Set-Location 'D:\work\english'
python -m pytest -q
$env:QT_QPA_PLATFORM='offscreen'
python main.py --smoke-test
python scripts/create_demo_data.py
& 'C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe' list
python main.py
```

## Suggested skills

- `handoff`：上下文再次接近上限时压缩当前进行中的工作，只保留下一位 Agent 必需的状态，并引用本文与 README。
- 不需要图像、文档排版、浏览器或多 Agent 技能来完成当前 P1 工程任务；优先直接检查代码、运行测试并做小步修改。

## 交接安全检查

- 本文不包含 API key、密码或 token。
- 不要把本地 `.env` 内容复制到聊天、日志或交接文档。
- 模型文件是 Ollama 管理的本机资产，不应加入工作区或版本控制。
