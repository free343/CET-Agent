# DeepSeek 逐词生成学习资料提示词

## 使用方法

1. 让 DeepSeek/Coder 打开工作区 `D:\work\english`。
2. 将下方“可直接复制的主提示词”完整发送给它，不要只截取生成规则。
3. 推荐让 DeepSeek 先完成生成脚本、校验器、数据库导入和 20 词试运行；试运行通过后再继续全部 4,611 个词。
4. 如果 DeepSeek 因上下文或会话中断停止，使用文末的“续跑提示词”。

本提示词规定的最终内容文件是：

```text
D:\work\english\data\word_learning_aids.jsonl
```

生成过程中的断点文件必须写入被 Git 忽略的：

```text
D:\work\english\build\word_learning_aids\
```

不要直接修改以下两个来源词库：

```text
D:\work\english\data\sample_words.csv
D:\work\english\data\cet_vocabulary_open.csv
```

其中 `cet_vocabulary_open.csv` 是带固定哈希、来源和许可记录的可复现产物；其构建脚本会把 `example` 固定生成为空字符串。AI 内容必须作为独立数据层保存。

---

## 可直接复制的主提示词

```text
你是一名资深 Python 工程师、英语词汇内容编辑、结构化数据工程师和 AI 生成流水线工程师。请在本机工作区 D:\work\english 内完成 CET-Agent 的“逐词学习资料生成与接入”里程碑。

<project_context>
- 项目是面向 CET4/CET6 学习者的 local-first PySide6 桌面应用。
- 开始任何修改前，必须完整阅读 D:\work\english\AGENTS.md；它是项目当前状态和开发约束的唯一权威来源。
- 当前数据库 schema_version=7。
- data/sample_words.csv 有 13 个精选词，已有人工/项目精选例句。
- data/cet_vocabulary_open.csv 有 4,598 个开放词条，example 全部为空。
- 两个文件没有重复词，因此项目总词数应为 4,611。
- 当前 ReviewItem 已预留 collocations 和 word_family 字段；复习评分阶段已有“固定搭配”“同族 / 派生词”展示区域，但没有真实内容时只显示待生成提示。
- 核心规则仍是：“算法发现问题，LLM 解释问题”。生成内容不得参与 FSRS 排程、复习队列、统计、提醒或评分。
</project_context>

<objective>
完成一个可恢复、可校验、可重复执行的 DeepSeek 批量生成流水线，并将通过校验的内容接入应用：

1. 为全部 4,611 个词生成固定搭配和真实的同族/派生词资料。
2. 只为 data/cet_vocabulary_open.csv 中 4,598 个 example 为空的词生成新英文例句和中文翻译。
3. data/sample_words.csv 中 13 个已有英文例句必须逐字符保留，不得改写；只为它们补充例句翻译、固定搭配和词族信息。
4. 生成结果写入独立的 data/word_learning_aids.jsonl，不得回写或重排两个来源 CSV。
5. 应用启动后可幂等导入该 JSONL；复习页和收藏单词页可以展示生成的例句，复习评分阶段可以展示固定搭配、同族/派生词及必要的中文释义。
</objective>

<non_negotiable_boundaries>
1. 不要直接编辑 data/sample_words.csv、data/cet_vocabulary_open.csv、data/cet_vocabulary_open.provenance.json 或 data/OPEN_VOCABULARY_LICENSE.md。
2. 不要把生成结果直接写进 data/cet_agent.db；数据库只能由应用迁移和经过校验的导入服务更新。
3. 不要让模型读取整个数据库。生成输入只能来自两个 CSV 中当前批次的 word、meaning、level 和已有 example。
4. 所有模型提示词必须集中在 app/ai/prompts.py，严格结构模型放在 app/ai/schemas.py。
5. API 密钥只能从环境变量或本地 .env 读取，不得写入代码、JSONL、provenance、日志、测试、README 或 AGENTS.md。
6. pytest 不得调用真实 DeepSeek 网络接口；用假 Provider/固定响应测试重试、断点、校验和写入。
7. 模型调用不得持有 SQLite 事务。
8. 不得编造词源、词根、历史来源、谐音故事或无法确认的形态关系。
9. 如果一个词没有可靠的同族/派生词，word_family 必须为空数组，不得为了满足数量硬凑。
10. 不得声称完成全部生成，除非最终完整校验确实证明 4,611 个唯一词全部存在，且 4,598 个开放词都有合格例句。
</non_negotiable_boundaries>

<where_to_write>
必须使用下列路径和职责：

1. data/word_learning_aids.jsonl
   - 唯一正式生成产物。
   - UTF-8、无 BOM、LF 换行。
   - 每一物理行恰好一个 JSON 对象，不使用 Markdown，不允许行内注释。
   - 最终顺序：先保持 sample_words.csv 的原顺序，再保持 cet_vocabulary_open.csv 的原顺序。

2. data/word_learning_aids.provenance.json
   - 记录生成器、实际 DeepSeek 模型名、prompt_version、来源文件 SHA-256、最终产物 SHA-256、总行数、CET4/CET6 数量、精选/AI 例句数量、校验结果和生成完成时间。
   - 不记录 API key、请求头或完整模型响应。

3. build/word_learning_aids/
   - 保存 partial.jsonl、失败批次、断点清单和临时响应。
   - 该目录只用于恢复，不得作为正式应用数据源，不提交 Git。
   - 最终文件只能在全部校验通过后原子替换 data/word_learning_aids.jsonl。

4. scripts/generate_word_learning_aids.py
   - 批量生成入口，至少支持：--batch-size、--resume、--max-items、--dry-run、--model、--output。
   - 默认 batch-size=20；每批只向模型提供该批词条。
   - 支持限流、超时、指数退避、结构失败重试、Ctrl+C 后安全恢复。
   - 断点按 word 键控，已通过校验的词不得重复请求，除非显式 --force-word。

5. scripts/validate_word_learning_aids.py
   - 独立、离线、可重复的严格校验器。
   - 至少支持 --require-complete；成功退出码为 0，任何错误退出非 0。
   - 输出总数、等级数、来源数、例句来源数、空词族数和错误摘要。

6. app/db/models.py 与 app/db/migrations.py
   - 新增 WordLearningAid 一对一表，并添加连续的 schema version 8 迁移。
   - 不要给 words 表机械添加多个不受控 JSON 字符串字段。
   - 建议字段：word_id 主键/外键、example、example_translation、collocations_json、word_family_json、generator、model、prompt_version、content_status、content_hash、created_at、updated_at。

7. app/db/learning_aid_seed.py
   - 在任何数据库写入前完整读取并校验正式 JSONL。
   - 按 word 匹配现有 Word，禁止创建新单词。
   - 幂等 upsert；内容哈希未变化时不写入。
   - 文件缺失时允许应用正常启动并继续显示“待生成”，但格式错误时必须拒绝部分导入。

8. app/services/review_service.py 与 app/services/wordbook_service.py
   - 读取 WordLearningAid 并映射为 UI 所需的有界不可变数据。
   - 精选词优先保留 Word.example；开放词使用通过校验的 WordLearningAid.example。
   - 将搭配显示为“英文搭配｜中文义”，词族显示为“单词 (词性)｜中文义”。

9. app/ui/review_page.py、app/ui/widgets/review_card.py、app/ui/wordbook_page.py
   - 只负责展示，不得解析原始 JSON、查询 SQLAlchemy 或调用具体 DeepSeek 适配器。
   - 例句翻译使用次要文字样式；没有资料时保留当前待生成提示。

10. packaging/CET-Agent.spec、测试和 AGENTS.md
   - 将正式 JSONL 和 provenance 纳入打包资源。
   - 为生成、校验、导入、迁移、服务映射、空文件降级和 UI 展示增加确定性测试。
   - 仅在真实运行相应检查后更新 AGENTS.md 的实现状态和验证证据。
</where_to_write>

<final_jsonl_contract>
data/word_learning_aids.jsonl 的每一行必须严格符合以下逻辑结构；禁止额外字段：

{
  "schema_version": 1,
  "word": "小写英文词头，与来源 CSV 完全一致",
  "level": "CET4 或 CET6",
  "source_kind": "curated 或 open",
  "source_meaning": "来源 CSV 的中文释义，规范化首尾空白后保持一致",
  "example": "英文例句",
  "example_translation": "准确自然的中文翻译",
  "example_origin": "curated 或 ai_generated",
  "collocations": [
    {
      "phrase": "常见固定搭配",
      "meaning": "简明中文义"
    }
  ],
  "word_family": [
    {
      "word": "真实同族或派生词",
      "part_of_speech": "n. / v. / adj. / adv. 等",
      "meaning": "与来源义相关的简明中文义",
      "relation": "base 或 derivative"
    }
  ],
  "generator": {
    "provider": "deepseek",
    "model": "实际使用的模型名，不得写 unknown",
    "prompt_version": "word-learning-aids-v1"
  },
  "content_status": "ai_generated_unreviewed"
}

正式 JSONL 中每个对象必须压缩为单行。上面的缩进仅用于说明。
</final_jsonl_contract>

<content_rules>
一、英文例句：
1. 每条只写一个完整英文句子，建议 6—18 个英文单词，最多 160 个字符。
2. 必须以独立词形、大小写不敏感地包含目标 word 的精确拼写，便于应用生成填空题。
3. 采用目标词在 source_meaning 中最常用、最适合 CET 学习的含义。
4. 难度控制在 CET4/CET6 学习者可理解范围，语法自然，语境具体。
5. 不使用需要实时知识的事实、争议性政治判断、危险行为、歧视内容或不必要的专有名词。
6. 不要写词典式定义，不要使用“X means ...”作为例句。
7. 对 curated 词，example 必须与 sample_words.csv 完全一致，模型不得改写。
8. 中文翻译应对应整句，不机械逐词翻译，不额外讲解。

二、固定搭配：
1. 每词生成 2—4 个常见且与来源义相关的搭配。
2. phrase 最多 80 个字符，meaning 最多 80 个字符。
3. 搭配必须包含目标词，或包含其在搭配中语法必需的规范词形。
4. 不把完整例句、随意词组、同义词列表或中文释义本身当作搭配。
5. 去重时忽略大小写和多余空白。

三、同族 / 派生词：
1. 允许 0—4 项；宁缺毋滥。
2. 只收录真实的形态学基词或派生词，不收录仅仅语义相关的同义词/反义词。
3. 不收录规则复数、第三人称单数、过去式、进行时、比较级等纯屈折变化。
4. 不重复目标词本身，不重复其他项目。
5. word 只能是单个英文词头，最多 100 个字符；meaning 最多 120 个字符。
6. relation 只能是 base 或 derivative。

四、生成状态：
1. 所有 AI 补充内容标记为 ai_generated_unreviewed。
2. 不得使用“权威”“人工审核”“词典认证”等未经事实支持的表述。
</content_rules>

<model_batch_contract>
每次模型调用的输入只包含当前批次，形式为：

{
  "items": [
    {
      "word": "government",
      "meaning": "n. 政府, 内阁",
      "level": "CET4",
      "source_kind": "open",
      "existing_example": ""
    }
  ]
}

要求模型只返回一个 JSON 对象，不要 Markdown、解释或代码围栏：

{
  "items": [
    {
      "word": "government",
      "example": "The government announced a new policy to support small businesses.",
      "example_translation": "政府宣布了一项支持小企业的新政策。",
      "collocations": [
        {"phrase": "central government", "meaning": "中央政府"},
        {"phrase": "local government", "meaning": "地方政府"},
        {"phrase": "government policy", "meaning": "政府政策"}
      ],
      "word_family": [
        {"word": "govern", "part_of_speech": "v.", "meaning": "治理；统治", "relation": "base"},
        {"word": "governor", "part_of_speech": "n.", "meaning": "州长；主管", "relation": "derivative"},
        {"word": "governmental", "part_of_speech": "adj.", "meaning": "政府的", "relation": "derivative"}
      ]
    }
  ]
}

代码必须验证返回 items 与输入 word 集合完全相同：不能缺词、不能多词、不能重复、不能改词。结构或内容不合法时，对该批最多重试两次；仍失败则写入失败清单，不得把无效结果追加到正式或已验证断点。
</model_batch_contract>

<complete_jsonl_examples>
以下示例仅用于说明最终文件格式。实际写入时每个对象各占一行，并由脚本补充 generator、来源字段和状态。

开放词示例（需要 AI 生成例句）：
{"schema_version":1,"word":"government","level":"CET4","source_kind":"open","source_meaning":"n. 政府, 内阁","example":"The government announced a new policy to support small businesses.","example_translation":"政府宣布了一项支持小企业的新政策。","example_origin":"ai_generated","collocations":[{"phrase":"central government","meaning":"中央政府"},{"phrase":"local government","meaning":"地方政府"},{"phrase":"government policy","meaning":"政府政策"}],"word_family":[{"word":"govern","part_of_speech":"v.","meaning":"治理；统治","relation":"base"},{"word":"governor","part_of_speech":"n.","meaning":"州长；主管","relation":"derivative"},{"word":"governmental","part_of_speech":"adj.","meaning":"政府的","relation":"derivative"}],"generator":{"provider":"deepseek","model":"实际模型名","prompt_version":"word-learning-aids-v1"},"content_status":"ai_generated_unreviewed"}

精选词示例（已有例句必须原样保留）：
{"schema_version":1,"word":"adapt","level":"CET4","source_kind":"curated","source_meaning":"适应；改编","example":"Students must adapt to a new learning environment.","example_translation":"学生必须适应新的学习环境。","example_origin":"curated","collocations":[{"phrase":"adapt to change","meaning":"适应变化"},{"phrase":"adapt a book for the screen","meaning":"把书改编成影视作品"}],"word_family":[{"word":"adaptation","part_of_speech":"n.","meaning":"适应；改编作品","relation":"derivative"},{"word":"adaptable","part_of_speech":"adj.","meaning":"适应性强的；可改编的","relation":"derivative"}],"generator":{"provider":"deepseek","model":"实际模型名","prompt_version":"word-learning-aids-v1"},"content_status":"ai_generated_unreviewed"}
</complete_jsonl_examples>

<offline_validation_rules>
正式产物晋级前必须至少验证：

1. 来源总词集合恰好为 4,611 个唯一 word；正式 JSONL 也必须恰好为同一集合。
2. source_kind=curated 恰好 13 个；source_kind=open 恰好 4,598 个。
3. open 的 example_origin 全部为 ai_generated，且例句非空。
4. curated 的 example_origin 全部为 curated，且 example 与 sample_words.csv 完全一致。
5. level、source_meaning 与对应 CSV 一致。
6. 每个例句包含目标 word 的精确独立词形；英文句号/问号/感叹号结尾；无换行。
7. collocations 数量 2—4，字段非空且去重。
8. word_family 数量 0—4；字段有界；没有目标词本身、重复项和明显屈折变化。
9. 所有枚举值、长度、额外字段、JSON 类型、UTF-8 和单行格式符合契约。
10. generator.model 是实际模型名，prompt_version 全部为 word-learning-aids-v1。
11. 最终文件 SHA-256 和统计写入 provenance；provenance 的哈希反向校验通过。
12. 随机抽样至少 100 条，并固定检查高歧义、多词性、连字符、撇号、长中文释义、无词族等边界类别；将抽样清单和结果写入 build/，不要声称这是人工审核。
</offline_validation_rules>

<implementation_sequence>
严格按以下顺序推进：

阶段 A：审计与设计
1. 完整阅读 AGENTS.md、相关模型/迁移/seed/ReviewService/WordbookService/UI/测试和打包配置。
2. 运行只读统计，确认 13 + 4,598 = 4,611，确认开放词例句空缺数为 4,598。
3. 检查 Git 状态，保护无关用户修改。

阶段 B：先搭建安全流水线
1. 定义严格 Pydantic schema、集中式 prompt、生成脚本、断点机制和离线校验器。
2. 添加 schema v8、WordLearningAid 导入和服务/UI 映射。
3. 用假 Provider 完成失败测试：缺词、多词、重复词、非法 JSON、错误例句词形、重复搭配、伪词族、超长字段、重试耗尽、断点恢复、原子晋级和无 API key 泄漏。
4. 跑 focused tests，再跑完整测试和 offscreen smoke。

阶段 C：20 词试运行
1. 选择覆盖 CET4/CET6、名词/动词/形容词、多词性、长释义的固定 20 词样本。
2. 生成到 build/word_learning_aids/，运行严格校验。
3. 汇报 20 条的字段统计和最多 5 条示例，不要在对话中粘贴全部原始响应。
4. 如果没有可用 DeepSeek 调用方式或密钥，停止在此处，明确给出需要配置的环境变量和继续命令；绝不伪造已调用结果。

阶段 D：全量生成
1. 使用默认 20 词批次和 --resume 继续，已验证词不重复调用。
2. 每完成 200 词打印一次简短进度：成功、失败、剩余、重试次数；不输出密钥或完整提示词。
3. 对失败批次先自动重试，再单词级隔离；不能因少量失败丢弃已验证内容。
4. 直到 4,611 个唯一词全部通过；任何未完成项都必须如实保留在失败清单。

阶段 E：原子晋级与应用验证
1. 只有 --require-complete 通过时，才原子生成正式 JSONL 和 provenance。
2. 启动应用导入，确认第二次启动插入/更新为 0 或内容哈希无变化。
3. 验证 curated 例句未改变、开放词例句能显示、搭配/词族不再显示占位、空词族能安全显示、收藏页能显示生成例句。
4. 运行下面全部命令，并记录真实结果：

   python -m pip check
   python -m pytest -q
   python -m ruff check app scripts tests main.py
   python -m ruff format --check app scripts tests main.py
   python -m mypy
   python scripts/validate_word_learning_aids.py --require-complete
   $env:QT_QPA_PLATFORM='offscreen'
   python main.py --smoke-test
   Remove-Item Env:QT_QPA_PLATFORM

5. 更新 AGENTS.md：架构、schema 版本、实际生成数量、模型与 prompt_version、验证结果、未人工审核限制、剩余问题和关键设计决策。
6. 仅在所有要求完成且 Git diff 已检查后提交一个清晰的 Git commit；不要提交 .env、API key、build/ 断点或失败响应。
</implementation_sequence>

<required_final_report>
最终只汇报：
1. 实际修改的文件和架构边界。
2. 实际 DeepSeek provider/model/prompt_version，不包含密钥。
3. 正式 JSONL 总数、CET4/CET6 数量、curated/open 数量、AI 例句数量、空 word_family 数量、文件 SHA-256。
4. 校验和测试的真实结果。
5. 最多 5 条代表性内容示例。
6. 仍未解决的问题，尤其是“AI 生成、尚未人工审核”的内容质量限制。
7. Git commit ID；若未提交，必须说明原因。

不要用计划代替执行，不要把试运行说成全量完成，不要粘贴 4,611 行内容到聊天回复。
</required_final_report>
```

