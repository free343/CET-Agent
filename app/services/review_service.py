"""Transactional review queue and submission operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.db.database import Database
from app.db.models import (
    LearningState,
    MasteredWord,
    ReviewLog,
    Word,
    WordAcquisitionState,
    WordLevel,
)
from app.db.repositories import LearningStateRepository, ReviewLogRepository
from app.domain.fsrs_scheduler import Rating, ReviewScheduleResult, schedule_review
from app.services.review_item_view import (
    ReviewItem,
    build_review_items,
)
from app.services.study_eligibility import effective_proficiency, is_not_mastered
from app.utils.datetime_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    review_log_id: int
    word_id: int
    rating: Rating
    is_correct: bool
    schedule: ReviewScheduleResult


@dataclass(frozen=True, slots=True)
class ReviewUndoResult:
    review_log_id: int
    word_id: int


@dataclass(frozen=True, slots=True)
class ExtraStudyResult:
    unlocked_count: int
    remaining_count: int
    due_count: int


class ReviewService:
    def __init__(
        self,
        database: Database,
        study_level: WordLevel | str | None = None,
        *,
        extra_study_limit: int = 5,
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None
        if not 1 <= int(extra_study_limit) <= 50:
            raise ValueError("extra_study_limit must be between 1 and 50")
        self.extra_study_limit = int(extra_study_limit)

    def get_due_words(
        self, limit: int = 30, now: datetime | None = None
    ) -> list[ReviewItem]:
        """Return the legacy union queue used by compatibility callers."""
        return self._get_due_words(limit, now)

    def get_new_words(
        self, limit: int = 30, now: datetime | None = None
    ) -> list[ReviewItem]:
        """Return released cards whose acquisition proficiency is below 3."""
        return self._get_due_words(
            limit,
            now,
            effective_proficiency() < 3,
        )

    def get_due_review_words(
        self, limit: int = 30, now: datetime | None = None
    ) -> list[ReviewItem]:
        """Return acquired cards whose formal review time has arrived."""
        return self._get_due_words(
            limit,
            now,
            effective_proficiency() == 3,
        )

    def _get_due_words(
        self,
        limit: int,
        now: datetime | None,
        *conditions: ColumnElement[bool],
    ) -> list[ReviewItem]:
        checked_at = ensure_utc(now or utc_now())
        safe_limit = max(1, min(limit, 200))
        with self.database.session() as session:
            states = session.scalars(
                LearningStateRepository(session)
                .due_query(checked_at, self.study_level)
                .where(is_not_mastered(), *conditions)
                .limit(safe_limit)
            ).all()
            return build_review_items(session, states)

    def get_words_by_ids(self, word_ids: list[int]) -> list[ReviewItem]:
        """Build review-card projections while preserving caller order."""
        ordered_ids = list(dict.fromkeys(int(word_id) for word_id in word_ids))[:200]
        if not ordered_ids:
            return []
        with self.database.session() as session:
            statement = (
                select(LearningState)
                .join(Word, LearningState.word_id == Word.id)
                .options(joinedload(LearningState.word))
                .where(LearningState.word_id.in_(ordered_ids))
                .where(is_not_mastered())
            )
            if self.study_level is not None:
                statement = statement.where(Word.level == self.study_level)
            states = list(session.scalars(statement))
            state_by_word_id = {state.word_id: state for state in states}
            ordered_states = [
                state_by_word_id[word_id]
                for word_id in ordered_ids
                if word_id in state_by_word_id
            ]
            return build_review_items(session, ordered_states)

    def due_count(self, now: datetime | None = None) -> int:
        """Count the legacy union queue used by compatibility callers."""
        return self._due_count(now)

    def new_count(self, now: datetime | None = None) -> int:
        return self._due_count(
            now,
            effective_proficiency() < 3,
        )

    def due_review_count(self, now: datetime | None = None) -> int:
        return self._due_count(
            now,
            effective_proficiency() == 3,
        )

    def _due_count(
        self,
        now: datetime | None,
        *conditions: ColumnElement[bool],
    ) -> int:
        checked_at = ensure_utc(now or utc_now())
        with self.database.session() as session:
            return int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        LearningState.next_review_at <= checked_at,
                        is_not_mastered(),
                        *conditions,
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
        limit: int | None = None,
        now: datetime | None = None,
    ) -> ExtraStudyResult:
        """Make a small explicit pack of untouched future cards due now."""

        if self.study_level is None:
            raise ValueError("Extra study requires a selected CET level")
        requested_limit = self.extra_study_limit if limit is None else int(limit)
        if requested_limit <= 0:
            raise ValueError("Extra study limit must be positive")
        checked_at = ensure_utc(now or utc_now())
        safe_limit = min(requested_limit, 50)
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            due_count = int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        Word.level == self.study_level,
                        LearningState.next_review_at <= checked_at,
                        effective_proficiency() < 3,
                        is_not_mastered(),
                    )
                )
                or 0
            )
            eligible = (
                Word.level == self.study_level,
                LearningState.next_review_at > checked_at,
                effective_proficiency() < 3,
                is_not_mastered(),
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
            if session.get(MasteredWord, word_id) is not None:
                raise ValueError("A mastered word cannot receive formal reviews")
            acquisition = session.get(WordAcquisitionState, word_id)
            if acquisition is not None and acquisition.proficiency_level < 3:
                raise ValueError("Word acquisition must be completed before review")
            if state.last_review_at is not None and review_time <= ensure_utc(
                state.last_review_at
            ):
                raise ValueError("Review time must be later than the previous review")

            previous_stability = state.stability
            previous_difficulty = state.difficulty
            previous_last_review_at = state.last_review_at
            previous_next_review_at = state.next_review_at
            previous_fsrs_state = state.fsrs_state
            previous_fsrs_step = state.fsrs_step
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
                    previous_last_review_at=previous_last_review_at,
                    previous_next_review_at=previous_next_review_at,
                    previous_fsrs_state=previous_fsrs_state,
                    previous_fsrs_step=previous_fsrs_step,
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

    def undo_review(self, review_log_id: int) -> ReviewUndoResult:
        """Atomically remove the latest review and restore its exact card state."""
        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            review = session.scalar(
                select(ReviewLog).where(ReviewLog.id == review_log_id).with_for_update()
            )
            if review is None:
                raise LookupError(f"No review log for id={review_log_id}")
            state = LearningStateRepository(session).get_for_update(review.word_id)
            if state is None:
                raise LookupError(f"No learning state for word_id={review.word_id}")
            if (
                review.previous_next_review_at is None
                or review.previous_fsrs_state is None
            ):
                raise ValueError("Review does not contain an undo snapshot")
            if state.last_review_at is None or ensure_utc(
                state.last_review_at
            ) != ensure_utc(review.reviewed_at):
                raise ValueError("Only the latest review for a card can be undone")

            self._validate_undo_counters(state, review)
            state.difficulty = review.previous_difficulty
            state.stability = review.previous_stability
            state.last_review_at = review.previous_last_review_at
            state.next_review_at = review.previous_next_review_at
            state.fsrs_state = review.previous_fsrs_state
            state.fsrs_step = review.previous_fsrs_step
            state.review_count -= 1
            if review.is_correct:
                state.correct_count -= 1
            else:
                state.error_count -= 1
                if review.rating == int(Rating.AGAIN):
                    state.lapse_count -= 1
            word_id = review.word_id
            session.delete(review)

        logger.info(
            "Review undone review_log_id=%s word_id=%s",
            review_log_id,
            word_id,
        )
        return ReviewUndoResult(review_log_id=review_log_id, word_id=word_id)

    @staticmethod
    def _validate_undo_counters(state: LearningState, review: ReviewLog) -> None:
        if state.review_count < 1:
            raise ValueError("Review counters are inconsistent; undo was cancelled")
        if review.is_correct and state.correct_count < 1:
            raise ValueError("Review counters are inconsistent; undo was cancelled")
        if not review.is_correct and state.error_count < 1:
            raise ValueError("Review counters are inconsistent; undo was cancelled")
        if review.rating == int(Rating.AGAIN) and state.lapse_count < 1:
            raise ValueError("Review counters are inconsistent; undo was cancelled")
