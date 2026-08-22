"""Provider construction from application settings."""

from __future__ import annotations

from app.ai.embedding_provider import (
    CachedEmbeddingProvider,
    EmbeddingProvider,
    OllamaEmbeddingProvider,
)
from app.ai.llm_provider import LLMProvider
from app.ai.ollama_provider import OllamaProvider
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.config import Settings
from app.db.database import Database


def create_llm_provider(settings: Settings) -> LLMProvider:
    return _create_chat_provider(
        settings.llm_provider,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_api_key,
        setting_name="LLM_PROVIDER",
    )


def create_advanced_llm_provider(settings: Settings) -> LLMProvider | None:
    if not settings.advanced_llm_provider:
        return None
    return _create_chat_provider(
        settings.advanced_llm_provider,
        settings.advanced_llm_base_url,
        settings.advanced_llm_model,
        settings.advanced_llm_api_key,
        setting_name="ADVANCED_LLM_PROVIDER",
    )


def _create_chat_provider(
    provider_name: str,
    base_url: str,
    model: str,
    api_key: str | None,
    *,
    setting_name: str,
) -> LLMProvider:
    provider = provider_name.strip().lower().replace("_", "-")
    if provider == "ollama":
        return OllamaProvider(base_url, model)
    if provider == "openai-compatible":
        return OpenAICompatibleProvider(base_url, model, api_key)
    raise ValueError(f"Unsupported {setting_name}: {provider_name}")


def create_embedding_provider(
    settings: Settings,
    database: Database,
) -> EmbeddingProvider:
    provider = settings.embedding_provider.strip().lower()
    if provider == "ollama":
        return CachedEmbeddingProvider(
            OllamaEmbeddingProvider(
                settings.embedding_base_url,
                settings.embedding_model,
            ),
            database,
        )
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")
