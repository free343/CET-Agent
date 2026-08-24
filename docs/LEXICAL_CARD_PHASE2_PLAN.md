# CET-Agent 单词卡词典化优化方案（Phase 2）

状态：来源契约、全量覆盖审计、ECDICT 词形候选工件和扩展关系候选工件已完成；正式词卡事实保持不变，来源候选已通过独立 schema-v13 overlay 进入应用并以“来源候选 · 待审核”显示。

## 1. 目标与边界

目标是让用户在答题后直接看到可靠、相关、简洁的词形与近反义关系，尽量不必询问 LLM。事实主要来自可复制、修改和再分发的固定版本词典；模型只能解释已经固定的候选内容，不能创造或认证事实。

本阶段不改变 FSRS、学习队列、数据库调度、答题隔离和现有动态布局。来源候选只进入独立展示列，不会创建 Word、LearningState、复习任务或统计证据；缺失内容继续隐藏，覆盖率不足不是模型猜测补齐的理由。

## 2. 用户最终看到的内容

- `词形`：只展示与该词词性有关的复数、时态、分词、比较级/最高级、序数词或其他高价值变化。规则变化可压缩成一行；不规则、易错、多变体和读音变化优先。
- `搭配`：继续使用现有生成内容并保留 `AI · 未审核`，后续可由开放语料或词典证据替换。
- `近反义`：数据按“关系类型 + 词性 + 当前义项”分组，但词卡与确定性助手只呈现目标词信息：`近义：目标词 adj./adv./n./v. 翻译` 或 `反义：目标词 adj./adv./n./v. 翻译`，不重复当前学习单词的词性和义项。即使只有一个义项，也必须显示目标词性。每组最多保留常用、单词级候选；不存在可靠关系时整组隐藏。
- `派生词`：继续与语法词形严格分离。只有真实构词关系才进入该组。
- 已验证事实和 AI 内容保持分区信任状态。答案揭示前仍不得显示会泄露题目答案的内容。

## 3. 第一批来源允许清单

精确机器可读契约位于 `data/lexical_source_manifest.json`。

| 来源 | 固定版本 | 用途 | 许可边界 |
|---|---|---|---|
| ECDICT | `bc015ed2…` | `exchange` 词形、词性、英汉释义、频率 | MIT；允许修改和再分发，但必须保留版权及许可声明 |
| Open English WordNet | 2025 | synset 近义候选、显式反义关系、英文义项 | CC BY 4.0 + 底层 WordNet 许可；必须同时署名两个项目 |
| Chinese Open Wordnet | 2.0 | 通过共享 ILI 提供中文义项辅助对齐 | WordNet 类宽松许可；必须保留版权、许可和免责声明 |

商业词典、仅限 API 调用、禁止再分发、非商业许可或来源不清的数据不进入正式产物。公共领域或 CC0 词典可以后续加入，但仍必须固定具体版本、下载地址和哈希；“出版年代久远”本身不是公版证明。

## 4. 数据流与信任升级

```text
来源清单与许可人工核对
    ↓
固定 URL / 版本 / SHA-256 下载门禁
    ↓
ECDICT exchange 解析 + WordNet/COW ILI 对齐
    ↓
候选覆盖、冲突和缺失报告（不进入应用）
    ↓
逐词字段级词形候选 JSONL（仅候选，不进入应用）
    ↓
WordNet/COW 多义项关系候选 JSONL（仅候选 artifact）
    ↓
词性/义项/重复/常用度/目标词边界过滤
    ↓
schema-v13 候选 overlay 导入 → 词卡与确定性助手以“待审核”展示
    ↓
分层人工抽检与问题回流
    ↓
带字段级证据的 lexical-facts v2 候选
    ↓
独立完整验证 → 正式 JSONL → 正式 verified UI
```

每条词形范式和关系组都需要证据引用，至少包含 `source_id`、固定版本和可回溯定位符。Phase 2 正式晋升时应把词汇事实契约升级为 v2，在范式/关系组上保存 `evidence_ids`，并让 provenance 固定来源清单哈希。当前单一 `source` 字符串不足以表达“词形来自 ECDICT、关系来自两个 WordNet”的字段级谱系，因此不能直接覆盖正式 artifact。

