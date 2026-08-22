"""Focused persistence operations used by application services."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    AIAnalysis,
    ConfusionEdge,
    EmbeddingCache,
    LearningState,
    ReviewLog,
    Word,
)


class WordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, word_id: int) -> Word | None:
        return self.session.get(Word, word_id)

    def get_by_text(self, text: str) -> Word | None:
        return self.session.scalar(select(Word).where(Word.word == text.lower()))

    def all(self) -> list[Word]:
        return list(self.session.scalars(select(Word).order_by(Word.frequency.desc())))

    def add(self, word: Word) -> Word:
        self.session.add(word)
        self.session.flush()
        return word


class LearningStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_update(self, word_id: int) -> LearningState | None:
        statement = select(LearningState).where(LearningState.word_id == word_id).with_for_update()
        return self.session.scalar(statement)

    def due_query(self, now: datetime) -> Select[tuple[LearningState]]:
        return (
            select(LearningState)
            .options(joinedload(LearningState.word))
            .where(LearningState.next_review_at <= now)
            .order_by(
                LearningState.next_review_at.asc(),
                LearningState.lapse_count.desc(),
                LearningState.error_count.desc(),
            )
        )


class ReviewLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, review: ReviewLog) -> ReviewLog:
        self.session.add(review)
        self.session.flush()
        return review

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(ReviewLog.id))) or 0)


class ConfusionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def all_edges(self, threshold: float = 0.0) -> list[ConfusionEdge]:
        statement = (
            select(ConfusionEdge)
            .options(joinedload(ConfusionEdge.word_a), joinedload(ConfusionEdge.word_b))
            .where(ConfusionEdge.total_score >= threshold)
            .order_by(ConfusionEdge.total_score.desc())
        )
        return list(self.session.scalars(statement))


class AIAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_cached(self, analysis_type: str, content_hash: str) -> AIAnalysis | None:
        return self.session.scalar(
            select(AIAnalysis).where(
                AIAnalysis.analysis_type == analysis_type,
                AIAnalysis.content_hash == content_hash,
            )
        )

    def add(self, analysis: AIAnalysis) -> AIAnalysis:
        self.session.add(analysis)
        self.session.flush()
        return analysis


class EmbeddingCacheRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_vector(self, model: str, content_hash: str) -> list[float] | None:
        row = self.session.scalar(
            select(EmbeddingCache).where(
                EmbeddingCache.model == model,
                EmbeddingCache.content_hash == content_hash,
            )
        )
        return json.loads(row.vector_json) if row else None
