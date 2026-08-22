from __future__ import annotations

from app.ai.embedding_provider import OllamaEmbeddingProvider
from app.ai.ollama_provider import OllamaProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
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