## 5. 首次全量审计结果

审计命令读取 4,611 个目标词，但只输出统计报告，不写数据库或正式 JSONL。

| 指标 | 结果 | 含义 |
|---|---:|---|
| ECDICT 精确命中 | 4,611 / 4,611 | 所有目标词均可回溯到固定版本 ECDICT |
| 有可用词形 exchange | 3,906 | 可作为规则词形的独立来源证据 |
| 可补充当前缺失词形 | 224 | 742 个缺失词形中，224 个已有 ECDICT 候选 |
| 当前词形角色获 ECDICT 佐证 | 9,780 | 可保留并补充证据引用 |
| 当前词形角色与 ECDICT 冲突 | 827 | 必须分类审计，不能自动选择任一方 |
| OEWN 精确命中 | 4,583 / 4,611 | 英文 WordNet 头词覆盖率约 99.4% |
| 有近义/反义候选 | 4,119 | 候选覆盖广，但尚未完成义项过滤 |
| 有中文 ILI 义项 | 3,872 | 可使用 Chinese Open Wordnet 辅助对齐 |
| 严格中文重合且有关系候选 | 2,753 | 进入后续候选审核池，不等于自动通过 |
| 只有一个严格匹配关系组 | 1,629 | 最适合作为首轮人工试验池 |
| 严格匹配近义边 | 9,931 | 仍需常用度、重复和互换边界筛选 |
| 严格匹配反义边 | 623 | 只使用 WordNet 显式反义关系 |

已生成的字段级 ECDICT 词形候选工件（`data/word_lexical_fact_candidates.jsonl`）覆盖全部
4,611 个头词，包含 11,725 个带证据的角色比较：1,118 个来源新增角色候选、9,780 个
与当前事实重合的角色、827 个冲突角色。冲突启发式分类为 750 个“当前旧规则候选”和
77 个可能的 `-l` 单/双写地域变体；这些标签只用于排序人工审核，不是正确性结论。
工件的每行都保存 ECDICT 固定版本、`exchange` 字段、词头/代码定位符、源文件哈希和
来源清单哈希，并由独立脚本校验内容哈希、完整词集、来源字段和 provenance。正式
`word_lexical_facts.jsonl`、SQLite 和 UI 均未被此工件改写。

关系候选工件（`data/word_lexical_relation_candidates.jsonl`）覆盖全部 4,611 个头词。
扩展版保留所有中文重合对齐的可用义项，目标从完整 ECDICT 中选取单词级、频率大于 0、
词性兼容的词，允许目标词超出 CET 学习库（仅作参考显示）。工件共保留 4,318 个关系组
（3,781 近义、537 反义）和 8,447 个关系目标，2,408 个词具备近义候选、483 个词具备
反义候选；1,550 个单义项、947 个多义项完整保留、91 个多义项按最高频关系组确定性截断，
2,023 个词暂无中文对齐义项。每个目标保留 OEWN、COW、ECDICT 三条字段证据。

这些值仍然是 source-backed candidate，不是人工审核后的 verified fact。应用通过 schema-v13
的 `candidate_relations_json` 独立列导入候选，并在词卡标题与助手答案中显示“来源候选 · 待审核”；
正式关系列、FSRS、学习队列、复习日志和统计不受影响。

827 个冲突证明现有常规拼写规则过度简化，例如 `admit → admited`、`arise → arised` 等明显错误；也包含 `barreled/barrelled` 这类地域变体和 `bound/bounded` 这类义项差异。因此该数字是“需审核队列”，不能整体视为 ECDICT 正确、当前数据错误。

## 6. 发布门禁

### 词形

