"""Optional recall practice that is deliberately isolated from FSRS scheduling."""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

from sqlalchemy import func, select

from app.db.database import Database
from app.db.models import (
    FavoriteWord,
    LearningState,
    MasteredWord,
    PracticeLog,
    PracticeScope,
    ReviewLog,
    Word,
    WordLevel,
)
from app.services.review_service import ReviewItem, ReviewService
from app.services.study_eligibility import is_not_mastered
from app.utils.datetime_utils import UTC, ensure_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PracticeSubmission:
    practice_log_id: int
    word_id: int
    is_correct: bool
    scope: PracticeScope
    practiced_at: datetime


class PracticeService:
    """Select learned cards and store attempts without touching LearningState."""

    def __init__(
        self,
        database: Database,
        study_level: WordLevel | str | None = None,
        *,
        local_timezone: tzinfo | None = None,
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None
        self.local_timezone = local_timezone or utc_now().astimezone().tzinfo or UTC
        self.review_items = ReviewService(database, self.study_level)

    def get_words(
        self,
        scope: PracticeScope | str = PracticeScope.YESTERDAY,
        limit: int = 30,
        now: datetime | None = None,
        *,
        exclude_word_ids: Collection[int] = (),
    ) -> list[ReviewItem]:
        selected_scope = PracticeScope(scope)
        if selected_scope is PracticeScope.CONFUSION_CLUSTER:
            raise ValueError("Confusion-cluster practice requires explicit word IDs")
        checked_at = ensure_utc(now or utc_now())
        safe_limit = max(1, min(int(limit), 200))
        excluded_ids = tuple(
            dict.fromkeys(int(word_id) for word_id in exclude_word_ids)
        )[:10_000]
        common_conditions = [
            LearningState.review_count > 0,
            LearningState.last_review_at.is_not(None),
            LearningState.last_review_at <= checked_at,
            is_not_mastered(),
            *(
                (Word.level == self.study_level,)
                if self.study_level is not None
                else ()
            ),
        ]
        if excluded_ids:
            common_conditions.append(LearningState.word_id.not_in(excluded_ids))

        with self.database.session() as session:
            if selected_scope is PracticeScope.YESTERDAY:
                yesterday_start, today_start = self._yesterday_bounds(checked_at)
                rows = session.execute(
                    select(
                        LearningState.word_id,
                        func.max(ReviewLog.reviewed_at).label("latest_review_at"),
                    )
                    .join(Word, LearningState.word_id == Word.id)
                    .join(ReviewLog, ReviewLog.word_id == LearningState.word_id)
                    .where(
                        *common_conditions,
                        ReviewLog.reviewed_at >= yesterday_start,
                        ReviewLog.reviewed_at < today_start,
                        ReviewLog.reviewed_at <= checked_at,
                        ReviewLog.question_type != "demo_confusion",
                    )
                    .group_by(LearningState.word_id)
                    .order_by(
                        func.max(ReviewLog.reviewed_at).desc(),
                        LearningState.word_id.asc(),
                    )
                    .limit(safe_limit)
                ).all()
                word_ids = [int(row.word_id) for row in rows]
            else:
                statement = (
                    select(LearningState.word_id)
                    .join(Word, LearningState.word_id == Word.id)
                    .where(*common_conditions)
                )
                if selected_scope is PracticeScope.RECENT:
                    statement = statement.order_by(
                        LearningState.last_review_at.desc(),
                        LearningState.word_id.asc(),
                    )
                elif selected_scope is PracticeScope.WRONG:
                    statement = statement.where(LearningState.error_count > 0).order_by(
                        LearningState.error_count.desc(),
                        LearningState.lapse_count.desc(),
                        LearningState.last_review_at.desc(),
                        LearningState.word_id.asc(),
                    )
                else:
                    statement = statement.join(
                        FavoriteWord,
                        FavoriteWord.word_id == LearningState.word_id,
                    ).order_by(
                        LearningState.last_review_at.desc(),
                        LearningState.word_id.asc(),
                    )
                word_ids = list(session.scalars(statement.limit(safe_limit)))

        return self.review_items.get_words_by_ids(word_ids)

    def get_words_by_ids(
        self,
        word_ids: Collection[int],
        limit: int = 30,
        now: datetime | None = None,
        *,
        exclude_word_ids: Collection[int] = (),
    ) -> list[ReviewItem]:
        """Return an ordered, learned-only custom practice queue.

        The caller supplies a deterministic word-ID order (for example, the
        core of one confusion cluster). Eligibility is checked here instead
        of trusting the source page: untouched, mastered, future-imported,
        cross-level, duplicate, and explicitly completed IDs are removed
        before card projections are built.
        """
        checked_at = ensure_utc(now or utc_now())
        safe_limit = max(1, min(int(limit), 200))
        ordered_ids = list(dict.fromkeys(int(word_id) for word_id in word_ids))[:10_000]
        excluded_ids = {int(word_id) for word_id in exclude_word_ids}
        ordered_ids = [
            word_id for word_id in ordered_ids if word_id not in excluded_ids
        ]
        if not ordered_ids:
            return []

        conditions = [
            LearningState.word_id.in_(ordered_ids),
            LearningState.review_count > 0,
            LearningState.last_review_at.is_not(None),
            LearningState.last_review_at <= checked_at,
            is_not_mastered(),
            *(
                (Word.level == self.study_level,)
                if self.study_level is not None
                else ()
            ),
        ]
        with self.database.session() as session:
            eligible_ids = set(
                session.scalars(
                    select(LearningState.word_id)
                    .join(Word, LearningState.word_id == Word.id)
                    .where(*conditions)
                )
            )

        selected_ids = [word_id for word_id in ordered_ids if word_id in eligible_ids][
            :safe_limit
        ]
        return self.review_items.get_words_by_ids(selected_ids)

    def record_attempt(
        self,
        word_id: int,
        *,
        is_correct: bool,
        response_time_ms: int,
        scope: PracticeScope | str,
        question_type: str = "meaning_recall",
        user_answer: str = "",
        practiced_at: datetime | None = None,
    ) -> PracticeSubmission:
        selected_scope = PracticeScope(scope)
        practice_time = ensure_utc(practiced_at or utc_now())
        safe_response_time = max(0, int(response_time_ms))
        safe_question_type = question_type.strip()[:50] or "meaning_recall"
        safe_user_answer = user_answer[:4_000]

        with self.database.session() as session:
            self.database.begin_serialized_write(session)
            state = session.scalar(
                select(LearningState)
                .join(Word, LearningState.word_id == Word.id)
                .where(
                    LearningState.word_id == word_id,
                    *(
                        (Word.level == self.study_level,)
                        if self.study_level is not None
                        else ()
                    ),
                )
                .with_for_update()
            )
            if state is None:
                raise LookupError(f"No learning state for word_id={word_id}")
            if session.get(MasteredWord, word_id) is not None:
                raise ValueError("A mastered word cannot receive practice attempts")
            if state.review_count <= 0 or state.last_review_at is None:
                raise ValueError("Practice requires a previously learned word")

            attempt = PracticeLog(
                word_id=word_id,
                practiced_at=practice_time,
                is_correct=bool(is_correct),
                response_time_ms=safe_response_time,
                practice_scope=selected_scope,
                question_type=safe_question_type,
                user_answer=safe_user_answer,
            )
            session.add(attempt)
            session.flush()
            result = PracticeSubmission(
                practice_log_id=attempt.id,
                word_id=word_id,
                is_correct=bool(is_correct),
                scope=selected_scope,
                practiced_at=practice_time,
            )

        logger.info(
            "Practice recorded word_id=%s scope=%s correct=%s response_ms=%s",
            word_id,
            selected_scope.value,
            is_correct,
            safe_response_time,
        )
        return result

    def _yesterday_bounds(self, checked_at: datetime) -> tuple[datetime, datetime]:
        local_now = checked_at.astimezone(self.local_timezone)
        today_start = datetime.combine(
            local_now.date(),
            time.min,
            tzinfo=self.local_timezone,
        )
        return (
            ensure_utc(today_start - timedelta(days=1)),
            ensure_utc(today_start),
        )
