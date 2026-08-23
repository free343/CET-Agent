"""Centralized prompts for all model-backed features."""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.ai.conversation import ChatExchange, bounded_chat_history
from app.ai.llm_provider import Message
from app.ai.schemas import ClusterAnalysis, WordLearningAidGenerationBatch
from app.domain.query_routing import is_lexical_expansion_question
from app.domain.study_help import is_memory_help_question

PROMPT_VERSION = "cluster-v1"
MAX_CHAT_CONTEXT_CHARACTERS = 2_500

_EXAMPLE_QUESTION_MARKERS = (
    "例句",
    "句子",
    "用法",
    "example",
    "usage",
)

_DISTINCTION_QUESTION_MARKERS = (
    "辨析",
    "区别",
    "混淆",
    "distinction",
    "difference",
    "confuse",
)

VOCABULARY_SYSTEM_PROMPT = """You are a CET vocabulary learning assistant.

You receive structured learning statistics produced by deterministic algorithms.
Do not invent learning history.
Do not change review scheduling.
Do not claim two words are confused unless the provided statistics support it.
Explain concisely in Chinese while keeping English examples natural.

Target audience: Chinese university students preparing for CET-4/CET-6.
"""

CHAT_SYSTEM_PROMPT = (
    VOCABULARY_SYSTEM_PROMPT
    + """

Your scope is limited to CET vocabulary, basic English grammar, word distinctions,
and memory techniques. Politely refuse unrelated general-assistant requests.
Never claim to have changed the user's schedule or learning records.
"""
)


