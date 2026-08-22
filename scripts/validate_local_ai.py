"""Run repeatable end-to-end checks against the configured local AI models."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.ai.factory import create_embedding_provider, create_llm_provider
from app.bootstrap import initialize_database
from app.config import settings
from app.db.models import EmbeddingCache
from app.services.ai_service import AIService
from app.services.analysis_service import AnalysisService
from scripts.create_demo_data import create_demo_data


def _embedding_cache_count(database) -> int:
    with database.session() as session:
        return int(session.scalar(select(func.count(EmbeddingCache.id))) or 0)


def validate_local_ai() -> dict[str, object]:
    """Validate both providers and the services that consume them."""

    create_demo_data()
    database = initialize_database()
    try:
        embedding_provider = create_embedding_provider(settings, database)
        probe_texts = [
            "adapt: 适应；改编",
            "adopt: 采用；收养",
        ]
        cache_before = _embedding_cache_count(database)
        embedding_started = perf_counter()
        first_vectors = embedding_provider.embed(probe_texts)
        embedding_seconds = perf_counter() - embedding_started
        cache_after_first = _embedding_cache_count(database)
        second_vectors = embedding_provider.embed(probe_texts)
        cache_after_second = _embedding_cache_count(database)

        if len(first_vectors) != len(probe_texts) or not first_vectors[0]:
            raise RuntimeError("Embedding provider returned incomplete vectors")
        if any(len(vector) != len(first_vectors[0]) for vector in first_vectors):
            raise RuntimeError("Embedding vectors have inconsistent dimensions")
        if first_vectors != second_vectors:
            raise RuntimeError("Embedding cache returned different vectors")
        if cache_after_second != cache_after_first:
            raise RuntimeError("Repeated embedding call unexpectedly grew the cache")

        analysis_service = AnalysisService(database, embedding_provider)
        graph_started = perf_counter()
        graph = analysis_service.rebuild_confusion_graph()
        graph_seconds = perf_counter() - graph_started
        if not graph.embedding_available:
            raise RuntimeError("Graph rebuild degraded without embeddings")
        clusters = analysis_service.get_clusters()
        if not clusters:
            raise RuntimeError("Demo data produced no confusion clusters")

        llm_provider = create_llm_provider(settings)
        ai_service = AIService(database, llm_provider)
        chat_started = perf_counter()
        answer = ai_service.ask("economic 和 economical 有什么区别？")
        chat_seconds = perf_counter() - chat_started
        if answer.degraded or not answer.text.strip():
            raise RuntimeError(f"Chat validation degraded: {answer.text}")

        analysis_started = perf_counter()
        first_analysis = ai_service.analyze_cluster(clusters[0])
        analysis_seconds = perf_counter() - analysis_started
        if first_analysis.degraded:
            raise RuntimeError(
                "Structured cluster analysis degraded: "
                f"{first_analysis.analysis.confusion_reason}"
            )
        second_analysis = ai_service.analyze_cluster(clusters[0])
        if not second_analysis.cached:
            raise RuntimeError("Second cluster analysis did not hit the AI cache")

        return {
            "chat": {
                "model": answer.model,
                "seconds": round(chat_seconds, 3),
                "preview": answer.text.strip().replace("\n", " ")[:160],
            },
            "embedding": {
                "model": embedding_provider.model,
                "vectors": len(first_vectors),
                "dimension": len(first_vectors[0]),
                "seconds": round(embedding_seconds, 3),
                "cache_rows_before": cache_before,
                "cache_rows_after_first": cache_after_first,
                "cache_rows_after_second": cache_after_second,
            },
            "graph": {
                "candidates": graph.candidate_count,
                "edges": graph.edge_count,
                "clusters": graph.cluster_count,
                "embedding_available": graph.embedding_available,
                "seconds": round(graph_seconds, 3),
            },
            "structured_analysis": {
                "model": first_analysis.model,
                "first_cached": first_analysis.cached,
                "second_cached": second_analysis.cached,
                "seconds": round(analysis_seconds, 3),
                "words": list(clusters[0].words),
            },
        }
    finally:
        database.dispose()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(validate_local_ai(), ensure_ascii=False, indent=2))
