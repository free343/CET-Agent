"""Build and query the personal vocabulary confusion graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload

from app.ai.embedding_provider import EmbeddingProvider, EmbeddingUnavailableError
from app.config import Settings, settings
from app.db.database import Database
from app.db.models import ConfusionEdge, RelationType, ReviewLog, Word
from app.domain.clustering import cluster_word_ids, select_core_word_ids
from app.domain.confusion_graph import (
    GraphEdge,
    RelationScores,
    RelationWeights,
    score_relation,
)
from app.domain.similarity import (
    coerror_score,
    cosine_similarity,
    spelling_similarity,
    temporal_score,
)
from app.utils.datetime_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CandidateWord:
    word_id: int
    word: str
    meaning: str
    error_times: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    candidate_count: int
    edge_count: int
    cluster_count: int
    embedding_available: bool


@dataclass(frozen=True, slots=True)
class EdgeSummary:
    word_a: str
    word_b: str
    total_score: float
    relation_type: RelationType


@dataclass(frozen=True, slots=True)
class ConfusionCluster:
    cluster_number: int
    word_ids: tuple[int, ...]
    words: tuple[str, ...]
    error_counts: tuple[int, ...]
    relation_type: RelationType
    average_score: float


class AnalysisService:
    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self.database = database
        self.embedding_provider = embedding_provider
        self.settings = app_settings

    def _candidates(self, now: datetime) -> list[CandidateWord]:
        cutoff = now - timedelta(days=self.settings.confusion_window_days)
        with self.database.session() as session:
            rows = session.execute(
                select(Word.id, Word.word, Word.meaning, func.count(ReviewLog.id).label("errors"))
                .join(ReviewLog, ReviewLog.word_id == Word.id)
                .where(
                    ReviewLog.reviewed_at >= cutoff,
                    ReviewLog.is_correct.is_(False),
                )
                .group_by(Word.id)
                .having(func.count(ReviewLog.id) >= 2)
                .order_by(func.count(ReviewLog.id).desc(), Word.id.asc())
                .limit(self.settings.max_confusion_candidates)
            ).all()
            if not rows:
                return []
            candidate_ids = [row.id for row in rows]
            errors_by_word: dict[int, list[datetime]] = {word_id: [] for word_id in candidate_ids}
            for word_id, reviewed_at in session.execute(
                select(ReviewLog.word_id, ReviewLog.reviewed_at).where(
                    ReviewLog.word_id.in_(candidate_ids),
                    ReviewLog.reviewed_at >= cutoff,
                    ReviewLog.is_correct.is_(False),
                )
            ):
                errors_by_word[word_id].append(reviewed_at)
            return [
                CandidateWord(
                    word_id=row.id,
                    word=row.word,
                    meaning=row.meaning,
                    error_times=tuple(errors_by_word[row.id]),
                )
                for row in rows
            ]

    def rebuild_confusion_graph(self, now: datetime | None = None) -> GraphBuildResult:
        checked_at = ensure_utc(now or utc_now())
        candidates = self._candidates(checked_at)
        vectors: dict[int, list[float]] = {}
        embedding_available = self.embedding_provider is not None
        if candidates and self.embedding_provider is not None:
            try:
                embedded = self.embedding_provider.embed(
                    [f"{item.word}: {item.meaning}" for item in candidates]
                )
                vectors = {
                    item.word_id: vector
                    for item, vector in zip(candidates, embedded, strict=True)
                }
            except (EmbeddingUnavailableError, ValueError) as exc:
                embedding_available = False
                logger.warning("Graph build continuing without semantic vectors: %s", exc)

        weights = RelationWeights(
            semantic=self.settings.semantic_weight,
            spelling=self.settings.spelling_weight,
            coerror=self.settings.coerror_weight,
            temporal=self.settings.temporal_weight,
        )
        computed_edges: list[tuple[CandidateWord, CandidateWord, RelationScores]] = []
        for first, second in combinations(candidates, 2):
            semantic = 0.0
            if first.word_id in vectors and second.word_id in vectors:
                semantic = cosine_similarity(vectors[first.word_id], vectors[second.word_id])
            scores = score_relation(
                semantic=semantic,
                spelling=spelling_similarity(first.word, second.word),
                coerror=coerror_score(
                    first.error_times,
                    second.error_times,
                    timedelta(hours=self.settings.coerror_window_hours),
                ),
                temporal=temporal_score(
                    first.error_times,
                    second.error_times,
                    timedelta(hours=self.settings.coerror_window_hours),
                ),
                weights=weights,
            )
            if scores.total >= self.settings.confusion_threshold:
                computed_edges.append((first, second, scores))

        with self.database.session() as session:
            session.execute(delete(ConfusionEdge))
            for first, second, scores in computed_edges:
                word_a_id, word_b_id = sorted((first.word_id, second.word_id))
                session.add(
                    ConfusionEdge(
                        word_a_id=word_a_id,
                        word_b_id=word_b_id,
                        semantic_score=scores.semantic,
                        spelling_score=scores.spelling,
                        coerror_score=scores.coerror,
                        temporal_score=scores.temporal,
                        total_score=scores.total,
                        relation_type=scores.relation_type,
                    )
                )

        graph_edges = [
            GraphEdge(first.word_id, second.word_id, scores.total)
            for first, second, scores in computed_edges
        ]
        clusters = cluster_word_ids(graph_edges, self.settings.confusion_threshold)
        logger.info(
            "Confusion graph rebuilt candidates=%s edges=%s clusters=%s",
            len(candidates),
            len(computed_edges),
            len(clusters),
        )
        return GraphBuildResult(
            candidate_count=len(candidates),
            edge_count=len(computed_edges),
            cluster_count=len(clusters),
            embedding_available=embedding_available,
        )

    def get_edges(self) -> list[EdgeSummary]:
        with self.database.session() as session:
            edges = session.scalars(
                select(ConfusionEdge)
                .options(joinedload(ConfusionEdge.word_a), joinedload(ConfusionEdge.word_b))
                .where(ConfusionEdge.total_score >= self.settings.confusion_threshold)
                .order_by(ConfusionEdge.total_score.desc())
            ).all()
            return [
                EdgeSummary(
                    word_a=edge.word_a.word,
                    word_b=edge.word_b.word,
                    total_score=edge.total_score,
                    relation_type=edge.relation_type,
                )
                for edge in edges
            ]

    def get_clusters(self, now: datetime | None = None) -> list[ConfusionCluster]:
        checked_at = ensure_utc(now or utc_now())
        cutoff = checked_at - timedelta(days=self.settings.confusion_window_days)
        with self.database.session() as session:
            edges = session.scalars(
                select(ConfusionEdge).where(
                    ConfusionEdge.total_score >= self.settings.confusion_threshold
                )
            ).all()
            graph_edges = [
                GraphEdge(edge.word_a_id, edge.word_b_id, edge.total_score) for edge in edges
            ]
            components = cluster_word_ids(graph_edges, self.settings.confusion_threshold)
            if not components:
                return []
            word_ids = {word_id for component in components for word_id in component}
            words = {
                word.id: word
                for word in session.scalars(select(Word).where(Word.id.in_(word_ids)))
            }
            error_counts = dict(
                session.execute(
                    select(ReviewLog.word_id, func.count(ReviewLog.id))
                    .where(
                        ReviewLog.word_id.in_(word_ids),
                        ReviewLog.is_correct.is_(False),
                        ReviewLog.reviewed_at >= cutoff,
                    )
                    .group_by(ReviewLog.word_id)
                ).tuples().all()
            )
            results: list[ConfusionCluster] = []
            for number, component in enumerate(components, start=1):
                core_ids = select_core_word_ids(component, graph_edges, 8)
                component_set = set(component)
                component_edges = [
                    edge
                    for edge in edges
                    if edge.word_a_id in component_set and edge.word_b_id in component_set
                ]
                relation_totals: dict[RelationType, float] = {}
                for edge in component_edges:
                    relation_totals[edge.relation_type] = (
                        relation_totals.get(edge.relation_type, 0.0) + edge.total_score
                    )
                relation = max(
                    relation_totals,
                    key=relation_totals.__getitem__,
                    default=RelationType.MIXED,
                )
                average = sum(edge.total_score for edge in component_edges) / max(
                    1, len(component_edges)
                )
                results.append(
                    ConfusionCluster(
                        cluster_number=number,
                        word_ids=tuple(core_ids),
                        words=tuple(words[word_id].word for word_id in core_ids),
                        error_counts=tuple(int(error_counts.get(word_id, 0)) for word_id in core_ids),
                        relation_type=relation,
                        average_score=average,
                    )
                )
            return results
