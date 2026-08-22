"""Unified language-model provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

Message = dict[str, str]


class LLMUnavailableError(RuntimeError):
    pass


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        """Generate assistant content; schema hints do not replace validation."""


def safe_response_text(payload: dict[str, Any], *path: str | int) -> str:
    current: Any = payload
    try:
        for segment in path:
            current = current[segment]
    except (KeyError, IndexError, TypeError):
        return ""
    return current if isinstance(current, str) else ""

