from __future__ import annotations

import pytest

from app.ai.embedding_provider import (
    EmbeddingUnavailableError,
    OllamaEmbeddingProvider,
)
from app.ai.llm_provider import LLMUnavailableError
from app.ai.ollama_provider import OllamaProvider
from app.ai.openai_compatible_provider import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def test_ollama_embedding_bypasses_environment_proxy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"embeddings": [[0.1, 0.2]]})

    monkeypatch.setattr("app.ai.embedding_provider.httpx.post", fake_post)

    provider = OllamaEmbeddingProvider("http://127.0.0.1:11434", "embed")
    vectors = provider.embed(["adapt"])

    assert vectors == [[0.1, 0.2]]
    assert provider.timeout_seconds == 60.0
    assert captured["trust_env"] is False


def test_ollama_chat_bypasses_environment_proxy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr("app.ai.ollama_provider.httpx.post", fake_post)

    content = OllamaProvider("http://127.0.0.1:11434", "chat").generate(
        [{"role": "user", "content": "hello"}]
    )

    assert content == "ok"
    assert captured["trust_env"] is False
    assert captured["json"]["options"]["num_predict"] == 2_048


def test_openai_chat_sets_output_token_budget(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.ai.openai_compatible_provider.httpx.post", fake_post)

    content = OpenAICompatibleProvider("http://localhost:1234", "chat").generate(
        [{"role": "user", "content": "hello"}]
    )

    assert content == "ok"
    assert captured["json"]["max_tokens"] == 2_048


def test_ollama_embedding_normalizes_non_object_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ai.embedding_provider.httpx.post",
        lambda *args, **kwargs: FakeResponse([]),
    )

    with pytest.raises(EmbeddingUnavailableError):
        OllamaEmbeddingProvider("http://127.0.0.1:11434", "embed").embed(["adapt"])


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"choices": "not-a-list"},
        {"choices": [{"message": []}]},
    ),
)
def test_openai_compatible_normalizes_malformed_payload(monkeypatch, payload) -> None:
    monkeypatch.setattr(
        "app.ai.openai_compatible_provider.httpx.post",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    with pytest.raises(LLMUnavailableError):
        OpenAICompatibleProvider("http://localhost:1234", "chat").generate(
            [{"role": "user", "content": "hello"}]
        )
