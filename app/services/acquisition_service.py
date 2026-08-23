"""Persistent 0-3 new-word acquisition before formal FSRS review."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.database import Database
from app.db.models import (
    AcquisitionAttempt,
    LearningState,
    MasteredWord,
    Word,
    WordAcquisitionState,
    WordLevel,
)
from app.domain.acquisition import (
    advance_proficiency,
    spelling_matches,
    task_for_level,
)
from app.services.review_item_view import ReviewItem
from app.services.review_service import ExtraStudyResult, ReviewService
from app.utils.datetime_utils import ensure_utc, utc_now

logger = logging.getLogger(__name__)

FIRST_FORMAL_REVIEW_DELAY = timedelta(days=1)
DEFAULT_ACQUISITION_GROUP_SIZE = 10


@dataclass(frozen=True, slots=True)
class AcquisitionSubmission:
    attempt_id: int
    word_id: int
    level_before: int
    level_after: int
    is_correct: bool
    self_confirmed: bool
    first_review_at: datetime | None
    next_item: ReviewItem | None = None

    @property
    def completed(self) -> bool:
        return self.level_after == 3


class AcquisitionService:
    """Own acquisition selection and atomic proficiency transitions."""

    def __init__(
        self,
        database: Database,
        study_level: WordLevel | str | None = None,
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None
        self.review_service = ReviewService(database, self.study_level)

    def get_group(
        self,
        limit: int = DEFAULT_ACQUISITION_GROUP_SIZE,
        now: datetime | None = None,
    ) -> list[ReviewItem]:
        safe_limit = max(1, min(int(limit), 50))
        return self.review_service.get_new_words(safe_limit, now)

    def remaining_count(self, now: datetime | None = None) -> int:
        return self.review_service.new_count(now)

    def get_item(self, word_id: int) -> ReviewItem | None:
        """Return the current projection after a persisted attempt."""

        items = self.review_service.get_words_by_ids([word_id])
        return items[0] if items else None

    def unlock_extra_words(
        self,
        limit: int = 5,
        now: datetime | None = None,
    ) -> ExtraStudyResult:
        return self.review_service.unlock_extra_words(limit, now)

    def record_attempt(
        self,
        word_id: int,
        *,
        expected_level: int,
        selected_word_id: int | None = None,
        spelling_answer: str = "",
        self_confirmed: bool = False,
        response_time_ms: int = 0,
        attempted_at: datetime | None = None,
    ) -> AcquisitionSubmission:
        if not 0 <= expected_level <= 2:
            raise ValueError("Expected acquisition level must be between 0 and 2")
        attempt_time = ensure_utc(attempted_at or utc_now())
        safe_response_time = max(0, int(response_time_ms))

        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            row = session.execute(
                select(Word, LearningState)
                .join(LearningState, LearningState.word_id == Word.id)
                .where(
                    Word.id == word_id,
                    *(
                        (Word.level == self.study_level,)
                        if self.study_level is not None
                        else ()
                    ),
                )
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise LookupError(f"No learning state for word_id={word_id}")
            word, learning_state = row
            if session.get(MasteredWord, word_id) is not None:
                raise ValueError("A mastered word cannot receive acquisition attempts")

            acquisition = session.get(WordAcquisitionState, word_id)
            if acquisition is None:
                fallback_level = (
                    3
                    if learning_state.review_count > 0
                    or learning_state.last_review_at is not None
                    else 0
                )
                acquisition = WordAcquisitionState(
                    word_id=word_id,
                    proficiency_level=fallback_level,
                    completed_at=(
                        learning_state.last_review_at if fallback_level == 3 else None
                    ),
                )
                session.add(acquisition)
                session.flush()
            if acquisition.proficiency_level != expected_level:
                raise ValueError("Acquisition state changed; reload the current group")

            selected_word: Word | None = None
            if expected_level in {0, 1}:
                if selected_word_id is None:
                    raise ValueError("This acquisition stage requires one choice")
                selected_word = session.get(Word, selected_word_id)
                if selected_word is None or selected_word.level != word.level:
                    raise ValueError("The selected choice is not valid for this word")
                is_correct = selected_word_id == word_id
                user_answer = selected_word.word
            else:
                if selected_word_id is not None:
                    raise ValueError("The spelling stage does not accept a choice id")
                if self_confirmed:
                    is_correct = True
                    user_answer = "[self-confirmed]"
                else:
                    user_answer = spelling_answer[:200]
                    is_correct = spelling_matches(spelling_answer, word.word)

            level_after = advance_proficiency(
                expected_level,
                is_correct=is_correct,
            )
            first_review_at: datetime | None = None
            acquisition.proficiency_level = level_after
            acquisition.updated_at = attempt_time
            if level_after == 3:
                acquisition.completed_at = attempt_time
                first_review_at = attempt_time + FIRST_FORMAL_REVIEW_DELAY
                learning_state.next_review_at = first_review_at
                learning_state.updated_at = attempt_time

            attempt = AcquisitionAttempt(
                word_id=word_id,
                attempted_at=attempt_time,
                level_before=expected_level,
                level_after=level_after,
                task_type=task_for_level(
                    expected_level,
                    self_confirmed=self_confirmed,
                ),
                is_correct=is_correct,
                self_confirmed=self_confirmed,
                response_time_ms=safe_response_time,
                user_answer=user_answer,
            )
            session.add(attempt)
            session.flush()
            result = AcquisitionSubmission(
                attempt_id=attempt.id,
                word_id=word_id,
                level_before=expected_level,
                level_after=level_after,
                is_correct=is_correct,
                self_confirmed=self_confirmed,
                first_review_at=first_review_at,
            )

        if result.level_after < 3:
            result = AcquisitionSubmission(
                attempt_id=result.attempt_id,
                word_id=result.word_id,
                level_before=result.level_before,
                level_after=result.level_after,
                is_correct=result.is_correct,
                self_confirmed=result.self_confirmed,
                first_review_at=result.first_review_at,
                next_item=self.get_item(word_id),
            )

        logger.info(
            "Acquisition attempt recorded word_id=%s level=%s->%s correct=%s",
            word_id,
            expected_level,
            level_after,
            is_correct,
        )
        return result
