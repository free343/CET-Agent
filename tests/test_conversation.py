from __future__ import annotations

import pytest

from app.ai.conversation import ChatExchange, bounded_chat_history
from app.ai.prompts import chat_messages


def test_history_keeps_recent_complete_exchanges_within_budgets() -> None:
    history = [
        ChatExchange(user=f"question-{index}", assistant=f"answer-{index}")
        for index in range(6)
    ]

    bounded = bounded_chat_history(history, max_exchanges=3, max_characters=100)

    assert [exchange.user for exchange in bounded] == [
        "question-3",
        "question-4",
        "question-5",
    ]


def test_history_drops_oversized_latest_exchange_without_splitting() -> None:
    history = [
        ChatExchange(user="short", assistant="answer"),
        ChatExchange(user="latest", assistant="x" * 100),
    ]

    assert bounded_chat_history(history, max_characters=50) == ()


def test_chat_messages_preserve_roles_and_current_question_last() -> None:
    messages = chat_messages(
        "current",
        [ChatExchange(user="previous", assistant="prior answer")],
    )

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[-1]["content"] == "current"


def test_contextual_memory_question_gets_grounded_small_model_instructions() -> None:
    messages = chat_messages(
        "这个词如何记忆？",
        context="word=adapt\nmeaning=适应；改编\nexample=Students adapt quickly.",
    )

    prompt = messages[-1]["content"]
    assert "禁止编造词源" in prompt
    assert "禁止使用谐音" in prompt
    assert "不得只说“发音联想到释义”" in prompt
    assert "记忆钩子：" in prompt
    assert "场景联想：" in prompt
    assert "主动回忆：" in prompt
    assert "英文填空" in prompt
    assert "word=adapt" in prompt


def test_contextual_example_question_keeps_example_specific_instructions() -> None:
    messages = chat_messages(
        "请解释这个词在例句中的用法。",
        context="word=adapt\nmeaning=适应；改编\nexample=Students adapt quickly.",
    )

    prompt = messages[-1]["content"]
    assert "例句句意：" in prompt
    assert "本句用法：" in prompt
    assert "替换练习：" in prompt


def test_history_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError):
        bounded_chat_history([], max_exchanges=0)
