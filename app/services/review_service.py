"""Transactional review queue and submission operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.db.database import Database
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.db.repositories import LearningStateRepository, ReviewLogRepository
from app.domain.fsrs_scheduler import Rating, ReviewScheduleResult, schedule_review
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


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    review_log_id: int
    word_id: int
    rating: Rating
    is_correct: bool
    schedule: ReviewScheduleResult


class ReviewService:
    def __init__(
        self, database: Database, study_level: WordLevel | str | None = None
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None

    def get_due_words(self, limit: int = 30, now: datetime | None = None) -> list[ReviewItem]:
        checked_at = ensure_utc(now or utc_now())
        safe_limit = max(1, min(limit, 200))
        with self.database.session() as session:
            states = session.scalars(
                LearningStateRepository(session)
                .due_query(checked_at, self.study_level)
                .limit(safe_limit)
            ).all()
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
                )
                for state in states
            ]

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
