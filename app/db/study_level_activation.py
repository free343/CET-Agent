"""Idempotent activation and release rebasing for independently staged levels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    LearningState,
    ReviewLog,
    StudyLevelActivation,
    Word,
    WordLevel,
)
from app.db.seed import VocabularySeedRow
from app.utils.datetime_utils import ensure_utc, utc_now


@dataclass(frozen=True, slots=True)
class LevelActivationResult:
    level: WordLevel
    activated_at: datetime
    newly_activated: bool
    schedule_rebased: bool
    rebased_word_count: int


def activate_study_level(
    session: Session,
    level: WordLevel | str,
    open_vocabulary: Sequence[VocabularySeedRow],
    *,
    activated_at: datetime | None = None,
) -> LevelActivationResult:
    """Activate a level once without moving cards that have learning history.

    A legacy level with any ReviewLog is adopted as already active. Otherwise,
    untouched open-vocabulary cards are staged from the first activation time.
    Curated/demo words are absent from ``open_vocabulary`` and remain immediate.
    """
    selected_level = WordLevel(level)
    existing = session.get(StudyLevelActivation, selected_level)
    if existing is not None:
        return LevelActivationResult(
            level=selected_level,
            activated_at=existing.activated_at,
            newly_activated=False,
            schedule_rebased=existing.schedule_rebased,
            rebased_word_count=0,
        )

    release_delays = {
        row.word: row.initial_delay_days
        for row in open_vocabulary
        if row.level is selected_level
    }
    earliest_review = session.scalar(
        select(func.min(ReviewLog.reviewed_at))
        .join(Word, ReviewLog.word_id == Word.id)
        .where(
            Word.level == selected_level,
            Word.word.in_(release_delays),
        )
    )
    if earliest_review is not None:
        activation = StudyLevelActivation(
            level=selected_level,
            activated_at=earliest_review,
            schedule_rebased=False,
            rebased_word_count=0,
        )
        session.add(activation)
        session.flush()
        return LevelActivationResult(
            level=selected_level,
            activated_at=earliest_review,
            newly_activated=True,
            schedule_rebased=False,
            rebased_word_count=0,
        )

    activation_time = ensure_utc(activated_at or utc_now())
    rebased = 0
    if release_delays:
        reviewed_word_exists = (
            select(ReviewLog.id)
            .where(ReviewLog.word_id == LearningState.word_id)
            .exists()
        )
        rows = session.execute(
            select(LearningState, Word.word)
            .join(Word, LearningState.word_id == Word.id)
            .where(
                Word.level == selected_level,
                Word.word.in_(release_delays),
                LearningState.review_count == 0,
                LearningState.last_review_at.is_(None),
                ~reviewed_word_exists,
            )
        ).all()
        for state, word in rows:
            state.next_review_at = activation_time + timedelta(
                days=release_delays[word]
            )
            rebased += 1

    session.add(
        StudyLevelActivation(
            level=selected_level,
            activated_at=activation_time,
            schedule_rebased=True,
            rebased_word_count=rebased,
        )
    )
    session.flush()
    return LevelActivationResult(
        level=selected_level,
        activated_at=activation_time,
        newly_activated=True,
        schedule_rebased=True,
        rebased_word_count=rebased,
    )
