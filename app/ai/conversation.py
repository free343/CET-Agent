"""Bounded in-session context for the scoped vocabulary assistant."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_CHAT_HISTORY_EXCHANGES = 4
MAX_CHAT_HISTORY_CHARACTERS = 6_000


@dataclass(frozen=True, slots=True)
class ChatExchange:
    user: str
    assistant: str


def bounded_chat_history(
    history: Sequence[ChatExchange],
    *,
    max_exchanges: int = MAX_CHAT_HISTORY_EXCHANGES,
    max_characters: int = MAX_CHAT_HISTORY_CHARACTERS,
) -> tuple[ChatExchange, ...]:
    if max_exchanges <= 0 or max_characters <= 0:
        raise ValueError("Chat history budgets must be positive")
    selected: list[ChatExchange] = []
    used_characters = 0
    for exchange in reversed(history):
        user = exchange.user.strip()
        assistant = exchange.assistant.strip()
        if not user or not assistant:
            continue
        exchange_size = len(user) + len(assistant)
        if exchange_size > max_characters - used_characters:
            break
        selected.append(ChatExchange(user=user, assistant=assistant))
        used_characters += exchange_size
        if len(selected) == max_exchanges:
            break
    selected.reverse()
    return tuple(selected)