1. 目标词必须精确匹配，不允许模糊匹配或从相似词推断。
2. 只接受 ECDICT 文档定义的 `s/p/d/i/3/r/t` 字段；`0/1` lemma 信息不得混入派生词。
3. 当前值与来源一致时保留并增加证据；来源能填补缺失时进入新增候选。
4. 冲突按“明显规则错误、合法地区变体、多义词差异、来源疑点”分类。
5. 不规则动词、辅音双写、`-f/-fe` 复数、同形变化、不可数名词和多变体必须进入分层人工抽检。

### 近反义关系

1. 近义词只能来自同一 OEWN synset；反义词只能来自显式 `antonym` 关系。
2. 英文义项必须通过同一 ILI 与 COW 中文义项连接，禁止按文件位置或翻译猜测匹配。
3. COW 中文义项必须与当前 ECDICT 中文释义产生严格片段重合；无重合只保留为诊断候选。
4. 必须保留词性和义项分组，移除自身、重复、多词短语、罕见噪声和不适合 CET 学习的候选。
5. DeepSeek 可以为已固定候选补充中文区别与互换限制，但内容保持 `AI · 未审核`，不得改变候选集合。

### 数据质量

- 完整性：正式 artifact 必须仍精确覆盖 4,611 个词；缺失用明确状态表示。
- 唯一性：头词、范式角色、义项关系组和关系目标均不得重复。
- 有效性：来源、许可、URL、版本、哈希、字段用途和署名全部通过 allowlist。
- 准确性：字段由词典证据决定；冲突进入审核，不用多数投票静默覆盖。
- 一致性：artifact、provenance、SQLite 导入和 UI 投影使用同一内容哈希。
- 可复现性：相同固定输入必须生成字节一致的候选报告和正式产物。

## 7. 实施顺序

1. **已完成：来源基础设施。** 三个来源的机器可读许可/哈希契约、离线解析器、候选审计脚本和覆盖报告。
2. **已完成：词形修复候选。** `scripts/generate_lexical_fact_candidates.py` 输出逐词字段级证据 JSONL，`scripts/validate_lexical_fact_candidates.py --require-complete` 独立校验 4,611 行和 827 个冲突分类；该工件仍完全 candidate-only。
3. **已完成：扩展关系候选与安全可见 overlay。** `scripts/generate_lexical_relation_candidates.py` 与独立验证器保留 2,408 个近义词候选所属词头和 483 个反义词候选所属词头；schema-v13 将候选列与正式事实隔离，启动导入、词卡投影和确定性查询均显示待审核状态。
4. **下一步：分层人工审核与正式晋升。** 按 CET4/CET6、词性、冲突类别、频率和规则/不规则样本审核词形候选；对 2,408 个关系词按近义/反义、多义和目标频率抽样，形成错误、合法变体、词义疑点和可晋升清单。
5. **质量门槛。** 词形目标精确率至少 98%，关系目标精确率至少 95%；未达标则改过滤器，不扩大数据。对高频/低频、CET4/CET6、各词性、单义/多义、同义/反义进行分层抽样。
6. **正式晋升。** 升级字段级证据契约，加入许可证 NOTICE，重新生成完整 artifact，运行独立验证、数据库幂等导入、确定性查询和 UI 回归。

## 8. 开发与验证命令

```powershell
Set-Location 'D:\work\english'

# 已有缓存时只校验并审计；缺失时显式允许下载
python scripts/audit_lexical_sources.py
python scripts/audit_lexical_sources.py --download-missing
python scripts/generate_lexical_fact_candidates.py
python scripts/validate_lexical_fact_candidates.py --require-complete
python scripts/generate_lexical_relation_candidates.py
python scripts/validate_lexical_relation_candidates.py --require-complete

python -m pytest -q tests/test_lexical_source_pipeline.py
python -m pytest -q tests/test_lexical_candidate_pipeline.py
python -m pytest -q tests/test_lexical_relation_candidate_pipeline.py
python scripts/validate_lexical_facts.py --require-complete
python -m pytest -q
python -m ruff check app scripts tests main.py
python -m ruff format --check app scripts tests main.py
python -m mypy
```

下载缓存位于 Git 忽略的 `build/lexical_sources/`。正式应用启动不会联网，也不会读取这些原始下载文件。
