# Contributing to CET-Agent

感谢贡献。CET-Agent 是一个本地优先的 PySide6 学习应用，贡献应保持“算法发现问题，LLM 解释问题”的边界。

## 开发环境

- Python 3.11 或更高版本；
- Windows 开发环境可选安装 Ollama，但确定性学习、复习和词卡查询不应依赖模型可用性。

```powershell
python -m pip install -r requirements-dev.lock
python -m pip check
python -m pytest -q
python -m ruff check app scripts tests main.py
python -m ruff format --check app scripts tests main.py
python -m mypy
```

## 提交边界

- UI 不直接查询 SQLAlchemy，也不直接依赖具体模型 Provider；数据库事务和用例编排放在 `app/services/`。
- 调度、队列、统计、混淆图、候选筛选和提醒时机必须由确定性代码决定，不能交给 LLM。
- 不要提交 `.env`、API Key、运行时数据库、日志、`build/`、`dist/` 或本地模型文件。
- 词库或词卡事实变更必须保留来源版本、下载地址、哈希、许可证、转换方式和可重复验证步骤；未审核的 AI 内容不得伪装成已验证事实。
- 新的后台任务必须遵守现有 Qt worker 生命周期和主窗口延迟关闭约束。

## Pull request 检查清单

- 说明行为变化、数据库迁移影响和回滚/兼容边界；
- 为服务、领域算法和 UI 回归补充测试；
- 在本地运行上面的完整检查，并说明 Ollama/Windows 专属检查是否执行；
- 审查 `git diff --check`，确认没有密钥、个人学习数据或构建产物。
