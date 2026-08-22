"""Embedding provider abstraction, Ollama adapter, and SQLite cache wrapper."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from abc import ABC, abstractmethod

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.database import Database
from app.db.models import EmbeddingCache

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    model: str

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one numeric vector for every source text."""


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, base_url: str, model: str, timeout_seconds: float = 60.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=self.timeout_seconds,
                # Windows proxy settings can otherwise capture localhost traffic.
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Embedding endpoint returned a non-object payload")
            vectors = payload.get("embeddings", [])
            if len(vectors) != len(texts):
                raise ValueError("Embedding response length does not match input")
            return [[float(value) for value in vector] for vector in vectors]
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Embedding provider unavailable: %s", exc)
            raise EmbeddingUnavailableError("本地 Embedding 服务暂不可用") from exc


class CachedEmbeddingProvider(EmbeddingProvider):
    def __init__(self, provider: EmbeddingProvider, database: Database) -> None:
        self.provider = provider
        self.database = database
        self.model = provider.model
        provider_identity = "|".join(
            (
                type(provider).__name__,
                str(getattr(provider, "base_url", "local")),
                provider.model,
            )
        )
        identity_hash = hashlib.sha256(provider_identity.encode("utf-8")).hexdigest()[
            :16
        ]
        self.cache_model_key = f"{provider.model}:{identity_hash}"

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_vector(values: object) -> list[float]:
        if not isinstance(values, list) or not values:
            raise ValueError("Embedding vector must be a non-empty list")
        vector = [float(value) for value in values]
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("Embedding vector contains a non-finite value")
        return vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float] | None] = [None] * len(texts)
        missing_by_hash: dict[str, tuple[str, list[int]]] = {}

        # Do not keep a SQLite transaction open while waiting for the model.
        # A long cold start would otherwise make a later read-to-write upgrade
        # vulnerable to "database is locked" when another UI action commits.
        with self.database.session() as session:
            for index, source_text in enumerate(texts):
                content_hash = self._hash(source_text)
                cached = session.scalar(
                    select(EmbeddingCache).where(
                        EmbeddingCache.model == self.cache_model_key,
                        EmbeddingCache.content_hash == content_hash,
                    )
                )
                if cached:
                    try:
                        vectors[index] = self._normalize_vector(
                            json.loads(cached.vector_json)
                        )
                        continue
                    except (TypeError, ValueError):
                        logger.warning(
                            "Discarding invalid embedding cache row id=%s", cached.id
                        )
                        session.delete(cached)
                entry = missing_by_hash.setdefault(content_hash, (source_text, []))
                entry[1].append(index)

        if missing_by_hash:
            missing_items = list(missing_by_hash.items())
            try:
                generated = self.provider.embed([item[1][0] for item in missing_items])
                if len(generated) != len(missing_items):
                    raise ValueError("Embedding response length does not match input")
                normalized_vectors = [
                    self._normalize_vector(vector) for vector in generated
                ]
            except (TypeError, ValueError) as exc:
                raise EmbeddingUnavailableError("Embedding 服务返回了无效向量") from exc

            with self.database.session() as session:
                for (content_hash, (source_text, indices)), vector in zip(
                    missing_items, normalized_vectors, strict=True
                ):
                    for index in indices:
                        vectors[index] = vector
                    statement = sqlite_insert(EmbeddingCache).values(
                        model=self.cache_model_key,
                        content_hash=content_hash,
                        source_text=source_text,
                        vector_json=json.dumps(vector),
                    )
                    session.execute(
                        statement.on_conflict_do_update(
                            index_elements=(
                                EmbeddingCache.model,
                                EmbeddingCache.content_hash,
                            ),
                            set_={
                                "source_text": source_text,
                                "vector_json": json.dumps(vector),
                            },
                        )
                    )

        if any(vector is None for vector in vectors):
            raise EmbeddingUnavailableError("Embedding 缓存结果不完整")
        completed = [vector for vector in vectors if vector is not None]
        if len({len(vector) for vector in completed}) != 1:
            raise EmbeddingUnavailableError("Embedding 向量维度不一致")
        return completed
