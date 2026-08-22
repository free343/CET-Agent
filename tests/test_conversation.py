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


def test_history_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError):
        bounded_chat_history([], max_exchanges=0)
