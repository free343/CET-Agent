"""Measure the deterministic worst-case 100-candidate graph rebuild."""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.embedding_provider import EmbeddingProvider
from app.config import Settings
from app.db.database import Database
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.services.analysis_service import AnalysisService, GraphBuildResult
from app.utils.datetime_utils import UTC

BENCHMARK_NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
DEFAULT_CANDIDATES = 100
DEFAULT_ITERATIONS = 3


class IdenticalEmbeddingProvider(EmbeddingProvider):
    """Force a dense graph so persistence cost is included in the baseline."""

    model = "benchmark-identical"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _text in texts]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    candidate_count: int
    edge_count: int
    cluster_count: int
    durations: tuple[float, ...]

    @property
    def median_seconds(self) -> float:
        return statistics.median(self.durations)


def populate_dense_case(
    database: Database,
    *,
    candidate_count: int = DEFAULT_CANDIDATES,
    now: datetime = BENCHMARK_NOW,
) -> None:
    if not 2 <= candidate_count <= 100:
        raise ValueError("candidate_count must be between 2 and 100")
    with database.session() as session:
        for index in range(candidate_count):
            word = Word(
                word=f"term{index:03d}",
                meaning=f"基准词条 {index}",
                level=WordLevel.CET4,
                frequency=candidate_count - index,
            )
            word.learning_state = LearningState(next_review_at=now)
            session.add(word)
            session.flush()
            for days_ago in (1, 2):
                session.add(_error_log(word.id, now - timedelta(days=days_ago)))


def run_benchmark(
    database: Database,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    candidate_count: int = DEFAULT_CANDIDATES,
) -> BenchmarkResult:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    app_settings = Settings(
        confusion_threshold=0.65,
        max_confusion_candidates=candidate_count,
    )
    service = AnalysisService(
        database,
        IdenticalEmbeddingProvider(),
        app_settings,
    )
    durations: list[float] = []
    latest: GraphBuildResult | None = None
    for _iteration in range(iterations):
        started = perf_counter()
        latest = service.rebuild_confusion_graph(BENCHMARK_NOW)
        durations.append(perf_counter() - started)

    assert latest is not None
    expected_edges = candidate_count * (candidate_count - 1) // 2
    if latest.candidate_count != candidate_count:
        raise RuntimeError("Benchmark did not select the requested candidate count")
    if latest.edge_count != expected_edges or latest.cluster_count != 1:
        raise RuntimeError("Benchmark did not produce the expected dense graph")
    return BenchmarkResult(
        candidate_count=latest.candidate_count,
        edge_count=latest.edge_count,
        cluster_count=latest.cluster_count,
        durations=tuple(durations),
    )


def _error_log(word_id: int, reviewed_at: datetime) -> ReviewLog:
    return ReviewLog(
        word_id=word_id,
        reviewed_at=reviewed_at,
        rating=1,
        is_correct=False,
        response_time_ms=1_000,
        question_type="scale_benchmark",
        user_answer="",
        previous_stability=1.0,
        new_stability=0.4,
        previous_difficulty=5.0,
        new_difficulty=5.9,
        scheduled_days=10 / (24 * 60),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument(
        "--max-median-seconds",
        type=float,
        default=5.0,
        help="Return a failure status when the median rebuild exceeds this budget.",
    )
    arguments = parser.parse_args()
    if arguments.max_median_seconds <= 0:
        parser.error("--max-median-seconds must be positive")

    with tempfile.TemporaryDirectory(prefix="cet-agent-graph-benchmark-") as name:
        database = Database(f"sqlite:///{(Path(name) / 'benchmark.db').as_posix()}")
        try:
            database.create_tables()
            populate_dense_case(
                database,
                candidate_count=arguments.candidates,
            )
            result = run_benchmark(
                database,
                iterations=arguments.iterations,
                candidate_count=arguments.candidates,
            )
        finally:
            database.dispose()

    durations = ", ".join(f"{value:.3f}s" for value in result.durations)
    print(
        f"candidates={result.candidate_count} edges={result.edge_count} "
        f"clusters={result.cluster_count} runs=[{durations}] "
        f"median={result.median_seconds:.3f}s"
    )
    if result.median_seconds > arguments.max_median_seconds:
        print(
            f"Median exceeded {arguments.max_median_seconds:.3f}s budget.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
