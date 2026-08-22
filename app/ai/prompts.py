"""Centralized prompts for all model-backed features."""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.ai.conversation import ChatExchange, bounded_chat_history
from app.ai.llm_provider import Message
from app.ai.schemas import ClusterAnalysis
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
        task_instruction = _context_task_instruction(question)
        current_question = (
            "以下是学习界面提供的当前词卡上下文，只用于回答本次问题；"
            "不要据此推断其他学习记录。\n"
            f"{task_instruction}\n\n"
            f"CONTEXT:\n{bounded_context}\n\nQUESTION:\n{question}"
        )
    messages.append({"role": "user", "content": current_question})
    return messages


def _context_task_instruction(question: str) -> str:
    normalized = question.casefold()
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
