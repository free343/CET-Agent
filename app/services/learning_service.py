"""Read-only learning statistics for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import case, func, select

from app.db.database import Database
from app.db.models import LearningState, ReviewLog, Word, WordLevel
from app.services.study_eligibility import effective_proficiency, is_not_mastered
from app.utils.datetime_utils import ensure_utc, utc_now


@dataclass(frozen=True, slots=True)
class WrongWordStat:
    word: str
    error_count: int


@dataclass(frozen=True, slots=True)
class DashboardStats:
    due_count: int
    today_completed: int
    seven_day_accuracy: float
    learning_streak: int
    high_frequency_wrong: tuple[WrongWordStat, ...]
    new_count: int = 0
    future_review_count: int = 0
    latest_future_review_at: datetime | None = None


def _local_day_bounds_utc(now: datetime) -> tuple[datetime, datetime]:
    local_now = ensure_utc(now).astimezone()
    local_zone = local_now.tzinfo
    day_start = datetime.combine(local_now.date(), time.min, tzinfo=local_zone)
    return ensure_utc(day_start), ensure_utc(day_start + timedelta(days=1))


class LearningService:
    def __init__(
        self, database: Database, study_level: WordLevel | str | None = None
    ) -> None:
        self.database = database
        self.study_level = WordLevel(study_level) if study_level is not None else None

    def dashboard_stats(self, now: datetime | None = None) -> DashboardStats:
        checked_at = ensure_utc(now or utc_now())
        today_start, tomorrow_start = _local_day_bounds_utc(checked_at)
        seven_days_ago = today_start - timedelta(days=6)
        thirty_days_ago = checked_at - timedelta(days=30)
        level_filter = (
            (Word.level == self.study_level,) if self.study_level is not None else ()
        )

        with self.database.session() as session:
            new_count = int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        LearningState.next_review_at <= checked_at,
                        effective_proficiency() < 3,
                        is_not_mastered(),
                        *level_filter,
                    )
                )
                or 0
            )
            due_count = int(
                session.scalar(
                    select(func.count(LearningState.id))
                    .join(Word, LearningState.word_id == Word.id)
                    .where(
                        LearningState.next_review_at <= checked_at,
                        effective_proficiency() == 3,
                        is_not_mastered(),
                        *level_filter,
                    )
                )
                or 0
            )
            future_review_count, latest_future_review_at = session.execute(
                select(
                    func.count(ReviewLog.id),
                    func.max(ReviewLog.reviewed_at),
                )
                .join(Word, ReviewLog.word_id == Word.id)
                .where(
                    ReviewLog.reviewed_at > checked_at + timedelta(minutes=5),
                    ReviewLog.question_type != "demo_confusion",
                    *level_filter,
                )
            ).one()
            today_completed = int(
                session.scalar(
                    select(func.count(ReviewLog.id))
                    .join(Word, ReviewLog.word_id == Word.id)
                    .where(
                        ReviewLog.reviewed_at >= today_start,
                        ReviewLog.reviewed_at < tomorrow_start,
                        ReviewLog.reviewed_at <= checked_at,
                        *level_filter,
                    )
                )
                or 0
            )
            seven_total, seven_correct = session.execute(
                select(
                    func.count(ReviewLog.id),
                    func.sum(case((ReviewLog.is_correct.is_(True), 1), else_=0)),
                )
                .join(Word, ReviewLog.word_id == Word.id)
                .where(
                    ReviewLog.reviewed_at >= seven_days_ago,
                    ReviewLog.reviewed_at <= checked_at,
                    *level_filter,
                )
            ).one()
            accuracy = (int(seven_correct or 0) / int(seven_total or 1)) * 100

            recent_reviews = session.scalars(
                select(ReviewLog.reviewed_at)
                .join(Word, ReviewLog.word_id == Word.id)
                .where(
                    ReviewLog.reviewed_at >= checked_at - timedelta(days=120),
                    ReviewLog.reviewed_at <= checked_at,
                    *level_filter,
                )
            ).all()
            active_days = {reviewed.astimezone().date() for reviewed in recent_reviews}
            current_day = checked_at.astimezone().date()
            streak = 0
            while current_day in active_days:
                streak += 1
                current_day -= timedelta(days=1)

            wrong_rows = session.execute(
                select(Word.word, func.count(ReviewLog.id).label("errors"))
                .join(ReviewLog, ReviewLog.word_id == Word.id)
                .join(LearningState, LearningState.word_id == Word.id)
                .where(
                    ReviewLog.reviewed_at >= thirty_days_ago,
                    ReviewLog.reviewed_at <= checked_at,
                    ReviewLog.is_correct.is_(False),
                    is_not_mastered(),
                    *level_filter,
                )
                .group_by(Word.id)
                .order_by(func.count(ReviewLog.id).desc(), Word.word.asc())
                .limit(5)
            ).all()

        return DashboardStats(
            due_count=due_count,
            today_completed=today_completed,
            seven_day_accuracy=round(accuracy, 1),
            learning_streak=streak,
            high_frequency_wrong=tuple(
                WrongWordStat(word=row.word, error_count=int(row.errors))
                for row in wrong_rows
            ),
            new_count=new_count,
            future_review_count=int(future_review_count or 0),
            latest_future_review_at=(
                ensure_utc(latest_future_review_at)
                if latest_future_review_at is not None
                else None
            ),
        )
