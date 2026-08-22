"""Reserved adapter for local or cloud OpenAI-compatible chat endpoints."""

from __future__ import annotations

import json
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


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def chat_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate(
        self,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        body: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2_048,
        }
        if response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "strict": True,
                    "schema": response_schema.model_json_schema(),
                },
            }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                self.chat_url,
                json=body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Compatible endpoint returned a non-object payload")
            content = safe_response_text(payload, "choices", 0, "message", "content")
            if not content:
                parsed = None
                choices = payload.get("choices")
                if (
                    isinstance(choices, list)
                    and choices
                    and isinstance(choices[0], dict)
                ):
                    message = choices[0].get("message")
                    if isinstance(message, dict):
                        parsed = message.get("parsed")
                if parsed is not None:
                    content = json.dumps(parsed, ensure_ascii=False)
            if not content:
                raise ValueError("Compatible endpoint returned empty assistant content")
            logger.info(
                "LLM call completed provider=openai-compatible model=%s", self.model
            )
            return content
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
            logger.warning(
                "Compatible LLM call failed model=%s error=%s", self.model, exc
            )
            raise LLMUnavailableError("配置的模型服务暂不可用。") from exc
