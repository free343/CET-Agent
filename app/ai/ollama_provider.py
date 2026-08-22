"""Ollama chat adapter using its local HTTP API."""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from app.ai.llm_provider import (
    LLMProvider,
    LLMUnavailableError,
    Message,
    safe_response_text,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(
        self, base_url: str, model: str, timeout_seconds: float = 60.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        body: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 2_048},
        }
        if response_schema is not None:
            body["format"] = response_schema.model_json_schema()
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=body,
                timeout=self.timeout_seconds,
                # Ollama is a direct endpoint; never route it through OS proxies.
                trust_env=False,
            )
            response.raise_for_status()
            content = safe_response_text(response.json(), "message", "content")
            if not content:
                raise ValueError("Ollama returned empty assistant content")
            logger.info("LLM call completed provider=ollama model=%s", self.model)
            return content
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Ollama call failed model=%s error=%s", self.model, exc)
            raise LLMUnavailableError(
                "本地模型暂不可用，请确认 Ollama 已启动且模型已下载。"
            ) from exc
