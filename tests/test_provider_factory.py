from __future__ import annotations

from app.ai.embedding_provider import CachedEmbeddingProvider, OllamaEmbeddingProvider
from app.ai.factory import create_embedding_provider
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.config import Settings


def test_openai_compatible_url_does_not_duplicate_v1() -> None:
    with_version = OpenAICompatibleProvider("http://localhost:1234/v1", "local")
    without_version = OpenAICompatibleProvider("http://localhost:1234", "local")
    assert with_version.chat_url == "http://localhost:1234/v1/chat/completions"
    assert without_version.chat_url == "http://localhost:1234/v1/chat/completions"


def test_embedding_provider_uses_independent_base_url(database) -> None:
    provider = create_embedding_provider(
        Settings(
            llm_base_url="http://llm.invalid:8000",
            embedding_base_url="http://embedding.invalid:11434",
        ),
        database,
    )
    assert isinstance(provider, CachedEmbeddingProvider)
    assert isinstance(provider.provider, OllamaEmbeddingProvider)
    assert provider.provider.base_url == "http://embedding.invalid:11434"


def test_embedding_cache_namespace_changes_with_endpoint(database) -> None:
    first = CachedEmbeddingProvider(
        OllamaEmbeddingProvider("http://first:11434", "same-model"), database
    )
    second = CachedEmbeddingProvider(
        OllamaEmbeddingProvider("http://second:11434", "same-model"), database
    )
    assert first.cache_model_key != second.cache_model_key
