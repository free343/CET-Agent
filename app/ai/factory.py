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
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return OllamaProvider(settings.llm_base_url, settings.llm_model)
    if provider in {"openai-compatible", "openai_compatible"}:
        return OpenAICompatibleProvider(
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_api_key,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


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
