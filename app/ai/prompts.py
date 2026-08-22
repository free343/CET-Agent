"""Centralized prompts for all model-backed features."""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.ai.conversation import ChatExchange, bounded_chat_history
from app.ai.llm_provider import Message
from app.ai.schemas import ClusterAnalysis

PROMPT_VERSION = "cluster-v1"

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
) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for exchange in bounded_chat_history(history):
        messages.extend(
            (
                {"role": "user", "content": exchange.user},
                {"role": "assistant", "content": exchange.assistant},
            )
        )
    messages.append({"role": "user", "content": question})
    return messages