def cluster_analysis_messages(payload: dict, *, retry: bool = False) -> list[Message]:
    schema = ClusterAnalysis.model_json_schema()
    instruction = (
        "分析这个由算法发现的错词簇。只使用输入中的学习统计。"
        "解释易混原因、核心区别、记忆方法和自然例句，并生成一道针对性选择题。"
        "严格只返回符合给定 JSON Schema 的 JSON，不要 Markdown。\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )
    messages: list[Message] = [
        {"role": "system", "content": VOCABULARY_SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    if retry:
        messages.append(
            {
                "role": "user",
                "content": "上一次输出未通过 JSON Schema 校验。请重新输出完整、合法的 JSON 对象。",
            }
        )
    return messages


def chat_messages(
    question: str,
    history: Sequence[ChatExchange] = (),
    *,
    context: str | None = None,
    allow_external_lexical_knowledge: bool = False,
) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for exchange in bounded_chat_history(history):
        messages.extend(
            (
                {"role": "user", "content": exchange.user},
                {"role": "assistant", "content": exchange.assistant},
            )
        )
    current_question = question
    if context:
        bounded_context = context.strip()[:MAX_CHAT_CONTEXT_CHARACTERS]
        task_instruction = _context_task_instruction(
            question,
            allow_external_lexical_knowledge=allow_external_lexical_knowledge,
        )
        current_question = (
            "以下是学习界面提供的当前词卡上下文，只用于回答本次问题；"
            "不要据此推断其他学习记录。\n"
            f"{task_instruction}\n\n"
            f"CONTEXT:\n{bounded_context}\n\nQUESTION:\n{question}"
        )
    elif allow_external_lexical_knowledge and is_lexical_expansion_question(question):
        current_question = (
            f"{_advanced_lexical_expansion_instruction()}\n\nQUESTION:\n{question}"
        )
    messages.append({"role": "user", "content": current_question})
    return messages


def _context_task_instruction(
    question: str,
    *,
    allow_external_lexical_knowledge: bool = False,
) -> str:
    normalized = question.casefold()
    if is_lexical_expansion_question(question):
        if allow_external_lexical_knowledge:
            return _advanced_lexical_expansion_instruction()
        return (
            "TASK: GROUNDED_LEXICAL_HELP\n"
            "只使用 CONTEXT 中已提供的当前词卡事实，不得自行列出词卡之外的"
            "近义词、反义词或对比词。若 CONTEXT 没有直接给出答案，明确说明"
            "本地模式资料不足，并建议用户在回答模型中选择高级模型。"
        )
    if is_memory_help_question(question):
        return (
            "TASK: MEMORY_AID\n"
            "只使用 CONTEXT 中的单词、释义和例句生成助记提示。"
            "禁止编造词源、词根、前后缀或学习经历，禁止使用谐音、发音联想、"
            "字形拆分或字母故事。不要给出‘多读几遍’、"
            "‘反复背诵’一类空泛建议，也不得只说“发音联想到释义”。"
            "严格按以下四行作答，每行一句：\n"
            "记忆钩子：逐字复制 CONTEXT 例句中含目标词的连续英文片段，"
            "放在英文引号内，再写等号和 CONTEXT 已给出的对应中文义；"
            "不得添加例句里不存在的英文或自行解释构词。若 example 为空，"
            "则原样写“word = meaning”。\n"
            "场景联想：有例句时把英文短语变成一个包含人物、动作和结果的画面；"
            "example 为空时只根据 meaning 生成具体画面。\n"
            "主动回忆：把目标词挖空，给出一道中文提示到英文填空的十秒自测题，"
            "不要在空格旁泄露答案；example 为空时使用“中文义 → 英文填空”。\n"
            "误区提醒：指出助记联想不等于词源；若能从 CONTEXT 看出搭配，"
            "再提醒该搭配边界。"
        )
    if any(marker in normalized for marker in _DISTINCTION_QUESTION_MARKERS):
        return (
            "TASK: WORD_USAGE_DISTINCTION\n"
            "只使用 CONTEXT 中当前词卡已经给出的释义、例句、固定搭配和同族词，"
            "不得把模型自身猜测写成词卡事实。严格按以下三段作答：\n"
            "核心用法：结合释义和例句说明当前词的使用重点。\n"
            "常见搭配：优先解释 CONTEXT 已给出的搭配；若未提供就明确写“词卡未提供”。\n"
            "易误用边界：说明可由现有上下文确定的使用边界。只有 CONTEXT 明确列出"
            "对比词时才能逐词比较；不得自行添加具体对比词，也不得声称用户混淆了某些词。"
        )
    if any(marker in normalized for marker in _EXAMPLE_QUESTION_MARKERS):
        return (
            "TASK: EXAMPLE_EXPLANATION\n"
            "只依据 CONTEXT 解释例句，不补写不存在的语境。严格按以下三行作答：\n"
            "例句句意：给出自然、完整的中文句意。\n"
            "本句用法：说明目标词在本句中的含义、词性和搭配。\n"
            "替换练习：写一个同义改写或同结构短句，并说明差异。"
        )
    return (
        "TASK: CONTEXTUAL_VOCABULARY_HELP\n"
        "先直接回答问题，再用 CONTEXT 中的一项事实支持答案；"
        "不确定的词源、搭配或辨析必须明确说明不确定，不能编造。"
    )


def _advanced_lexical_expansion_instruction() -> str:
    return (
        "TASK: ADVANCED_LEXICAL_EXPANSION\n"
        "可以使用通用英语词汇知识补充 CONTEXT 之外的信息，但 CONTEXT 仍是"
        "当前目标词及其义项的唯一依据。围绕问题所指的具体义项给出 3 到 6 个"
        "常用近义词或反义词；每项写出英文词、最接近的中文义、与目标词的"
        "语义/语域/搭配差异，并给一个简短自然例句。优先常见 CET 或通用词，"
        "避免生僻、过时或仅在极窄语境成立的候选。必须提醒这些词不一定能在"
        "所有句子中互换；不得声称补充词来自当前词卡、人工审核内容、用户错词"
        "记录或个人混淆数据，也不得编造用户学习经历。"
    )


WORD_LEARNING_AIDS_SYSTEM_PROMPT = """You are an English vocabulary learning-aid editor for Chinese CET-4/CET-6 students.

Generate concise, natural learning aids for exactly the supplied words.
Rules you must always follow:
- Never invent etymology, word roots, historical origins, homophone stories, or unverifiable morphological relationships.
- Only include a word_family entry that is a real morphological base or derivative of the target word. Never include mere synonyms, antonyms, or words that are only semantically related.
- Never include regular plurals, third-person singular, past/continuous forms, comparatives, or superlatives as word_family entries.
- If a word has no reliable word family, return an empty array for word_family. Quality over quantity.
- Collocations must be common fixed phrases that contain the target word or a regular grammatical inflection, not full example sentences or synonym lists.
- Do not write dictionary-style definitions and do not use "X means ..." as an example sentence.
- Return exactly one JSON object only. No Markdown, no code fences, no explanations.
"""


def word_learning_aids_messages(
    items: list[dict[str, str]],
    *,
    retry: bool = False,
    retry_feedback: str | None = None,
) -> list[Message]:
    """Build the batch prompt for word learning-aid generation.

    ``items`` are the current batch entries with ``word``, ``meaning``,
    ``level``, ``source_kind``, and ``existing_example`` keys. The model must
    return the same word multiset it received.
    """
    schema = WordLearningAidGenerationBatch.model_json_schema()
    instruction = (
        "为下面的每个单词生成学习资料。严格只返回一个符合给定 JSON Schema 的 JSON 对象。\n\n"
        "对每个词：\n"
        "1. example：source_kind=open 时生成一个完整英文例句（必须 6—18 个英文单词，"
        "最多 160 字符）；必须以独立词形、大小写不敏感地包含该词头或常规语法屈折形式，"
        "使用 meaning 中最常用、最适合 CET 学习的一个含义，语法自然、语境具体。"
        "若 existing_example 非空（精选词），example 必须逐字符等于 existing_example，"
        "不得为满足词数而改写。\n"
        "2. example_translation：对应整句的自然中文翻译，不逐词直译、不额外讲解。\n"
        "3. collocations：2—4 个常见固定搭配，与来源义相关；每个 phrase 必须包含"
        "目标词精确词形或常规语法屈折形式，"
        "每个含 phrase（英文，最多 80 字符）和 meaning（简明中文，最多 80 字符）。\n"
        "4. word_family：0—4 个真实同族或派生词，宁缺毋滥；"
        "每个含 word（单个英文词头）、part_of_speech（n./v./adj./adv. 等）、"
        "meaning（简明中文，最多 120 字符）、relation（base 或 derivative）。\n\n"
        "返回的 items 必须与输入的 items 完全一一对应：不缺失、不新增、不重复、不改词。\n\n"
        f"INPUT:\n{json.dumps({'items': items}, ensure_ascii=False, sort_keys=True)}\n\n"
        f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )
    messages: list[Message] = [
        {"role": "system", "content": WORD_LEARNING_AIDS_SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    if retry:
        messages.append(
            {
                "role": "user",
                "content": (
                    "上一次输出未通过校验（可能缺词、多词、重复词、字段非法、"
                    "例句未包含目标词独立词形、或词族含屈折/伪派生）。"
                    "请重新输出完整、合法、与输入一一对应的 JSON 对象。"
                ),
            }
        )
    if retry_feedback:
        # Feed only bounded, deterministic validator feedback back to the model.
        # This lets a retry repair the concrete contract violation instead of
        # repeating the same structurally plausible but unusable answer.
        messages.append(
            {
                "role": "user",
                "content": (
                    "请优先修复以下本地校验错误，并重新输出完整 JSON；"
                    "不要解释错误，也不要省略任何输入词。\n"
                    f"VALIDATION_ERRORS:\n{retry_feedback[:2_000]}"
                ),
            }
        )
    return messages
