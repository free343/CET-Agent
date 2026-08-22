"""Transactional review queue and submission operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import Database
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.db.repositories import LearningStateRepository, ReviewLogRepository
from app.domain.fsrs_scheduler import Rating, ReviewScheduleResult, schedule_review
from app.domain.meaning_quiz import (
    MeaningCandidate,
    MeaningOption,
    build_meaning_options,
)
from app.utils.datetime_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    word_id: int
    word: str
    phonetic: str
    meaning: str
    example: str
    level: WordLevel
    lapse_count: int
    error_count: int
    next_review_at: datetime
    meaning_options: tuple[MeaningOption, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    review_log_id: int
    word_id: int
    rating: Rating
    is_correct: bool
    schedule: ReviewScheduleResult


@dataclass(frozen=True, slots=True)
class ExtraStudyResult:
    unlocked_count: int
    remaining_count: int
    due_count: int


class ReviewService:
    def __init__(
        self, database: Database, study_level: WordLevel | str | None = None
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None

    def get_due_words(
        self, limit: int = 30, now: datetime | None = None
    ) -> list[ReviewItem]:
        checked_at = ensure_utc(now or utc_now())
        safe_limit = max(1, min(limit, 200))
        with self.database.session() as session:
            states = session.scalars(
                LearningStateRepository(session)
                .due_query(checked_at, self.study_level)
                .limit(safe_limit)
            ).all()
            candidates_by_level = self._meaning_candidates_by_level(session, states)
            return [
                ReviewItem(
                    word_id=state.word.id,
                    word=state.word.word,
                    phonetic=state.word.phonetic,
                    meaning=state.word.meaning,
                    example=state.word.example,
                    level=state.word.level,
                    lapse_count=state.lapse_count,
                    error_count=state.error_count,
                    next_review_at=state.next_review_at,
                    meaning_options=build_meaning_options(
                        MeaningCandidate(
                            word_id=state.word.id,
                            meaning=state.word.meaning,
                            frequency=state.word.frequency,
                            review_count=state.review_count,
                        ),
                        candidates_by_level.get(state.word.level, []),
                    ),
                )
                for state in states
            ]

    @staticmethod
    def _meaning_candidates_by_level(
        session: Session,
        states: list[LearningState],
    ) -> dict[WordLevel, list[MeaningCandidate]]:
        levels = {state.word.level for state in states}
        if not levels:
            return {}
        candidates_by_level: dict[WordLevel, list[MeaningCandidate]] = {
            level: [] for level in levels
        }
        rows = session.execute(
            select(
                Word.id,
                Word.meaning,
                Word.frequency,
                Word.level,
                LearningState.review_count,
            )
            .join(LearningState, LearningState.word_id == Word.id)
            .where(Word.level.in_(levels))
        ).all()
        for row in rows:
            candidates_by_level[row.level].append(
                MeaningCandidate(
                    word_id=row.id,
                    meaning=row.meaning,
                    frequency=row.frequency,
                    review_count=row.review_count,
                )
            )
        return candidates_by_level

    def due_count(self, now: datetime | None = None) -> int:
        checked_at = ensure_utc(now or utc_now())
        with self.database.session() as session:
            return int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        LearningState.next_review_at <= checked_at,
                        *(
                            (Word.level == self.study_level,)
                            if self.study_level is not None
                            else ()
                        ),
                    )
                )
                or 0
            )

    def unlock_extra_words(
        self,
        limit: int = 5,
        now: datetime | None = None,
    ) -> ExtraStudyResult:
        """Make a small explicit pack of untouched future cards due now."""

        if self.study_level is None:
            raise ValueError("Extra study requires a selected CET level")
        if limit <= 0:
            raise ValueError("Extra study limit must be positive")
        checked_at = ensure_utc(now or utc_now())
        safe_limit = min(int(limit), 50)
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            due_count = int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        Word.level == self.study_level,
                        LearningState.next_review_at <= checked_at,
                    )
                )
                or 0
            )
            has_review = (
                select(ReviewLog.id)
                .where(ReviewLog.word_id == LearningState.word_id)
                .exists()
            )
            eligible = (
                Word.level == self.study_level,
                LearningState.next_review_at > checked_at,
                LearningState.review_count == 0,
                LearningState.last_review_at.is_(None),
                ~has_review,
            )
            total = int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(*eligible)
                )
                or 0
            )
            states: list[LearningState] = []
            if due_count == 0:
                states = session.scalars(
                    select(LearningState)
                    .join(Word, LearningState.word_id == Word.id)
                    .where(*eligible)
                    .order_by(
                        LearningState.next_review_at.asc(),
                        Word.frequency.desc(),
                        Word.id.asc(),
                    )
                    .limit(safe_limit)
                    .with_for_update()
                ).all()
            for state in states:
                state.next_review_at = checked_at
            unlocked_count = len(states)
        logger.info(
            "Extra study unlocked level=%s count=%s remaining=%s due=%s",
            self.study_level.value,
            unlocked_count,
            max(0, total - unlocked_count),
            due_count,
        )
        return ExtraStudyResult(
            unlocked_count=unlocked_count,
            remaining_count=max(0, total - unlocked_count),
            due_count=due_count,
        )

    def submit_review(
        self,
        word_id: int,
        rating: Rating | int,
        response_time_ms: int,
        *,
        question_type: str = "meaning_recall",
        user_answer: str = "",
        reviewed_at: datetime | None = None,
    ) -> ReviewSubmission:
        selected_rating = Rating(rating)
        review_time = ensure_utc(reviewed_at or utc_now())
        safe_response_time = max(0, int(response_time_ms))

        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            state = LearningStateRepository(session).get_for_update(word_id)
            if state is None:
                raise LookupError(f"No learning state for word_id={word_id}")
            if state.last_review_at is not None and review_time <= ensure_utc(
                state.last_review_at
            ):
                raise ValueError("Review time must be later than the previous review")

            previous_stability = state.stability
            previous_difficulty = state.difficulty
            schedule = schedule_review(state, selected_rating, review_time)
            is_correct = selected_rating is not Rating.AGAIN

            state.difficulty = schedule.new_difficulty
            state.stability = schedule.new_stability
            state.last_review_at = review_time
            state.next_review_at = schedule.next_review_at
            state.fsrs_state = schedule.fsrs_state
            state.fsrs_step = schedule.fsrs_step
            state.review_count += 1
            if is_correct:
                state.correct_count += 1
            else:
                state.error_count += 1
                state.lapse_count += 1

            review = ReviewLogRepository(session).add(
                ReviewLog(
                    word_id=word_id,
                    reviewed_at=review_time,
                    rating=int(selected_rating),
                    is_correct=is_correct,
                    response_time_ms=safe_response_time,
                    question_type=question_type[:50] or "meaning_recall",
                    user_answer=user_answer,
                    previous_stability=previous_stability,
                    new_stability=schedule.new_stability,
                    previous_difficulty=previous_difficulty,
                    new_difficulty=schedule.new_difficulty,
                    scheduled_days=schedule.scheduled_days,
                )
            )
            submission = ReviewSubmission(
                review_log_id=review.id,
                word_id=word_id,
                rating=selected_rating,
                is_correct=is_correct,
                schedule=schedule,
            )

        logger.info(
            "Review submitted word_id=%s rating=%s response_ms=%s",
            word_id,
            selected_rating.name,
            safe_response_time,
        )
        return submission
