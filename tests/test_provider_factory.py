from __future__ import annotations

from app.ai.embedding_provider import CachedEmbeddingProvider, OllamaEmbeddingProvider
from app.ai.factory import create_advanced_llm_provider, create_embedding_provider
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


def test_advanced_provider_is_disabled_by_default() -> None:
    settings = Settings(
        advanced_llm_provider="",
        advanced_llm_model="",
        advanced_llm_base_url="",
        advanced_llm_api_key=None,
    )

    assert create_advanced_llm_provider(settings) is None


def test_advanced_openai_compatible_provider_has_independent_settings() -> None:
    provider = create_advanced_llm_provider(
        Settings(
            advanced_llm_provider="openai_compatible",
            advanced_llm_model="advanced-model",
            advanced_llm_base_url="https://models.example/v1",
            advanced_llm_api_key="test-only-key",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "advanced-model"
    assert provider.chat_url == "https://models.example/v1/chat/completions"
    assert provider.api_key == "test-only-key"
