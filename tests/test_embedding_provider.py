from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from app.ai.embedding_provider import CachedEmbeddingProvider, EmbeddingProvider
from app.db.models import EmbeddingCache


class FakeEmbeddingProvider(EmbeddingProvider):
    model = "fake-v1"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), 1.0] for text in texts]


class DatabaseWritingEmbeddingProvider(EmbeddingProvider):
    model = "writing-v1"

    def __init__(self, database) -> None:
        self.database = database

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self.database.session() as session:
            session.add(
                EmbeddingCache(
                    model="concurrent-write-probe",
                    content_hash="probe",
                    source_text="probe",
                    vector_json="[1.0]",
                )
            )
        return [[float(len(text)), 1.0] for text in texts]


class BarrierEmbeddingProvider(EmbeddingProvider):
    model = "barrier-v1"

    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.barrier.wait(timeout=5)
        return [[float(len(text)), 1.0] for text in texts]


def test_embedding_cache_avoids_duplicate_provider_calls(database) -> None:
    fake = FakeEmbeddingProvider()
    provider = CachedEmbeddingProvider(fake, database)
    first = provider.embed(["adapt", "adopt", "adapt"])
    second = provider.embed(["adapt", "adopt"])

    assert first[0] == first[2]
    assert second == first[:2]
    assert fake.calls == 1
    with database.session() as session:
        assert session.scalar(select(func.count(EmbeddingCache.id))) == 2


def test_corrupt_embedding_cache_is_replaced_from_provider(database) -> None:
    fake = FakeEmbeddingProvider()
    provider = CachedEmbeddingProvider(fake, database)
    content_hash = provider._hash("adapt")
    with database.session() as session:
        session.add(
            EmbeddingCache(
                model=provider.cache_model_key,
                content_hash=content_hash,
                source_text="adapt",
                vector_json='{"not": "a vector"}',
            )
        )

    first = provider.embed(["adapt"])
    second = provider.embed(["adapt"])

    assert first == [[5.0, 1.0]]
    assert second == first
    assert fake.calls == 1


def test_model_wait_does_not_hold_cache_transaction_open(database) -> None:
    provider = CachedEmbeddingProvider(
        DatabaseWritingEmbeddingProvider(database),
        database,
    )

    assert provider.embed(["adapt"]) == [[5.0, 1.0]]

    with database.session() as session:
        assert session.scalar(select(func.count(EmbeddingCache.id))) == 2


def test_concurrent_embedding_cache_writes_converge(database) -> None:
    provider = CachedEmbeddingProvider(
        BarrierEmbeddingProvider(Barrier(2)),
        database,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: provider.embed(["adapt"]), range(2)))

    assert results == [[[5.0, 1.0]], [[5.0, 1.0]]]
    with database.session() as session:
        assert session.scalar(select(func.count(EmbeddingCache.id))) == 1