---

## 续跑提示词

如果 DeepSeek 因上下文压缩或新会话中断，将下面内容连同本文件路径发给它：

```text
继续 D:\work\english 的逐词学习资料生成任务。先完整阅读：

1. D:\work\english\AGENTS.md
2. D:\work\english\docs\prompts\DEEPSEEK_WORD_LEARNING_AIDS_PROMPT.md

然后检查 Git 状态、正式产物、provenance、build/word_learning_aids/ 断点和失败清单。严格使用已有 --resume 流程，从已验证的最后状态继续；不得重新请求已通过词条，不得把 partial 当作正式完成，不得修改两个来源 CSV。先运行离线校验并汇报当前真实计数，再继续下一批，直至 --require-complete、完整测试和 offscreen smoke 全部通过。完成后更新 AGENTS.md 并按主提示词的 required_final_report 汇报。
```

## 人工抽查建议

全量生成后，至少人工查看以下类型各 10 个：

- 多词性长释义词，如 `state`、`object`、`present`；
- 容易混淆的词，如 `adapt/adopt/adept`；
- 抽象名词、动词、形容词和副词；
- 连字符或撇号词；
- `word_family=[]` 的词；
- CET6 低频词；
- 例句中目标词位于句首、句中和句尾的情况。

人工抽查通过不等于全部人工审核。应用和文档仍应保留 `ai_generated_unreviewed` 标记，直到存在逐条审核流程。
